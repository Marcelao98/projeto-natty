"""
Módulo Echo — camada de serviço.

Duas ferramentas, sem nenhuma dependência de discord.py:

1. Detecção da senha "NAT20, por favor" com Vosk + grammar restrita:
   streaming, pacote a pacote, procurando só entre poucas frases fechadas
   em vez de no idioma inteiro. É o que o cog.py usa hoje — leve (~2% de
   CPU do tempo de fala, medido) e sem esperar transcrição.
2. Transcrição livre com Whisper local (offline, sem custo de API). O cog
   não usa mais pra detectar a senha, mas fica aqui pro dia em que for
   preciso entender comando livre depois dela ("rola 1d20"), e pra qualquer
   outro módulo (ex: transcrição de sessão inteira) chamar transcrever().

Nos dois casos, quem decide se o texto é a senha é tem_wake_word() (regex).
Echo não decide o que fazer com o comando reconhecido — isso é Dice, Bardo
etc. Ver README.md.
"""

from __future__ import annotations

import audioop  # removido do stdlib no 3.13; vem do pacote audioop-lts (dependência do discord.py)
import json
import os
import re
import tempfile
import time
import unicodedata
import wave
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# --- Vosk (detecção da senha em streaming) -----------------------------------

# Modelo baixado à mão de https://alphacephei.com/vosk/models (NÃO commitado:
# 31MB em muitos arquivos pequenos — ver README, "Como ativar").
PASTA_MODELO_VOSK = Path(__file__).parent / "assets" / "vosk-model-small-pt-0.3"
TAXA_VOSK = 16000

# Frases que o Vosk pode reconhecer. Grammar restrita só aceita palavras do
# vocabulário do modelo, e "nat" NÃO está lá (o Vosk descarta a palavra
# calado e sobra "vinte por favor"). Por isso o "NAT" entra pelas palavras
# existentes que soam parecido — testado com voz sintética: "néti vinte, por
# favor" saiu "net vinte por favor". Calibrar com a lista do log [echo].
# "[unk]" absorve qualquer fala fora da lista, pra ela não ser forçada a
# virar a senha.
PALAVRAS_PARECIDAS_COM_NAT = ("nate", "net", "nata", "neto", "nathan")
# O que pode vir logo depois da senha, na mesma frase ("NAT20, por favor,
# saia"). Precisa estar na grammar — palavra fora dela vira "[unk]" e some,
# igual o "dê" sumia. O Vosk aceita uma frase da lista seguida de outra.
PALAVRAS_SAIR = ("saia", "sai", "sair")
PALAVRAS_MUSICA = ("música",)
PALAVRAS_PARAR_MUSICA = ("pare", "para", "parar")  # para a música; a Natty continua na call
# Controles do Bardo por voz: palavra falada depois da senha -> o que vai
# depois de "natty" no texto que o Echo posta ("🎙️ natty pula"). O Bardo
# já entende todos por texto. "loop" não existe no vocabulário do modelo
# (nem "proxima" sem acento) — por voz é "repete" e "próxima".
COMANDOS_DO_BARDO_POR_VOZ = {
    "próxima": "pula", "pula": "pula", "pular": "pula",
    "repete": "repete", "repetir": "repete", "repita": "repete",
    "pausa": "pausa", "pausar": "pausa",
    "continua": "continua", "continuar": "continua",
}
# Frases inteiras na grammar (as três palavras precisam estar lá). Checadas
# ANTES de "pare/para": "para de repetir" desliga o loop, não para a música.
FRASES_PARAR_DE_REPETIR = ("para de repetir", "pare de repetir", "parar de repetir")
PALAVRAS_DEPOIS_DA_SENHA = (
    PALAVRAS_SAIR + PALAVRAS_MUSICA + PALAVRAS_PARAR_MUSICA + tuple(COMANDOS_DO_BARDO_POR_VOZ) + ("rolo",)
)
FRASES_VOSK = (
    [f"{p} vinte por favor" for p in PALAVRAS_PARECIDAS_COM_NAT]
    + list(PALAVRAS_DEPOIS_DA_SENHA)
    + list(FRASES_PARAR_DE_REPETIR)
    + ["[unk]"]
)

_MODELO_VOSK = None


def _carregar_vosk():
    """Carrega o modelo do Vosk uma única vez (mesmo padrão do _carregar_modelo do Whisper)."""
    global _MODELO_VOSK
    if _MODELO_VOSK is None:
        if not PASTA_MODELO_VOSK.is_dir():
            raise FileNotFoundError(
                f"falta o modelo {PASTA_MODELO_VOSK.name} em modules/echo/assets/ "
                "(baixar em alphacephei.com/vosk/models)"
            )
        import vosk

        vosk.SetLogLevel(-1)  # o Kaldi loga muito no stderr
        _MODELO_VOSK = vosk.Model(_caminho_ascii(PASTA_MODELO_VOSK))
    return _MODELO_VOSK


def _caminho_ascii(caminho: Path) -> str:
    """
    A biblioteca C do Vosk não abre caminho com acento no Windows ("Failed to
    create a model") — e o projeto mora em "Repositórios". Tenta o caminho
    relativo à pasta atual (o rodar_natty.bat roda da raiz do projeto); se
    ainda tiver acento, o nome curto 8.3 do Windows, que é só ASCII.
    """
    absoluto = str(caminho.resolve())
    if absoluto.isascii():
        return absoluto
    try:
        relativo = os.path.relpath(absoluto)
        if relativo.isascii():
            return relativo
    except ValueError:  # outro drive
        pass
    if os.name == "nt":
        import ctypes

        buffer = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(absoluto, buffer, len(buffer)) and buffer.value.isascii():
            return buffer.value
    return absoluto


def _criar_reconhecedor_vosk(sample_rate: int = TAXA_VOSK):
    """
    Reconhecedor NOVO a cada chamada: ele guarda o contexto da fala em
    andamento, então cada pessoa na call precisa do seu. O modelo é compartilhado.
    """
    import vosk

    # ensure_ascii=False: com o padrão, palavra acentuada vira "\\u00e9" e o
    # Vosk não acha no vocabulário.
    gramatica = json.dumps(FRASES_VOSK, ensure_ascii=False)
    return vosk.KaldiRecognizer(_carregar_vosk(), sample_rate, gramatica)


