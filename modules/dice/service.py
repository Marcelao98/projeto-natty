"""
Rolagem de dados em linguagem natural. Lógica pura, sem discord.py.

    roll("eu rolo 1d20+5 com vantagem, Teste de Ataque vs CD 15")
    roll("rolo 4d6! tiro 1")   # explosivo e tira o menor
    roll("rolo 10d8, maior que 5")  # conta quantos dados passam
"""

import random
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .coins import CoinFlip, flip_coin
from .conditional_rerolls import (
    ConditionalReroll,
    RerollResult,
    apply_conditional_reroll,
    parse_conditional_reroll,
)

# Limites contra mensagens que travariam o bot (ex: "rolo 99999999d99999999").
MAX_DADOS = 100
MAX_LADOS = 1000
MAX_TERMOS = 20

# Padrões compartilhados com detector.py.
# Um dado aceita explosivo (!, !!, !!!) e filtro colado: t = tira os menores,
# m/k/kh = mantém os maiores. Ex: "4d6!t1", "4d6kh3".
_SUFIXO = r"(?:!{1,3})?(?:(?:kh|k|t|m)\d+)?"
DADO = rf"(?<![\w])(\d*)d(\d+)(!{{0,3}})(?:(kh|k|t|m)(\d+))?(?![\w])"
_DADO_SEM_GRUPO = rf"(?<![\w])\d*d\d+{_SUFIXO}(?![\w])"
EXPRESSAO = rf"{_DADO_SEM_GRUPO}(?:\s*[+-]\s*(?:{_DADO_SEM_GRUPO}|\d+(?![\w])))*"
DESVANTAGEM = r"(?<!sem )\b(?:desvantagem|desvant|disadvantage|dis)\b"
VANTAGEM = r"(?<!sem )\b(?:vantagem|vant|advantage|adv)\b"
DC = r"\b(?:vs\.?|contra|dc|cd)\s*(?:(?:dc|cd)\s*)?(\d+)\b"
# Filtro por extenso: "tiro 1", "tiro os 2 menores", "mantenho 3", "mantenho o maior".
TIRA = r"\b(?:tiro|tira|tirando|descarto|descarta)\s+(?:(?:os?\s+)?(\d+)|o\s+menor)\b"
MANTEM = r"\b(?:mantenho|mant[ée]m|mantendo)\s+(?:(?:os?\s+)?(\d+)|o\s+maior)\b"

# Teste por dado: "maior que 5", "menor ou igual a 3", "igual a 6", ">= 10".
LIMIAR = (
    r"(?:\b(maior|menor)\s+(?:(?:do\s+)?que\s+)?(ou\s+igual\s+(?:a\s+)?)?"
    r"|\b(igual)\s+(?:a\s+)?|(>=|<=|≥|≤|>|<|=)\s*)(\d+)\b"
)
# Operador de cada forma e o seu contrário (usado nas falhas).
_OPERADOR = {("maior", False): ">", ("maior", True): ">=", ("menor", False): "<",
             ("menor", True): "<=", ("igual", False): "="}
_SIMBOLO = {"≥": ">=", "≤": "<="}
CONTRARIO = {">": "<=", ">=": "<", "<": ">=", "<=": ">", "=": "!="}
_COMPARA = {
    ">": lambda v, x: v > x, ">=": lambda v, x: v >= x,
    "<": lambda v, x: v < x, "<=": lambda v, x: v <= x, "=": lambda v, x: v == x,
}

_TERMO = re.compile(rf"([+-])\s*(?:{DADO}|(\d+))", re.IGNORECASE)
_TESTE = re.compile(r"\bteste\s+(?:de\s+)?(\w+)", re.IGNORECASE)


@dataclass
class Termo:
    """Um grupo de dados da expressão, ex: "-2d6" ou "4d6!t1"."""
    expressao: str             # "4d6!t1" (filtro por extenso vira a forma curta)
    sinal: int                 # +1 ou -1
    rolagens: List[int]        # dados rolados (sem as explosões)
    descartado: Optional[int]  # d20 descartado por vantagem/desvantagem
    subtotal: int              # soma dos dados mantidos, já com o sinal
    lados: int = 0
    explosoes: List[int] = field(default_factory=list)  # dados extras das explosões
    filtro: Optional[str] = None  # "t" (tira os menores) ou "m" (mantém os maiores)
    filtro_qtd: int = 0
    removidos: List[int] = field(default_factory=list)  # dados tirados pelo filtro

    @property
    def mantidos(self) -> List[int]:
        """Dados que contam no total: sem o d20 descartado e sem os removidos."""
        dados = list(self.rolagens)
        if self.descartado is not None:
            dados.remove(self.descartado)
        dados += self.explosoes
        for v in self.removidos:
            dados.remove(v)
        return dados


