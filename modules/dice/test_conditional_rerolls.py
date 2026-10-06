"""
Testes dos rerolls condicionais. Da raiz do projeto:
    python -m unittest discover -s modules/dice -t .
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from modules.dice.conditional_rerolls import parse_conditional_reroll  # noqa: E402
from modules.dice.detector import extract_conditional_reroll, is_roll_message  # noqa: E402
from modules.dice.format import describe_roll, describe_roll_compact  # noqa: E402
from modules.dice.service import roll  # noqa: E402
from modules.dice.test_service import Dados  # noqa: E402


def rolar(msg, *valores):
    return roll(msg, Dados(*valores), conditional_reroll=extract_conditional_reroll(msg))


class TestParse(unittest.TestCase):
    def test_de_novo(self):
        c = parse_conditional_reroll("rolo 1d8 se 8 role de novo")
        self.assertEqual((c.trigger_value, c.trigger_die, c.reroll_notation), (8, None, None))

    def test_notacao(self):
        self.assertEqual(parse_conditional_reroll("se 20 role 1d100").reroll_notation, "1d100")
        self.assertEqual(parse_conditional_reroll("se 1 role 2d6").reroll_notation, "2d6")
        self.assertEqual(parse_conditional_reroll("se 20 rola d100").reroll_notation, "1d100")

    def test_variacoes(self):
        self.assertEqual(parse_conditional_reroll("se 8, rola novamente").trigger_value, 8)
        self.assertEqual(parse_conditional_reroll("se 8 rerola de novo").trigger_value, 8)

    def test_dado_especifico(self):
        c = parse_conditional_reroll("rolo 1d20+1d6 se o d6 der 6 role 1d8")
        self.assertEqual((c.trigger_value, c.trigger_die, c.reroll_notation), (6, 6, "1d8"))

    def test_sem_condicao(self):
        self.assertIsNone(parse_conditional_reroll("rolo 1d20+5 vs 15"))


class TestReroll(unittest.TestCase):
    def test_de_novo_ativa(self):
        r = rolar("rolo 1d8 se 8 role de novo", 8, 5)
        self.assertEqual(r.final, 13)
        self.assertEqual(r.conditional_reroll_result.expressao, "1d8")

    def test_nao_ativa(self):
        r = rolar("rolo 1d8 se 8 role de novo", 3)
        self.assertEqual(r.final, 3)
        self.assertIsNone(r.conditional_reroll_result)

    def test_notacao_customizada(self):
        r = rolar("rolo 1d20 se 20 role 1d100", 20, 67)
        self.assertEqual((r.expressao, r.final), ("1d20", 87))

    def test_varios_dados(self):
        r = rolar("rolo 2d6 se 6 role de novo", 4, 6, 3)
        self.assertEqual(r.final, 13)
        self.assertEqual(r.conditional_reroll_result.rolagens, [3])

    def test_sem_cascata(self):
        r = rolar("rolo 1d8 se 8 role de novo", 8, 8)
        self.assertEqual(r.final, 16)

    def test_vantagem(self):
        r = rolar("rolo 1d20 com vantagem se 20 role de novo", 20, 4, 11)
        self.assertEqual((r.modificador, r.final), ("vantagem", 31))

    def test_vantagem_descartado_nao_ativa(self):
        r = rolar("rolo 1d20 com desvantagem se 20 role de novo", 20, 4)
        self.assertEqual(r.final, 4)
        self.assertIsNone(r.conditional_reroll_result)

    def test_dado_especifico(self):
        # O d20 deu 6, mas só o d6 conta.
        r = rolar("rolo 1d20+1d6 se o d6 der 6 role 1d8", 6, 2)
        self.assertIsNone(r.conditional_reroll_result)
        r = rolar("rolo 1d20+1d6 se o d6 der 6 role 1d8", 10, 6, 5)
        self.assertEqual(r.final, 21)

    def test_reroll_conta_na_cd(self):
        r = rolar("rolo 1d8 vs 12 se 8 role de novo", 8, 5)
        self.assertEqual(r.resultado, "sucesso")

    def test_limite_do_reroll(self):
        with self.assertRaises(ValueError):
            rolar("rolo 1d20 se 20 role 1d5000", 20)

    def test_detector_continua_rolando(self):
        self.assertTrue(is_roll_message("rolo 1d20 se 20 role 1d100"))
        self.assertTrue(is_roll_message("1d8 se 8 role de novo"))


class TestFormat(unittest.TestCase):
    def test_compacto(self):
        r = rolar("rolo 1d20 se 20 role 1d100", 20, 67)
        self.assertEqual(
            describe_roll_compact(r),
            "🎲 1d20 [20] + ✨ 1d100 [67] = **87**\n-# ✨ Reroll ativado (20)",
        )

    def test_completo(self):
        r = rolar("rolo 2d6 se 6 role de novo", 4, 6, 3)
        self.assertEqual(
            describe_roll(r),
            "🎲 2d6 [4, 6]\n✨ Reroll ativado (6)!\n🎲 Reroll: 1d6 [3]\n**Total: 13**",
        )


if __name__ == "__main__":
    unittest.main()