def resample_para_16k_mono(pcm_48k_stereo: bytes, sample_rate: int = 48000, canais: int = 2) -> bytes:
    """
    Converte o PCM que o Discord entrega (48kHz, estéreo, 16-bit) pra 16kHz
    mono 16-bit — o que Vosk (e a maioria dos motores de fala) espera. Sem
    estado entre chamadas: cada pacote do Discord (20ms) vira exatamente 320
    amostras, então reiniciar o ratecv a cada pacote não desalinha nada.
    """
    if not pcm_48k_stereo:
        return b""
    mono = audioop.tomono(pcm_48k_stereo, 2, 0.5, 0.5) if canais == 2 else pcm_48k_stereo
    convertido, _ = audioop.ratecv(mono, 2, 1, sample_rate, TAXA_VOSK, None)
    return convertido


def processar_chunk_vosk(reconhecedor, pcm_16k_mono: bytes) -> Optional[str]:
    """
    Alimenta o reconhecedor com um pedaço de áudio. Quando o próprio Vosk
    decide que a frase terminou, devolve o texto dela (que pode ser "" ou
    "[unk]"); enquanto a frase está em andamento, devolve None. Se é a
    senha, quem decide é tem_wake_word().
    """
    if reconhecedor.AcceptWaveform(pcm_16k_mono):
        return json.loads(reconhecedor.Result()).get("text", "")
    return None


# Energia (RMS, PCM 16-bit) a partir da qual um pacote conta como voz. Silêncio
# do Discord é 0; ruído de fundo de microfone fica na casa das dezenas.
LIMIAR_VOZ_RMS = 300


def tem_voz(pcm_16k_mono: bytes) -> bool:
    """True se o pacote tem energia de fala (não é silêncio nem chiado baixo)."""
    return bool(pcm_16k_mono) and audioop.rms(pcm_16k_mono, 2) >= LIMIAR_VOZ_RMS


def finalizar_vosk(reconhecedor) -> str:
    """Força o fim da frase em andamento e devolve o texto (pode ser "")."""
    return json.loads(reconhecedor.FinalResult()).get("text", "")


def juntar_pedacos_vosk(pedacos: list) -> str:
    """
    Junta as frases que o Vosk fechou a cada respiração numa fala só. O "[unk]"
    nas pontas de cada pedaço é ruído da pausa — sem tirar, ele cairia no MEIO
    da fala juntada e normalizar_comando_dado() rejeitaria tudo.
    """
    limpos = []
    for pedaco in pedacos:
        palavras = (pedaco or "").split()
        while palavras and palavras[0] == "[unk]":
            palavras.pop(0)
        while palavras and palavras[-1] == "[unk]":
            palavras.pop()
        if palavras:
            limpos.append(" ".join(palavras))
    return " ".join(limpos)


# --- Modo comando: rolagem de dados falada ------------------------------------
#
# Depois da senha, a pessoa tem alguns segundos pra falar uma rolagem ("rola
# dado vinte mais cinco com vantagem contra quinze"). Um segundo reconhecedor,
# com o vocabulário de rolagem, ouve; normalizar_comando_dado() converte pro
# texto que o Dice já entende ("rolo 1d20+5 com vantagem contra 15"), e o cog
# posta isso no canal. Tudo que o Dice entende por texto tem forma falada:
# vários dados, bônus, vantagem, CD, explosivo, filtros, teste por dado,
# reroll condicional, moedas e nome do teste (ver README, "Rolagem falada").
#
# Fala-se "dado vinte", não "um dê vinte": em call real (01/10/2026) o "dê"
# nunca chegou no texto — "rola um dê vinte" saiu "rola vinte". A palavra
# existe no vocabulário do modelo, mas uma letra sozinha (~100ms) é curta
# demais pra ele ouvir. "dado" é palavra comum e é como a mesa fala.

_UNIDADES = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
}
_DEZ_A_DEZENOVE = {
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14,
    "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
}
_DEZENAS = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60,
    "setenta": 70, "oitenta": 80, "noventa": 90,
}
_NUMEROS_FALADOS = {**_UNIDADES, **_DEZ_A_DEZENOVE, **_DEZENAS, "cem": 100}

LADOS_FALADOS = {2, 3, 4, 6, 8, 10, 12, 20, 100}  # dados de mesa: menos chance de ouvir errado
MAX_DADOS_FALADOS = 50  # o Dice ainda aplica os limites dele (100 dados, contando explosões)

_VERBOS = {"rola", "rolo", "role", "rolar", "jogo", "joga"}  # "role": o Vosk escreveu assim em call real
_PALAVRA_DADO = {"dado", "dados"}  # aceita as duas com qualquer quantidade: o plural é fácil de ouvir errado
_SINAIS = {"mais": "+", "menos": "-"}
_VANTAGENS = {"vantagem", "desvantagem"}
_EXPLOSIVO = {"explosivo", "explodindo", "explode"}
_CONTRA = {"contra", "dificuldade", "cd"}
_TIRA = {"tiro", "tirando", "tira"}
_MANTEM = {"mantenho", "mantendo", "mantém"}
_GATILHO = {"der", "cair", "tirar", "sair"}  # "se cair oito", "se o dado seis der seis"
_REPETE = {"novo", "novamente"}  # "de novo", "novamente", "outra vez"
_MOEDA = {"moeda", "moedas"}
# Perícias/testes de D&D 5e que existem no vocabulário do modelo ("arcanismo" e
# "furtividade" não existem). Só servem pro título da resposta do Dice.
_TESTES = {
    "ataque", "iniciativa", "dano", "força", "destreza", "constituição", "inteligência",
    "sabedoria", "carisma", "acrobacia", "atletismo", "atuação", "enganação", "história",
    "intimidação", "intuição", "investigação", "medicina", "natureza", "percepção",
    "persuasão", "prestidigitação", "religião", "sobrevivência", "resistência", "morte",
}
# Palavras de ligação que aparecem na fala e não mudam nada.
_LIGACAO = {"e", "com", "o", "a", "os", "de", "que", "ou", "igual", "se", "por", "cento",
            "outra", "vez", "menor", "menores", "maior", "maiores", "role", "ponderada",
            "ponderadas", "cara", "caras", "teste", "então"}

PALAVRAS_COMANDO_DADO = sorted(
    set(_NUMEROS_FALADOS) | _VERBOS | _PALAVRA_DADO | set(_SINAIS) | _VANTAGENS | _EXPLOSIVO
    | _CONTRA | _TIRA | _MANTEM | _GATILHO | _REPETE | _MOEDA | _TESTES | _LIGACAO
    | {"música"}  # "NAT20, por favor" → 👂 → "música": troca pro pedido de música (ver escolheu_musica)
)


