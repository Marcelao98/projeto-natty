"""Módulo Bardo — camada de serviço.

Reconhece pedidos de música em linguagem natural ("natty toca <link>",
"natty pausa", "natty volume 30") e resolve links do YouTube num stream de
áudio tocável. Segue o mesmo padrão do NAT-CORE: lógica pura aqui, sem
nenhuma dependência de discord.py, pra qualquer outro módulo (inclusive um
futuro módulo de LLM) poder chamar direto.

"natty toca <tema>" sem link vira busca booleana no dataset local
(dataset/musicas.json): "natty toca triste e bloodborne".
"""

from __future__ import annotations

import json
import random
import re
import shlex
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from modules.bardo import youtube

_YOUTUBE_URL_RE = re.compile(
    r"(https?://)?(www\.|music\.)?(youtube\.com/watch\?v=[\w-]+|youtu\.be/[\w-]+)(\S*)?",
    re.IGNORECASE,
)

_TOCAR_RE = re.compile(
    r"\b(toca|toque|tocar|bota|coloca|põe|poe|play|adiciona|adicione|add)\b", re.IGNORECASE
)
_PULAR_RE = re.compile(r"\b(pula|pule|pular|pr[oó]xima|skip|next)\b", re.IGNORECASE)
_FILA_RE = re.compile(r"\b(fila|playlist|queue)\b", re.IGNORECASE)
_LIMPAR_RE = re.compile(r"\b(limpa|limpe|limpar|esvazia|esvazie|apaga|zera|clear)\b", re.IGNORECASE)
_PAUSAR_RE = re.compile(r"\b(pausa|pause|pausar)\b", re.IGNORECASE)
_CONTINUAR_RE = re.compile(
    r"\b(continua|continue|continuar|despausa|retoma|volta|resume)\b", re.IGNORECASE
)
_PARAR_RE = re.compile(r"\b(para|pare|parar|stop|chega|desliga|sai|sair)\b", re.IGNORECASE)
_REPETIR_RE = re.compile(r"\b(repete|repetir|repita|loop)\b", re.IGNORECASE)
# "para de repetir", "repete não", "chega de loop", "desliga o repetir".
_DESLIGAR_REPETIR_RE = re.compile(r"\b(n[ãa]o|para|pare|parar|chega|desliga|tira)\b", re.IGNORECASE)
_VOLUME_RE = re.compile(r"\bvolume\b", re.IGNORECASE)
_AUMENTAR_RE = re.compile(r"\b(aumenta|sobe|mais alto)\b", re.IGNORECASE)
_DIMINUIR_RE = re.compile(r"\b(abaixa|baixa|diminui|mais baixo)\b", re.IGNORECASE)
_NUMERO_RE = re.compile(r"\b(\d{1,3})\s*%?")

VOLUME_PADRAO = 50  # %; o áudio do YouTube a 100% fica alto demais no Discord
PASSO_VOLUME = 20  # %; quanto "aumenta"/"abaixa" o volume mexe
MAX_FILA = 50  # músicas esperando, sem contar a que está tocando

# Flags de reconexão recomendadas pelo próprio discord.py para streaming via
# FFmpeg: sem elas, uma soluço de rede na fonte derruba o playback de vez.
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# Música que "acaba" antes disso sem ninguém pular não tocou de verdade: o
# YouTube às vezes recusa a URL de áudio (403) e o FFmpeg sai sem som.
SEGUNDOS_PARA_FALHA_RAPIDA = 5


def opcoes_ffmpeg(http_headers: dict[str, str] | None = None) -> dict[str, str]:
    """FFMPEG_OPTIONS com os headers que o yt-dlp usou pra resolver a URL.

    Sem eles o FFmpeg se apresenta com o User-Agent dele, e o YouTube
    recusa a URL de áudio com mais frequência.
    """
    if not http_headers:
        return dict(FFMPEG_OPTIONS)
    headers = "".join(f"{k}: {v}\r\n" for k, v in http_headers.items())
    return {
        "before_options": f"{FFMPEG_OPTIONS['before_options']} -headers {shlex.quote(headers)}",
        "options": FFMPEG_OPTIONS["options"],
    }


