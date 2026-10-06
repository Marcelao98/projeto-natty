"""
Rerolls condicionais escritos na própria mensagem. Lógica pura, sem discord.py.

    "rolo 1d8 se 8 role de novo"      → se algum d8 der 8, rola mais 1d8
    "rolo 1d20 se 20 role 1d100"      → se o d20 der 20, rola 1d100
    "rolo 2d6 se o d6 der 6 role 1d8" → só checa os d6

O reroll acontece uma vez só (sem cascata) e soma no total.
"""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .service import RollResult

REROLL = re.compile(
    r"\bse\s+"
    r"(?:(?:o\s+)?d(\d+)\s+(?:der|cair|for|tirar)\s+)?"  # trigger_die (opcional)
    r"(\d+)\s*,?\s+"                                      # trigger_value
    r"(?:ent[ãa]o\s+)?(?:re)?rol(?:e|a|o|ar)\s+"
    r"(?:(de\s+novo|novamente|outr[oa]\s+vez)|(\d*)d(\d+))\b",
    re.IGNORECASE,
)


@dataclass
class ConditionalReroll:
    trigger_value: int                     # valor que ativa (8, 20, 1...)
    trigger_die: Optional[int] = None      # lados do dado a checar; None = todos
    reroll_notation: Optional[str] = None  # "1d100"; None = repete o dado que ativou


@dataclass
class RerollResult:
    triggered: bool
    trigger_value: int
    expressao: Optional[str] = None        # dado rolado no reroll, ex: "1d8"
    rolagens: List[int] = field(default_factory=list)
    total: int = 0


def parse_conditional_reroll(message: str) -> Optional[ConditionalReroll]:
    """Acha "se X role Y" na mensagem. Retorna None se não houver."""
    m = REROLL.search(message)
    if not m:
        return None
    trigger_die = int(m.group(1)) if m.group(1) else None
    notation = None
    if not m.group(3):
        notation = f"{int(m.group(4) or 1)}d{int(m.group(5))}"
    return ConditionalReroll(int(m.group(2)), trigger_die, notation)


def apply_conditional_reroll(result: "RollResult", condition: ConditionalReroll, rng) -> RerollResult:
    """
    Procura trigger_value nos dados de `result` e, se achar, rola o reroll.
    Não altera `result`; quem chama soma `total` no final.
    """
    for termo in result.termos:
        lados = termo.lados
        if condition.trigger_die is not None and lados != condition.trigger_die:
            continue
        # Só dados que contam: sem o d20 descartado nem os tirados por filtro.
        if condition.trigger_value in termo.mantidos:
            break
    else:
        return RerollResult(triggered=False, trigger_value=condition.trigger_value)

    expressao = condition.reroll_notation or f"1d{lados}"
    qtd, lados_reroll = (int(x) for x in expressao.split("d"))
    rolagens = [rng.randint(1, lados_reroll) for _ in range(qtd)]
    return RerollResult(
        triggered=True,
        trigger_value=condition.trigger_value,
        expressao=expressao,
        rolagens=rolagens,
        total=sum(rolagens),
    )