def _criar_reconhecedor_comando_vosk(sample_rate: int = TAXA_VOSK):
    """
    Reconhecedor do modo comando. A grammar é uma lista de PALAVRAS soltas (não
    frases): o Vosk aceita qualquer sequência delas, então "rola dado vinte
    mais cinco" não precisa estar listado inteiro. Fala fora do tema vira
    "[unk]" ou lixo curto ("com"), que normalizar_comando_dado() rejeita.
    """
    import vosk

    gramatica = json.dumps(PALAVRAS_COMANDO_DADO + ["[unk]"], ensure_ascii=False)
    return vosk.KaldiRecognizer(_carregar_vosk(), sample_rate, gramatica)


def _juntar_numeros(palavras: list) -> list:
    """Troca números por extenso por int: "vinte e cinco" -> 25, "trinta" -> 30, "três" -> 3."""
    saida = []
    i = 0
    while i < len(palavras):
        p = palavras[i]
        if p in _DEZENAS:
            valor = _DEZENAS[p]
            # "vinte e cinco" — e também "vinte cinco": o Vosk às vezes engole o
            # "e" ("contra vinte e dois" saiu "contra vinte dois").
            if i + 2 < len(palavras) and palavras[i + 1] == "e" and _UNIDADES.get(palavras[i + 2], 0) > 0:
                valor += _UNIDADES[palavras[i + 2]]
                i += 2
            elif i + 1 < len(palavras) and _UNIDADES.get(palavras[i + 1], 0) > 0:
                valor += _UNIDADES[palavras[i + 1]]
                i += 1
            saida.append(valor)
        elif p in _NUMEROS_FALADOS:
            saida.append(_NUMEROS_FALADOS[p])
        else:
            saida.append(p)
        i += 1
    return saida


class _Leitor:
    """Cursor sobre as palavras já com números convertidos."""

    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def fim(self) -> bool:
        return self.i >= len(self.t)

    def olha(self, deslocamento: int = 0):
        j = self.i + deslocamento
        return self.t[j] if j < len(self.t) else None

    def eh(self, conjunto, deslocamento: int = 0) -> bool:
        x = self.olha(deslocamento)
        return isinstance(x, str) and x in conjunto

    def eh_numero(self, deslocamento: int = 0) -> bool:
        return isinstance(self.olha(deslocamento), int)

    def pega(self):
        x = self.t[self.i]
        self.i += 1
        return x

    def pula(self, *palavras) -> bool:
        """Consome a sequência exata de palavras, se estiver ali."""
        if all(self.olha(k) == w for k, w in enumerate(palavras)):
            self.i += len(palavras)
            return True
        return False

    def numero(self):
        return self.pega() if self.eh_numero() else None

    def quantidade(self):
        """
        Número numa posição de QUANTIDADE (dados, moedas, quantos tirar/manter).
        O Vosk ouve "três" como "treze" ("três moedas" saiu "treze moedas"), e
        13 dados/moedas é bem menos provável que 3 — então aqui 13 vira 3. Em
        CD, bônus e teste por dado, 13 continua 13.
        """
        n = self.numero()
        return 3 if n == 13 else n


# "dados seis" soa como "dezesseis" e "dados oito" como "dezoito": em call real
# "cinco dados seis maior que três" saiu "cinco dezesseis maior três". Como d16
# e d18 não são dados de mesa, "N dezesseis" / "dado dezesseis" só podem ser 6
# lados (e "dezoito", 8). Em CD e bônus ("contra dezesseis") nada muda.
_DADO_COLADO = {16: 6, 18: 8}


def _termo_de_dado(leitor: _Leitor):
    """[N] dado(s) M [explosivo] -> "NdM" ou "NdM!"; None se não houver dado aqui."""
    inicio = leitor.i
    if leitor.eh_numero() and leitor.eh_numero(1) and leitor.olha(1) in _DADO_COLADO:
        # "cinco dezesseis" = "cinco dados seis" (o "dados" grudou no número).
        qtd = leitor.quantidade()
        lados = _DADO_COLADO[leitor.pega()]
    else:
        qtd = leitor.quantidade() if leitor.eh_numero() and leitor.eh(_PALAVRA_DADO, 1) else 1
        if not leitor.eh(_PALAVRA_DADO):
            leitor.i = inicio
            return None
        leitor.pega()
        lados = leitor.numero()
        lados = _DADO_COLADO.get(lados, lados)  # "dado dezesseis" = "dados seis"
    if lados not in LADOS_FALADOS or not 1 <= qtd <= MAX_DADOS_FALADOS:
        leitor.i = inicio
        return None
    explosivo = ""
    if leitor.eh(_EXPLOSIVO):
        leitor.pega()
        explosivo = "!"
    return f"{qtd}d{lados}{explosivo}"


def _expressao(leitor: _Leitor):
    """termo ((mais|menos) (termo | número))* -> "1d20+1d6+3"; None se não começar com dado."""
    primeiro = _termo_de_dado(leitor)
    if primeiro is None:
        return None
    partes = [primeiro]
    while leitor.eh(_SINAIS):
        sinal = _SINAIS[leitor.pega()]
        termo = _termo_de_dado(leitor)
        if termo is None:
            n = leitor.numero()
            if n is None:
                return None
            termo = str(n)
        partes.append(f"{sinal}{termo}")
    return "".join(partes)