@dataclass(frozen=True)
class Pedido:
    """O que pediram pra Natty fazer com a música.

    acao: "tocar", "pausar", "continuar", "parar", "volume", "pular", "fila",
        "limpar_fila" ou "repetir".
    link: só em "tocar"; None se pediram pra tocar sem mandar link.
    busca: só em "tocar" sem link; o que vem depois do verbo ("triste e
        bloodborne"), pra buscar_musicas(). None se não sobrou nada.
    volume: só em "volume"; valor absoluto (0-100) pedido.
    delta_volume: só em "volume"; +/-PASSO_VOLUME para "aumenta"/"abaixa".
    Em "volume" sem número nem direção, os dois ficam None (é pergunta).
    repetir: só em "repetir"; False = desligar ("para de repetir", "repete
        não"), None = alternar ("natty repete" liga, de novo desliga).
    """

    acao: str
    link: str | None = None
    busca: str | None = None
    volume: int | None = None
    delta_volume: int | None = None
    repetir: bool | None = None


def interpretar_pedido(texto: str) -> Pedido | None:
    """Traduz um pedido em linguagem natural num Pedido, ou None se não for de música.

    Não verifica se o texto é dirigido à Natty — isso é com o cog, que exige
    menção de verdade (@Natty ou o cargo). Escrever só "natty" não basta.
    """
    link = extrair_link_youtube(texto)
    # O link sai antes das outras regras: "para" ou "volta" dentro de uma
    # URL não pode virar comando.
    sem_link = _YOUTUBE_URL_RE.sub(" ", texto)

    if link and _TOCAR_RE.search(sem_link):
        return Pedido("tocar", link=link)
    # Fila antes de parar/tocar: "natty limpa a fila" não é "para", e
    # "natty toca a próxima" é pular, não pedido sem link.
    if _FILA_RE.search(sem_link) and _LIMPAR_RE.search(sem_link):
        return Pedido("limpar_fila")
    # Repetir antes de parar: "natty para de repetir" desliga o loop, não para
    # a música. Mas se "toca" vem antes, é busca ("natty toca Repete Comigo").
    repetir = _REPETIR_RE.search(sem_link)
    tocar_antes = _TOCAR_RE.search(sem_link)
    if repetir and not (tocar_antes and tocar_antes.start() < repetir.start()):
        desligar = _DESLIGAR_REPETIR_RE.search(sem_link)
        return Pedido("repetir", repetir=False if desligar else None)
    if _PULAR_RE.search(sem_link):
        return Pedido("pular")
    if _FILA_RE.search(sem_link):
        return Pedido("fila")
    if _VOLUME_RE.search(sem_link) or _AUMENTAR_RE.search(sem_link) or _DIMINUIR_RE.search(sem_link):
        return _pedido_de_volume(sem_link)
    if _PAUSAR_RE.search(sem_link):
        return Pedido("pausar")
    if _CONTINUAR_RE.search(sem_link):
        return Pedido("continuar")
    # Depois de pausar/continuar: "natty para de pausar" é esquisito, mas
    # "natty para de tocar" tem que parar, não pedir link. Quem vem primeiro
    # decide: em "natty toca uma música para relaxar" o "para" é preposição.
    parar = _PARAR_RE.search(sem_link)
    tocar = _TOCAR_RE.search(sem_link)
    if parar and _para_de_outra_coisa(sem_link[parar.end():]):
        # "natty para de transcrever" é comando do Echo (Escriba), não do
        # Bardo: "para de X" só para a música se X for tocar/cantar/música.
        return None
    if parar and not (tocar and tocar.start() < parar.start()):
        return Pedido("parar")
    if tocar:
        # A menção (<@id>) e o nome da Natty vêm antes do verbo, então o que
        # sobra depois dele é só a busca.
        busca = sem_link[tocar.end():].strip(" \t\n,.!?:;")
        return Pedido("tocar", busca=busca or None)
    return None


