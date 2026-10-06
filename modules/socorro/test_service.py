"""
Testes do módulo Socorro. Da raiz do projeto:
    python -m unittest discover -s modules/socorro -t .
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from modules.socorro.service import MODULOS, interpretar_pedido, texto_de_ajuda  # noqa: E402


class InterpretarPedido(unittest.TestCase):
    """O cog só chama com menção de verdade e passa o texto SEM a menção."""

    def test_geral(self):
        for texto in [" socorro", ", socorro!", " ajuda", " help", " comandos"]:
            with self.subTest(texto=texto):
                self.assertEqual(interpretar_pedido(texto), "geral")

    def test_por_modulo(self):
        casos = {
            " socorro dice": "dice",
            " socorro dados": "dice",
            " ajuda com rolagem": "dice",
            " socorro bardo": "bardo",
            " socorro música": "bardo",
            " socorro core": "core",
            " ajuda personagens": "core",
            " socorro registrar": "core",
            " socorro voz": "voz",
            " ajuda echo": "voz",
            " socorro nat20": "voz",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(interpretar_pedido(texto), esperado)

    def test_nao_e_socorro(self):
        for texto in [" toca isso, socorro", " pausa", " socorrista"]:
            with self.subTest(texto=texto):
                self.assertIsNone(interpretar_pedido(texto))

    def test_nome_escrito_nao_chama_mais(self):
        # Sem @, o cog nem chama; e mesmo que chamasse, o nome sobraria no texto.
        self.assertIsNone(interpretar_pedido("natty socorro"))


class Textos(unittest.TestCase):
    def test_geral_cita_todos_os_modulos(self):
        geral = texto_de_ajuda().lower()
        for modulo in MODULOS:
            with self.subTest(modulo=modulo):
                self.assertIn(f"@natty socorro {modulo}", geral)

    def test_ajuda_nao_ensina_o_nome_sem_arroba(self):
        for topico in ("geral", *MODULOS):
            with self.subTest(topico=topico):
                self.assertNotIn("`natty ", texto_de_ajuda(topico))

    def test_cabem_numa_mensagem(self):
        for topico in ("geral", *MODULOS):
            with self.subTest(topico=topico):
                self.assertLessEqual(len(texto_de_ajuda(topico)), 2000)


if __name__ == "__main__":
    unittest.main()
