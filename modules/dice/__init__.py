"""
Módulo Dice: rolagem de dados em linguagem natural.

    from modules.dice import roll, describe_roll_compact
    print(describe_roll_compact(roll("1d20+5 com vantagem vs 15")))
"""

from .coins import CoinFlip, flip_coin, parse_coin_conditional, parse_coin_pattern
from .conditional_rerolls import (
    ConditionalReroll,
    RerollResult,
    apply_conditional_reroll,
    parse_conditional_reroll,
)
from .detector import (
    detect_roll_pattern,
    extract_coin_conditional,
    extract_coin_pattern,
    extract_conditional_reroll,
    is_coin_message,
    extract_roll_input,
    is_roll_message,
)
from .format import describe_coin_flip, describe_coin_roll, describe_roll, describe_roll_compact
from .service import (
    CoinRollResult,
    RollResult,
    Termo,
    ThresholdTest,
    parse_threshold_test,
    roll,
    roll_coins,
)

__all__ = [
    "roll",
    "RollResult",
    "Termo",
    "ThresholdTest",
    "parse_threshold_test",
    "detect_roll_pattern",
    "extract_roll_input",
    "is_roll_message",
    "extract_conditional_reroll",
    "ConditionalReroll",
    "RerollResult",
    "parse_conditional_reroll",
    "apply_conditional_reroll",
    "describe_roll",
    "describe_roll_compact",
    "roll_coins",
    "CoinRollResult",
    "CoinFlip",
    "flip_coin",
    "parse_coin_pattern",
    "parse_coin_conditional",
    "extract_coin_pattern",
    "extract_coin_conditional",
    "is_coin_message",
    "describe_coin_flip",
    "describe_coin_roll",
]