_PARA_DE_RE = re.compile(r"^\s+de\s+(\w+)", re.IGNORECASE)
_O_QUE_O_BARDO_PARA = {"tocar", "tocando", "cantar", "cantando", "música", "musica", "som", "barulho"}


def _para_de_outra_coisa(depois_do_para: str) -> bool:
    """True em "para de X" quando X não é música: "para de transcrever", "para de pausar"."""
    m = _PARA_DE_RE.match(depois_do_para)
    return bool(m) and m.group(1).lower() not in _O_QUE_O_BARDO_PARA


def _pedido_de_volume(texto: str) -> Pedido:
    numero = _NUMERO_RE.search(texto)
    if numero:
        return Pedido("volume", volume=limitar_volume(int(numero.group(1))))
    if _AUMENTAR_RE.search(texto):
        return Pedido("volume", delta_volume=PASSO_VOLUME)
    if _DIMINUIR_RE.search(texto):
        return Pedido("volume", delta_volume=-PASSO_VOLUME)
    return Pedido("volume")


def limitar_volume(volume: int) -> int:
    return max(0, min(100, volume))


def novo_volume(atual: int, pedido: Pedido) -> int:
    """Volume (0-100) depois de aplicar um Pedido de volume sobre `atual`."""
    if pedido.volume is not None:
        return pedido.volume
    if pedido.delta_volume is not None:
        return limitar_volume(atual + pedido.delta_volume)
    return atual


@dataclass(frozen=True)
class Musica:
    titulo: str
    # O link, não a URL do stream: a URL de áudio do YouTube expira, então
    # quem toca resolve de novo na hora.
    link: str
    duracao_segundos: int | None = None


class FilaCheia(Exception):
    pass


class Fila:
    """A música tocando e as que esperam a vez, de um servidor.

    Só guarda estado; quem toca de verdade (cog.py) chama avancar() quando
    uma música acaba — ou, com `repetir` ligado, toca a mesma de novo
    (deve_repetir).
    """

    def __init__(self):
        self.tocando: Musica | None = None
        self._proximas: deque[Musica] = deque()
        # Repetir a faixa ATUAL (não a fila): quando ela acaba sozinha, volta
        # do começo em vez de avançar. Pular e parar desligam.
        self.repetir: bool = False

    def alternar_repetir(self, pedido: Pedido) -> bool:
        """Aplica um Pedido("repetir") e devolve o estado novo (None = alternar, False = desligar)."""
        self.repetir = (not self.repetir) if pedido.repetir is None else pedido.repetir
        return self.repetir

    def deve_repetir(self, musica: Musica) -> bool:
        """`musica` acabou sozinha: toca de novo? Só se o repetir está ligado e ela ainda é a atual."""
        return self.repetir and self.tocando is musica

    @property
    def proximas(self) -> tuple[Musica, ...]:
        return tuple(self._proximas)

    def adicionar(self, musica: Musica) -> int:
        """Põe no fim da fila e devolve a posição (1 = a próxima a tocar)."""
        if len(self._proximas) >= MAX_FILA:
            raise FilaCheia(f"A fila já tem {MAX_FILA} músicas.")
        self._proximas.append(musica)
        return len(self._proximas)

    def adicionar_varias(self, musicas: list[Musica]) -> int:
        """Põe no fim da fila as que couberem (até MAX_FILA) e devolve quantas entraram."""
        cabem = MAX_FILA - len(self._proximas)
        entram = musicas[: max(cabem, 0)]
        self._proximas.extend(entram)
        return len(entram)

    def avancar(self) -> Musica | None:
        """Passa pra próxima música (que vira a `tocando`) e a devolve; None se acabou."""
        self.tocando = self._proximas.popleft() if self._proximas else None
        return self.tocando

    def limpar(self) -> int:
        """Tira as músicas que esperam (a atual continua). Devolve quantas saíram."""
        quantas = len(self._proximas)
        self._proximas.clear()
        return quantas

    def resetar(self) -> None:
        """Esvazia tudo, inclusive a atual (e desliga o repetir)."""
        self.limpar()
        self.tocando = None
        self.repetir = False


