"""
Testes das moedas. Da raiz do projeto:
    python -m unittest discover -s modules/dice -t .
"""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from modules.dice.coins import MAX_MOEDAS, flip_coin, parse_coin_pattern  # noqa: E402
from modules.dice.detector import (  # noqa: E402
    extract_coin_conditional,
    extract_coin_pattern,
    is_roll_message,
)
from modules.dice.format import describe_coin_roll  # noqa: E402
from modules.dice.service import roll_coins  # noqa: E402
from modules.dice.test_service import Dados  # noqa: E402

C, K = 0.1, 0.9  # random() que dá Cara / Coroa numa moeda justa


class Sorte(Dados):
    """rng falso: `moedas` para random(), o resto para randint()."""

    def __init__(self, moedas, *dados):
        super().__init__(*dados)
        self.moedas = list(moedas)

    def random(self):
        return self.moedas.pop(0)


def jogar(msg, moedas, *dados):
    return roll_coins(extract_coin_pattern(msg), extract_coin_conditional(msg), Sorte(moedas, *dados))


class TestFlip(unittest.TestCase):
    def test_contagem(self):
        f = flip_coin(5, rng=Sorte([C, K, C, C, K]))
        self.assertEqual(f.results, ["Cara", "Coroa", "Cara", "Cara", "Coroa"])
        self.assertEqual((f.count, f.heads_count, f.tails_count), (5, 3, 2))

    def test_ponderada(self):
        self.assertEqual(flip_coin(1, 0.7, Sorte([0.65])).results, ["Cara"])
        self.assertEqual(flip_coin(1, 0.7, Sorte([0.75])).results, ["Coroa"])

    def test_extremos(self):
        rng = random.Random(1)
        self.assertEqual(flip_coin(50, 0.0, rng).heads_count, 0)
        self.assertEqual(flip_coin(50, 1.0, rng).heads_count, 50)

    def test_limites(self):
        for count, bias in [(0, 0.5), (MAX_MOEDAS + 1, 0.5), (1, 1.5), (1, -0.1)]:
            with self.subTest(count=count, bias=bias), self.assertRaises(ValueError):
                flip_coin(count, bias)


class TestParse(unittest.TestCase):
    def test_quantidade(self):
        casos = [("rolo moeda", 1), ("rolo uma moeda", 1), ("rolo 2 moedas", 2),
                 ("rolo 10 moedas", 10), ("jogo duas moedas", 2)]
        for msg, count in casos:
            with self.subTest(msg=msg):
                self.assertEqual(parse_coin_pattern(msg), {"count": count, "bias": 0.5})

    def test_ponderada(self):
        self.assertEqual(parse_coin_pattern("moeda 70% cara"), {"count": 1, "bias": 0.7})
        self.assertEqual(parse_coin_pattern("moeda ponderada 70% cara")["bias"], 0.7)
        self.assertEqual(parse_coin_pattern("3 moedas com 25% de cara"), {"count": 3, "bias": 0.25})

    def test_condicional(self):
        self.assertEqual(
            extract_coin_conditional("rolo moeda se cara role 1d20"),
            {"coin_count": 1, "target_heads": 1, "reroll": "1d20"},
        )
        self.assertEqual(
            extract_coin_conditional("3 moedas se 2 caras role 2d6"),
            {"coin_count": 3, "target_heads": 2, "reroll": "2d6"},
        )
        self.assertEqual(
            extract_coin_conditional("rolo moeda se der cara, rola 1d20+5 com vantagem!")["reroll"],
            "1d20+5 com vantagem",
        )

    def test_sem_condicional(self):
        self.assertIsNone(extract_coin_conditional("rolo 2 moedas"))