def _extras(leitor: _Leitor, extras: dict) -> bool:
    """
    Lê UM complemento depois da expressão e grava em `extras`. False se a
    próxima palavra não é complemento conhecido (ou repete um que já veio).
    """
    def guarda(chave, valor):
        if chave in extras:
            return False
        extras[chave] = valor
        return True

    leitor.pula("e")  # "com vantagem e contra quinze"

    # Vantagem/desvantagem: "com vantagem" ou só "vantagem".
    if leitor.eh(_VANTAGENS) or (leitor.olha() == "com" and leitor.eh(_VANTAGENS, 1)):
        leitor.pula("com")
        return guarda("vantagem", f"com {leitor.pega()}")

    # CD: "contra quinze", "dificuldade quinze", "cd quinze".
    if leitor.eh(_CONTRA):
        leitor.pega()
        n = leitor.numero()
        return n is not None and guarda("cd", f"contra {n}")

    # Filtros: "tirando o menor", "tiro os dois menores", "tiro dois";
    # "mantendo o maior", "mantenho os três maiores", "mantenho três".
    # Tolerante a artigo e número: "tirando o menor" já saiu "tirando menores".
    for palavras, chave, extremos in ((_TIRA, "tiro", ("menor", "menores")), (_MANTEM, "mantenho", ("maior", "maiores"))):
        if leitor.eh(palavras):
            leitor.pega()
            leitor.pula("os") or leitor.pula("o")
            n = leitor.quantidade()
            disse_extremo = leitor.pula(extremos[0]) or leitor.pula(extremos[1])
            if n is None and not disse_extremo:
                return False
            return guarda("filtro", f"{chave} {n or 1}")

    # Teste por dado: "maior que cinco", "maior ou igual a dez", "menor que três",
    # "menor ou igual a quatro", "igual a seis". O Dice entende igualzinho, com dígitos.
    for comeco in ("maior", "menor"):
        if leitor.olha() == comeco:
            leitor.pega()
            if leitor.pula("ou", "igual"):
                leitor.pula("a")
                n = leitor.numero()
                return n is not None and guarda("limiar", f"{comeco} ou igual a {n}")
            leitor.pula("que")
            n = leitor.numero()
            return n is not None and guarda("limiar", f"{comeco} que {n}")
    if leitor.pula("igual"):
        leitor.pula("a")
        n = leitor.numero()
        return n is not None and guarda("limiar", f"igual a {n}")

    # Reroll: "se oito rola de novo", "se cair vinte rola dado cem",
    # "se o dado seis der seis rola dado oito".
    if leitor.olha() == "se":
        leitor.pega()
        dado_gatilho = ""
        if leitor.pula("o") or leitor.eh(_PALAVRA_DADO):
            if not leitor.eh(_PALAVRA_DADO):
                return False
            leitor.pega()
            lados = leitor.numero()
            if lados is None or not leitor.eh(_GATILHO):
                return False
            dado_gatilho = f"o d{lados} der "
        if leitor.eh(_GATILHO):
            leitor.pega()
        valor = leitor.numero()
        if valor is None:
            return False
        leitor.pula("então")
        if not (leitor.eh(_VERBOS) or leitor.olha() == "role"):
            return False
        leitor.pega()
        if leitor.pula("de", "novo") or leitor.pula("novamente") or leitor.pula("outra", "vez"):
            return guarda("reroll", f"se {dado_gatilho}{valor} role de novo")
        termo = _termo_de_dado(leitor)
        if termo is None or termo.endswith("!"):
            return False
        return guarda("reroll", f"se {dado_gatilho}{valor} role {termo}")

    # Nome do teste no fim: "... teste de ataque".
    if leitor.olha() == "teste":
        leitor.pega()
        leitor.pula("de")
        if not leitor.eh(_TESTES):
            return False
        return guarda("teste", leitor.pega())

    return False


def _rolagem(leitor: _Leitor):
    """Expressão + complementos, no formato do Dice (sem o "rolo"). None se não entender tudo."""
    expressao = _expressao(leitor)
    if expressao is None:
        return None, None
    extras = {}
    while not leitor.fim():
        if leitor.eh(_SINAIS):
            # Bônus que veio depois de um complemento ("dado vinte com vantagem
            # mais dois"): volta pra expressão, que é onde o Dice procura.
            sinal = _SINAIS[leitor.pega()]
            termo = _termo_de_dado(leitor)
            n = None if termo else leitor.numero()
            if termo is None and n is None:
                return None, None
            expressao += f"{sinal}{termo or n}"
        elif not _extras(leitor, extras):
            return None, None
    # Ordem que o Dice lê bem: filtro e teste por dado DEPOIS da expressão (ele
    # só procura ali), CD em qualquer lugar, reroll por último.
    partes = [expressao] + [extras[k] for k in ("filtro", "vantagem", "limiar", "cd", "reroll") if k in extras]
    return " ".join(partes), extras.get("teste")


def _moedas(leitor: _Leitor):
    """
    "[N] moeda(s) [ponderada] [setenta por cento de cara] [se [der] [N] cara(s) rola <rolagem>]"
    -> "rolo 3 moedas 70% de cara se 2 caras role 1d6". None se não entender tudo.
    """
    qtd = leitor.quantidade() if leitor.eh_numero() else 1
    if not leitor.eh(_MOEDA):
        return None
    leitor.pega()
    texto = f"rolo {qtd} {'moeda' if qtd == 1 else 'moedas'}"
    leitor.pula("ponderada") or leitor.pula("ponderadas")
    leitor.pula("com")
    if leitor.eh_numero() and leitor.olha(1) == "por":
        pct = leitor.pega()
        if not (leitor.pula("por", "cento") and 0 <= pct <= 100):
            return None
        leitor.pula("de")
        if not (leitor.pula("cara") or leitor.pula("caras")):
            return None
        texto += f" {pct}% de cara"
    if leitor.fim():
        return texto
    if not leitor.pula("se"):
        return None
    if leitor.eh(_GATILHO) or leitor.olha() in ("derem", "caírem", "saírem"):
        leitor.pega()
    caras = leitor.quantidade() if leitor.eh_numero() else 1
    if not (leitor.pula("cara") or leitor.pula("caras")):
        return None
    leitor.pula("então")
    if not (leitor.eh(_VERBOS) or leitor.olha() == "role"):
        return None
    leitor.pega()
    rolagem, _ = _rolagem(leitor)
    if rolagem is None:
        return None
    return f"{texto} se {caras} {'cara' if caras == 1 else 'caras'} role {rolagem}"


def normalizar_comando_dado(texto: str) -> Optional[str]:
    """
    Converte a rolagem falada (como o Vosk escreve) pro texto que o Dice
    entende, ou None se sobrar qualquer palavra que não faça parte de uma
    rolagem — melhor "não entendi" que rolar a coisa errada.

        "rola dado vinte mais cinco com vantagem contra quinze"
            -> "rolo 1d20+5 com vantagem contra 15"
        "quatro dados seis tirando o menor"   -> "rolo 4d6 tiro 1"
        "dez dados oito maior que cinco"      -> "rolo 10d8 maior que 5"
        "dado oito se oito rola de novo"      -> "rolo 1d8 se 8 role de novo"
        "três moedas se duas caras rola dado seis" -> "rolo 3 moedas se 2 caras role 1d6"
        "teste de ataque dado vinte mais cinco"    -> "teste de ataque: rolo 1d20+5"
    """
    palavras = texto.lower().split()
    # "[unk]" nas pontas é ruído antes/depois da fala; no meio, algo não entendido.
    while palavras and palavras[0] == "[unk]":
        palavras.pop(0)
    while palavras and palavras[-1] == "[unk]":
        palavras.pop()
    if not palavras or "[unk]" in palavras:
        return None

    leitor = _Leitor(_juntar_numeros(palavras))
    teste = None
    if leitor.olha() == "teste":  # "teste de ataque, dado vinte..."
        leitor.pega()
        leitor.pula("de")
        if not leitor.eh(_TESTES):
            return None
        teste = leitor.pega()
    if leitor.eh(_VERBOS):
        leitor.pega()

    inicio = leitor.i
    moedas = _moedas(leitor)
    if moedas is not None:
        return moedas if teste is None else None
    leitor.i = inicio

    rolagem, teste_no_fim = _rolagem(leitor)
    if rolagem is None or (teste and teste_no_fim):
        return None
    teste = teste or teste_no_fim
    return f"teste de {teste}: rolo {rolagem}" if teste else f"rolo {rolagem}"