# ---------------------------------------------------------------------------
# Dataset e busca booleana em linguagem natural
#
# Query como "triste e bloodborne" ou "boss fight e elden ring ou hollow
# knight" ou "calmo e fire emblem sem batalha" (sem = exclui o termo).
# "e" combina (AND), "ou" separa grupos alternativos (OR), "sem"/"não" na
# frente de um termo nega ele. O "ou" tem precedência menor: "a e b ou c"
# é "(a e b) ou c". Um termo bate com a faixa se:
#   - aparece (substring, sem acento) no nome da faixa, na origem, nos temas
#     ou nas categorias; ou
#   - é sinônimo de uma categoria da faixa, segundo o vocabulario.json
#     ("tragico" acha as faixas da categoria "triste").
# ---------------------------------------------------------------------------

_DATASET_PATH = Path(__file__).parent / "dataset" / "musicas.json"
_VOCABULARIO_PATH = Path(__file__).parent / "dataset" / "vocabulario.json"

# Se a busca achar mais que isso, sorteia: algumas franquias do dataset têm
# 200+ faixas, e enfileirar tudo prenderia a mesa numa franquia por horas.
MAX_RESULTADOS_DA_BUSCA = 15

_FILLER_WORDS = {
    "musica", "musicas", "som", "sons", "faixa", "faixas", "trilha", "sonora",
    "algo", "alguma", "algum", "uma", "um", "umas", "uns",
    "de", "do", "da", "dos", "das", "a", "o", "as", "os",
    "para", "pra", "pro", "com", "no", "na", "nos", "nas", "em",
    "tipo", "bem", "muito", "mais", "clima", "cena", "hora", "estilo", "vibe",
}

_dataset_cache: list[dict] | None = None


def carregar_dataset(caminho: Path | None = None) -> list[dict]:
    """Carrega (com cache em memória) o dataset de músicas taggeadas."""
    global _dataset_cache
    if caminho is not None:
        # Uso principalmente em teste: não usa o cache global.
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)["musicas"]
    if _dataset_cache is None:
        with open(_DATASET_PATH, encoding="utf-8") as f:
            _dataset_cache = json.load(f)["musicas"]
    return _dataset_cache


@dataclass(frozen=True)
class Vocabulario:
    """vocabulario.json já normalizado.

    sinonimos: palavra que as pessoas digitam → categorias que ela puxa.
    por_tema: tema cru do dataset → categorias que ele dá à faixa.
    """

    sinonimos: dict[str, frozenset[str]]
    por_tema: dict[str, frozenset[str]]


_vocabulario_cache: Vocabulario | None = None


def _com_feminino(palavras: set[str]) -> set[str]:
    """Acrescenta o feminino das palavras soltas: "animado" → "animada", "assustador" → "assustadora".

    O vocabulario.json fica só no masculino; quem digita (ou marca o tema)
    "animada" ou "sombria" cai na mesma categoria.
    """
    femininos = set()
    for p in palavras:
        if " " in p:
            continue
        if p.endswith("o") and not p.endswith("ao"):
            femininos.add(p[:-1] + "a")
        elif p.endswith("or"):
            femininos.add(p + "a")
    return palavras | femininos


