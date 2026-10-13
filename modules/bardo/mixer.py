"""Módulo Bardo — mixer: várias camadas de áudio numa saída só pro Discord.

O Discord toca UMA fonte por conexão. O MixerSource é essa fonte: a cada
20 ms o player do discord.py (na thread dele) chama read(), e o mixer soma
as camadas e devolve 3840 bytes (960 amostras × 2 canais × int16, 48 kHz).

Camadas, em três barramentos (bus):
  - música: uma faixa por vez (FFmpegPCMAudio), com fim avisado pro motor;
  - ambiente: N loops (chuva, taverna...) com volume e fade próprios;
  - efeito: one-shots já decodificados em memória (numpy) — o pad dispara
    sem esperar ffmpeg.

Regras que seguram o áudio:
  - Cada camada de stream tem uma thread leitora com ~1 s de buffer: um
    stream lento não trava a mistura (falta de dado = silêncio naquela camada).
  - Comandos (tocar, parar, volume...) entram numa fila e são aplicados no
    começo de cada read(): sem lock no caminho quente.
  - Soma em float32, ganho por camada e por bus com rampa (contra clique),
    ducking da música quando um efeito "duck" toca, e limiter suave no master.
  - O mixer vive no motor, não na conexão: se a call cai e volta, ele é
    tocado de novo na conexão nova (MotorBardo._garantir_player).

numpy e não audioop: o audioop saiu do Python 3.13.
"""

from __future__ import annotations

import collections
import itertools
import logging
import queue
import subprocess
import threading
from typing import Callable

import discord
import numpy as np

log = logging.getLogger(__name__)

TAXA = 48000
CANAIS = 2
AMOSTRAS = 960                       # 20 ms
BYTES_POR_QUADRO = AMOSTRAS * CANAIS * 2
SEGUNDOS_DE_BUFFER = 1.0
QUADROS_DE_BUFFER = int(SEGUNDOS_DE_BUFFER * TAXA / AMOSTRAS)
SILENCIO = bytes(BYTES_POR_QUADRO)
# Ocioso (sem camada nenhuma) por esse tempo, o mixer devolve b"" e o player
# para; o motor toca ele de novo quando precisar. Cobre o vão entre uma
# música e a próxima (resolver o link leva uns segundos) sem parar o player.
QUADROS_OCIOSO_ANTES_DE_PARAR = int(5 * TAXA / AMOSTRAS)
QUADROS_DE_RAMPA = 1                 # 20 ms: rampa mínima de qualquer mudança de ganho
LIMIAR_DO_LIMITER = 0.8
DUCK_ATAQUE_S = 0.05
DUCK_SOLTURA_S = 0.4


def _coeficiente(segundos: float) -> float:
    """Quanto do caminho até o alvo um envelope anda por quadro, pra chegar em ~63% em `segundos`."""
    return 1.0 - float(np.exp(-(AMOSTRAS / TAXA) / segundos))


def pcm_para_float(dados: bytes) -> np.ndarray:
    """int16 intercalado → float32 (n, 2) em [-1, 1]. Completa com silêncio se vier curto."""
    if len(dados) < BYTES_POR_QUADRO:
        dados = dados + bytes(BYTES_POR_QUADRO - len(dados))
    return np.frombuffer(dados[:BYTES_POR_QUADRO], dtype="<i2").reshape(-1, CANAIS).astype(np.float32) / 32768.0


def float_para_pcm(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def limiter(x: np.ndarray, limiar: float = LIMIAR_DO_LIMITER) -> np.ndarray:
    """Compressão suave acima do limiar (tanh): nunca passa de 1.0, e abaixo do limiar não mexe."""
    magnitude = np.abs(x)
    acima = magnitude > limiar
    if not acima.any():
        return x
    folga = 1.0 - limiar
    y = x.copy()
    y[acima] = np.sign(x[acima]) * (limiar + folga * np.tanh((magnitude[acima] - limiar) / folga))
    return y


def decodificar_arquivo(caminho: str, max_segundos: float = 30.0) -> np.ndarray:
    """Arquivo de áudio inteiro → float32 (n, 2) a 48 kHz, via ffmpeg. Pros efeitos (pads)."""
    processo = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", caminho, "-t", str(max_segundos),
         "-f", "s16le", "-ac", str(CANAIS), "-ar", str(TAXA), "-"],
        capture_output=True, check=True, timeout=60,
    )
    return np.frombuffer(processo.stdout, dtype="<i2").reshape(-1, CANAIS).astype(np.float32) / 32768.0