# --- Whisper (transcrição livre) ---------------------------------------------

_MODELO = None
NOME_MODELO_PADRAO = "base"

# Senha de ativação: "NAT20, por favor" (referência à designação dela,
# NAT/20-01-XR7-Δ9, e ao crítico natural de 20 no d20). Exige "por favor"
# junto de propósito, por dois motivos validados com Whisper real:
# 1. "NAT20" sozinho (frase de 1 palavra) faz o Whisper alucinar texto
#    ("24.", "Agunha TV") — frase mais longa transcreve certo e mais rápido.
# 2. Evita falso positivo quando alguém tira um nat 20 de verdade jogando
#    ("consegui um nat 20 na iniciativa!") sem querer ativar a Natty.
#
# O "NAT" é a parte que o Whisper mais erra: sem dica, ouviu "NAA-20",
# "Enheá-te 20", "N-A-T20", "INIATE 20". Duas defesas:
# - DICA_WHISPER (initial_prompt) ensina a grafia: com ela, a voz de teste
#   passou a sair "NAT20, por favor." — e silêncio/ruído continuaram vazios,
#   sem o Whisper "repetir a dica" (testado, 29/09/2026).
# - A regex aceita qualquer palavra curta com "n" no lugar do "nat" — quem
#   segura o falso positivo é o "20/vinte" + "por favor" logo em seguida.
#   Custo conhecido: "tenho 20, por favor" também ativa.
DICA_WHISPER = "NAT20, por favor."
_SENHA_RE = re.compile(
    r"(?<![\w-])[a-zà-ú.\-]{0,8}n[a-zà-ú.\-]{0,8}[\s\-]*(?:20|vinte|twenty)\b[\s,.!]*por\s+favor\b",
    re.IGNORECASE,
)


@dataclass
class Transcricao:
    texto: str
    idioma: str
    duracao_segundos: float


@dataclass
class Reconhecimento:
    """Resultado de ouvir um trecho de fala."""

    transcricao: Transcricao
    chamou_natty: bool
    comando: Optional[str]  # texto sem a wake word; None se não tem (ou se só disse o nome)


def _carregar_modelo(nome: str = NOME_MODELO_PADRAO):
    """Carrega o modelo Whisper uma única vez (download ~140MB pro "base", validado)."""
    global _MODELO
    if _MODELO is None:
        import whisper

        _MODELO = whisper.load_model(nome)
    return _MODELO


def transcrever(
    caminho_audio: str,
    idioma: Optional[str] = "pt",
    modelo: str = NOME_MODELO_PADRAO,
    dica: Optional[str] = DICA_WHISPER,
) -> Transcricao:
    """
    Transcreve um arquivo de áudio (wav/mp3/etc) em texto. Roda local, sem API paga.
    `dica` vai como initial_prompt: a da senha ajuda a grafia do "NAT20", mas
    atrapalharia um nome de música — o pedido de música passa dica=None.
    """
    m = _carregar_modelo(modelo)
    resultado = m.transcribe(caminho_audio, language=idioma, initial_prompt=dica)
    segmentos = resultado.get("segments") or []
    duracao = segmentos[-1]["end"] if segmentos else 0.0
    return Transcricao(
        texto=resultado["text"].strip(),
        idioma=resultado.get("language", idioma),
        duracao_segundos=duracao,
    )


