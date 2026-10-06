"""Módulo Bardo — interface Discord.

Só traduz mensagem em linguagem natural → chamada de service.py, e cuida da
parte que é inerentemente Discord (conectar em canal de voz, tocar o
áudio, pausar, volume, passar pra próxima da fila quando uma música acaba).
Nenhuma lógica de reconhecimento de pedido mora aqui.

Dois jeitos de pedir, como no Dice: em linguagem natural ("@Natty toca
<link>", "natty pula", "@Natty volume 30") ou pelos slash commands
(/tocar, /pular, /fila, /limpar-fila, /pausar, /continuar, /parar,
/volume), que não dependem de menção nem da Message Content Intent.
"""

from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import escape_markdown

from modules.bardo import service

log = logging.getLogger(__name__)

MUSICAS_MOSTRADAS_NA_FILA = 10

# Pedido falado na call: a própria Natty posta "🎙️ natty toca <o que ouviu>"
# no canal (quem transcreve a fala é o módulo Echo). Mesma convenção do Dice:
# só mensagem dela com esse marcador no começo é aceita — as respostas do
# Bardo nunca começam assim, então não há laço. O Bardo não importa nada do Echo.
# Só o caractere-base do 🎙, sem o seletor de emoji (U+FE0F), que pode vir ou não.
MARCADOR_VOZ = "\U0001F399"


def _parar_audio(voice_client) -> None:
    """
    Para só a música. Com o Echo escutando, a conexão é um VoiceRecvClient, e
    nele `stop()` para a música E a escuta — "natty pula"/"natty para"
    deixavam a Natty surda pra senha. `stop_playing()` (só existe lá) para só
    a música; numa conexão comum, `stop()` já é só a música. Sem importar o Echo.
    """
    getattr(voice_client, "stop_playing", voice_client.stop)()


def _deve_ignorar(message: discord.Message, eu: discord.abc.User | None) -> bool:
    """Ignora bots (a própria Natty, o Avrae...), exceto o pedido falado que a Natty posta."""
    if not message.author.bot:
        return False
    return not (eu is not None and message.author.id == eu.id and message.content.startswith(MARCADOR_VOZ))


class BardoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._volumes: dict[int, int] = {}  # guild.id → volume (0-100)
        self._filas: dict[int, service.Fila] = {}  # guild.id → fila
        self._travas: dict[int, asyncio.Lock] = {}  # guild.id → trava do _tocar
        # guild.id → canal de texto do último pedido, pra avisar "tocando agora"
        # quando a fila anda sozinha.
        self._canais_de_aviso: dict[int, discord.abc.Messageable] = {}
        # guild.id de quem pulou/parou a música de propósito: aí uma música
        # que acabou rápido não é falha pra tentar de novo.
        self._interrompidas: set[int] = set()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if _deve_ignorar(message, self.bot.user) or message.guild is None:
            return
        # Reply à pergunta "era essa?" é a resposta dela — com ou sem @ (dá
        # pra responder no Discord com a menção desligada). Só reply conta.
        respondendo_a = message.reference.message_id if message.reference else None
        if service.eh_resposta_da_pendencia(message.guild.id, respondendo_a):
            await self._responder_pendencia(message)
            return
        if not self._falou_com_a_natty(message):
            return

        pedido = service.interpretar_pedido(message.content)
        if pedido is None:
            return

        guild = message.guild
        if pedido.acao == "tocar":
            if pedido.link:
                async with message.channel.typing():
                    resposta = await self._tocar(guild, message.author, message.channel, pedido.link)
            elif pedido.busca:
                async with message.channel.typing():
                    resposta = await self._tocar_busca(guild, message.author, message.channel, pedido.busca)
            else:
                resposta = (
                    "Me manda o link do YouTube, ou descreve o que quer ouvir "
                    '(ex: "@Natty toca triste e bloodborne").'
                )
        elif pedido.acao == "pular":
            resposta = self._pular(guild)
        elif pedido.acao == "fila":
            resposta = self._descrever_fila(guild)
        elif pedido.acao == "limpar_fila":
            resposta = self._limpar_fila(guild)
        elif pedido.acao == "pausar":
            resposta = self._pausar(guild)
        elif pedido.acao == "continuar":
            resposta = self._continuar(guild)
        elif pedido.acao == "repetir":
            resposta = self._repetir(guild, pedido)
        elif pedido.acao == "parar":
            resposta = await self._parar(guild)
        else:  # volume
            resposta = self._mudar_volume(guild, pedido)

        enviada = await message.reply(resposta, mention_author=False)
        # Se esse pedido abriu um "era essa?", a pergunta está nesta mensagem:
        # só reply a ela vai contar como resposta.
        service.registrar_pergunta_da_pendencia(guild.id, enviada.id)

    def _falou_com_a_natty(self, message: discord.Message) -> bool:
        """
        Só menção de verdade: @Natty ou o cargo automático dela (o Discord
        oferece os dois ao digitar "@Natty"). Escrever "natty" sem @ não conta
        mais — evitava que conversa normal da mesa virasse comando.

        Exceção: o pedido falado que a própria Natty posta com 🎙 (Echo →
        "🎙️ natty toca X"). O marcador já diz que é pra ela.
        """
        if message.author.id == getattr(self.bot.user, "id", None) and message.content.startswith(MARCADOR_VOZ):
            return True
        cargo_da_natty = message.guild.self_role
        return self.bot.user in message.mentions or (
            cargo_da_natty is not None and cargo_da_natty in message.role_mentions
        )

    @app_commands.command(name="tocar", description="Toca um link do YouTube ou uma busca no dataset (ou põe na fila)")
    @app_commands.describe(pedido="Link do YouTube, ou uma busca como: triste e bloodborne")
    @app_commands.guild_only()
    async def tocar(self, interaction: discord.Interaction, pedido: str):
        # Resolver o link no yt-dlp passa fácil dos 3s que o Discord dá pra responder.
        await interaction.response.defer(thinking=True)
        link_youtube = service.extrair_link_youtube(pedido)
        if link_youtube:
            resposta = await self._tocar(interaction.guild, interaction.user, interaction.channel, link_youtube)
        else:
            resposta = await self._tocar_busca(interaction.guild, interaction.user, interaction.channel, pedido)
        enviada = await interaction.followup.send(resposta, wait=True)
        service.registrar_pergunta_da_pendencia(interaction.guild.id, enviada.id)  # se abriu um "era essa?"

    @app_commands.command(name="pular", description="Pula pra próxima música da fila")
    @app_commands.guild_only()
    async def pular(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._pular(interaction.guild))

    @app_commands.command(name="fila", description="Mostra a música tocando e as próximas")
    @app_commands.guild_only()
    async def fila(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._descrever_fila(interaction.guild))

    @app_commands.command(name="limpar-fila", description="Tira todas as músicas da fila (a atual continua)")
    @app_commands.guild_only()
    async def limpar_fila(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._limpar_fila(interaction.guild))

    @app_commands.command(name="pausar", description="Pausa a música")
    @app_commands.guild_only()
    async def pausar(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._pausar(interaction.guild))

    @app_commands.command(name="continuar", description="Continua a música pausada")
    @app_commands.guild_only()
    async def continuar(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._continuar(interaction.guild))

    @app_commands.command(name="parar", description="Para a música e limpa a fila (continua no canal de voz)")
    @app_commands.guild_only()
    async def parar(self, interaction: discord.Interaction):
        await interaction.response.send_message(await self._parar(interaction.guild))

    @app_commands.command(name="volume", description="Muda o volume da música (0 a 100)")
    @app_commands.describe(nivel="Volume de 0 a 100; sem valor, mostra o volume atual")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, nivel: app_commands.Range[int, 0, 100] | None = None):
        pedido = service.Pedido("volume", volume=nivel)
        await interaction.response.send_message(self._mudar_volume(interaction.guild, pedido))

    async def _tocar(
        self,
        guild: discord.Guild,
        membro: discord.Member,
        canal_de_texto: discord.abc.Messageable,
        link: str,
        info: dict | None = None,
    ) -> str:
        """Toca `link` no canal de voz de `membro`, ou põe na fila se já tiver música. Devolve a resposta.

        `info` é o link já resolvido (ex: pela busca livre), pra não resolver duas vezes.
        """
        voice_state = membro.voice
        if not voice_state or not voice_state.channel:
            return "Entra num canal de voz primeiro, aí eu toco."

        canal = voice_state.channel
        self._canais_de_aviso[guild.id] = canal_de_texto

        if info is None:
            try:
                info = await asyncio.to_thread(service.resolver_musica, link)
            except Exception:
                log.exception("Bardo: falha ao resolver %s", link)
                return "Não consegui pegar essa música. Confere o link?"

        musica = service.Musica(info["titulo"], link, info["duracao_segundos"])
        fila = self._fila(guild)

        # Um pedido por vez daqui pra frente: se dois chegarem juntos, o
        # segundo espera o primeiro conectar e vai pra fila.
        async with self._travas.setdefault(guild.id, asyncio.Lock()):
            if guild.voice_client is None or not guild.voice_client.is_connected():
                # Tiraram a Natty do canal (ou a conexão caiu) sem passar
                # pelo "para": o que estava na fila não vale mais.
                fila.resetar()

            if fila.tocando is not None:
                try:
                    posicao = fila.adicionar(musica)
                except service.FilaCheia as e:
                    return f"{e} Espera andar um pouco ou pede `@Natty limpa a fila`."
                return f"Adicionei **{escape_markdown(musica.titulo)}** na fila (posição {posicao}) 📜"

            fila.tocando = musica
            try:
                voice_client = await self._conectar(guild, canal)
                self._tocar_stream(guild, voice_client, info, musica)
            except Exception:
                fila.tocando = None
                raise

        return f"Tocando **{escape_markdown(musica.titulo)}** 🎵"

    async def _tocar_busca(
        self, guild: discord.Guild, membro: discord.Member, canal_de_texto: discord.abc.Messageable, busca: str
    ) -> str:
        """Busca `busca` no dataset e põe o resultado na fila; se nada tocava, já começa. Devolve a resposta."""
        voice_state = membro.voice
        if not voice_state or not voice_state.channel:
            return "Entra num canal de voz primeiro, aí eu toco."

        musicas, achadas = service.buscar_musicas(busca)
        if not musicas:
            return await self._tocar_do_youtube(guild, membro, canal_de_texto, busca)

        self._canais_de_aviso[guild.id] = canal_de_texto
        aviso = f" (achei {achadas}, sorteei {len(musicas)})" if achadas > len(musicas) else ""
        fila = self._fila(guild)

        async with self._travas.setdefault(guild.id, asyncio.Lock()):
            if guild.voice_client is None or not guild.voice_client.is_connected():
                fila.resetar()

            entraram = fila.adicionar_varias(musicas)
            if entraram == 0:
                return f"A fila já tem {service.MAX_FILA} músicas. Espera andar um pouco ou pede `@Natty limpa a fila`."
            if fila.tocando is not None:
                return f"Adicionei {entraram} música{'s' if entraram > 1 else ''} na fila{aviso} 📜"

            await self._conectar(guild, voice_state.channel)
            tocando = await self._tocar_proxima(guild, avisar=False)

        if tocando is None:
            return "Não consegui tocar nenhuma das músicas que achei."
        resto = len(fila.proximas)
        complemento = f" — mais {resto} na fila" if resto else ""
        return f"Tocando **{escape_markdown(tocando.titulo)}** 🎵{complemento}{aviso}"

    async def _tocar_do_youtube(
        self, guild: discord.Guild, membro: discord.Member, canal_de_texto: discord.abc.Messageable, busca: str
    ) -> str:
        """Busca que não achou nada no dataset: toca o 1º resultado do YouTube e pergunta se era essa."""
        try:
            info = await asyncio.to_thread(service.resolver_por_busca_livre, busca)
        except Exception:
            log.exception("Bardo: falha na busca livre por %r", busca)
            return f'Não achei nada pra "{escape_markdown(busca)}", nem no dataset nem no YouTube. Tenta outros termos?'

        link = info["link"]
        resposta = await self._tocar(guild, membro, canal_de_texto, link, info)
        fila = self._fila(guild)
        entrou = any(m.link == link for m in (fila.tocando, *fila.proximas) if m is not None)
        if not entrou:  # não conseguiu tocar nem enfileirar: não tem o que perguntar
            return resposta

        service.criar_pendencia(guild.id, info["titulo"], link, canal_id=getattr(canal_de_texto, "id", None))
        return (
            f"Não achei no dataset, mas achei no YouTube. {resposta}\n"
            "Era essa mesmo? **Responde a esta mensagem** (reply) com uns temas dela que eu aprendo "
            '(ex: "é taverna e animado") — ou "não" se não for.'
        )

    async def _responder_pendencia(self, message: discord.Message) -> None:
        """Mensagem pra Natty que não é pedido: se tem pergunta "era essa?" em aberto neste canal, é a resposta."""
        pendencia = service.pendencia_do_servidor(message.guild.id)  # já some se venceu
        if pendencia is None or pendencia["canal_id"] != message.channel.id:
            return

        temas = service.interpretar_resposta_de_pendencia(message.content)
        service.limpar_pendencia(message.guild.id)
        titulo = escape_markdown(pendencia["titulo"])
        if temas is None:
            await message.reply(f"Ok, não guardei **{titulo}** 👍", mention_author=False)
            return

        try:
            entrada = await asyncio.to_thread(
                service.adicionar_descoberta_ao_dataset, pendencia["titulo"], pendencia["link"], temas
            )
        except service.MusicaJaNoDataset as e:
            await message.reply(
                f"**{escape_markdown(e.musica['nome'])}** já estava no dataset, deixei como está.",
                mention_author=False,
            )
            return
        except Exception:
            log.exception("Bardo: falha ao gravar descoberta %s", pendencia["link"])
            await message.reply("Não consegui salvar no dataset, deu erro aqui 😕", mention_author=False)
            return

        if entrada["temas"] == [service.NAO_CLASSIFICADO]:
            detalhe = 'como "não classificado" (sem temas por enquanto)'
        else:
            detalhe = "com os temas " + ", ".join(entrada["temas"])
        await message.reply(f"Adicionei **{titulo}** ao dataset {detalhe} 🎉", mention_author=False)

    async def _conectar(self, guild: discord.Guild, canal: discord.VoiceChannel) -> discord.VoiceClient:
        voice_client = guild.voice_client
        if voice_client is None:
            return await canal.connect()
        if voice_client.channel != canal:
            await voice_client.move_to(canal)
        return voice_client

    def _tocar_stream(
        self,
        guild: discord.Guild,
        voice_client: discord.VoiceClient,
        info: dict,
        musica: service.Musica,
        tentativa: int = 0,
    ) -> None:
        fonte = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(info["stream_url"], **service.opcoes_ffmpeg(info.get("http_headers"))),
            volume=self._volume(guild) / 100,
        )
        inicio = time.monotonic()
        self._interrompidas.discard(guild.id)

        def ao_terminar(erro: Exception | None) -> None:
            # Roda na thread do player do discord.py, não no event loop.
            if erro:
                log.error("Bardo: erro tocando música", exc_info=erro)
            interrompida = guild.id in self._interrompidas
            self._interrompidas.discard(guild.id)
            falhou = not interrompida and time.monotonic() - inicio < service.SEGUNDOS_PARA_FALHA_RAPIDA
            asyncio.run_coroutine_threadsafe(
                self._depois_de_tocar(guild, musica, tentativa, falhou, interrompida), self.bot.loop
            )

        voice_client.play(fonte, after=ao_terminar)

    async def _depois_de_tocar(
        self, guild: discord.Guild, musica: service.Musica, tentativa: int, falhou: bool, interrompida: bool = False
    ) -> None:
        """
        Chamada quando uma música acaba: tenta de novo se ela falhou logo de
        cara; com o repetir ligado e a música tendo acabado sozinha (ninguém
        pulou/parou), toca a mesma de novo; senão anda a fila.
        """
        if not falhou:
            if not interrompida and self._fila(guild).deve_repetir(musica):
                await self._repetir_musica(guild, musica)
                return
            await self._tocar_proxima(guild)
            return

        voice_client = guild.voice_client
        # Se enquanto isso pararam ou trocaram a música, não tem o que refazer.
        mesma_musica = self._fila(guild).tocando is musica
        if tentativa == 0 and mesma_musica and voice_client is not None and voice_client.is_connected():
            log.warning("Bardo: %s acabou logo de cara (YouTube recusou?), tentando de novo", musica.link)
            try:
                # URL nova: a anterior pode ter sido recusada de vez.
                info = await asyncio.to_thread(service.resolver_musica, musica.link)
                self._tocar_stream(guild, voice_client, info, musica, tentativa + 1)
                return
            except Exception:
                log.exception("Bardo: falha ao tentar de novo %s", musica.link)

        if mesma_musica:
            log.error("Bardo: %s não tocou nem na segunda tentativa", musica.link)
            await self._avisar(guild, f"O YouTube não deixou tocar **{escape_markdown(musica.titulo)}**, pulei.")
        await self._tocar_proxima(guild)

    async def _repetir_musica(self, guild: discord.Guild, musica: service.Musica) -> None:
        """Toca `musica` de novo, do começo (repetir ligado). Sem aviso no canal a cada volta."""
        voice_client = guild.voice_client
        if voice_client is None or not voice_client.is_connected():
            self._fila(guild).resetar()
            return
        try:
            # URL nova: a de áudio do YouTube expira, e a música pode ter durado horas.
            info = await asyncio.to_thread(service.resolver_musica, musica.link)
            self._tocar_stream(guild, voice_client, info, musica)
        except Exception:
            log.exception("Bardo: falha ao repetir %s", musica.link)
            self._fila(guild).repetir = False
            await self._avisar(
                guild, f"Não consegui repetir **{escape_markdown(musica.titulo)}**, desliguei a repetição e segui a fila."
            )
            await self._tocar_proxima(guild)

    async def _tocar_proxima(self, guild: discord.Guild, avisar: bool = True) -> service.Musica | None:
        """Toca a próxima da fila, se tiver, e a devolve.

        Chamada quando uma música acaba (ou foi pulada), e pelo _tocar_busca
        pra começar a primeira, que responde ele mesmo (avisar=False).
        """
        fila = self._fila(guild)
        while True:
            voice_client = guild.voice_client
            if voice_client is None or not voice_client.is_connected():
                fila.resetar()
                return None

            musica = fila.avancar()
            if musica is None:
                return None

            try:
                info = await asyncio.to_thread(service.resolver_musica, musica.link)
                self._tocar_stream(guild, voice_client, info, musica)
            except Exception:
                log.exception("Bardo: falha ao tocar %s da fila", musica.link)
                await self._avisar(guild, f"Não consegui tocar **{escape_markdown(musica.titulo)}**, pulei.")
                continue

            if avisar:
                await self._avisar(guild, f"Tocando agora **{escape_markdown(musica.titulo)}** 🎵")
            return musica

    async def _avisar(self, guild: discord.Guild, texto: str) -> None:
        canal = self._canais_de_aviso.get(guild.id)
        if canal is None:
            return
        try:
            await canal.send(texto)
        except discord.HTTPException:
            log.exception("Bardo: não consegui avisar no canal de texto")

    def _pular(self, guild: discord.Guild) -> str:
        voice_client = guild.voice_client
        if voice_client is None or not (voice_client.is_playing() or voice_client.is_paused()):
            return "Não tem nada tocando."
        fila = self._fila(guild)
        tem_proxima = bool(fila.proximas)
        # Pular é "chega dessa": desliga o repetir, senão a próxima também
        # entraria em loop sem ninguém ter pedido.
        repetia = fila.repetir
        fila.repetir = False
        self._interrompidas.add(guild.id)
        _parar_audio(voice_client)  # o `after` do player chama _tocar_proxima
        aviso = " (repetição desligada)" if repetia else ""
        return f"Pulei ⏭️{aviso}" if tem_proxima else f"Pulei ⏭️ A fila acabou.{aviso}"

    def _descrever_fila(self, guild: discord.Guild) -> str:
        fila = self._fila(guild)
        if fila.tocando is None:
            return "Não tem nada tocando, e a fila está vazia."

        repetindo = " 🔁 (repetindo)" if fila.repetir else ""
        linhas = [f"🎵 Tocando: **{escape_markdown(fila.tocando.titulo)}**{_duracao(fila.tocando)}{repetindo}"]
        proximas = fila.proximas
        if not proximas:
            linhas.append("A fila está vazia.")
        else:
            linhas.append("📜 Próximas:")
            for i, musica in enumerate(proximas[:MUSICAS_MOSTRADAS_NA_FILA], start=1):
                linhas.append(f"{i}. {escape_markdown(musica.titulo)}{_duracao(musica)}")
            if len(proximas) > MUSICAS_MOSTRADAS_NA_FILA:
                linhas.append(f"… e mais {len(proximas) - MUSICAS_MOSTRADAS_NA_FILA}")
        return "\n".join(linhas)

    def _repetir(self, guild: discord.Guild, pedido: service.Pedido) -> str:
        """Liga/desliga o repetir da faixa atual e diz qual estado ficou — nunca muda calado."""
        fila = self._fila(guild)
        if fila.tocando is None and (pedido.repetir is None and not fila.repetir):
            return "Não tem nada tocando pra repetir."
        if fila.alternar_repetir(pedido):
            return (
                f"🔁 Repetindo **{escape_markdown(fila.tocando.titulo)}** — quando acabar, volta do começo. "
                "Pra parar: `@Natty para de repetir` (ou `@Natty repete` de novo)."
            )
        return "➡️ Repetição desligada — quando essa acabar, sigo a fila."

    def _limpar_fila(self, guild: discord.Guild) -> str:
        quantas = self._fila(guild).limpar()
        if quantas == 0:
            return "A fila já está vazia."
        return f"Limpei a fila ({quantas} música{'s' if quantas > 1 else ''}) 🧹"

    def _pausar(self, guild: discord.Guild) -> str:
        voice_client = guild.voice_client
        if voice_client is None or not voice_client.is_playing():
            return "Não tem nada tocando."
        voice_client.pause()
        return "Pausei ⏸️"

    def _continuar(self, guild: discord.Guild) -> str:
        voice_client = guild.voice_client
        if voice_client is None or not voice_client.is_paused():
            return "Não tem nada pausado."
        voice_client.resume()
        return "Continuando ▶️"

    async def _parar(self, guild: discord.Guild) -> str:
        # Reseta antes do stop(): o `after` do player vai procurar a próxima
        # e tem que achar a fila vazia.
        self._fila(guild).resetar()
        voice_client = guild.voice_client
        if voice_client is None:
            return "Não estou tocando nada."
        if voice_client.is_playing() or voice_client.is_paused():
            self._interrompidas.add(guild.id)
        # Só para a música, não sai da call: quem tira a Natty da call agora é
        # só o Echo ("NAT20, por favor, saia" / "@Natty, tampe os ouvidos").
        # Assim "NAT20, por favor, pare" não derruba a escuta.
        _parar_audio(voice_client)
        return "Parei ⏹️"

    def _mudar_volume(self, guild: discord.Guild, pedido: service.Pedido) -> str:
        atual = self._volume(guild)
        if pedido.volume is None and pedido.delta_volume is None:
            return f"O volume está em {atual}%."

        novo = service.novo_volume(atual, pedido)
        self._volumes[guild.id] = novo
        voice_client = guild.voice_client
        if voice_client is not None and isinstance(voice_client.source, discord.PCMVolumeTransformer):
            voice_client.source.volume = novo / 100
        return f"Volume em {novo}% 🔊"

    def _volume(self, guild: discord.Guild) -> int:
        return self._volumes.get(guild.id, service.VOLUME_PADRAO)

    def _fila(self, guild: discord.Guild) -> service.Fila:
        return self._filas.setdefault(guild.id, service.Fila())


def _duracao(musica: service.Musica) -> str:
    if musica.duracao_segundos is None:
        return ""
    minutos, segundos = divmod(int(musica.duracao_segundos), 60)
    return f" ({minutos}:{segundos:02d})"


async def setup(bot: commands.Bot):
    await bot.add_cog(BardoCog(bot))
