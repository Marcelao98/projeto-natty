"""
Testes do teste por dado ("rolo 10d8, maior que 5"). Da raiz do projeto:
    python -m unittest discover -s modules/dice -t .
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from modules.dice.detector import extract_conditional_reroll, is_roll_message  # noqa: E402
from modules.dice.format import describe_roll_compact  # noqa: E402
from modules.dice.service import parse_threshold_test, roll  # noqa: E402
from modules.dice.test_service import Dados  # noqa: E402

DEZ_D8 = (3, 6, 2, 8, 4, 7, 5, 1, 8, 6)


def rolar(msg, *valores):
    return roll(msg, Dados(*valores), conditional_reroll=extract_conditional_reroll(msg))


class TestParse(unittest.TestCase):
    def test_operadores(self):
        casos = [
            ("maior que 5", (">", 5)), ("> 5", (">", 5)), (">5", (">", 5)),
            ("menor que 3", ("<", 3)), ("< 3", ("<", 3)),
            ("igual a 6", ("=", 6)), ("igual 6", ("=", 6)), ("= 6", ("=", 6)),
            ("maior ou igual 50", (">=", 50)), ("maior ou igual a 50", (">=", 50)),
            ("maior que ou igual a 50", (">=", 50)), (">= 10", (">=", 10)), ("≥ 10", (">=", 10)),
            ("menor ou igual a 2", ("<=", 2)), ("<= 2", ("<=", 2)), ("≤2", ("<=", 2)),
            ("Maior Que 5", (">", 5)),
        ]
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                self.assertEqual(parse_threshold_test(texto), esperado)

    def test_sem_condicao(self):
        for texto in ["", "vs 15", "tiro o menor", "mantenho o maior", "tiro os 2 menores"]:
            with self.subTest(texto=texto):
                self.assertIsNone(parse_threshold_test(texto))


class TestThreshold(unittest.TestCase):
    def test_maior_que(self):
        th = rolar("rolo 10d8, maior que 5", *DEZ_D8).threshold
        self.assertEqual((th.sucessos, th.falhas), ([6, 8, 7, 8, 6], [3, 2, 4, 5, 1]))
        self.assertEqual((th.success_count, th.failure_count, th.percentual), (5, 5, 50))

    def test_menor_que(self):
        th = rolar("rolo 10d8, menor que 3", *DEZ_D8).threshold
        self.assertEqual((th.sucessos, th.percentual), ([2, 1], 20))

    def test_igual(self):
        th = rolar("rolo 5d6, igual a 6", 6, 2, 6, 5, 6).threshold
        self.assertEqual((th.sucessos, th.falhas), ([6, 6, 6], [2, 5]))

    def test_maior_ou_igual(self):
        th = rolar("rolo 4d20, maior ou igual 10", 7, 10, 12, 9).threshold
        self.assertEqual(th.sucessos, [10, 12])

    def test_menor_ou_igual(self):
        th = rolar("rolo 4d20 <= 9", 7, 10, 12, 9).threshold
        self.assertEqual(th.sucessos, [7, 9])

    def test_sem_condicao(self):
        self.assertIsNone(rolar("rolo 2d6", 3, 4).threshold)

    def test_mencao_antes_nao_e_condicao(self):
        # "<@123>" (menção do Discord) antes dos dados não vira "< 123".
        self.assertIsNone(rolar("<@123> rolo 2d6", 3, 4).threshold)

    def test_explosivo(self):
        th = rolar("rolo 3d6! maior que 4", 6, 2, 5, 3).threshold
        self.assertEqual((th.dados, th.sucessos), ([6, 2, 5, 3], [6, 5]))

    def test_tira_mantem(self):
        th = rolar("rolo 4d6t1 > 3", 4, 3, 5, 3).threshold
        self.assertEqual((th.dados, th.sucessos, th.falhas), ([4, 5, 3], [4, 5], [3]))
        th = rolar("rolo 4d6 mantenho 2, maior que 4", 6, 2, 5, 4).threshold
        self.assertEqual((th.dados, th.sucessos), ([6, 5], [6, 5]))

    def test_vantagem(self):
        th = rolar("rolo 1d20 com vantagem >= 10", 4, 15).threshold
        self.assertEqual((th.dados, th.sucessos), ([15], [15]))

    def test_bonus_nao_entra(self):
        r = rolar("rolo 2d6+10 > 4", 3, 5)
        self.assertEqual((r.threshold.sucessos, r.final), ([5], 18))
        self.assertTrue(r.avisos)

    def test_detector(self):
        for msg in ["rolo 10d8, maior que 5", "10d8 > 5", "5d100 menor que 20"]:
            with self.subTest(msg=msg):
                self.assertTrue(is_roll_message(msg))


class TestFormat(unittest.TestCase):
    def test_listas(self):
        self.assertEqual(
            describe_roll_compact(rolar("rolo 10d8, maior que 5", *DEZ_D8)),
            "🎲 10d8 [3, 6, 2, 8, 4, 7, 5, 1, 8, 6] · maior que 5\n"
            "✅ Sucessos (>5): [6, 8, 7, 8, 6]\n"
            "❌ Falhas (≤5): [3, 2, 4, 5, 1]\n"
            "📊 **5 sucessos de 10** (50%)",
        )

    def test_nenhum_e_singular(self):
        self.assertEqual(
            describe_roll_compact(rolar("rolo 2d6 = 6", 6, 2)).splitlines()[1:],
            ["✅ Sucessos (=6): [6]", "❌ Falhas (≠6): [2]", "📊 **1 sucesso de 2** (50%)"],
        )
        self.assertIn("nenhum", describe_roll_compact(rolar("rolo 2d6 > 5", 1, 2)))

    def test_muitos_dados_so_contagem(self):
        texto = describe_roll_compact(rolar("rolo 30d6 > 4", *([5] * 10 + [1] * 20)))
        self.assertNotIn("Sucessos", texto)
        self.assertTrue(texto.endswith("📊 **10 sucessos de 30** (33%)"))

    def test_com_cd(self):
        texto = describe_roll_compact(rolar("rolo 2d6 > 3 vs 8", 4, 5))
        self.assertTrue(texto.startswith("🎲 2d6 [4, 5] · maior que 3 · total **9** · CD 8 ✅ Sucesso\n"))


if __name__ == "__main__":
    unittest.main()