def montar_vocabulario(bruto: dict) -> Vocabulario:
    """Monta o Vocabulario a partir do conteúdo do vocabulario.json."""
    sinonimos: dict[str, set[str]] = {}
    por_tema: dict[str, set[str]] = {}
    for categoria, spec in bruto["categorias"].items():
        palavras = _com_feminino({_normalizar(p) for p in [categoria, *spec.get("palavras", [])]})
        for p in palavras:
            sinonimos.setdefault(p, set()).add(categoria)
        # Toda palavra também conta como tema; os "temas" só puxam a faixa.
        for t in palavras | _com_feminino({_normalizar(t) for t in spec.get("temas", [])}):
            por_tema.setdefault(t, set()).add(categoria)
    return Vocabulario(
        {k: frozenset(v) for k, v in sinonimos.items()},
        {k: frozenset(v) for k, v in por_tema.items()},
    )


def carregar_vocabulario() -> Vocabulario:
    """Carrega (com cache em memória) o vocabulário de categorias."""
    global _vocabulario_cache
    if _vocabulario_cache is None:
        with open(_VOCABULARIO_PATH, encoding="utf-8") as f:
            _vocabulario_cache = montar_vocabulario(json.load(f))
    return _vocabulario_cache


def categorias_dos_temas(temas: list[str], vocabulario: Vocabulario | None = None) -> list[str]:
    """Categorias que os temas crus de uma faixa dão a ela, em ordem alfabética."""
    vocabulario = vocabulario or carregar_vocabulario()
    categorias: set[str] = set()
    for tema in temas:
        categorias |= vocabulario.por_tema.get(_normalizar(tema), frozenset())
    return sorted(categorias)


def _normalizar(texto: str) -> str:
    """minúsculas, sem acento — pra 'É Pico' bater com 'epico'."""
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _texto_buscavel(musica: dict) -> str:
    partes = [
        musica["nome"], musica["origem"]["nome"], musica["origem"]["tipo"],
        *musica["temas"], *musica.get("categorias", []),
    ]
    return _normalizar(" ".join(partes))


def _parse_query(texto: str) -> list[list[tuple[bool, str]]]:
    """'triste e bloodborne ou calmo sem triste' ->
    [[(F,'triste'),(F,'bloodborne')], [(F,'calmo'),(T,'triste')]]

    Formato: lista de grupos OR; cada grupo é uma lista de termos AND,
    cada termo é (negado: bool, termo: str). 'e' separa termo normal,
    'sem'/'nao' separa termo negado — ambos funcionam como ponto de corte
    dentro do grupo (não precisam vir logo no início dele).
    """
    texto = _normalizar(texto)
    grupos = []
    for bruto_ou in re.split(r"\bou\b", texto):
        # captura o separador junto: ['termo0', 'e'|'sem'|'nao', 'termo1', ...]
        pedacos = re.split(r"\b(e|sem|nao)\b", bruto_ou)
        termos = []
        negado_atual = False
        for pedaco in pedacos:
            pedaco = pedaco.strip()
            if pedaco in ("e", "sem", "nao"):
                negado_atual = pedaco in ("sem", "nao")
                continue
            palavras = [p for p in pedaco.split() if p not in _FILLER_WORDS]
            termo_limpo = " ".join(palavras).strip()
            if termo_limpo:
                termos.append((negado_atual, termo_limpo))
            negado_atual = False
        if termos:
            grupos.append(termos)
    return grupos


def _contem(alvo: str, categorias: set[str], termo: str, vocabulario: Vocabulario) -> bool:
    return termo in alvo or bool(vocabulario.sinonimos.get(termo, frozenset()) & categorias)


def _termo_bate(alvo: str, categorias: set[str], negado: bool, termo: str, vocabulario: Vocabulario) -> bool:
    # Primeiro a frase inteira ("boss fight", "hollow knight"); se não bater,
    # cada palavra por si ("luta chefe" = luta e chefe).
    contido = _contem(alvo, categorias, termo, vocabulario) or (
        " " in termo and all(_contem(alvo, categorias, p, vocabulario) for p in termo.split())
    )
    return (not contido) if negado else contido


