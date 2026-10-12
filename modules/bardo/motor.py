"""Módulo Bardo — motor do player.

A parte que toca de verdade, separada do cog: conectar no canal de voz,
tocar/pular/pausar/repetir, andar a fila quando uma música acaba, tentar de
novo quando o YouTube recusa, sair da call vazia. Usa objetos do Discord
(guild, voice_client), mas não recebe Interaction nem Message: quem chama é
o cog (comando de texto ou slash) e o painel web (via ControleBardo), pelo
mesmo caminho.

Toda mudança de estado avisa os assinantes (eventos.Publicador) — é assim
que o painel acompanha ao vivo o que foi pedido pelo Discord ou pela voz.
"""

from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.utils import escape_markdown

from modules.bardo import service
from modules.bardo.eventos import Publicador

log = logging.getLogger(__name__)

MUSICAS_MOSTRADAS_NA_FILA = 10


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


def _eh_mestre(membro) -> bool:
    """Tem o cargo de mestre do Bardo (Condutor, por padrão)? Dono do servidor sempre é."""
    if getattr(getattr(membro, "guild", None), "owner_id", None) == membro.id:
        return True
    return service.eh_mestre([c.name for c in getattr(membro, "roles", [])])


def _duracao(musica: service.Musica) -> str:
    if musica.duracao_segundos is None:
        return ""
    minutos, segundos = divmod(int(musica.duracao_segundos), 60)
    return f" ({minutos}:{segundos:02d})"


class MotorBardo:
    """Estado e ações do player, por servidor. O BardoCog herda daqui."""

    def __init__(self, bot):
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
        self.eventos = Publicador()
        # guild.id → quando a música atual começou (epoch), pro painel mostrar o progresso.
        self._tocando_desde: dict[int, float] = {}

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
                self._notificar(guild.id)
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

        musicas, achadas = service.buscar_musicas(busca, guild_id=guild.id)
        if not musicas:
            # Depois do dataset, a pasta de músicas local; só então o YouTube.
            musicas = service.buscar_arquivos_locais(busca)
            achadas = len(musicas)
        if not musicas:
            return await self._tocar_do_youtube(guild, membro, canal_de_texto, busca)

        aviso = f" (achei {achadas}, sorteei {len(musicas)})" if achadas > len(musicas) else ""
        return await self._enfileirar(guild, voice_state.channel, canal_de_texto, musicas, aviso)

    async def _tocar_playlist_salva(
        self, guild: discord.Guild, membro: discord.Member, canal_de_texto: discord.abc.Messageable, nome: str | None
    ) -> str:
        """Põe uma playlist salva do servidor (/playlist salvar) na fila."""
        voice_state = membro.voice
        if not voice_state or not voice_state.channel:
            return "Entra num canal de voz primeiro, aí eu toco."
        try:
            nome, musicas = await asyncio.to_thread(service.carregar_playlist, guild.id, nome or "")
        except service.ErroDeColecao as e:
            return str(e)
        resposta = await self._enfileirar(guild, voice_state.channel, canal_de_texto, musicas)
        return f"📃 Playlist **{escape_markdown(nome)}**: {resposta}"

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
                self._notificar(guild.id)
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
        self._tocando_desde[guild.id] = time.time()
        self._notificar(guild.id)

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
                self._notificar(guild.id)  # a fila acabou
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
        self._notificar(guild.id)
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
        ligou = fila.alternar_repetir(pedido)
        self._notificar(guild.id)
        if not ligou:
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
        self._notificar(guild.id)
        return f"Tirei **{escape_markdown(musica.titulo)}** da fila 🗑️"

    def _limpar_fila(self, guild: discord.Guild) -> str:
        quantas = self._fila(guild).limpar()
        if quantas == 0:
            return "A fila já está vazia."
        self._notificar(guild.id)
        return f"Limpei a fila ({quantas} música{'s' if quantas > 1 else ''}) 🧹"

    def _pausar(self, guild: discord.Guild) -> str:
        voice_client = guild.voice_client
        if voice_client is None or not voice_client.is_playing():
            return "Não tem nada tocando."
        voice_client.pause()
        self._notificar(guild.id)
        return "Pausei ⏸️"

    def _continuar(self, guild: discord.Guild) -> str:
        voice_client = guild.voice_client
        if voice_client is None or not voice_client.is_paused():
            return "Não tem nada pausado."
        voice_client.resume()
        self._notificar(guild.id)
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
        self._notificar(guild.id)
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
        self._notificar(guild.id)
        return f"Volume em {novo}% 🔊"

    def _volume(self, guild: discord.Guild) -> int:
        return self._volumes.get(guild.id, service.VOLUME_PADRAO)

    def _notificar(self, guild_id: int) -> None:
        """Avisa quem acompanha o estado do Bardo (o painel) que algo mudou."""
        self.eventos.publicar(guild_id)

    def _fila(self, guild: discord.Guild) -> service.Fila:
        return self._filas.setdefault(guild.id, service.Fila())

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
        self._notificar(guild.id)
        log.info("Bardo: saí da call vazia em %s", guild.id)
        await self._avisar(guild, "Todo mundo saiu da call, então saí também 👋")
        return True


def _musica_para_o_painel(musica: service.Musica | None) -> dict | None:
    if musica is None:
        return None
    return {"titulo": musica.titulo, "link": musica.link, "duracao": musica.duracao_segundos}


class ControleBardo:
    """O que uma superfície (o painel web) pode ver e fazer no Bardo, sem importar o módulo.

    O cog registra em `bot.controles["bardo"]`; o painel só conhece esta
    interface: assinar/cancelar (eventos), pode_controlar, estado e executar.
    """

    def __init__(self, motor: MotorBardo):
        self._motor = motor

    def assinar(self, assinante) -> None:
        self._motor.eventos.assinar(assinante)

    def cancelar(self, assinante) -> None:
        self._motor.eventos.cancelar(assinante)

    def pode_controlar(self, membro) -> bool:
        """Membro com o cargo de mestre (Condutor) ou dono do servidor."""
        return _eh_mestre(membro)

    def estado(self, guild) -> dict:
        """Foto do player do servidor, em tipos simples (vai como JSON pro painel)."""
        motor = self._motor
        fila = motor._fila(guild)
        voice_client = guild.voice_client
        conectado = voice_client is not None and voice_client.is_connected()
        return {
            "conectado": conectado,
            "canal": getattr(getattr(voice_client, "channel", None), "name", None) if conectado else None,
            "tocando": _musica_para_o_painel(fila.tocando),
            "pausado": bool(conectado and voice_client.is_paused()),
            "desde": motor._tocando_desde.get(guild.id) if fila.tocando else None,
            "proximas": [_musica_para_o_painel(m) for m in fila.proximas],
            "repetir": fila.repetir,
            "repetir_fila": fila.repetir_fila,
            "volume": motor._volume(guild),
            "max_fila": service.MAX_FILA,
        }