class Leitor:
    """Thread que lê quadros de uma fonte (tipo FFmpegPCMAudio) pra um buffer de ~1 s.

    `fabrica` cria a fonte; com `loop`, quando ela acaba cria outra (ambiente
    em loop). O mixer só pega o que já está no buffer: nunca espera a fonte.
    """

    def __init__(self, fabrica: Callable[[], object], loop: bool = False, quadros: int = QUADROS_DE_BUFFER):
        self._fabrica, self._loop = fabrica, loop
        self._buffer: collections.deque[bytes] = collections.deque()
        self._cheio = threading.Condition()
        self._max = quadros
        self._parar = threading.Event()
        self._fim = threading.Event()
        self.erro: Exception | None = None
        self._thread = threading.Thread(target=self._rodar, name="bardo-leitor", daemon=True)
        self._thread.start()

    def _rodar(self) -> None:
        fonte = None
        try:
            while not self._parar.is_set():
                fonte = self._fabrica()
                lidos = 0
                while not self._parar.is_set():
                    dados = fonte.read()
                    if not dados:
                        break
                    lidos += 1
                    with self._cheio:
                        while len(self._buffer) >= self._max and not self._parar.is_set():
                            self._cheio.wait(0.1)
                        self._buffer.append(dados)
                _limpar(fonte)
                fonte = None
                if not self._loop or lidos == 0:  # loop de arquivo vazio/quebrado não gira à toa
                    break
        except Exception as e:  # ffmpeg sumiu, arquivo ilegível...
            self.erro = e
            log.warning("Bardo: leitor de áudio parou: %s", e)
        finally:
            _limpar(fonte)
            self._fim.set()

    def proximo(self) -> bytes | None:
        """O próximo quadro, ou None se ainda não tem (ou acabou: ver `acabou`)."""
        try:
            dados = self._buffer.popleft()
        except IndexError:
            return None
        with self._cheio:
            self._cheio.notify()
        return dados

    @property
    def acabou(self) -> bool:
        return self._fim.is_set() and not self._buffer

    def parar(self) -> None:
        self._parar.set()
        with self._cheio:
            self._cheio.notify_all()


def _limpar(fonte) -> None:
    if fonte is not None:
        try:
            fonte.cleanup()
        except Exception:
            pass


class Camada:
    """Uma voz do mixer. `ganho` é o alvo; `atual` anda até ele em rampa (ou fade)."""

    def __init__(self, id_: str, bus: str, ganho: float = 1.0, fade_s: float = 0.0,
                 ao_terminar: Callable[[], None] | None = None, duck: bool = False):
        self.id, self.bus, self.ganho, self.duck = id_, bus, ganho, duck
        self.atual = 0.0 if fade_s > 0 else ganho
        self.passo = self._passo(fade_s, ganho)
        self.pausada = False
        self.saindo = False          # fade-out e tchau
        self.ao_terminar = ao_terminar

    @staticmethod
    def _passo(fade_s: float, ganho: float) -> float:
        quadros = max(QUADROS_DE_RAMPA, int(fade_s * TAXA / AMOSTRAS))
        return max(abs(ganho), 1e-3) / quadros

    def alvo(self) -> float:
        return 0.0 if (self.pausada or self.saindo) else self.ganho

    def andar(self) -> tuple[float, float]:
        """(ganho no começo do quadro, no fim) e já avança `atual`."""
        inicio, alvo = self.atual, self.alvo()
        if abs(alvo - inicio) <= self.passo:
            self.atual = alvo
        else:
            self.atual = inicio + self.passo * (1 if alvo > inicio else -1)
        return inicio, self.atual

    def quadro(self) -> np.ndarray | None:
        raise NotImplementedError

    @property
    def acabou(self) -> bool:
        raise NotImplementedError

    def fechar(self) -> None:
        pass


class CamadaStream(Camada):
    def __init__(self, id_, bus, fabrica, loop=False, **kw):
        super().__init__(id_, bus, **kw)
        self.leitor = Leitor(fabrica, loop=loop)

    def quadro(self):
        dados = self.leitor.proximo()
        return None if dados is None else pcm_para_float(dados)

    @property
    def acabou(self):
        return self.leitor.acabou

    def fechar(self):
        self.leitor.parar()


