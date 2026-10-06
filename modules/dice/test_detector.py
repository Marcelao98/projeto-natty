"""
Testes do detector. Da raiz do projeto:
    python -m unittest discover -s modules/dice -t .
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from modules.dice.detector import detect_roll_pattern, is_roll_message  # noqa: E402


class TestDetector(unittest.TestCase):
    def test_detecta(self):
        casos = [
            ("eu rolo 1d20", "1d20"),
            ("rolo 2d6+3d8", "2d6+3d8"),
            ("1d20 com vantagem", "1d20 com vantagem"),
            ("roll 1d20 vs 15", "1d20 vs 15"),
            ("fiz um teste de destreza: 1d20+2 contra 12", "1d20+2 contra 12"),
            ("1d20", "1d20"),
            ("2d6", "2d6"),
            ("d20", "d20"),
            ("1d20!", "1d20!"),  # explosivo
            ("1d20.", "1d20"),
            ("4d6 tiro 1", "4d6 tiro 1"),
            ("rolo 4d6!t1", "4d6!t1"),
            ("Teste de Ataque: 1d20+5 vs DC 13", "1d20+5 vs DC 13"),
            ("rolando 1d20-1 com desvantagem, cd 10", "1d20-1 com desvantagem, cd 10"),
        ]
        for mensagem, esperado in casos:
            with self.subTest(mensagem=mensagem):
                self.assertEqual(detect_roll_pattern(mensagem), esperado)

    def test_ignora(self):
        casos = [
            "oi tudo bem",
            "como vai",
            "a espada dá 1d8 de dano",  # expressão solta numa frase
            "!r 1d20",                  # comando do Avrae
            "!roll 1d20+5",
            "o mapa tem 3d terreno",     # não é dado
            "abc1d20",
        ]
        for mensagem in casos:
            with self.subTest(mensagem=mensagem):
                self.assertFalse(is_roll_message(mensagem))


if __name__ == "__main__":
    unittest.main()