def _musica_bate(musica: dict, grupos_ou: list[list[tuple[bool, str]]], vocabulario: Vocabulario) -> bool:
    alvo = _texto_buscavel(musica)
    categorias = set(musica.get("categorias", []))
    return any(
        all(_termo_bate(alvo, categorias, negado, termo, vocabulario) for negado, termo in grupo_and)
        for grupo_and in grupos_ou
    )


def buscar_por_tags(
    texto_busca: str, dataset: list[dict] | None = None, vocabulario: Vocabulario | None = None
) -> list[dict]:
    """Busca booleana em linguagem natural no dataset de músicas.

    Retorna as entradas do dataset que batem com a query; lista vazia se
    nada bate ou se a query só tinha palavras de preenchimento.
    """
    grupos = _parse_query(texto_busca)
    if not grupos:
        return []
    musicas = dataset if dataset is not None else carregar_dataset()
    vocabulario = vocabulario or carregar_vocabulario()
    return [m for m in musicas if _musica_bate(m, grupos, vocabulario)]


def buscar_musicas(
    texto_busca: str, dataset: list[dict] | None = None, vocabulario: Vocabulario | None = None
) -> tuple[list[Musica], int]:
    """buscar_por_tags() já no formato da fila, sorteando até MAX_RESULTADOS_DA_BUSCA.

    Devolve (músicas escolhidas, quantas bateram no total).
    """
    resultados = buscar_por_tags(texto_busca, dataset, vocabulario)
    if len(resultados) > MAX_RESULTADOS_DA_BUSCA:
        escolhidas = random.sample(resultados, MAX_RESULTADOS_DA_BUSCA)
    else:
        escolhidas = resultados
    return [Musica(m["nome"], m["link"]) for m in escolhidas], len(resultados)


def extrair_link_youtube(texto: str) -> str | None:
    """Extrai a primeira URL de YouTube encontrada no texto, ou None."""
    m = _YOUTUBE_URL_RE.search(texto)
    return m.group(0) if m else None


def resolver_musica(url: str) -> dict:
    """Resolve um link de YouTube em algo tocável.

    Retorna {"titulo": str, "stream_url": str, "duracao_segundos": int|None,
    "http_headers": dict} — os headers vão pro FFmpeg via opcoes_ffmpeg().
    """
    return youtube.resolver_stream(url)


# ---------------------------------------------------------------------------
# Busca livre no YouTube e aprendizado por confirmação
#
# Quando a busca no dataset não acha nada, o cog busca o texto direto no
# YouTube, toca, e pergunta no canal se era essa e quais temas ela tem. A
# pergunta fica "em aberto" por servidor (uma pendência); a próxima mensagem
# no canal responde. Confirmando, a faixa entra no dataset.
# ---------------------------------------------------------------------------

SEGUNDOS_PARA_RESPONDER = 180  # depois disso a pendência vence sem resposta
MAX_TEMAS_DESCOBERTA = 5
NAO_CLASSIFICADO = "não classificado"
ORIGEM_DESCOBERTA = {"nome": "Descoberta em mesa", "tipo": "outro"}

_NEGACAO_RE = re.compile(r"\bn[ãa]o\b", re.IGNORECASE)
_SEPARADOR_DE_TEMAS_RE = re.compile(r"\s*(?:[,;/\n]|\s\be\b\s)\s*", re.IGNORECASE)
# Confirmação e conversa que não é tema ("sim, é essa mesmo").
_PALAVRAS_DE_CONFIRMACAO = {
    "sim", "s", "isso", "isso ai", "é", "e", "era", "essa", "esse", "ela", "ele", "mesmo", "mesma",
    "exato", "exatamente", "certo", "certa", "aham", "uhum", "ok", "okay", "yes", "sure", "natty",
    "ei", "oi", "ô", "ai", "aí", "tem", "temas", "tema", "ela é", "seria", "acho", "que", "boa", "ótima", "otima",
}
_TEM_PALAVRA_RE = re.compile(r"[^\W\d_]{3,}")  # "1d20" ou "ss" não viram tema