@dataclass
class ThresholdTest:
    """Teste por dado ("maior que 5"): quais dados mantidos passam."""
    operador: str                  # ">", ">=", "<", "<=", "="
    valor: int
    dados: List[int]               # todos os dados mantidos, em ordem
    sucessos: List[int]            # os que passaram, em ordem
    falhas: List[int]              # os que não passaram, em ordem

    @property
    def success_count(self) -> int:
        return len(self.sucessos)

    @property
    def failure_count(self) -> int:
        return len(self.falhas)

    @property
    def percentual(self) -> int:
        return round(100 * len(self.sucessos) / len(self.dados)) if self.dados else 0


@dataclass
class RollResult:
    expressao: str                     # "1d20+1d6+5"
    termos: List[Termo]
    bonus: int                         # soma dos números fixos (pode ser negativa)
    modificador: Optional[str]         # "vantagem", "desvantagem" ou None
    final: int
    teste: Optional[str]               # "ataque", "destreza"...
    dc: Optional[int]
    resultado: Optional[str]           # "sucesso", "falha", "crítico" ou None (sem CD)
    natural: Optional[int] = None      # valor do d20 usado, se houver
    avisos: List[str] = field(default_factory=list)
    conditional_reroll_result: Optional[RerollResult] = None  # só se o reroll ativou
    threshold: Optional[ThresholdTest] = None  # só se a mensagem pediu teste por dado


@dataclass
class _Parte:
    """Um termo já validado, antes de rolar. `qtd` 0 = número fixo (`valor`)."""
    sinal: int
    qtd: int = 0
    lados: int = 0
    explosivo: int = 0         # quantos "!"
    filtro: Optional[str] = None
    filtro_qtd: int = 0
    valor: int = 0

    @property
    def expressao(self) -> str:
        filtro = f"{self.filtro}{self.filtro_qtd}" if self.filtro else ""
        return f"{self.qtd}d{self.lados}{'!' * self.explosivo}{filtro}"


def _modificador(texto: str) -> Optional[str]:
    # Desvantagem primeiro: "desvantagem" contém "vantagem".
    texto = texto.lower()
    if re.search(DESVANTAGEM, texto):
        return "desvantagem"
    if re.search(VANTAGEM, texto):
        return "vantagem"
    return None


def parse_threshold_test(texto: str):
    """(operador, valor) de "maior que 5" / ">= 10" / "igual a 6", ou None."""
    m = re.search(LIMIAR, texto, re.IGNORECASE)
    if not m:
        return None
    if m.group(4):
        operador = _SIMBOLO.get(m.group(4), m.group(4))
    else:
        operador = _OPERADOR[((m.group(1) or m.group(3)).lower(), bool(m.group(2)))]
    return operador, int(m.group(5))


def _filtro_por_extenso(texto: str):
    """("t" ou "m", quantidade) de "tiro 1" / "mantenho 3", ou None."""
    for filtro, padrao in (("t", TIRA), ("m", MANTEM)):
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            return filtro, int(m.group(1) or 1)
    return None


