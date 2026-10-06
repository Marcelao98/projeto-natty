"""
Decide se uma mensagem do chat é um pedido de rolagem. Só regex, sem discord.py.

Rola quando:
- a mensagem tem uma expressão de dados E uma palavra de rolagem
  ("eu rolo 1d20", "Teste de Ataque: 1d20+5 vs CD 13"); ou
- a mensagem é só a rolagem ("1d20", "2d6+3 com vantagem vs 15").

Uma expressão solta numa frase ("a espada dá 1d8 de dano") não rola.
Mensagens começando com "!" são do Avrae e são ignoradas.

Moedas (extract_coin_pattern) rolam quando a mensagem começa com a moeda
("moeda 70% cara", "2 moedas se 2 caras role 1d6") ou quando ela vem logo
depois de um verbo ("eu rolo uma moeda", "jogo 3 moedas"). "Comprei uma moeda"
não rola, e uma mensagem com dados fora do condicional ("rolo 1d20 e perco uma
moeda") fica com os dados.
"""

import re
from typing import Optional

from .coins import CONDICIONAL, NUM, parse_coin_conditional, parse_coin_pattern
from .conditional_rerolls import REROLL, ConditionalReroll, parse_conditional_reroll
from .service import DC, EXPRESSAO, LIMIAR, MANTEM, TIRA

_PALAVRA_ROLAGEM = re.compile(
    r"\b(?:rol(?:o|a|ar|ando|ei|ou)|roll|teste|test)\b", re.IGNORECASE
)
_MODIFICADOR = r"(?:com\s+)?(?:desvantagem|desvant|disadvantage|dis|vantagem|vant|advantage|adv)\b"
_EXTRAS = rf"(?:\s*,?\s*(?:{_MODIFICADOR}|{DC}|{TIRA}|{MANTEM}|{LIMIAR}))*"
_ROLAGEM = re.compile(rf"{EXPRESSAO}{_EXTRAS}", re.IGNORECASE)

_VERBO_MOEDA = (
    r"rol(?:o|a|ar|ei|ou)|roll|flip|jog(?:o|a|ar|uei|ou)|"
    r"lan[çc](?:o|a|ar|ou)|lancei|joguei|tiro|tira|tirar"
)
_PEDIDO_MOEDA = re.compile(
    rf"(?:^\s*|\b(?:{_VERBO_MOEDA})\s+(?:(?:a|as)\s+)?)(?:(?:{NUM})\s+)?moedas?\b",
    re.IGNORECASE,
)


def detect_roll_pattern(message: str) -> Optional[str]:
    """Retorna o trecho da rolagem ("1d20+5 vs DC 13") ou None."""
    texto = message.strip()
    if texto.startswith("!"):
        return None
    # "1d8 se 8 role de novo" ainda é só a rolagem.
    texto = REROLL.sub("", texto).strip()

    m = _ROLAGEM.search(texto)
    if not m:
        return None

    so_a_rolagem = m.start() == 0 and not texto[m.end():].strip(" .!?")
    if so_a_rolagem or _PALAVRA_ROLAGEM.search(texto):
        return m.group(0)
    return None


def extract_roll_input(message: str) -> Optional[str]:
    """Mesmo que detect_roll_pattern (mantido por compatibilidade)."""
    return detect_roll_pattern(message)


def extract_conditional_reroll(message: str) -> Optional[ConditionalReroll]:
    """Reroll condicional da mensagem ("se 8 role de novo") ou None."""
    return parse_conditional_reroll(message)


def extract_coin_pattern(message: str) -> Optional[dict]:
    """{count, bias} se a mensagem é um pedido de moeda, senão None."""
    texto = message.strip()
    if texto.startswith("!"):
        return None
    m = CONDICIONAL.search(texto)
    antes = texto[:m.start()] if m else texto
    if re.search(EXPRESSAO, antes, re.IGNORECASE) or not _PEDIDO_MOEDA.search(antes):
        return None
    return parse_coin_pattern(antes)


def extract_coin_conditional(message: str) -> Optional[dict]:
    """{coin_count, target_heads, reroll} de "moeda se cara role 1d20", ou None."""
    if extract_coin_pattern(message) is None:
        return None
    return parse_coin_conditional(message)


def is_coin_message(message: str) -> bool:
    return extract_coin_pattern(message) is not None


def is_roll_message(message: str) -> bool:
    return detect_roll_pattern(message) is not None