class MusicaJaNoDataset(Exception):
    """A descoberta já está no dataset (mesmo vídeo); .musica é a entrada que existe."""

    def __init__(self, musica: dict):
        super().__init__(musica["nome"])
        self.musica = musica


_pendencias: dict[int, dict] = {}  # guild_id → pergunta em aberto


def resolver_por_busca_livre(texto: str) -> dict:
    """Busca `texto` no YouTube e resolve o primeiro resultado em algo tocável.

    Mesmo retorno de resolver_musica(), mais "link" (o link de watch, que
    não expira — é ele que vai pro dataset). LookupError se não achar nada.
    """
    return youtube.buscar_stream(texto)


def criar_pendencia(
    guild_id: int,
    titulo: str,
    link: str,
    canal_id: int | None = None,
    agora: float | None = None,
    mensagem_pergunta_id: int | None = None,
) -> dict:
    """
    Abre (ou substitui) a pergunta "era essa?" do servidor e a devolve.

    `mensagem_pergunta_id` é a mensagem da Natty com a pergunta: só um REPLY a
    ela conta como resposta (ver eh_resposta_da_pendencia). Quando a pergunta
    sai junto da resposta do pedido, o id ainda não existe na hora de criar —
    o cog completa com registrar_pergunta_da_pendencia depois de enviar.
    """
    pendencia = {
        "titulo": titulo,
        "link": link,
        "canal_id": canal_id,
        "criado_em": time.time() if agora is None else agora,
        "mensagem_pergunta_id": mensagem_pergunta_id,
    }
    _pendencias[guild_id] = pendencia
    return pendencia


def registrar_pergunta_da_pendencia(guild_id: int, mensagem_id: int) -> None:
    """Grava o id da mensagem com o "era essa?" na pendência aberta que ainda não tem."""
    pendencia = _pendencias.get(guild_id)
    if pendencia is not None and pendencia.get("mensagem_pergunta_id") is None:
        pendencia["mensagem_pergunta_id"] = mensagem_id


def eh_resposta_da_pendencia(guild_id: int, respondendo_a: int | None, agora: float | None = None) -> bool:
    """
    A mensagem é resposta ao "era essa?"? Só se for um REPLY à mensagem da
    pergunta (`respondendo_a` = message.reference.message_id). Antes valia
    qualquer mensagem que chamasse a Natty em 3 min — e um "@Natty escuta" /
    "@Natty transcreve" (de outro módulo) virou tema de música no acervo.
    """
    pendencia = pendencia_do_servidor(guild_id, agora)
    return (
        pendencia is not None
        and respondendo_a is not None
        and pendencia.get("mensagem_pergunta_id") == respondendo_a
    )


def pendencia_do_servidor(guild_id: int, agora: float | None = None) -> dict | None:
    """A pergunta em aberto do servidor; None se não tem, ou se venceu (aí já limpa)."""
    pendencia = _pendencias.get(guild_id)
    if pendencia is None:
        return None
    agora = time.time() if agora is None else agora
    if agora - pendencia["criado_em"] > SEGUNDOS_PARA_RESPONDER:
        limpar_pendencia(guild_id)
        return None
    return pendencia


def limpar_pendencia(guild_id: int) -> None:
    _pendencias.pop(guild_id, None)


