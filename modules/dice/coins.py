"""
Moedas: cara ou coroa, várias moedas, moeda ponderada e condicional. Lógica
pura, sem discord.py.

    "rolo uma moeda"                    → Cara ou Coroa
    "rolo 5 moedas"                     → 5 resultados + contagem
    "moeda ponderada 70% cara"          → 70% de chance de cara
    "rolo 3 moedas se 2 caras role 1d6" → se der 2+ caras, rola 1d6
"""

import random
import re
from dataclasses import dataclass, field
from typing import List, Optional

MAX_MOEDAS = 100

CARA = "Cara"
COROA = "Coroa"

_NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3}
NUM = r"\d+|uma?|duas|dois|tr[êe]s"

MOEDA = re.compile(rf"(?:\b({NUM})\s+)?\bmoedas?\b", re.IGNORECASE)
PONDERADA = re.compile(
    r"\bmoedas?\s+(?:ponderadas?\s+)?(?:com\s+)?(\d+(?:[.,]\d+)?)\s*%\s*(?:de\s+)?caras?\b",
    re.IGNORECASE,
)
CONDICIONAL = re.compile(
    r"\bse\s+(?:(?:der|derem|cair|caírem|cairem|sair|saírem|sairem|tirar)\s+)?"
    rf"(?:({NUM})\s+)?caras?\s*,?\s+"                    # target_heads (opcional)
    r"(?:ent[ãa]o\s+)?(?:re)?rol(?:e|a|o|ar)\s+"
    r"(.+?)[\s.!?]*$",                                     # resto: a rolagem
    re.IGNORECASE,
)


@dataclass
class CoinFlip:
    results: List[str] = field(default_factory=list)  # ["Cara", "Coroa", ...]
    bias: float = 0.5                                  # chance de cara

    @property
    def count(self) -> int:
        return len(self.results)

    @property
    def heads_count(self) -> int:
        return self.results.count(CARA)

    @property
    def tails_count(self) -> int:
        return self.results.count(COROA)


def _numero(texto: Optional[str]) -> Optional[int]:
    if texto is None:
        return None
    texto = texto.lower()
    return int(texto) if texto.isdigit() else _NUMEROS[texto]


def flip_coin(count: int = 1, bias: float = 0.5, rng: random.Random = random) -> CoinFlip:
    """Joga `count` moedas; cada uma dá Cara com probabilidade `bias`."""
    if count < 1:
        raise ValueError("Preciso de pelo menos 1 moeda.")
    if count > MAX_MOEDAS:
        raise ValueError(f"Moedas demais (máximo {MAX_MOEDAS}).")
    if not 0 <= bias <= 1:
        raise ValueError("A chance de cara precisa estar entre 0% e 100%.")
    return CoinFlip([CARA if rng.random() < bias else COROA for _ in range(count)], bias)


def parse_coin_pattern(message: str) -> Optional[dict]:
    """
    Quantidade e peso das moedas citadas na mensagem, ou None se não houver moeda.
    Não decide se é um pedido de rolagem: isso é com o detector.
    """
    m = MOEDA.search(message)
    if not m:
        return None
    m_peso = PONDERADA.search(message)
    bias = float(m_peso.group(1).replace(",", ".")) / 100 if m_peso else 0.5
    return {"count": _numero(m.group(1)) or 1, "bias": bias}


def parse_coin_conditional(message: str) -> Optional[dict]:
    """
    Acha "se [N] cara(s) role X" na mensagem. `reroll` é o texto depois de
    "role" (ex: "1d20+5 com vantagem"), passado inteiro para o roll().
    """
    m = CONDICIONAL.search(message)
    if not m:
        return None
    moedas = parse_coin_pattern(message[:m.start()])
    return {
        "coin_count": moedas["count"] if moedas else 1,
        "target_heads": _numero(m.group(1)) or 1,
        "reroll": m.group(2).strip(),
    }
