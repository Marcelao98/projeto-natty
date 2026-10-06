"""
Testes de dados explosivos (!) e filtros tira/mantém (t/m/kh). Da raiz do projeto:
    python -m unittest discover -s modules/dice -t .
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from modules.dice.detector import extract_conditional_reroll, is_roll_message  # noqa: E402
from modules.dice.format import describe_roll_compact  # noqa: E402
from modules.dice.service import roll  # noqa: E402
from modules.dice.test_service import Dados  # noqa: E402


def rolar(msg, *valores):
    return roll(msg, Dados(*valores), conditional_reroll=extract_conditional_reroll(msg))


class TestExplosivo(unittest.TestCase):
    def test_explode(self):
        r = rolar("rolo 1d6!", 6, 4)
        self.assertEqual((r.final, r.termos[0].explosoes), (10, [4]))

    def test_nao_explode(self):
        self.assertEqual(rolar("rolo 1d6!", 5).final, 5)

    def test_limite_de_um(self):
        # "!" explode uma vez só, mesmo se o extra cair no máximo.
        r = rolar("rolo 1d6!", 6, 6)
        self.assertEqual((r.final, r.termos[0].explosoes), (12, [6]))

    def test_cadeia_dupla(self):
        r = rolar("rolo 2d10!!", 10, 7, 10, 5)
        self.assertEqual((r.termos[0].explosoes, r.final), ([10, 5], 32))

    def test_cada_dado_explode(self):
        r = rolar("rolo 3d6!", 6, 2, 6, 1, 3)
        self.assertEqual((r.termos[0].explosoes, r.final), ([1, 3], 18))

    def test_d20_explode_e_critica(self):
        r = rolar("rolo 1d20!+5 vs 30", 20, 3)
        self.assertEqual((r.final, r.natural, r.resultado), (28, 20, "crítico"))

    def test_vantagem_explode_o_mantido(self):
        r = rolar("rolo 1d20! com vantagem", 20, 4, 11)
        self.assertEqual((r.final, r.termos[0].explosoes), (31, [11]))

    def test_desvantagem_descartado_nao_explode(self):
        r = rolar("rolo 1d20! com desvantagem", 20, 4)
        self.assertEqual((r.final, r.termos[0].explosoes), (4, []))

    def test_limite_conta_explosoes(self):
        with self.assertRaises(ValueError):
            rolar("rolo 40d6!!")  # pior caso: 120 dados
        rolar("rolo 50d6!", *([1] * 50))


class TestFiltro(unittest.TestCase):
    def test_tira(self):
        for msg in ["rolo 4d6 tiro 1", "rolo 4d6t1", "rolo 4d6 tiro o menor", "4d6 tiro 1"]:
            with self.subTest(msg=msg):
                r = rolar(msg, 3, 5, 2, 6)
                self.assertEqual((r.final, r.termos[0].removidos), (14, [2]))

    def test_tira_dois(self):
        for msg in ["rolo 4d6t2", "rolo 4d6 tiro os 2 menores"]:
            with self.subTest(msg=msg):
                self.assertEqual(rolar(msg, 4, 3, 5, 2).final, 9)

    def test_mantem(self):
        for msg in ["rolo 4d6 mantenho 3", "rolo 4d6m3", "rolo 4d6kh3", "rolo 4d6k3"]:
            with self.subTest(msg=msg):
                r = rolar(msg, 6, 2, 5, 4)
                self.assertEqual((r.final, r.termos[0].removidos, r.termos[0].expressao),
                                 (15, [2], "4d6m3"))

    def test_mantem_o_maior(self):
        self.assertEqual(rolar("rolo 2d20 mantenho o maior", 7, 15).final, 15)

    def test_por_extenso_vale_para_o_ultimo_dado(self):
        r = rolar("rolo 1d20+4d6+2 tiro 1", 10, 3, 5, 2, 6)
        self.assertEqual((r.termos[0].removidos, r.termos[1].removidos, r.final), ([], [2], 26))

    def test_negativo(self):
        self.assertEqual(rolar("rolo 10-2d6t1", 3, 5).final, 5)

    def test_invalidos(self):
        for msg in ["rolo 4d6t4", "rolo 1d6 tiro 1", "rolo 4d6m5", "rolo 4d6m0", "rolo 4d6t1 tiro 2"]:
            with self.subTest(msg=msg), self.assertRaises(ValueError):
                rolar(msg)

    def test_frase_sem_numero_nao_filtra(self):
        # "tiro" como substantivo não vira filtro.
        self.assertEqual(rolar("rolo 2d6 de dano do tiro", 3, 4).final, 7)


class TestCombinado(unittest.TestCase):
    def test_explode_depois_tira(self):
        for msg in ["rolo 4d6! tiro 1", "rolo 4d6!t1"]:
            with self.subTest(msg=msg):
                r = rolar(msg, 4, 6, 5, 3, 2)
                self.assertEqual((r.termos[0].explosoes, r.termos[0].removidos, r.final),
                                 ([2], [2], 18))

    def test_explosao_dupla_mantem_um(self):
        for msg in ["rolo 2d10!!kh1", "rolo 2d10!! mantenho 1"]:
            with self.subTest(msg=msg):
                self.assertEqual(rolar(msg, 10, 7, 10, 5).final, 10)

    def test_vantagem_sem_d20_avisa(self):
        r = rolar("rolo 8d6 tiro 2 com vantagem", 1, 2, 3, 4, 5, 6, 6, 6)
        self.assertEqual((r.modificador, r.final), (None, 30))
        self.assertTrue(r.avisos)

    def test_reroll_condicional_ignora_tirados(self):
        r = rolar("rolo 4d6t1 se 1 role de novo", 1, 5, 4, 3)
        self.assertIsNone(r.conditional_reroll_result)
        r = rolar("rolo 4d6! se 6 role de novo", 6, 1, 1, 1, 2, 3)
        self.assertEqual(r.final, 14)  # 6+1+1+1, explosão 2, reroll 3

    def test_detector(self):
        for msg in ["rolo 1d6!", "rolo 4d6!t1", "rolo 2d10!!kh1", "4d6 mantenho 3"]:
            with self.subTest(msg=msg):
                self.assertTrue(is_roll_message(msg))


class TestFormat(unittest.TestCase):
    def test_explosao_e_tirado(self):
        self.assertEqual(
            describe_roll_compact(rolar("rolo 4d6! tiro 1", 4, 6, 5, 3, 2)),
            "🎲 4d6!t1 [4, 6, 5, 3, ~~💥2~~] = **18**",
        )

    def test_mantem(self):
        self.assertEqual(
            describe_roll_compact(rolar("rolo 4d6kh3", 6, 2, 5, 4)),
            "🎲 4d6m3 [6, ~~2~~, 5, 4] = **15**",
        )

    def test_vantagem_explosiva(self):
        self.assertEqual(
            describe_roll_compact(rolar("rolo 1d20! com vantagem", 4, 20, 11)),
            "🎲 1d20! [~~4~~, 20, 💥11] (vantagem) = **31**",
        )


if __name__ == "__main__":
    unittest.main()