def _preparar(user_input: str, conditional_reroll: Optional[ConditionalReroll] = None):
    """
    Acha e valida a expressão (limites incluindo o reroll). Não rola nada.
    Retorna (expressão, partes, onde a expressão termina em user_input).
    """
    m = re.search(EXPRESSAO, user_input, re.IGNORECASE)
    if not m:
        raise ValueError("Não achei nenhum dado para rolar (ex: 1d20+5).")
    expressao = re.sub(r"\s+", "", m.group(0)).lower()

    matches = list(_TERMO.finditer("+" + expressao))
    if len(matches) > MAX_TERMOS:
        raise ValueError(f"Expressão longa demais (máximo {MAX_TERMOS} termos).")

    partes: List[_Parte] = []
    for p in matches:
        sinal = -1 if p.group(1) == "-" else 1
        if p.group(3) is None:
            partes.append(_Parte(sinal, valor=int(p.group(7))))
            continue
        filtro = p.group(5) and ("t" if p.group(5) == "t" else "m")  # k/kh = m
        partes.append(_Parte(
            sinal, int(p.group(2) or 1), int(p.group(3)), len(p.group(4)),
            filtro, int(p.group(6) or 0),
        ))

    # "tiro 1" / "mantenho 3" valem para o último dado da expressão.
    por_extenso = _filtro_por_extenso(user_input[m.end():])
    if por_extenso:
        ultimo = [p for p in partes if p.qtd][-1]
        if ultimo.filtro:
            raise ValueError(f"{ultimo.expressao} já tem filtro; use só um (tiro ou mantenho).")
        ultimo.filtro, ultimo.filtro_qtd = por_extenso

    total_dados = 0
    for p in partes:
        if not p.qtd and not p.lados:
            continue
        if p.qtd < 1 or p.lados < 1:
            raise ValueError("Quantidade e lados dos dados precisam ser pelo menos 1.")
        if p.lados > MAX_LADOS:
            raise ValueError(f"Dado grande demais (máximo d{MAX_LADOS}).")
        if p.filtro == "t" and not 1 <= p.filtro_qtd < p.qtd:
            raise ValueError(f"Não dá pra tirar {p.filtro_qtd} de {p.qtd}d{p.lados}: não sobraria nenhum dado.")
        if p.filtro == "m" and not 1 <= p.filtro_qtd <= p.qtd:
            raise ValueError(f"Não dá pra manter {p.filtro_qtd} de {p.qtd}d{p.lados}.")
        # Pior caso: todo dado explode o máximo de vezes.
        total_dados += p.qtd * (1 + p.explosivo)
    if conditional_reroll and conditional_reroll.reroll_notation:
        qtd, lados = (int(x) for x in conditional_reroll.reroll_notation.split("d"))
        if qtd < 1 or lados < 1:
            raise ValueError("Quantidade e lados dos dados precisam ser pelo menos 1.")
        if lados > MAX_LADOS:
            raise ValueError(f"Dado grande demais (máximo d{MAX_LADOS}).")
        total_dados += qtd
    if total_dados > MAX_DADOS:
        raise ValueError(
            f"Dados demais (máximo {MAX_DADOS} por rolagem, contando as explosões possíveis)."
        )
    return expressao, partes, m.end()


def _explodir(valores: List[int], lados: int, limite: int, rng) -> List[int]:
    """Cada dado no máximo rola mais um, em cadeia, até `limite` vezes por dado."""
    extras = []
    for v in valores:
        for _ in range(limite):
            if v != lados:
                break
            v = rng.randint(1, lados)
            extras.append(v)
    return extras


def _filtrar(dados: List[int], filtro: Optional[str], qtd: int) -> List[int]:
    """Dados removidos: os `qtd` menores (t) ou todos menos os `qtd` maiores (m)."""
    if not filtro:
        return []
    ordenados = sorted(dados)
    return ordenados[:qtd] if filtro == "t" else ordenados[:len(dados) - qtd]