class CamadaMemoria(Camada):
    """One-shot (efeito) já decodificado: sem thread, sem latência."""

    def __init__(self, id_, bus, amostras: np.ndarray, **kw):
        super().__init__(id_, bus, **kw)
        self.amostras, self.pos = amostras, 0

    def quadro(self):
        if self.acabou:
            return None
        pedaco = self.amostras[self.pos:self.pos + AMOSTRAS]
        self.pos += AMOSTRAS
        if len(pedaco) < AMOSTRAS:
            pedaco = np.concatenate([pedaco, np.zeros((AMOSTRAS - len(pedaco), CANAIS), np.float32)])
        return pedaco

    @property
    def acabou(self):
        return self.pos >= len(self.amostras)


MUSICA = "musica"
AMBIENTE = "ambiente"
EFEITO = "efeito"


class MixerSource(discord.AudioSource):
    """A fonte única que o Discord toca. Métodos públicos são chamados do loop; read() da thread do player."""

    def __init__(self):
        self._comandos: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._camadas: dict[str, Camada] = {}
        self._ganho_bus = {MUSICA: 0.5, AMBIENTE: 1.0, EFEITO: 1.0}
        self._atual_bus = dict(self._ganho_bus)
        self._master = self._atual_master = 1.0
        self._duck_profundidade = 0.6       # quanto a música abaixa (0 = nada, 1 = some)
        self._envelope = 1.0
        self._ocioso = 0
        self._ids = itertools.count(1)
        self._geracao = 0                   # cada tocar_musica: só a música mais nova mexe no espelho
        # Espelhos pro loop ler sem esperar a thread do player (só o loop escreve).
        self.musica: str | None = None      # None, "tocando" ou "pausada"
        self.ambientes: dict[str, dict] = {}
        # False quando o read() devolveu b"" (o player parou): o motor toca de novo.
        self.ativo = False

    # -- API do loop (thread-safe: tudo vira comando) ------------------------------

    def _enviar(self, comando: Callable[[], None]) -> None:
        self._comandos.put(comando)

    def tocar_musica(self, fonte, ao_terminar: Callable[[], None] | None = None) -> None:
        """Troca a música (a anterior sai sem avisar o fim). `ao_terminar` roda NA THREAD DO PLAYER."""
        camada = CamadaStream(MUSICA, MUSICA, lambda: fonte, ao_terminar=ao_terminar)
        self._geracao += 1
        camada.geracao = self._geracao
        self.musica = "tocando"

        def aplicar():
            velha = self._camadas.pop(MUSICA, None)
            if velha is not None:
                velha.fechar()
            self._camadas[MUSICA] = camada
        self._enviar(aplicar)

    def parar_musica(self) -> None:
        """Fade curto e fim: o `ao_terminar` da música roda (o motor decide se anda a fila)."""
        self.musica = None

        def aplicar():
            camada = self._camadas.get(MUSICA)
            if camada is not None:
                camada.saindo = True
        self._enviar(aplicar)

    def pausar_musica(self, pausar: bool) -> None:
        if self.musica is None:
            return
        self.musica = "pausada" if pausar else "tocando"

        def aplicar():
            camada = self._camadas.get(MUSICA)
            if camada is not None:
                camada.pausada = pausar
        self._enviar(aplicar)

    def volume(self, bus: str, ganho: float) -> None:
        ganho = max(0.0, min(1.0, float(ganho)))
        self._enviar(lambda: self._ganho_bus.__setitem__(bus, ganho))

    def master(self, ganho: float) -> None:
        ganho = max(0.0, min(1.0, float(ganho)))

        def aplicar():
            self._master = ganho
        self._enviar(aplicar)

    def ducking(self, profundidade: float) -> None:
        profundidade = max(0.0, min(1.0, float(profundidade)))

        def aplicar():
            self._duck_profundidade = profundidade
        self._enviar(aplicar)

    def tocar_ambiente(self, id_: str, fabrica: Callable[[], object], ganho: float = 1.0, fade_s: float = 2.0,
                       duck: bool = False) -> None:
        """Liga um loop de ambiente com fade-in; se já está ligado, só muda volume/duck (sem abrir outro ffmpeg)."""
        ganho = max(0.0, min(1.0, float(ganho)))
        chave = f"{AMBIENTE}:{id_}"
        self.ambientes[id_] = {"volume": ganho, "duck": duck}

        def aplicar():
            camada = self._camadas.get(chave)
            if camada is not None and not camada.saindo:
                camada.ganho, camada.duck = ganho, duck
                camada.passo = Camada._passo(fade_s, max(ganho, camada.atual))
                return
            if camada is not None:
                camada.fechar()
            self._camadas[chave] = CamadaStream(chave, AMBIENTE, fabrica, loop=True, ganho=ganho, fade_s=fade_s,
                                                duck=duck)
        self._enviar(aplicar)

    def parar_ambiente(self, id_: str, fade_s: float = 2.0) -> None:
        chave = f"{AMBIENTE}:{id_}"
        self.ambientes.pop(id_, None)

        def aplicar():
            camada = self._camadas.get(chave)
            if camada is not None:
                camada.passo = Camada._passo(fade_s, camada.atual)
                camada.saindo = True
        self._enviar(aplicar)

    def disparar_efeito(self, amostras: np.ndarray, ganho: float = 1.0, duck: bool = False) -> None:
        ganho = max(0.0, min(1.0, float(ganho)))
        chave = f"{EFEITO}:{next(self._ids)}"
        self._enviar(lambda: self._camadas.__setitem__(
            chave, CamadaMemoria(chave, EFEITO, amostras, ganho=ganho, duck=duck)))

    def parar_tudo(self) -> None:
        """Fim de tudo (saiu da call): música sem avisar o fim, ambientes, efeitos."""
        self.musica = None
        self.ambientes.clear()

        def aplicar():
            for camada in self._camadas.values():
                camada.ao_terminar = None
                camada.fechar()
            self._camadas.clear()
        self._enviar(aplicar)

    # -- discord.AudioSource ---------------------------------------------------------

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        # O player chama isso quando para; o mixer continua vivo no motor.
        pass

    def read(self) -> bytes:
        while True:
            try:
                self._comandos.get_nowait()()
            except queue.Empty:
                break
            except Exception:
                log.exception("Bardo: comando do mixer falhou")

        if not self._camadas:
            self._ocioso += 1
            if self._ocioso > QUADROS_OCIOSO_ANTES_DE_PARAR:
                self._ocioso = 0
                self.ativo = False
                return b""
            return SILENCIO
        self._ocioso = 0

        barramentos = {MUSICA: np.zeros((AMOSTRAS, CANAIS), np.float32),
                       AMBIENTE: np.zeros((AMOSTRAS, CANAIS), np.float32),
                       EFEITO: np.zeros((AMOSTRAS, CANAIS), np.float32)}
        tem_duck = False
        for chave, camada in list(self._camadas.items()):
            if camada.pausada and camada.atual == 0.0:
                continue  # pausada: não consome a fonte
            if camada.saindo and camada.atual == 0.0:
                self._remover(chave, camada)
                continue
            quadro = camada.quadro()
            if quadro is None:
                if camada.acabou:
                    self._remover(chave, camada)
                continue  # stream atrasado: silêncio só nesta camada
            inicio, fim = camada.andar()
            if inicio == fim:
                barramentos[camada.bus] += quadro * fim
            else:
                barramentos[camada.bus] += quadro * np.linspace(inicio, fim, AMOSTRAS, dtype=np.float32)[:, None]
            tem_duck = tem_duck or (camada.duck and camada.bus != MUSICA)

        # Ducking: envelope no bus de música (ataque rápido, soltura lenta).
        alvo_env = 1.0 - self._duck_profundidade if tem_duck else 1.0
        coef = _coeficiente(DUCK_ATAQUE_S if alvo_env < self._envelope else DUCK_SOLTURA_S)
        env_inicio = self._envelope
        self._envelope += (alvo_env - self._envelope) * coef

        saida = np.zeros((AMOSTRAS, CANAIS), np.float32)
        for bus, sinal in barramentos.items():
            inicio, fim = self._atual_bus[bus], self._ganho_bus[bus]
            self._atual_bus[bus] = fim
            if bus == MUSICA:
                inicio, fim = inicio * env_inicio, fim * self._envelope
            if inicio == fim:
                saida += sinal * fim
            else:
                saida += sinal * np.linspace(inicio, fim, AMOSTRAS, dtype=np.float32)[:, None]
        inicio, self._atual_master = self._atual_master, self._master
        if inicio != self._master:
            saida *= np.linspace(inicio, self._master, AMOSTRAS, dtype=np.float32)[:, None]
        elif self._master != 1.0:
            saida *= self._master
        return float_para_pcm(limiter(saida))

    def _remover(self, chave: str, camada: Camada) -> None:
        self._camadas.pop(chave, None)
        camada.fechar()
        if camada.bus == MUSICA and getattr(camada, "geracao", None) == self._geracao:
            self.musica = None  # acabou (sozinha ou parada) e nenhuma outra foi pedida depois
        if camada.ao_terminar is not None:
            try:
                camada.ao_terminar()
            except Exception:
                log.exception("Bardo: aviso de fim de camada falhou")
