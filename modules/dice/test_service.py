"""
Testes do serviço e da formatação. Da raiz do projeto:
    python -m unittest discover -s modules/dice -t .
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from modules.dice.format import describe_roll, describe_roll_compact  # noqa: E402
from modules.dice.service import MAX_DADOS, MAX_LADOS, roll  # noqa: E402


class Dados:
    """rng falso: devolve os valores na ordem dada."""

    def __init__(self, *valores):
        self.valores = list(valores)

    def randint(self, a, b):
        v = self.valores.pop(0)
        assert a <= v <= b, f"{v} fora de {a}..{b}"
        return v


class TestRoll(unittest.TestCase):
    def test_simples(self):
        r = roll("1d20", Dados(12))
        self.assertEqual(r.final, 12)
        self.assertEqual(r.natural, 12)
        self.assertIsNone(r.resultado)

    def test_sem_quantidade(self):
        self.assertEqual(roll("d20", Dados(7)).final, 7)

    def test_multiplos_dados(self):
        self.assertEqual(roll("2d6", Dados(2, 5)).final, 7)

    def test_bonus_positivo_e_negativo(self):
        self.assertEqual(roll("2d6+5", Dados(3, 5)).final, 13)
        r = roll("1d20-2", Dados(10))
        self.assertEqual((r.bonus, r.final), (-2, 8))

    def test_dado_negativo(self):
        self.assertEqual(roll("1d20-1d4", Dados(10, 3)).final, 7)

    def test_dados_repetidos_somam(self):
        r = roll("1d20+1d20", Dados(5, 6))
        self.assertEqual(r.final, 11)
        self.assertEqual(len(r.termos), 2)

    def test_vantagem(self):
        r = roll("1d20 com vantagem", Dados(7, 15))
        self.assertEqual((r.modificador, r.final, r.termos[0].descartado), ("vantagem", 15, 7))

    def test_desvantagem(self):
        r = roll("1d20 com desvantagem", Dados(7, 15))
        self.assertEqual((r.modificador, r.final, r.termos[0].descartado), ("desvantagem", 7, 15))

    def test_desvantagem_abreviada(self):
        self.assertEqual(roll("1d20 desvant", Dados(7, 15)).modificador, "desvantagem")
        self.assertEqual(roll("1d20 dis", Dados(7, 15)).modificador, "desvantagem")
        self.assertEqual(roll("1d20 adv", Dados(7, 15)).modificador, "vantagem")

    def test_sem_vantagem(self):
        r = roll("rolo 1d20 sem vantagem", Dados(9))
        self.assertIsNone(r.modificador)
        self.assertEqual(r.final, 9)

    def test_vantagem_sem_d20_e_ignorada(self):
        r = roll("2d6 com vantagem", Dados(1, 2))
        self.assertIsNone(r.modificador)
        self.assertEqual(r.final, 3)
        self.assertTrue(r.avisos)

    def test_vantagem_so_no_primeiro_d20(self):
        r = roll("1d20+1d20 com vantagem", Dados(3, 18, 4))
        self.assertEqual(r.final, 18 + 4)

    def test_cd(self):
        self.assertEqual(roll("1d20 vs 10", Dados(10)).resultado, "sucesso")
        self.assertEqual(roll("1d20 contra 10", Dados(9)).resultado, "falha")
        self.assertEqual(roll("1d20+5 vs DC 13", Dados(8)).dc, 13)
        self.assertEqual(roll("1d20 cd 12", Dados(8)).dc, 12)

    def test_critico(self):
        self.assertEqual(roll("1d20 vs 25", Dados(20)).resultado, "crítico")
        # Na desvantagem o 20 só conta se os dois dados derem 20.
        self.assertEqual(roll("1d20 com desvantagem vs 5", Dados(20, 3)).resultado, "falha")

    def test_frase_completa(self):
        r = roll("Eu rolo 1d20+1d6, Teste de Ataque vs DC 12", Dados(2, 6))
        self.assertEqual((r.final, r.teste, r.dc, r.resultado), (8, "ataque", 12, "falha"))

    def test_sem_dados(self):
        with self.assertRaises(ValueError):
            roll("oi tudo bem")

    def test_limites(self):
        with self.assertRaises(ValueError):
            roll("99999999d99999999")
        with self.assertRaises(ValueError):
            roll(f"{MAX_DADOS + 1}d6")
        with self.assertRaises(ValueError):
            roll(f"1d{MAX_LADOS + 1}")
        with self.assertRaises(ValueError):
            roll("0d6")
        roll(f"{MAX_DADOS}d{MAX_LADOS}")  # no limite, passa


class TestFormat(unittest.TestCase):
    def test_compacto(self):
        r = roll("Teste de Ataque: 1d20+5 com vantagem vs 15", Dados(4, 17))
        self.assertEqual(
            describe_roll_compact(r),
            "🎲 Ataque: 1d20 [~~4~~, 17] + 5 (vantagem) = **22** · CD 15 ✅ Sucesso",
        )

    def test_compacto_negativos(self):
        r = roll("1d20-1d4-2", Dados(10, 3))
        self.assertEqual(describe_roll_compact(r), "🎲 1d20 [10] - 1d4 [3] - 2 = **5**")

    def test_detalhado(self):
        r = roll("1d20 vs 5", Dados(20))
        self.assertIn("Crítico", describe_roll(r))

    def test_mensagem_maxima_cabe_no_discord(self):
        r = roll(f"{MAX_DADOS}d{MAX_LADOS}")
        self.assertLess(len(describe_roll_compact(r)), 2000)


if __name__ == "__main__":
    unittest.main()