def roll(
    user_input: str,
    rng: random.Random = random,
    conditional_reroll: Optional[ConditionalReroll] = None,
) -> RollResult:
    """
    Rola os dados descritos em `user_input`. Aceita a mensagem inteira:
    acha a expressão (1d20+1d6-2), explosivos (1d6!), filtros (4d6t1,
    "tiro 1", "mantenho 3"), vantagem/desvantagem, CD e nome do teste.

    Ordem em cada dado: rola → vantagem (só 1d20) → explode → tira/mantém →
    teste por dado ("maior que 5": conta quais dados mantidos passam).

    `conditional_reroll` (de parse_conditional_reroll): se algum dado mantido
    cair no valor-gatilho, rola o reroll uma vez e soma no total, antes da CD.

    Levanta ValueError (com mensagem para o jogador) se não houver dados ou
    se a rolagem passar dos limites.
    """
    expressao, partes, fim = _preparar(user_input, conditional_reroll)

    modificador = _modificador(user_input)
    termos: List[Termo] = []
    bonus = 0
    natural = None
    vantagem_aplicada = False

    for p in partes:
        if not p.qtd:
            bonus += p.sinal * p.valor
            continue

        rolagens = [rng.randint(1, p.lados) for _ in range(p.qtd)]
        descartado = None
        base = list(rolagens)

        # Vantagem/desvantagem vale para o primeiro d20 único da expressão.
        if p.lados == 20 and p.qtd == 1 and not vantagem_aplicada:
            vantagem_aplicada = True
            if modificador:
                rolagens.append(rng.randint(1, 20))
                escolha = max if modificador == "vantagem" else min
                base = [escolha(rolagens)]
                descartado = rolagens[1] if base[0] == rolagens[0] else rolagens[0]
            natural = base[0]

        explosoes = _explodir(base, p.lados, p.explosivo, rng)
        removidos = _filtrar(base + explosoes, p.filtro, p.filtro_qtd)
        termo = Termo(
            expressao=p.expressao,
            sinal=p.sinal,
            rolagens=rolagens,
            descartado=descartado,
            subtotal=0,
            lados=p.lados,
            explosoes=explosoes,
            filtro=p.filtro,
            filtro_qtd=p.filtro_qtd,
            removidos=removidos,
        )
        termo.subtotal = p.sinal * sum(termo.mantidos)
        termos.append(termo)

    avisos = []
    if modificador and not vantagem_aplicada:
        avisos.append(f"{modificador.capitalize()} ignorada: não há 1d20 na rolagem.")
        modificador = None

    final = sum(t.subtotal for t in termos) + bonus

    threshold = None
    # Só depois da expressão: "<@123>" (menção) antes dos dados não é condição.
    limiar = parse_threshold_test(user_input[fim:])
    if limiar:
        operador, valor = limiar
        dados = [v for t in termos for v in t.mantidos]
        passa = _COMPARA[operador]
        threshold = ThresholdTest(
            operador, valor, dados,
            sucessos=[v for v in dados if passa(v, valor)],
            falhas=[v for v in dados if not passa(v, valor)],
        )
        if bonus:
            avisos.append("O bônus fixo não entra no teste por dado.")

    reroll = None
    if conditional_reroll:
        # O reroll só olha os termos, então dá pra montar o resultado parcial.
        parcial = RollResult(expressao, termos, bonus, modificador, final, None, None, None)
        reroll = apply_conditional_reroll(parcial, conditional_reroll, rng)
        if reroll.triggered:
            final += reroll.total
        else:
            reroll = None

    m_dc = re.search(DC, user_input, re.IGNORECASE)
    dc = int(m_dc.group(1)) if m_dc else None
    resultado = None
    if dc is not None:
        if natural == 20:
            resultado = "crítico"
        else:
            resultado = "sucesso" if final >= dc else "falha"

    m_teste = _TESTE.search(user_input)
    teste = m_teste.group(1).lower() if m_teste else None

    return RollResult(
        expressao=expressao,
        termos=termos,
        bonus=bonus,
        modificador=modificador,
        final=final,
        teste=teste,
        dc=dc,
        resultado=resultado,
        natural=natural,
        avisos=avisos,
        conditional_reroll_result=reroll,
        threshold=threshold,
    )


@dataclass
class CoinRollResult:
    flip: CoinFlip
    target_heads: Optional[int] = None  # None = sem condicional
    reroll: Optional[RollResult] = None  # só se a condição ativou


def roll_coins(
    coin: dict,
    coin_conditional: Optional[dict] = None,
    rng: random.Random = random,
) -> CoinRollResult:
    """
    Joga as moedas de `coin` ({count, bias}, de parse_coin_pattern).

    `coin_conditional` ({target_heads, reroll}, de parse_coin_conditional): se
    der pelo menos target_heads caras, passa `reroll` para o roll() — então a
    rolagem aceita tudo que o roll() aceita (vantagem, CD, "se 8 role de novo").

    Levanta ValueError (com mensagem para o jogador) antes de jogar as moedas,
    para o erro não depender da sorte.
    """
    if coin_conditional is None:
        return CoinRollResult(flip_coin(coin["count"], coin["bias"], rng))

    target = coin_conditional["target_heads"]
    if not 1 <= target <= coin["count"]:
        moedas = "moeda" if coin["count"] == 1 else "moedas"
        raise ValueError(f"Não dá pra tirar {target} caras com {coin['count']} {moedas}.")
    texto = coin_conditional["reroll"]
    reroll_do_reroll = parse_conditional_reroll(texto)
    _preparar(texto, reroll_do_reroll)

    flip = flip_coin(coin["count"], coin["bias"], rng)
    reroll = None
    if flip.heads_count >= target:
        reroll = roll(texto, rng, conditional_reroll=reroll_do_reroll)
    return CoinRollResult(flip, target, reroll)