def interpretar_resposta_de_pendencia(texto: str) -> list[str] | None:
    """Resposta a "era essa? que temas ela tem?" → temas, ou None se disseram que não.

    "sim, é triste e épico" → ["triste", "épico"]; "não" → None; "sim" → []
    (confirmou a música, mas não deu tema).
    """
    if _NEGACAO_RE.search(texto):
        return None
    # Tira menção (<@123>), emoji e pontuação; mantém letras, números, hífen.
    limpo = re.sub(r"<[@#:][^>]*>", " ", texto.lower())
    limpo = re.sub(r"[^\w\s,;/\n-]", " ", limpo)
    temas: list[str] = []
    for pedaco in _SEPARADOR_DE_TEMAS_RE.split(limpo):
        palavras = [p for p in pedaco.split() if p not in _PALAVRAS_DE_CONFIRMACAO and p not in _FILLER_WORDS]
        tema = " ".join(palavras)
        if tema and tema not in _PALAVRAS_DE_CONFIRMACAO and _TEM_PALAVRA_RE.search(tema) and tema not in temas:
            temas.append(tema)
    return temas[:MAX_TEMAS_DESCOBERTA]


def adicionar_descoberta_ao_dataset(
    titulo: str, link: str, temas: list[str], caminho: Path | None = None
) -> dict:
    """Grava uma música descoberta em mesa no musicas.json e devolve a entrada.

    Sem temas, entra como "não classificado". Levanta MusicaJaNoDataset se o
    vídeo já estiver lá. Com `caminho` (teste), não mexe no cache da busca.
    """
    arquivo = caminho or _DATASET_PATH
    dataset = json.loads(arquivo.read_text(encoding="utf-8"))
    musicas = dataset["musicas"]

    video = video_id(link)
    for m in musicas:
        if video_id(m["link"]) == video:
            raise MusicaJaNoDataset(m)

    ids = {m["id"] for m in musicas}
    base = f"{slug(ORIGEM_DESCOBERTA['nome'])}-{slug(titulo) or video.lower()}"
    id_, n = base, 2
    while id_ in ids:
        id_, n = f"{base}-{n}", n + 1

    temas = temas or [NAO_CLASSIFICADO]
    entrada = {
        "id": id_,
        "nome": titulo,
        "link": f"https://www.youtube.com/watch?v={video}",
        "escopo": "faixa_individual",
        "origem": dict(ORIGEM_DESCOBERTA),
        "temas": temas,
        "categorias": categorias_dos_temas(temas),
        "comentario_pessoal": "",
    }
    musicas.append(entrada)
    arquivo.write_text(formatar_dataset(dataset), encoding="utf-8")

    if caminho is None and _dataset_cache is not None:
        _dataset_cache.append(entrada)  # a busca já acha a faixa, sem reiniciar
    return entrada


# ---------------------------------------------------------------------------
# Utilitários do dataset (também usados pelos scripts/ de manutenção)
# ---------------------------------------------------------------------------

# Ordem dos campos de cada faixa no arquivo, pra ficar legível no diff.
_ORDEM_DOS_CAMPOS = ["id", "nome", "link", "escopo", "origem", "temas", "categorias", "comentario_pessoal"]


def formatar_dataset(dataset: dict) -> str:
    """musicas.json no formato do arquivo à mão: uma faixa por bloco, um campo por linha."""
    faixas = []
    for m in dataset["musicas"]:
        chaves = [k for k in _ORDEM_DOS_CAMPOS if k in m] + [k for k in m if k not in _ORDEM_DOS_CAMPOS]
        campos = ",\n".join(f"      {json.dumps(k)}: {json.dumps(m[k], ensure_ascii=False)}" for k in chaves)
        faixas.append("    {\n" + campos + "\n    }")
    comentario = json.dumps(dataset["_comentario"], ensure_ascii=False)
    return "{\n" f'  "_comentario": {comentario},\n' '  "musicas": [\n' + ",\n".join(faixas) + "\n  ]\n}\n"


def slug(texto: str) -> str:
    """'Queen's Gardens' -> 'queens-gardens' (sem acento, só [a-z0-9-])."""
    texto = _normalizar(texto)
    texto = re.sub(r"['’]", "", texto)
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")


def video_id(link: str) -> str:
    """Id do vídeo de um link do YouTube (watch?v=, youtu.be/); o próprio texto se não achar."""
    m = re.search(r"(?:[?&]v=|youtu\.be/)([\w-]+)", link)
    return m.group(1) if m else link
