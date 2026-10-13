"""
Testes do som de mesa: guardar sons (lista branca, tamanho, hash, sem path
traversal), apagar, cenas, e o motor ligando ambiente / disparando efeito
no mixer de verdade (com ffmpeg de verdade quando tem). Banco e pasta de
sons temporários.
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from modules.bardo import cog, motor, service
from modules.bardo.service import ErroDeColecao

GUILD = 1


class ComPastas(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        patcher = mock.patch.dict(os.environ, {"BARDO_DB_PATH": str(self.tmp / "bardo.db"),
                                               "BARDO_PASTA_SOM": str(self.tmp / "som")})
        patcher.start()
        self.addCleanup(patcher.stop)


class GuardarSom(ComPastas):
    def test_guarda_por_hash_com_padroes_do_tipo(self):
        som = service.guardar_som(GUILD, "Chuva Forte", "ambiente", "chuva.OGG", b"abc", 10, "clima, chuva, Clima")
        self.assertRegex(som["arquivo"], r"^[0-9a-f]{64}\.ogg$")
        self.assertTrue((self.tmp / "som" / "1" / som["arquivo"]).is_file())
        self.assertEqual((som["loop"], som["duck"], som["tags"]), (True, False, ["clima", "chuva"]))
        efeito = service.guardar_som(GUILD, "Trovão", "efeito", "x.wav", b"def")
        self.assertEqual((efeito["loop"], efeito["duck"]), (False, True))

    def test_recusas(self):
        service.guardar_som(GUILD, "Chuva", "ambiente", "a.mp3", b"abc")
        casos = [
            ("Outra", "ambiente", "a.exe", b"x"),         # extensão
            ("Outra", "ambiente", "a.mp3", b""),          # vazio
            ("Outra", "barulho", "a.mp3", b"x"),          # tipo
            ("chuva", "efeito", "b.mp3", b"zzz"),         # nome repetido
            ("Outra", "efeito", "b.mp3", b"abc"),         # mesmo áudio
        ]
        for nome, tipo, arquivo, conteudo in casos:
            with self.subTest(arquivo=arquivo, tipo=tipo, nome=nome), self.assertRaises(ErroDeColecao):
                service.guardar_som(GUILD, nome, tipo, arquivo, conteudo)
        with mock.patch.object(service, "MAX_BYTES_DO_SOM", 2), self.assertRaises(ErroDeColecao):
            service.guardar_som(GUILD, "Grande", "efeito", "g.mp3", b"123")

    def test_nome_do_arquivo_enviado_nao_vira_caminho(self):
        som = service.guardar_som(GUILD, "Esperto", "efeito", "../../etc/passwd.mp3", b"x")
        self.assertEqual(list((self.tmp / "som" / "1").iterdir()), [self.tmp / "som" / "1" / som["arquivo"]])
        for ruim in ("../x.mp3", "a" * 64 + ".mp3/../x", "nada.mp3"):
            with self.subTest(arquivo=ruim), self.assertRaises(service.ArquivoNaoEncontrado):
                service.caminho_do_som(GUILD, ruim)

    def test_som_tipo_musica_toca_pela_fila(self):
        som = service.guardar_som(GUILD, "Tema", "musica", "t.mp3", b"x")
        info = service.resolver_musica(service.link_do_som(GUILD, som))
        self.assertTrue(info["local"])
        self.assertTrue(info["stream_url"].endswith(som["arquivo"]))

    def test_apagar_tira_o_arquivo(self):
        som = service.guardar_som(GUILD, "Chuva", "ambiente", "a.mp3", b"abc", autor_id=10)
        with self.assertRaises(ErroDeColecao):
            service.apagar_som(GUILD, "Chuva", autor_id=20)
        self.assertEqual(service.apagar_som(GUILD, "chuva", autor_id=20, mestre=True), "Chuva")
        self.assertFalse((self.tmp / "som" / "1" / som["arquivo"]).exists())

    def test_configurar(self):
        service.guardar_som(GUILD, "Chuva", "ambiente", "a.mp3", b"abc")
        som = service.configurar_som(GUILD, "chuva", volume=140, duck=True, tags="noite")
        self.assertEqual((som["volume"], som["duck"], som["tags"]), (100, True, ["noite"]))

    def test_validar_cena(self):
        cena = service.validar_cena({"ambientes": [{"som": "chuva", "volume": 300}, {"som": ""}, "lixo"],
                                     "pads": ["trovão", 5], "ducking": "muito", "master": 40,
                                     "musica": {"playlist": "Taverna"}})
        self.assertEqual(cena, {"musica": {"playlist": "Taverna"}, "ambientes": [{"som": "chuva", "volume": 100}],
                                "pads": ["trovão"], "ducking": 60, "master": 40})
        with self.assertRaises(ErroDeColecao):
            service.validar_cena([])


def _wav(caminho: Path, segundos=0.4):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=330:duration={segundos}",
                    "-ac", "2", "-ar", "48000", str(caminho)], check=True)
    return caminho.read_bytes()


class Conexao:
    def __init__(self):
        self.source, self.tocando = None, False
        self.channel = SimpleNamespace(name="Taverna")

    def is_connected(self):
        return True

    def is_playing(self):
        return self.tocando

    def is_paused(self):
        return False

    def play(self, fonte, after=None):
        self.source, self.tocando = fonte, True


@unittest.skipUnless(shutil.which("ffmpeg"), "precisa do ffmpeg")
class MotorComSom(ComPastas):
    def setUp(self):
        super().setUp()
        self.bot = SimpleNamespace(user=None)
        self.c = cog.BardoCog(bot=self.bot)
        self.guild = SimpleNamespace(id=GUILD, voice_client=Conexao())
        self.addCleanup(self.desligar)
        self.ambiente = service.guardar_som(GUILD, "Chuva", "ambiente", "c.wav", _wav(self.tmp / "c.wav"))
        self.efeito = service.guardar_som(GUILD, "Trovão", "efeito", "t.wav", _wav(self.tmp / "t.wav", 0.2))

    def desligar(self):
        """Fecha os leitores antes de a pasta temporária sumir (senão o loop de ambiente reabre o ffmpeg)."""
        for mixer in self.c._mixers.values():
            mixer.parar_tudo()
            mixer.read()
        time.sleep(0.05)

    def rodar(self, corrotina):
        return asyncio.run(corrotina)

    def nivel_maximo(self, quadros=60):
        mixer, pico = self.c._mixer(self.guild), 0
        for _ in range(quadros):
            q = mixer.read()
            if q:
                pico = max(pico, int(np.abs(np.frombuffer(q, dtype="<i2")).max()))
            time.sleep(0.003)
        return pico

    def test_ambiente_liga_toca_e_desliga(self):
        resposta = self.rodar(self.c._som_tocar(self.guild, None, "chuva"))
        self.assertIn("Ambiente **Chuva** ligado", resposta)
        self.assertIs(self.guild.voice_client.source, self.c._mixer(self.guild))
        self.assertGreater(self.nivel_maximo(), 500)
        self.assertIn("Desliguei", self.rodar(self.c._som_parar(self.guild, "Chuva")))
        self.assertEqual(self.c._mixer(self.guild).ambientes, {})

    def test_efeito_dispara_e_fica_em_cache(self):
        self.assertEqual(self.rodar(self.c._som_tocar(self.guild, None, "trovão")), "💥 **Trovão**")
        self.assertGreater(self.nivel_maximo(15), 500)
        with mock.patch.object(motor, "decodificar_arquivo") as decodificar:
            self.rodar(self.c._som_tocar(self.guild, None, "Trovão"))
        decodificar.assert_not_called()

    def test_sem_call_e_sem_canal(self):
        guild = SimpleNamespace(id=GUILD, voice_client=None)
        self.assertIn("Chama a Natty", self.rodar(self.c._som_tocar(guild, None, "Chuva")))

    def test_nome_errado_sugere(self):
        with self.assertRaises(ErroDeColecao) as ctx:
            self.rodar(self.c._som_tocar(self.guild, None, "Chuvaa"))
        self.assertIn("Chuva", str(ctx.exception))

    def test_cena_salva_e_aplica(self):
        self.rodar(self.c._som_tocar(self.guild, None, "Chuva"))
        self.c._mudar_master(self.guild, 70)
        self.c._mudar_ducking(self.guild, 30)
        self.assertIn("Cena **Tempestade** salva (1 ambientes)", self.rodar(self.c._cena_salvar(self.guild, "Tempestade", 10)))
        self.rodar(self.c._som_parar(self.guild))
        self.c._mudar_master(self.guild, 100)
        resposta = self.rodar(self.c._cena_aplicar(self.guild, None, "tempestade"))
        self.assertIn("1 ambientes", resposta)
        self.assertEqual((self.c._master(self.guild), self.c._ducking(self.guild)), (70, 30))
        self.assertIn("chuva", self.c._mixer(self.guild).ambientes)

    def test_painel_comanda_o_som(self):
        self.rodar(self.c.cog_load())
        controle = self.bot.controles["bardo"]
        dono = SimpleNamespace(id=7, guild=SimpleNamespace(owner_id=7), roles=[], voice=None)
        sons = self.rodar(controle.executar(self.guild, dono, "sons", {}))["dados"]
        self.assertEqual({x["nome"] for x in sons}, {"Chuva", "Trovão"})
        self.assertTrue(self.rodar(controle.executar(self.guild, dono, "som_tocar", {"nome": "Chuva"}))["ok"])
        self.assertTrue(self.rodar(controle.executar(self.guild, dono, "som_volume", {"nome": "Chuva", "nivel": 40}))["ok"])
        self.assertEqual(controle.estado(self.guild)["mixer"]["ambientes"],
                         [{"som": "chuva", "volume": 40, "duck": False}])
        self.assertTrue(self.rodar(controle.executar(self.guild, dono, "master", {"nivel": 80}))["ok"])
        self.assertFalse(self.rodar(controle.executar(self.guild, dono, "master", {"nivel": 120}))["ok"])
        r = self.rodar(controle.enviar_som(self.guild, dono, "Porta", "efeito", "p.wav", b"RIFF"))
        self.assertTrue(r["ok"])
        viajante = SimpleNamespace(id=9, guild=SimpleNamespace(owner_id=7), roles=[])
        self.assertFalse(self.rodar(controle.enviar_som(self.guild, viajante, "X", "efeito", "x.wav", b"1"))["ok"])
        self.assertIsNotNone(self.rodar(controle.arquivo_do_som(self.guild, dono, "Porta")))


if __name__ == "__main__":
    unittest.main()