def transcrever_pcm(
    pcm: bytes,
    sample_rate: int = 48000,
    canais: int = 2,
    amostra_bits: int = 16,
    idioma: Optional[str] = "pt",
    modelo: str = NOME_MODELO_PADRAO,
    dica: Optional[str] = DICA_WHISPER,
) -> Transcricao:
    """
    Mesma coisa que transcrever(), mas recebe PCM cru — o formato que
    discord-ext-voice-recv entrega por trecho de fala — em vez de um
    arquivo. Escreve um .wav temporário porque o Whisper já lê qualquer
    formato via ffmpeg, o que poupa reimplementar resample/downmix na mão.
    """
    # delete=False + limpeza manual: no Windows, um NamedTemporaryFile aberto
    # com delete=True não pode ser reaberto por outro processo (o wave/ffmpeg
    # tentando ler o .wav) enquanto o handle original ainda existe.
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        f.close()
        with wave.open(f.name, "wb") as wav_file:
            wav_file.setnchannels(canais)
            wav_file.setsampwidth(amostra_bits // 8)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm)
        return transcrever(f.name, idioma, modelo, dica)
    finally:
        os.unlink(f.name)


def tem_wake_word(texto: str) -> bool:
    """True se o texto contém a senha de ativação ("NAT20"), em qualquer posição."""
    return bool(_SENHA_RE.search(texto))


def extrair_comando(texto: str) -> Optional[str]:
    """
    Tira a senha e devolve o que vem depois dela ("NAT20, por favor, rola
    1d20" -> "rola 1d20"). None se o texto não tem a senha, ou se tem mas
    não sobra nada depois (só "NAT20, por favor" sozinho).
    """
    m = _SENHA_RE.search(texto)
    if not m:
        return None
    resto = texto[m.end():].strip(" ,.!?")
    return resto or None


def acao_depois_da_senha(texto: str) -> str:
    """
    Senha ouvida: o que fazer com o resto da frase. "sair" se veio "saia/sai/
    sair" ("nate vinte por favor saia"); "musica" se veio "música"; "rolar"
    pra todo o resto — senha sozinha, "rolo", ou ruído — que abre a janela
    da rolagem, como sempre.
    """
    resto = (extrair_comando(texto) or "").split()
    resto = [p for p in resto if p != "[unk]"]
    if comando_do_bardo_por_voz(texto):
        return "bardo"
    if resto and resto[0] in PALAVRAS_SAIR:
        return "sair"
    if resto and resto[0] in PALAVRAS_MUSICA:
        return "musica"
    if resto and resto[0] in PALAVRAS_PARAR_MUSICA:
        return "parar_musica"
    return "rolar"


def comando_do_bardo_por_voz(texto: str) -> Optional[str]:
    """
    Controle do Bardo falado depois da senha → o que vai depois de "natty"
    no texto pro Bardo, ou None. "nate vinte por favor próxima" -> "pula";
    "… para de repetir" -> "para de repetir" (antes do "para" virar parar).
    """
    resto = [p for p in (extrair_comando(texto) or "").split() if p != "[unk]"]
    if " ".join(resto[:3]) in FRASES_PARAR_DE_REPETIR:
        return "para de repetir"
    if resto and resto[0] in COMANDOS_DO_BARDO_POR_VOZ:
        return COMANDOS_DO_BARDO_POR_VOZ[resto[0]]
    return None


def escolheu_musica(texto: str) -> bool:
    """
    A janela da rolagem ouviu "música" ("NAT20, por favor" → 👂 → "música"):
    a pessoa quer pedir música, não rolar. A palavra está na grammar da rolagem.
    """
    palavras = [p for p in texto.split() if p != "[unk]"]
    return bool(palavras) and palavras[0] in PALAVRAS_MUSICA


# Verbos/chamados que a pessoa pode falar antes do nome da música ("toca
# Garçom") — o cog já posta "natty toca ...", então saem pra não duplicar.
_ANTES_DA_MUSICA_RE = re.compile(
    # "música" sozinho também sai: em call real, quem falou "música" e emendou
    # o nome teve o pedido gravado como "Música combate."
    r"^(?:(?:ei|oi)\b\W*)?(?:natty\b\W*)?(?:(?:toca|toque|tocar|bota|coloca|põe|poe)\b\W*)?(?:(?:a\s+)?música\b\W*)?",
    re.IGNORECASE,
)


def limpar_pedido_de_musica(texto: str) -> Optional[str]:
    """
    O que o Whisper ouviu → o que vai depois de "natty toca" pro Bardo buscar.
    None se não sobrar nada (silêncio, ou só pontuação).

        "Garçom."               -> "Garçom"
        "Toca Song of Storms."  -> "Song of Storms"
        "Natty, toca a música triste e épica" -> "triste e épica"
    """
    limpo = texto.strip().strip(" \t\n,.!?:;\"'")
    limpo = _ANTES_DA_MUSICA_RE.sub("", limpo).strip(" \t\n,.!?:;\"'")
    return limpo or None


def reconhecer(caminho_audio: str, idioma: str = "pt", modelo: str = NOME_MODELO_PADRAO) -> Reconhecimento:
    """Ponto de entrada principal: transcreve e já separa o comando, se houver."""
    transcricao = transcrever(caminho_audio, idioma, modelo)
    chamou = tem_wake_word(transcricao.texto)
    comando = extrair_comando(transcricao.texto) if chamou else None
    return Reconhecimento(transcricao=transcricao, chamou_natty=chamou, comando=comando)


# --- faster-whisper (Escriba: ata da sessão, feita depois de gravada) -------
#
# A Escriba grava o áudio de cada pessoa continuamente (sem transcrever nada
# em tempo real — não tem motivo pra isso, a ata é lida depois) e só
# transcreve quando a gravação acaba. Usa faster-whisper (não o openai-whisper
# da música) porque aqui o volume de áudio é grande (sessão inteira) e o
# backend CTranslate2 é bem mais rápido/leve de RAM — relevante com 8GB de
# RAM na máquina. compute_type="int8" mantém a RAM baixa.
#
# Modelo: "large-v3-turbo" (multilíngue, qualidade perto do large-v3, mais
# rápido até que o medium). Histórico: o "small" errou nomes e palavras
# soltas num teste real (02/10/2026: "Nhalor" -> "um trailer", "toco música"
# -> "copo a física"). O "distil-large-v3" foi descartado: os distil-whisper
# são treinados só em inglês. Se a RAM apertar, "small" ou "base".

NOME_MODELO_ESCRIBA = "large-v3-turbo"
_MODELO_ESCRIBA = None

# Velocidade (02/10/2026: ~75 min de fala levavam mais de 2h). O padrão do
# faster-whisper testa 5 hipóteses por trecho (beam_size=5) e usa 4 threads;
# com 1 hipótese a qualidade em português de mesa quase não muda e fica 2-3x
# mais rápido, e a máquina estava 75% ociosa com 4 threads. Uma thread por
# núcleo físico (os.cpu_count() conta os lógicos, o dobro com hyperthreading).
ESCRIBA_BEAM_SIZE = 1
ESCRIBA_CPU_THREADS = max(1, (os.cpu_count() or 2) // 2)

# O Whisper processa SEMPRE janelas de 30s: um bloco de 2s custa o mesmo que
# um de 30s. Numa sessão real, 80% dos blocos tinham menos de 10s ("ok",
# "rolo ataque") — 336 chamadas pra 40 min de fala. Por isso blocos seguidos
# da mesma pessoa vão juntos num pacote de até ESCRIBA_PACOTE_SEGUNDO, com um
# silêncio entre eles, e cada palavra volta pro bloco dela pelo horário
# (`word_timestamps`) — o horário real na ata continua certo.
ESCRIBA_PACOTE_SEGUNDO = 28.0

# Idioma fixo: com language=None o faster-whisper roda o encoder (a parte
# pesada) uma vez A MAIS em cada chamada só pra detectar o idioma, e não
# reaproveita — o dobro do trabalho. A mesa fala português; nomes em inglês
# saem bem assim mesmo.
ESCRIBA_IDIOMA = "pt"
ESCRIBA_SILENCIO_ENTRE_BLOCOS = 1.0

# Nomes próprios da campanha, passados como `hotwords` (dica de vocabulário
# pro Whisper): era justamente o que ele mais errava.
TERMOS_DA_CAMPANHA = (
    "Natty, Nhalor, Crossroads, Vorric, Elijah Vorren, Thalassar, "
    "Veyra, Sylvara, Gorvak, Luminara, Astryra, Avaris, Erebos"
)

# Falas seguidas da mesma pessoa com pausa menor que isso viram um parágrafo
# só na ata (o Whisper corta em pedaços de ~7-10s, e frases saíam partidas).
PAUSA_NOVO_PARAGRAFO_SEGUNDO = 4.5
# Parágrafo da ata não passa disso (do começo da 1ª fala ao fim da última):
# quem narra sem pausa viraria um bloco enorme e difícil de ler.
DURACAO_MAX_PARAGRAFO_SEGUNDO = 60.0


def _carregar_modelo_escriba(nome: str = NOME_MODELO_ESCRIBA):
    global _MODELO_ESCRIBA
    if _MODELO_ESCRIBA is None:
        from faster_whisper import WhisperModel

        _MODELO_ESCRIBA = WhisperModel(
            nome, device="cpu", compute_type="int8", cpu_threads=ESCRIBA_CPU_THREADS
        )
    return _MODELO_ESCRIBA


def nome_arquivo_seguro(nome: str) -> str:
    """Nome de pessoa -> nome de arquivo seguro (sem acento, espaço, barra)."""
    sem_acento = unicodedata.normalize("NFD", nome)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-zA-Z0-9]+", "-", sem_acento).strip("-").lower() or "pessoa"


def horario_real(offset: float, marcas: list) -> float:
    """
    Posição (segundos) dentro do .wav de uma pessoa -> horário real (epoch).

    O Discord só manda áudio ENQUANTO a pessoa fala: nos silêncios não chega
    pacote nenhum, então o .wav é só fala colada com fala — a posição no
    arquivo não é o tempo da sessão. Por isso o cog grava `marcas`: a cada
    volta da fala depois de uma pausa, [posição no arquivo, horário real].
    O horário de um ponto é o da última marca antes dele + o que andou desde
    ela. Sem marcas, devolve o próprio offset.
    """
    if not marcas:
        return offset
    i = bisect_right([m[0] for m in marcas], offset) - 1
    posicao, quando = marcas[max(i, 0)]
    return quando + (offset - posicao)


def _duracao_wav(caminho: Path) -> float:
    with wave.open(str(caminho), "rb") as w:
        return w.getnframes() / w.getframerate()


def _ler_wav_como_array(caminho: Path):
    """
    .wav 16-bit da Escriba (16kHz mono) -> array float32. O faster-whisper
    NÃO recebe o caminho: o 1.2.1 abre arquivo pelo PyAV, e o PyAV 19 recusa
    um parâmetro que ele passa (TypeError "metadata_errors", visto em
    02/10/2026). Com array o decodificador nem é chamado.
    """
    import numpy as np

    with wave.open(str(caminho), "rb") as w:
        dados = w.readframes(w.getnframes())
        if w.getnchannels() != 1 or w.getframerate() != TAXA_VOSK:
            dados = resample_para_16k_mono(dados, w.getframerate(), w.getnchannels())
    return np.frombuffer(dados, dtype=np.int16).astype(np.float32) / 32768.0


def transcrever_sessao(pasta: Path, inicio: float, progresso=None) -> Optional[Path]:
    """
    Transcreve todos os .wav de `pasta` (um arquivo por pessoa, gravado pelo
    cog.py) e escreve `pasta/ata.txt` em ordem cronológica, mesclando as
    falas de todo mundo pelo horário real de cada segmento (ver
    horario_real; `pasta/marcas.json` vem do cog). `vad_filter=True` pula o
    que não é fala. `pasta/nomes.json` mapeia arquivo -> nome de exibição.
    Sem marcas (gravação antiga/incompleta), usa `inicio` + offset.
    Devolve o caminho da ata, ou None se não achou fala em nenhum arquivo.

    `progresso(porcento, feito_s, total_s)`, se passado, é chamado a cada 10%
    do áudio transcrito (segundos de fala somando todo mundo) — pro log.

    Retomável: cada pacote transcrito vai na hora pra `pasta/parcial.jsonl`.
    Se cair no meio (falta de RAM, bot reiniciado), a próxima chamada pula o
    que já está lá e continua dali. O parcial some quando a ata fica pronta.
    """
    def ler_json(nome):
        caminho = pasta / nome
        return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}

    nomes, marcas = ler_json("nomes.json"), ler_json("marcas.json")
    modelo = _carregar_modelo_escriba()
    wavs = sorted(pasta.glob("*.wav"))
    total_s = sum(_duracao_wav(w) for w in wavs)
    feito_s, ultimo_aviso = 0.0, 0
    falas = []
    caminho_parcial = pasta / ARQUIVO_PARCIAL
    ja_feitos = _ler_parcial(caminho_parcial)
    with open(caminho_parcial, "a", encoding="utf-8") as parcial:
        for wav in wavs:
            nome = nomes.get(wav.name, wav.stem)
            marcas_do_arquivo = marcas.get(wav.name) or [[0.0, inicio]]
            audio = _ler_wav_como_array(wav)
            # Um bloco por trecho de fala separado por pausa real longa: o .wav não
            # tem os silêncios (o Discord não manda), então transcrevendo inteiro o
            # Whisper "colava" falas com 1 min de diferença num trecho só. Os blocos
            # vão em pacotes (ver ESCRIBA_PACOTE_SEGUNDO) e cada palavra volta pro
            # bloco de onde veio.
            blocos = blocos_de_fala(marcas_do_arquivo, len(audio) / TAXA_VOSK)
            for pacote in agrupar_blocos(blocos):
                feito_s += sum(fim - ini for ini, fim in pacote)
                chave = f"{wav.name}:{pacote[0][0]:.3f}-{pacote[-1][1]:.3f}"
                if chave in ja_feitos:  # transcrito numa tentativa anterior
                    falas.extend(ja_feitos[chave])
                    continue
                pedaco, pecas = _montar_pacote(audio, pacote)
                segmentos, _ = modelo.transcribe(
                    pedaco,
                    language=ESCRIBA_IDIOMA,
                    vad_filter=True,
                    hotwords=TERMOS_DA_CAMPANHA,
                    # Sem o texto anterior como contexto: com ele, no teste real
                    # (02/10/2026) o turbo repetiu uma frase e PULOU o final.
                    condition_on_previous_text=False,
                    beam_size=ESCRIBA_BEAM_SIZE,
                    word_timestamps=True,
                )
                novas = [
                    (horario_real(ini_wav, marcas_do_arquivo), horario_real(fim_wav, marcas_do_arquivo), nome, texto)
                    for ini_wav, fim_wav, texto in falas_por_bloco(segmentos, pecas)
                ]
                falas.extend(novas)
                parcial.write(json.dumps({"pacote": chave, "falas": novas}, ensure_ascii=False) + "\n")
                parcial.flush()
                porcento = int(feito_s / total_s * 100) if total_s else 100
                if progresso and porcento // 10 > ultimo_aviso // 10:
                    ultimo_aviso = porcento
                    progresso(porcento, feito_s, total_s)
    if not falas:
        caminho_parcial.unlink(missing_ok=True)
        return None
    caminho_ata = pasta / "ata.txt"
    with open(caminho_ata, "w", encoding="utf-8") as f:
        for quando, nome, texto in juntar_em_paragrafos(falas):
            hora = time.strftime("%H:%M:%S", time.localtime(quando))
            f.write(f"[{hora}] {nome}: {texto}\n")
    caminho_parcial.unlink(missing_ok=True)
    return caminho_ata


