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
import collections
import logging
import time
from types import SimpleNamespace

import discord
from discord.utils import escape_markdown

from modules.bardo import service
from modules.bardo.eventos import Publicador
from modules.bardo.mixer import MUSICA, MixerSource, decodificar_arquivo

log = logging.getLogger(__name__)

MUSICAS_MOSTRADAS_NA_FILA = 10


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
        self._mixers: dict[int, MixerSource] = {}  # guild.id → mixer (sobrevive à conexão)
        self._masters: dict[int, int] = {}  # guild.id → volume geral (0-100)
        self._duckings: dict[int, int] = {}  # guild.id → quanto a música abaixa com efeito "duck" (0-100)
        # sha256 do efeito → amostras já decodificadas (o pad dispara sem esperar ffmpeg)
        self._efeitos: collections.OrderedDict[str, object] = collections.OrderedDict()
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
        if canal_de_texto is not None:  # pedido do painel não tem canal de texto
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
        if canal_de_texto is not None:  # pedido do painel não tem canal de texto
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
        if canal_de_texto is None:  # pedido do painel: não tem onde perguntar "era essa?"
            return f"Não achei no dataset, mas achei no YouTube. {resposta}"

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
        fonte = discord.FFmpegPCMAudio(
            info["stream_url"], **service.opcoes_ffmpeg(info.get("http_headers"), local=info.get("local", False))
        )
        inicio = time.monotonic()
        self._interrompidas.discard(guild.id)

        def ao_terminar() -> None:
            # Roda na thread do player do discord.py (o mixer avisa de lá), não no event loop.
            interrompida = guild.id in self._interrompidas
            self._interrompidas.discard(guild.id)
            falhou = not interrompida and time.monotonic() - inicio < service.SEGUNDOS_PARA_FALHA_RAPIDA
            asyncio.run_coroutine_threadsafe(
                self._depois_de_tocar(guild, musica, tentativa, falhou, interrompida), self.bot.loop
            )

        mixer = self._mixer(guild)
        mixer.volume(MUSICA, self._volume(guild) / 100)
        mixer.tocar_musica(fonte, ao_terminar=ao_terminar)
        self._garantir_player(guild, voice_client)
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
        if self._mixer(guild).musica is None:
            return "Não tem nada tocando."
        fila = self._fila(guild)
        tem_proxima = bool(fila.proximas)
        # Pular é "chega dessa": desliga o repetir, senão a próxima também
        # entraria em loop sem ninguém ter pedido.
        repetia = fila.repetir
        fila.repetir = False
        self._interrompidas.add(guild.id)
        self._mixer(guild).parar_musica()  # o fim da camada de música chama _tocar_proxima
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
        if fila.tocando is None and pedido.repetir is not False and not ligado:
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
        if self._mixer(guild).musica != "tocando":
            return "Não tem nada tocando."
        # Pausa só a música: ambiente e efeitos (etapa do mixer) continuam.
        self._mixer(guild).pausar_musica(True)
        self._notificar(guild.id)
        return "Pausei ⏸️"

    def _continuar(self, guild: discord.Guild) -> str:
        if self._mixer(guild).musica != "pausada":
            return "Não tem nada pausado."
        self._mixer(guild).pausar_musica(False)
        self._notificar(guild.id)
        return "Continuando ▶️"

    async def _parar(self, guild: discord.Guild) -> str:
        # Reseta antes de parar: o fim da música vai procurar a próxima e tem
        # que achar a fila vazia.
        self._fila(guild).resetar()
        if guild.voice_client is None:
            return "Não estou tocando nada."
        mixer = self._mixer(guild)
        if mixer.musica is not None:
            self._interrompidas.add(guild.id)
        # Só a camada de música: o player (e a escuta do Echo, que divide a
        # conexão) seguem de pé, e não sai da call — quem tira a Natty da call
        # é o Echo ("NAT20, por favor, saia") ou a call esvaziar.
        mixer.parar_musica()
        self._notificar(guild.id)
        return "Parei ⏹️"

    def _mudar_volume(self, guild: discord.Guild, pedido: service.Pedido) -> str:
        atual = self._volume(guild)
        if pedido.volume is None and pedido.delta_volume is None:
            return f"O volume está em {atual}%."

        novo = service.novo_volume(atual, pedido)
        self._volumes[guild.id] = novo
        self._mixer(guild).volume(MUSICA, novo / 100)
        self._notificar(guild.id)
        return f"Volume em {novo}% 🔊"

    def _volume(self, guild: discord.Guild) -> int:
        return self._volumes.get(guild.id, service.VOLUME_PADRAO)

    def _notificar(self, guild_id: int) -> None:
        """Avisa quem acompanha o estado do Bardo (o painel) que algo mudou."""
        self.eventos.publicar(guild_id)

    def _mixer(self, guild: discord.Guild) -> MixerSource:
        """O mixer do servidor. Vive aqui, não na conexão: sobrevive a reconexão e troca de cliente (Echo)."""
        return self._mixers.setdefault(guild.id, MixerSource())

    def _garantir_player(self, guild: discord.Guild, voice_client, tentativas: int = 20) -> None:
        """Põe o mixer pra tocar na conexão, se ela não está tocando ele (parou ocioso, conexão nova...)."""
        mixer = self._mixer(guild)
        if voice_client is None or not voice_client.is_connected():
            return
        if mixer.ativo and voice_client.is_playing() and voice_client.source is mixer:
            return
        if voice_client.is_playing() or voice_client.is_paused():
            if voice_client.source is mixer and not mixer.ativo and tentativas > 0:
                # O player está terminando (o mixer acabou de dizer b""): tenta já já.
                self.bot.loop.call_later(0.05, self._garantir_player, guild, voice_client, tentativas - 1)
                return
            if voice_client.source is not mixer:
                getattr(voice_client, "stop_playing", voice_client.stop)()  # outra fonte: o mixer manda
            else:
                return
        mixer.ativo = True
        voice_client.play(mixer, after=lambda erro: erro and log.error("Bardo: player parou com erro",
                                                                       exc_info=erro))

    # -- Som de mesa: ambientes, efeitos, master, cenas -------------------------------

    MAX_EFEITOS_EM_MEMORIA = 32

    async def _conectar_para_som(self, guild: discord.Guild, canal) -> object | None:
        """A conexão onde o som vai tocar: a atual; senão conecta no `canal` (de quem pediu)."""
        voice_client = guild.voice_client
        if voice_client is not None and voice_client.is_connected():
            return voice_client
        if canal is None:
            return None
        return await self._conectar(guild, canal)

    def _fabrica_do_som(self, guild_id: int, som: dict):
        caminho = str(service.caminho_do_som(guild_id, som["arquivo"]))
        return lambda: discord.FFmpegPCMAudio(caminho, **service.opcoes_ffmpeg(local=True))

    async def _amostras_do_efeito(self, guild_id: int, som: dict):
        amostras = self._efeitos.get(som["hash"])
        if amostras is None:
            caminho = str(service.caminho_do_som(guild_id, som["arquivo"]))
            amostras = await asyncio.to_thread(decodificar_arquivo, caminho)
            self._efeitos[som["hash"]] = amostras
            while len(self._efeitos) > self.MAX_EFEITOS_EM_MEMORIA:
                self._efeitos.popitem(last=False)
        self._efeitos.move_to_end(som["hash"])
        return amostras

    async def _som_tocar(self, guild: discord.Guild, canal, nome: str) -> str:
        """Ambiente: liga o loop (ou acerta o volume). Efeito: dispara. Música: vai pra fila."""
        som = await asyncio.to_thread(service.buscar_som, guild.id, nome)
        titulo = escape_markdown(som["nome"])
        if som["tipo"] == "musica":
            if canal is None and guild.voice_client is None:
                return "Chama a Natty pra uma call primeiro (ou entra numa)."
            destino = guild.voice_client.channel if guild.voice_client is not None else canal
            return await self._enfileirar(guild, destino, None, [
                service.Musica(som["nome"], service.link_do_som(guild.id, som))])
        voice_client = await self._conectar_para_som(guild, canal)
        if voice_client is None:
            return "Chama a Natty pra uma call primeiro (ou entra numa)."
        mixer = self._mixer(guild)
        if som["tipo"] == "ambiente":
            mixer.tocar_ambiente(som["nome_chave"], self._fabrica_do_som(guild.id, som), ganho=som["volume"] / 100,
                                 duck=som["duck"])
            resposta = f"🌫️ Ambiente **{titulo}** ligado ({som['volume']}%)."
        else:
            amostras = await self._amostras_do_efeito(guild.id, som)
            mixer.disparar_efeito(amostras, ganho=som["volume"] / 100, duck=som["duck"])
            resposta = f"💥 **{titulo}**"
        self._garantir_player(guild, voice_client)
        self._notificar(guild.id)
        return resposta

    async def _som_parar(self, guild: discord.Guild, nome: str | None = None) -> str:
        """Desliga um ambiente (com fade) ou, sem nome, todos."""
        mixer = self._mixer(guild)
        if nome:
            som = await asyncio.to_thread(service.buscar_som, guild.id, nome, "ambiente")
            if som["nome_chave"] not in mixer.ambientes:
                return f"O ambiente **{escape_markdown(som['nome'])}** não está ligado."
            mixer.parar_ambiente(som["nome_chave"])
            self._notificar(guild.id)
            return f"Desliguei o ambiente **{escape_markdown(som['nome'])}**."
        if not mixer.ambientes:
            return "Nenhum ambiente ligado."
        quantos = len(mixer.ambientes)
        for chave in list(mixer.ambientes):
            mixer.parar_ambiente(chave)
        self._notificar(guild.id)
        return f"Desliguei {quantos} ambiente{'s' if quantos > 1 else ''}."

    async def _som_volume(self, guild: discord.Guild, nome: str, nivel: int) -> str:
        """Volume guardado do som (vale pras próximas vezes) e, se é ambiente ligado, já muda."""
        som = await asyncio.to_thread(service.configurar_som, guild.id, nome, nivel)
        mixer = self._mixer(guild)
        if som["tipo"] == "ambiente" and som["nome_chave"] in mixer.ambientes:
            mixer.tocar_ambiente(som["nome_chave"], self._fabrica_do_som(guild.id, som), ganho=som["volume"] / 100,
                                 fade_s=0.3, duck=som["duck"])
        self._notificar(guild.id)
        return f"**{escape_markdown(som['nome'])}** em {som['volume']}%."

    def _master(self, guild: discord.Guild) -> int:
        return self._masters.get(guild.id, 100)

    def _ducking(self, guild: discord.Guild) -> int:
        return self._duckings.get(guild.id, service.PROFUNDIDADE_DUCKING_PADRAO)

    def _mudar_master(self, guild: discord.Guild, nivel: int) -> str:
        self._masters[guild.id] = max(0, min(100, int(nivel)))
        self._mixer(guild).master(self._master(guild) / 100)
        self._notificar(guild.id)
        return f"Volume geral em {self._master(guild)}% 🔊"

    def _mudar_ducking(self, guild: discord.Guild, nivel: int) -> str:
        self._duckings[guild.id] = max(0, min(100, int(nivel)))
        self._mixer(guild).ducking(self._ducking(guild) / 100)
        self._notificar(guild.id)
        return f"Com efeito tocando, a música abaixa {self._ducking(guild)}%."

    def _capturar_cena(self, guild: discord.Guild, pads: list[str] | None = None) -> dict:
        """O mixer agora, no formato de cena."""
        return service.validar_cena({
            "ambientes": [{"som": chave, "volume": round(a["volume"] * 100)}
                          for chave, a in self._mixer(guild).ambientes.items()],
            "pads": pads or [],
            "ducking": self._ducking(guild),
            "master": self._master(guild),
        })

    async def _cena_salvar(self, guild: discord.Guild, nome: str, autor_id: int | None,
                           dados: dict | None = None) -> str:
        dados = dados if dados is not None else self._capturar_cena(guild)
        nome = await asyncio.to_thread(service.salvar_cena, guild.id, nome, dados, autor_id)
        self._notificar(guild.id)
        return f"🎬 Cena **{escape_markdown(nome)}** salva ({len(dados.get('ambientes', []))} ambientes)."

    async def _cena_aplicar(self, guild: discord.Guild, canal, nome: str) -> str:
        """Liga a cena: volume geral, ducking, ambientes (desliga os que não são dela) e a playlist, se tiver."""
        nome, dados = await asyncio.to_thread(service.carregar_cena, guild.id, nome)
        voice_client = await self._conectar_para_som(guild, canal)
        if voice_client is None:
            return "Chama a Natty pra uma call primeiro (ou entra numa)."
        self._mudar_master(guild, dados["master"])
        self._mudar_ducking(guild, dados["ducking"])
        mixer = self._mixer(guild)
        queridos = {service.slug(a["som"]): a for a in dados["ambientes"]}
        for chave in list(mixer.ambientes):
            if chave not in queridos:
                mixer.parar_ambiente(chave)
        faltando = []
        for chave, ambiente in queridos.items():
            try:
                som = await asyncio.to_thread(service.buscar_som, guild.id, chave, "ambiente")
            except service.ErroDeColecao:
                faltando.append(ambiente["som"])
                continue
            mixer.tocar_ambiente(som["nome_chave"], self._fabrica_do_som(guild.id, som),
                                 ganho=ambiente["volume"] / 100, duck=som["duck"])
        partes = [f"🎬 Cena **{escape_markdown(nome)}**: {len(queridos) - len(faltando)} ambientes"]
        if dados["musica"]:
            try:
                _, musicas = await asyncio.to_thread(service.carregar_playlist, guild.id, dados["musica"]["playlist"])
                partes.append(await self._enfileirar(guild, voice_client.channel, None, musicas))
            except service.ErroDeColecao:
                faltando.append(f"playlist {dados['musica']['playlist']}")
        if faltando:
            partes.append("não achei: " + ", ".join(escape_markdown(f) for f in faltando))
        self._garantir_player(guild, voice_client)
        self._notificar(guild.id)
        return " · ".join(partes)

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
        self._mixer(guild).parar_tudo()
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
            "pausado": motor._mixer(guild).musica == "pausada",
            "desde": motor._tocando_desde.get(guild.id) if fila.tocando else None,
            "proximas": [_musica_para_o_painel(m) for m in fila.proximas],
            "repetir": fila.repetir,
            "repetir_fila": fila.repetir_fila,
            "volume": motor._volume(guild),
            "max_fila": service.MAX_FILA,
            "mixer": {
                "master": motor._master(guild),
                "ducking": motor._ducking(guild),
                "ambientes": [{"som": chave, "volume": round(a["volume"] * 100), "duck": a["duck"]}
                              for chave, a in motor._mixer(guild).ambientes.items()],
            },
        }

    # Comandos que o painel manda: nome → (precisa de quê, o que faz).
    COMANDOS = ("tocar", "pular", "pausar", "continuar", "parar", "volume", "repetir", "remover",
                "limpar_fila", "tocar_playlist", "salvar_playlist", "playlists",
                "sons", "som_tocar", "som_parar", "som_volume", "master", "ducking",
                "cenas", "cena_aplicar", "cena_salvar", "cena_apagar")

    async def executar(self, guild, membro, comando: str, args: dict) -> dict:
        """Roda um comando do painel pelo MESMO caminho do Discord. {"ok", "texto", "dados"?}.

        Quem chama já conferiu origem/sessão/membro; aqui só o que é regra do
        Bardo: comandar pede o cargo de mestre. Argumentos são validados aqui
        (vêm de fora).
        """
        if not self.pode_controlar(membro):
            return {"ok": False, "texto": f"Comandar a música pede o cargo {service.cargo_mestre()}."}
        if comando not in self.COMANDOS:
            return {"ok": False, "texto": "Comando desconhecido."}
        args = args if isinstance(args, dict) else {}
        motor = self._motor
        try:
            if comando == "tocar":
                texto = _texto(args.get("pedido"), 300)
                if not texto:
                    return {"ok": False, "texto": "Manda um link ou uma busca."}
                return {"ok": True, "texto": await self._tocar(guild, membro, texto)}
            if comando == "pular":
                return {"ok": True, "texto": motor._pular(guild)}
            if comando == "pausar":
                return {"ok": True, "texto": motor._pausar(guild)}
            if comando == "continuar":
                return {"ok": True, "texto": motor._continuar(guild)}
            if comando == "parar":
                return {"ok": True, "texto": await motor._parar(guild)}
            if comando == "limpar_fila":
                return {"ok": True, "texto": motor._limpar_fila(guild)}
            if comando == "volume":
                nivel = _inteiro(args.get("nivel"), 0, 100)
                if nivel is None:
                    return {"ok": False, "texto": "Volume vai de 0 a 100."}
                return {"ok": True, "texto": motor._mudar_volume(guild, service.Pedido("volume", volume=nivel))}
            if comando == "repetir":
                modo = args.get("modo")
                if modo not in ("faixa", "fila", "desligar"):
                    return {"ok": False, "texto": "Repetir: faixa, fila ou desligar."}
                pedido = (service.Pedido("repetir", repetir=False) if modo == "desligar"
                          else service.Pedido("repetir", repetir=True, alvo="fila" if modo == "fila" else None))
                return {"ok": True, "texto": motor._repetir(guild, pedido)}
            if comando == "remover":
                posicao = _inteiro(args.get("posicao"), 1, service.MAX_FILA)
                if posicao is None:
                    return {"ok": False, "texto": "Posição inválida."}
                return {"ok": True, "texto": motor._remover(guild, posicao)}
            if comando == "playlists":
                dados = await asyncio.to_thread(service.listar_playlists, guild.id)
                return {"ok": True, "texto": "", "dados": [{"nome": p["nome"], "quantas": p["quantas"]} for p in dados]}
            if comando == "salvar_playlist":
                fila = motor._fila(guild)
                musicas = [m for m in (fila.tocando, *fila.proximas) if m is not None]
                nome, quantas = await asyncio.to_thread(
                    service.salvar_playlist, guild.id, _texto(args.get("nome"), 100), musicas, membro.id,
                    bool(args.get("substituir")),
                )
                return {"ok": True, "texto": f"Salvei a playlist {nome} ({quantas} músicas)."}
            if comando == "sons":
                sons = await asyncio.to_thread(service.listar_sons, guild.id)
                return {"ok": True, "texto": "", "dados": [
                    {k: x[k] for k in ("nome", "nome_chave", "tipo", "volume", "duck", "tags")} for x in sons]}
            if comando == "som_tocar":
                return {"ok": True, "texto": _sem_negrito(await motor._som_tocar(
                    guild, self._canal_de_voz(guild, membro), _texto(args.get("nome"), 100)))}
            if comando == "som_parar":
                return {"ok": True, "texto": _sem_negrito(await motor._som_parar(
                    guild, _texto(args.get("nome"), 100) or None))}
            if comando in ("som_volume", "master", "ducking"):
                nivel = _inteiro(args.get("nivel"), 0, 100)
                if nivel is None:
                    return {"ok": False, "texto": "Vai de 0 a 100."}
                if comando == "master":
                    return {"ok": True, "texto": motor._mudar_master(guild, nivel)}
                if comando == "ducking":
                    return {"ok": True, "texto": motor._mudar_ducking(guild, nivel)}
                return {"ok": True, "texto": _sem_negrito(
                    await motor._som_volume(guild, _texto(args.get("nome"), 100), nivel))}
            if comando == "cenas":
                cenas = await asyncio.to_thread(service.listar_cenas, guild.id)
                return {"ok": True, "texto": "", "dados": [{"nome": c["nome"]} for c in cenas]}
            if comando == "cena_aplicar":
                return {"ok": True, "texto": _sem_negrito(await motor._cena_aplicar(
                    guild, self._canal_de_voz(guild, membro), _texto(args.get("nome"), 100)))}
            if comando == "cena_salvar":
                pads = args.get("pads") if isinstance(args.get("pads"), list) else None
                dados = motor._capturar_cena(guild, pads)
                return {"ok": True, "texto": _sem_negrito(await motor._cena_salvar(
                    guild, _texto(args.get("nome"), 100), membro.id, dados))}
            if comando == "cena_apagar":
                apagou = await asyncio.to_thread(service.apagar_cena, guild.id, _texto(args.get("nome"), 100))
                motor._notificar(guild.id)
                return {"ok": apagou, "texto": "Cena apagada." if apagou else "Essa cena não existe."}
            # tocar_playlist
            canal = self._canal_de_voz(guild, membro)
            if canal is None:
                return {"ok": False, "texto": "Entra num canal de voz (ou chama a Natty pra um) primeiro."}
            nome, musicas = await asyncio.to_thread(service.carregar_playlist, guild.id, _texto(args.get("nome"), 100))
            return {"ok": True, "texto": f"Playlist {nome}: " + await motor._enfileirar(guild, canal, None, musicas)}
        except service.ErroDeColecao as e:
            return {"ok": False, "texto": _sem_negrito(str(e))}
        except service.ArquivoNaoEncontrado:
            return {"ok": False, "texto": "O arquivo desse som sumiu da pasta da Natty."}

    async def enviar_som(self, guild, membro, nome: str, tipo: str, nome_do_arquivo: str, conteudo: bytes) -> dict:
        """Upload pelo painel: mesmas regras do /som enviar (lista branca, tamanho, nome por hash)."""
        if not self.pode_controlar(membro):
            return {"ok": False, "texto": f"Enviar som pede o cargo {service.cargo_mestre()}."}
        try:
            som = await asyncio.to_thread(service.guardar_som, guild.id, nome, tipo, nome_do_arquivo, conteudo,
                                          membro.id)
        except service.ErroDeColecao as e:
            return {"ok": False, "texto": _sem_negrito(str(e))}
        self._motor._notificar(guild.id)
        return {"ok": True, "texto": f"Guardei o {som['tipo']} {som['nome']}."}

    async def arquivo_do_som(self, guild, membro, nome: str):
        """Caminho do arquivo pra pré-escuta no painel (só quem é membro; o painel confere). None se não tem."""
        try:
            som = await asyncio.to_thread(service.buscar_som, guild.id, nome)
            return service.caminho_do_som(guild.id, som["arquivo"])
        except (service.ErroDeColecao, service.ArquivoNaoEncontrado):
            return None

    def _canal_de_voz(self, guild, membro):
        """Onde tocar um pedido do painel: a call em que a Natty já está; senão a de quem pediu."""
        voice_client = guild.voice_client
        if voice_client is not None and voice_client.is_connected():
            return voice_client.channel
        return getattr(getattr(membro, "voice", None), "channel", None)

    async def _tocar(self, guild, membro, texto: str) -> str:
        """Link ou busca, igual ao /tocar. Quem pediu pelo painel pode não estar na call: usa a da Natty."""
        canal = self._canal_de_voz(guild, membro)
        if canal is None:
            return "Entra num canal de voz (ou chama a Natty pra um) primeiro."
        pedinte = SimpleNamespace(voice=SimpleNamespace(channel=canal), id=membro.id)
        link = service.extrair_link(texto)
        if link:
            resposta = await self._motor._tocar(guild, pedinte, None, link)
        else:
            resposta = await self._motor._tocar_busca(guild, pedinte, None, texto)
        return _sem_negrito(resposta)


def _sem_negrito(texto: str) -> str:
    return texto.replace("**", "")


def _texto(valor, limite: int) -> str:
    return valor.strip()[:limite] if isinstance(valor, str) else ""


def _inteiro(valor, minimo: int, maximo: int) -> int | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor != int(valor):
        return None
    valor = int(valor)
    return valor if minimo <= valor <= maximo else None