class TestDetector(unittest.TestCase):
    def test_detecta(self):
        for msg in ["rolo uma moeda", "eu jogo 3 moedas", "moeda", "Moeda 70% cara",
                    "moeda ponderada 70% cara", "lanço a moeda", "rolo moeda se cara role 1d20",
                    "2 moedas se 2 caras role 1d100"]:
            with self.subTest(msg=msg):
                self.assertIsNotNone(extract_coin_pattern(msg))

    def test_ignora(self):
        for msg in ["comprei uma moeda", "a moeda caiu no chão", "!rolo moeda",
                    "rolo 1d20 e perco uma moeda", "oi"]:
            with self.subTest(msg=msg):
                self.assertIsNone(extract_coin_pattern(msg))

    def test_dados_continuam(self):
        self.assertIsNone(extract_coin_pattern("rolo 1d20+5 vs 15"))
        self.assertTrue(is_roll_message("rolo 1d20 e perco uma moeda"))


class TestRollCoins(unittest.TestCase):
    def test_simples(self):
        r = jogar("rolo 2 moedas", [C, K])
        self.assertEqual((r.flip.heads_count, r.target_heads, r.reroll), (1, None, None))

    def test_condicional_ativa(self):
        r = jogar("rolo moeda se cara role 1d20", [C], 14)
        self.assertEqual(r.reroll.final, 14)

    def test_condicional_nao_ativa(self):
        r = jogar("rolo moeda se cara role 1d20", [K])
        self.assertIsNone(r.reroll)

    def test_minimo_de_caras(self):
        self.assertIsNone(jogar("rolo 3 moedas se 2 caras role 1d100", [C, K, K]).reroll)
        self.assertEqual(jogar("rolo 3 moedas se 2 caras role 1d100", [C, K, C], 50).reroll.final, 50)
        self.assertEqual(jogar("rolo 3 moedas se 2 caras role 1d100", [C, C, C], 7).reroll.final, 7)

    def test_combina_com_vantagem_e_cd(self):
        r = jogar("rolo moeda se cara role 1d20+5 com vantagem vs 15", [C], 4, 12)
        self.assertEqual((r.reroll.modificador, r.reroll.final, r.reroll.resultado),
                         ("vantagem", 17, "sucesso"))

    def test_combina_com_reroll_de_dado(self):
        r = jogar("rolo moeda se cara role 1d8 se 8 role de novo", [C], 8, 3)
        self.assertEqual(r.reroll.final, 11)

    def test_ponderada_condicional(self):
        r = jogar("moeda 70% cara se cara role 1d6", [0.65], 4)
        self.assertEqual((r.flip.bias, r.reroll.final), (0.7, 4))

    def test_erros_antes_de_jogar(self):
        # Erro não depende da sorte: nenhuma moeda é consumida.
        for msg in ["rolo moeda se 2 caras role 1d20", "rolo moeda se cara role 1d5000",
                    "rolo moeda se cara role o dado"]:
            with self.subTest(msg=msg), self.assertRaises(ValueError):
                jogar(msg, [])


class TestFormat(unittest.TestCase):
    def test_uma(self):
        self.assertEqual(describe_coin_roll(jogar("rolo uma moeda", [C])), "🪙 Moeda = **Cara**")

    def test_varias(self):
        self.assertEqual(
            describe_coin_roll(jogar("rolo 5 moedas", [C, K, C, C, K])),
            "🪙 5 moedas = [Cara, Coroa, Cara, Cara, Coroa]\n**3 caras** · 2 coroas",
        )

    def test_ponderada(self):
        self.assertEqual(
            describe_coin_roll(jogar("moeda ponderada 70% cara", [0.9])),
            "🪙 Moeda (70% cara) = **Coroa**",
        )

    def test_condicional(self):
        self.assertEqual(
            describe_coin_roll(jogar("rolo moeda se cara role 1d20", [C], 14)),
            "🪙 Moeda = **Cara**\n✨ Condição ativada!\n🎲 1d20 [14] = **14**",
        )
        self.assertEqual(
            describe_coin_roll(jogar("rolo 2 moedas se 2 caras role 1d100", [C, K])),
            "🪙 2 moedas = [Cara, Coroa]\n**1 cara** · 1 coroa\n"
            "❌ Condição não ativada (1 cara, precisava 2)",
        )


if __name__ == "__main__":
    unittest.main()