ARQUIVO_PARCIAL = "parcial.jsonl"


def _ler_parcial(caminho: Path) -> dict:
    """parcial.jsonl -> {chave do pacote: [falas]}. Linha cortada (caiu escrevendo) é ignorada."""
    feitos = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(linha)
                feitos[item["pacote"]] = [tuple(f) for f in item["falas"]]
            except (ValueError, KeyError, TypeError):
                continue
    return feitos


def agrupar_blocos(
    blocos: list,
    max_s: float = ESCRIBA_PACOTE_SEGUNDO,
    silencio: float = ESCRIBA_SILENCIO_ENTRE_BLOCOS,
) -> list:
    """
    [(início, fim)] -> pacotes [[(início, fim), ...]] de blocos seguidos que,
    com `silencio` entre eles, cabem em `max_s`. Bloco maior que `max_s` vai
    sozinho (o Whisper anda em janelas de 30s por conta própria).
    """
    pacotes, tamanho = [], 0.0
    for ini, fim in blocos:
        dur = fim - ini
        if pacotes and tamanho + silencio + dur <= max_s:
            pacotes[-1].append((ini, fim))
            tamanho += silencio + dur
        else:
            pacotes.append([(ini, fim)])
            tamanho = dur
    return pacotes


def _montar_pacote(audio, pacote: list, silencio: float = ESCRIBA_SILENCIO_ENTRE_BLOCOS):
    """
    Junta os blocos do pacote num áudio só, com silêncio entre eles. Devolve
    (áudio, peças) — peças = [(posição no pacote, início no .wav, duração)].
    """
    import numpy as np

    partes, pecas, pos = [], [], 0.0
    vazio = np.zeros(int(silencio * TAXA_VOSK), dtype=audio.dtype)
    for i, (ini, fim) in enumerate(pacote):
        if i:
            partes.append(vazio)
            pos += len(vazio) / TAXA_VOSK
        trecho = audio[int(ini * TAXA_VOSK):int(fim * TAXA_VOSK)]
        partes.append(trecho)
        pecas.append((pos, ini, len(trecho) / TAXA_VOSK))
        pos += len(trecho) / TAXA_VOSK
    return np.concatenate(partes), pecas


