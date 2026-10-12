"""Módulo Bardo — interface Discord.

Só traduz mensagem em linguagem natural → chamada de service.py, e cuida da
parte que é inerentemente Discord (conectar em canal de voz, tocar o
áudio, pausar, volume, passar pra próxima da fila quando uma música acaba).
Nenhuma lógica de reconhecimento de pedido mora aqui.

Dois jeitos de pedir, como no Dice: em linguagem natural ("@Natty toca
<link>", "natty pula", "@Natty volume 30") ou pelos slash commands
(/tocar, /pular, /fila, /limpar-fila, /remover, /repetir, /pausar,
/continuar, /parar, /volume), que não dependem de menção nem da Message
Content Intent.

Quando todo mundo sai da call, a Natty sai também (depois de
SEGUNDOS_ANTES_DE_SAIR) — menos com o Echo escutando, que decide sozinho.
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


def _echo_escutando(voice_client) -> bool:
    """A conexão é a do Echo (VoiceRecvClient)? Só ela tem stop_playing(). Sem importar o Echo."""
    return hasattr(voice_client, "stop_playing")


def _pessoas_no_canal(canal) -> int:
    """Quantas pessoas (bots não contam) estão no canal de voz."""
    return sum(1 for m in getattr(canal, "members", []) if not m.bot)


def _motivo(erro: Exception) -> str:
    """O motivo de um erro do YouTube pra mesa; vazio se não for um erro conhecido."""
    if isinstance(erro, service.ErroDeMusica) and type(erro) is not service.ErroDeMusica:
        return f" ({erro.motivo})"
    return ""


def _logar_falha(texto: str, alvo: str, erro: Exception) -> None:
    """Erro conhecido (vídeo privado...) vira uma linha de aviso; o resto, traceback."""
    if isinstance(erro, service.ErroDeMusica) and type(erro) is not service.ErroDeMusica:
        log.warning("Bardo: %s %s: %s", texto, alvo, erro.motivo)
    else:
        log.error("Bardo: %s %s", texto, alvo, exc_info=erro)


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
        # guild.id → espera pra sair da call vazia (cancelada se alguém volta).
        self._saidas: dict[int, asyncio.Task] = {}

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
        if pedido.acao == "tocar" and not pedido.link and not pedido.busca:
            # "@Natty toca" com um arquivo de áudio anexado: toca o anexo.
            anexo = next((a for a in message.attachments if (a.content_type or "").startswith("audio/")), None)
            if anexo is not None:
                pedido = service.Pedido("tocar", link=anexo.url)
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
        elif pedido.acao == "remover":
            resposta = self._remover(guild, pedido.posicao)
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

    @app_commands.command(
        name="tocar", description="Toca um link (vídeo ou playlist do YouTube) ou uma busca no dataset (ou põe na fila)"
    )
    @app_commands.describe(pedido="Link (YouTube, SoundCloud, Bandcamp...; vídeo ou playlist), ou uma busca: triste e bloodborne")
    @app_commands.guild_only()
    async def tocar(self, interaction: discord.Interaction, pedido: str):
        # Resolver o link no yt-dlp passa fácil dos 3s que o Discord dá pra responder.
        await interaction.response.defer(thinking=True)
        link = service.extrair_link(pedido)
        if link:
            resposta = await self._tocar(interaction.guild, interaction.user, interaction.channel, link)
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

    @app_commands.command(name="remover", description="Tira uma música da fila")
    @app_commands.describe(posicao="Posição na fila (1 = a próxima; veja em /fila)")
    @app_commands.guild_only()
    async def remover(self, interaction: discord.Interaction, posicao: app_commands.Range[int, 1, service.MAX_FILA]):
        await interaction.response.send_message(self._remover(interaction.guild, posicao))

    @app_commands.command(name="repetir", description="Repete a música atual ou a fila inteira")
    @app_commands.describe(modo="O que repetir; sem escolher, liga/desliga a repetição da música atual")
    @app_commands.choices(
        modo=[
            app_commands.Choice(name="a música atual", value="faixa"),
            app_commands.Choice(name="a fila inteira", value="fila"),
            app_commands.Choice(name="desligar", value="desligar"),
        ]
    )
    @app_commands.guild_only()
    async def repetir(self, interaction: discord.Interaction, modo: app_commands.Choice[str] | None = None):
        await interaction.response.send_message(self._repetir(interaction.guild, _pedido_de_repetir(modo)))

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
        Link de playlist põe a playlist inteira na fila (_tocar_playlist).
        """
        voice_state = membro.voice
        if not voice_state or not voice_state.channel:
            return "Entra num canal de voz primeiro, aí eu toco."
        if service.eh_link_de_playlist(link):
            return await self._tocar_playlist(guild, voice_state.channel, canal_de_texto, link)

        canal = voice_state.channel
        self._canais_de_aviso[guild.id] = canal_de_texto

        if info is None:
            try:
                info = await asyncio.to_thread(service.resolver_musica, link)
            except Exception as e:
                _logar_falha("falha ao resolver", link, e)
                if _motivo(e):
                    return f"Não consigo tocar essa{_motivo(e)}."
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
            # Depois do dataset, a pasta de músicas local; só então o YouTube.
            musicas = service.buscar_arquivos_locais(busca)
            achadas = len(musicas)
        if not musicas:
            return await self._tocar_do_youtube(guild, membro, canal_de_texto, busca)

        aviso = f" (achei {achadas}, sorteei {len(musicas)})" if achadas > len(musicas) else ""
        return await self._enfileirar(guild, voice_state.channel, canal_de_texto, musicas, aviso)

    async def _tocar_playlist(
        self, guild: discord.Guild, canal: discord.VoiceChannel, canal_de_texto: discord.abc.Messageable, link: str
    ) -> str:
        """Põe uma playlist do YouTube inteira na fila (até MAX_FILA); se nada tocava, já começa."""
        try:
            nome, musicas = await asyncio.to_thread(service.listar_playlist, link)
        except Exception as e:
            _logar_falha("falha ao ler a playlist", link, e)
            return f"Não consegui abrir essa playlist{_motivo(e)}."
        cabem = service.MAX_FILA - len(self._fila(guild).proximas)
        aviso = f" (a playlist tem {len(musicas)}, só cabem {max(cabem, 0)})" if len(musicas) > cabem > 0 else ""
        resposta = await self._enfileirar(guild, canal, canal_de_texto, musicas, aviso)
        return f"📃 Playlist **{escape_markdown(nome)}**: {resposta}"

    async def _enfileirar(
        self,
        guild: discord.Guild,
        canal: discord.VoiceChannel,
        canal_de_texto: discord.abc.Messageable,
        musicas: list[service.Musica],
        aviso: str = "",
    ) -> str:
        """Põe `musicas` no fim da fila (as que couberem); se nada tocava, já começa a primeira."""
        self._canais_de_aviso[guild.id] = canal_de_texto
        fila = self._fila(guild)

        async with self._travas.setdefault(guild.id, asyncio.Lock()):
            if guild.voice_client is None or not guild.voice_client.is_connected():
                fila.resetar()

            entraram = fila.adicionar_varias(musicas)
            if entraram == 0:
                return f"A fila já tem {service.MAX_FILA} músicas. Espera andar um pouco ou pede `@Natty limpa a fila`."
            if fila.tocando is not None:
                return f"Adicionei {entraram} música{'s' if entraram > 1 else ''} na fila{aviso} 📜"

            await self._conectar(guild, canal)
            tocando = await self._tocar_proxima(guild, avisar=False)

        if tocando is None:
            return "Não consegui tocar nenhuma dessas músicas."
        resto = len(fila.proximas)
        complemento = f" — mais {resto} na fila" if resto else ""
        return f"Tocando **{escape_markdown(tocando.titulo)}** 🎵{complemento}{aviso}"

    async def _tocar_do_youtube(
        self, guild: discord.Guild, membro: discord.Member, canal_de_texto: discord.abc.Messageable, busca: str
    ) -> str:
        """Busca que não achou nada no dataset: toca o 1º resultado do YouTube e pergunta se era essa."""
        try:
            info = await asyncio.to_thread(service.resolver_por_busca_livre, busca)
        except service.NadaEncontrado:
            # Busca sem resultado não é falha do bot: sem traceback no log.
            log.info("Bardo: busca livre por %r não achou nada", busca)
            return f'Não achei nada pra "{escape_markdown(busca)}", nem no dataset nem no YouTube. Tenta outros termos?'
        except Exception as e:
            _logar_falha("falha na busca livre por", repr(busca), e)
            if _motivo(e):
                return f'Achei "{escape_markdown(busca)}" no YouTube, mas não consigo tocar{_motivo(e)}.'
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
            discord.FFmpegPCMAudio(
                info["stream_url"], **service.opcoes_ffmpeg(info.get("http_headers"), local=info.get("local", False))
            ),
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
            except Exception as e:
                _logar_falha("falha ao tentar de novo", musica.link, e)

        if mesma_musica:
            log.error("Bardo: %s não tocou nem na segunda tentativa", musica.link)
            # Não volta pro fim da fila com o repetir da fila: falharia pra sempre.
            self._fila(guild).descartar_atual()
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
            except Exception as e:
                _logar_falha("falha ao tocar da fila", musica.link, e)
                # Não volta pro fim da fila com o repetir da fila: falharia pra sempre.
                fila.descartar_atual()
                await self._avisar(guild, f"Não consegui tocar **{escape_markdown(musica.titulo)}**{_motivo(e)}, pulei.")
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
            linhas.append("A fila está vazia." + (" 🔁 (repetindo a fila)" if fila.repetir_fila else ""))
        else:
            linhas.append("📜 Próximas" + (" — 🔁 repetindo a fila:" if fila.repetir_fila else ":"))
            for i, musica in enumerate(proximas[:MUSICAS_MOSTRADAS_NA_FILA], start=1):
                linhas.append(f"{i}. {escape_markdown(musica.titulo)}{_duracao(musica)}")
            if len(proximas) > MUSICAS_MOSTRADAS_NA_FILA:
                linhas.append(f"… e mais {len(proximas) - MUSICAS_MOSTRADAS_NA_FILA}")
        return "\n".join(linhas)

    def _repetir(self, guild: discord.Guild, pedido: service.Pedido) -> str:
        """Liga/desliga o repetir (da faixa atual ou da fila) e diz qual estado ficou — nunca muda calado."""
        fila = self._fila(guild)
        ligado = fila.repetir_fila if pedido.alvo == "fila" else fila.repetir
        if fila.tocando is None and pedido.repetir is None and not ligado:
            return "Não tem nada tocando pra repetir."
        if not fila.alternar_repetir(pedido):
            return "➡️ Repetição desligada — quando essa acabar, sigo a fila."
        if pedido.alvo == "fila":
            total = len(fila.proximas) + 1
            return (
                f"🔁 Repetindo a fila ({total} música{'s' if total > 1 else ''}) — cada uma que acaba volta pro fim. "
                "Pra parar: `@Natty para de repetir`."
            )
        return (
            f"🔁 Repetindo **{escape_markdown(fila.tocando.titulo)}** — quando acabar, volta do começo. "
            "Pra parar: `@Natty para de repetir` (ou `@Natty repete` de novo)."
        )

    def _remover(self, guild: discord.Guild, posicao: int | None) -> str:
        """Tira uma música da fila pela posição (a de `@Natty fila`)."""
        fila = self._fila(guild)
        if not fila.proximas:
            return "A fila está vazia, não tem o que tirar."
        if posicao is None:
            return "Qual delas? Fala a posição (ex: `@Natty tira a 2 da fila`); `@Natty fila` mostra os números."
        try:
            musica = fila.remover(posicao)
        except service.PosicaoInvalida:
            total = len(fila.proximas)
            return f"A fila só tem {total} música{'s' if total > 1 else ''}; não existe a posição {posicao}."
        return f"Tirei **{escape_markdown(musica.titulo)}** da fila 🗑️"

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

    # -- Sair sozinha da call vazia -------------------------------------------

    async def cog_unload(self):
        for guild_id in list(self._saidas):
            self._cancelar_saida(guild_id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, membro: discord.Member, antes: discord.VoiceState, depois: discord.VoiceState):
        """Alguém entrou/saiu de um canal: se a call da Natty esvaziou, agenda a saída; se voltou gente, cancela."""
        if membro.bot:
            return
        guild = membro.guild
        voice_client = guild.voice_client
        if voice_client is None or voice_client.channel is None:
            return
        canal = voice_client.channel
        if canal not in (antes.channel, depois.channel):
            return
        if service.deve_sair_do_canal(_pessoas_no_canal(canal), _echo_escutando(voice_client)):
            if guild.id not in self._saidas:
                self._saidas[guild.id] = asyncio.create_task(self._sair_se_continuar_vazio(guild))
        else:
            self._cancelar_saida(guild.id)

    def _cancelar_saida(self, guild_id: int) -> None:
        tarefa = self._saidas.pop(guild_id, None)
        if tarefa is not None:
            tarefa.cancel()

    async def _sair_se_continuar_vazio(self, guild: discord.Guild, espera: float | None = None) -> bool:
        """Espera um pouco e sai da call se ela continuar vazia. Devolve se saiu."""
        try:
            await asyncio.sleep(service.SEGUNDOS_ANTES_DE_SAIR if espera is None else espera)
        except asyncio.CancelledError:
            return False
        self._saidas.pop(guild.id, None)
        voice_client = guild.voice_client
        if voice_client is None or voice_client.channel is None:
            return False
        if not service.deve_sair_do_canal(_pessoas_no_canal(voice_client.channel), _echo_escutando(voice_client)):
            return False
        # Como o "para": fila zerada antes, pro `after` do player não tocar a próxima.
        self._fila(guild).resetar()
        self._interrompidas.add(guild.id)
        await voice_client.disconnect()
        log.info("Bardo: saí da call vazia em %s", guild.id)
        await self._avisar(guild, "Todo mundo saiu da call, então saí também 👋")
        return True


def _pedido_de_repetir(modo: app_commands.Choice[str] | None) -> service.Pedido:
    """Opção do /repetir → Pedido("repetir")."""
    valor = modo.value if modo else None
    if valor == "desligar":
        return service.Pedido("repetir", repetir=False)
    return service.Pedido("repetir", alvo="fila" if valor == "fila" else None)


def _duracao(musica: service.Musica) -> str:
    if musica.duracao_segundos is None:
        return ""
    minutos, segundos = divmod(int(musica.duracao_segundos), 60)
    return f" ({minutos}:{segundos:02d})"


async def setup(bot: commands.Bot):
    await bot.add_cog(BardoCog(bot))