def falas_por_bloco(segmentos, pecas: list) -> list:
    """
    Segmentos do Whisper (com `words`) de um pacote -> [(início no .wav, fim
    no .wav, texto)], quebrando onde as palavras mudam de bloco: um segmento
    que atravessa o silêncio entre dois blocos (falas que na vida real tinham
    minutos entre si) vira duas falas, cada uma no horário dela. Sem palavras
    (não deveria acontecer), usa o segmento inteiro pelo começo.
    """
    inicios = [p[0] for p in pecas]

    def qual_peca(t):
        i = max(bisect_right(inicios, t) - 1, 0)
        pos, _, dur = pecas[i]
        if t > pos + dur and i + 1 < len(pecas):  # caiu no silêncio: é da próxima
            i += 1
        return i

    def no_wav(t, i):
        pos, ini, dur = pecas[i]
        return ini + min(max(t - pos, 0.0), dur)

    falas = []
    for s in segmentos:
        palavras = [(w.start, w.end, w.word) for w in (getattr(s, "words", None) or [])]
        if not palavras:
            palavras = [(s.start, s.end, s.text)]
        grupo, peca = [], None
        for palavra in palavras + [None]:
            i = qual_peca(palavra[0]) if palavra else None
            if grupo and i != peca:
                texto = "".join(p[2] for p in grupo).strip()
                if texto:
                    falas.append((no_wav(grupo[0][0], peca), no_wav(grupo[-1][1], peca), texto))
                grupo = []
            if palavra:
                grupo.append(palavra)
                peca = i
    return falas


def blocos_de_fala(marcas: list, duracao: float, pausa_min: float = PAUSA_NOVO_PARAGRAFO_SEGUNDO) -> list:
    """
    Divide o .wav de uma pessoa em blocos [início, fim) (segundos no arquivo)
    onde houve pausa REAL de pelo menos `pausa_min` entre uma marca e a
    próxima. A pausa real entre duas marcas = horário que passou − áudio que
    o arquivo andou. Sem marcas (ou uma só), um bloco com o arquivo todo.
    """
    if duracao <= 0:
        return []
    cortes = [0.0]
    for (pos_a, quando_a), (pos_b, quando_b) in zip(marcas, marcas[1:]):
        if (quando_b - quando_a) - (pos_b - pos_a) >= pausa_min and 0 < pos_b < duracao:
            cortes.append(pos_b)
    cortes.append(duracao)
    return [(a, b) for a, b in zip(cortes, cortes[1:]) if b > a]


def juntar_em_paragrafos(
    falas: list,
    pausa_max: float = PAUSA_NOVO_PARAGRAFO_SEGUNDO,
    duracao_max: float = DURACAO_MAX_PARAGRAFO_SEGUNDO,
) -> list:
    """
    [(início, fim, nome, texto)] de todo mundo -> [(início, nome, texto)] em
    ordem cronológica, juntando falas SEGUIDAS da mesma pessoa num parágrafo
    quando a pausa entre o fim de uma e o começo da outra é curta. Outra
    pessoa falando no meio, pausa longa, ou o parágrafo passar de
    `duracao_max` segundos abre linha nova.
    """
    paragrafos = []
    ultimo_fim = None
    for inicio, fim, nome, texto in sorted(falas, key=lambda f: f[0]):
        if (
            paragrafos
            and paragrafos[-1][1] == nome
            and inicio - ultimo_fim < pausa_max
            and fim - paragrafos[-1][0] <= duracao_max
        ):
            comeco, _, anterior = paragrafos[-1]
            paragrafos[-1] = (comeco, nome, f"{anterior} {texto}")
        else:
            paragrafos.append((inicio, nome, texto))
        ultimo_fim = fim
    return paragrafos


FORMATO_PASTA_SESSAO = "%Y-%m-%d-%Hh%M"


def inicio_da_pasta(pasta: Path) -> float:
    """Horário (epoch) em que a gravação começou, pelo nome da pasta; 0 se não der pra ler."""
    try:
        return time.mktime(time.strptime(pasta.name, FORMATO_PASTA_SESSAO))
    except ValueError:
        return 0.0


def sessao_esperando_transcricao(pasta_sessoes: Path, ignorar=()) -> Optional[Path]:
    """
    A sessão gravada mais recente que tem áudio e ainda não tem ata.txt; None
    se não houver. `ignorar`: pastas que já estão transcrevendo ou na fila.
    """
    if not pasta_sessoes.is_dir():
        return None
    candidatas = [
        p for p in pasta_sessoes.iterdir()
        if p.is_dir() and any(p.glob("*.wav")) and not (p / "ata.txt").exists() and p not in ignorar
    ]
    return max(candidatas, key=lambda p: p.stat().st_mtime, default=None)
