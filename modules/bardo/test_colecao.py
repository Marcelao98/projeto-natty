"""
Testes do bardo.db (storage.py) e do que o service faz em cima: playlists e
cenas salvas por servidor, descobertas em mesa por servidor, cargo de mestre.
Cada teste usa um banco novo numa pasta temporária (BARDO_DB_PATH).
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modules.bardo import service, storage
from modules.bardo.service import ErroDeColecao, Musica

GUILD, OUTRA = 1, 2


class ComBancoTemporario(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.banco = Path(tmp.name) / "bardo.db"
        patcher = mock.patch.dict(os.environ, {"BARDO_DB_PATH": str(self.banco)})
        patcher.start()
        self.addCleanup(patcher.stop)


def _musicas(n):
    return [Musica(f"Faixa {i}", f"https://youtu.be/{i}", 60 + i) for i in range(n)]


class Storage(ComBancoTemporario):
    def test_cria_o_schema_e_a_versao(self):
        storage.listar_playlists(GUILD)
        con = sqlite3.connect(self.banco)
        tabelas = {l[0] for l in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({"playlists", "playlist_itens", "sons", "cenas", "descobertas"} <= tabelas)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], storage.SCHEMA_VERSAO)
        con.close()

    def test_apagar_playlist_apaga_os_itens(self):
        storage.salvar_playlist(GUILD, "Taverna", "taverna", [{"titulo": "a", "link": "x"}], "10")
        storage.apagar_playlist(GUILD, "taverna")
        con = sqlite3.connect(self.banco)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM playlist_itens").fetchone()[0], 0)
        con.close()

    def test_sons(self):
        som = {"nome": "Chuva", "nome_chave": "chuva", "tipo": "ambiente", "arquivo": "abc.ogg", "hash": "abc",
               "tags": ["clima"], "volume": 70, "loop": True, "duck": False, "criado_por": "10"}
        storage.inserir_som(GUILD, som)
        self.assertEqual(storage.buscar_som(GUILD, "chuva")["tags"], ["clima"])
        self.assertTrue(storage.buscar_som(GUILD, "chuva")["loop"])
        self.assertEqual(storage.som_com_hash(GUILD, "abc")["nome"], "Chuva")
        self.assertIsNone(storage.buscar_som(OUTRA, "chuva"))
        self.assertTrue(storage.atualizar_som(GUILD, "chuva", {"volume": 30, "nome": "ignorado"}))
        self.assertEqual(storage.buscar_som(GUILD, "chuva")["volume"], 30)
        with self.assertRaises(sqlite3.IntegrityError):
            storage.inserir_som(GUILD, {**som, "tipo": "barulho", "nome_chave": "x"})
        self.assertEqual(storage.apagar_som(GUILD, "chuva")["arquivo"], "abc.ogg")
        self.assertEqual(storage.listar_sons(GUILD), [])


class Playlists(ComBancoTemporario):
    def test_salvar_e_carregar_na_ordem(self):
        self.assertEqual(service.salvar_playlist(GUILD, "  Taverna   do Javali ", _musicas(3), 10),
                         ("Taverna do Javali", 3))
        nome, musicas = service.carregar_playlist(GUILD, "taverna do javali")
        self.assertEqual(nome, "Taverna do Javali")
        self.assertEqual(musicas, _musicas(3))

    def test_por_servidor(self):
        service.salvar_playlist(GUILD, "Taverna", _musicas(1))
        with self.assertRaises(ErroDeColecao):
            service.carregar_playlist(OUTRA, "Taverna")
        self.assertEqual(service.listar_playlists(OUTRA), [])
        self.assertEqual([(p["nome"], p["quantas"]) for p in service.listar_playlists(GUILD)], [("Taverna", 1)])

    def test_nome_repetido_so_com_substituir(self):
        service.salvar_playlist(GUILD, "Taverna", _musicas(1))
        with self.assertRaises(ErroDeColecao):
            service.salvar_playlist(GUILD, "taverna", _musicas(2))
        service.salvar_playlist(GUILD, "taverna", _musicas(2), substituir=True)
        self.assertEqual(len(service.carregar_playlist(GUILD, "Taverna")[1]), 2)

    def test_recusas(self):
        for nome, musicas in [("", _musicas(1)), ("x" * 61, _musicas(1)), ("!!!", _musicas(1)), ("Vazia", [])]:
            with self.subTest(nome=nome), self.assertRaises(ErroDeColecao):
                service.salvar_playlist(GUILD, nome, musicas)

    def test_nome_errado_sugere(self):
        service.salvar_playlist(GUILD, "Taverna", _musicas(1))
        with self.assertRaises(ErroDeColecao) as ctx:
            service.carregar_playlist(GUILD, "Tavrena")
        self.assertIn("Você quis dizer **Taverna**?", str(ctx.exception))

    def test_apagar_so_quem_criou_ou_mestre(self):
        service.salvar_playlist(GUILD, "Taverna", _musicas(1), autor_id=10)
        with self.assertRaises(ErroDeColecao):
            service.apagar_playlist(GUILD, "Taverna", autor_id=20)
        self.assertEqual(service.apagar_playlist(GUILD, "Taverna", autor_id=20, mestre=True), "Taverna")
        service.salvar_playlist(GUILD, "Masmorra", _musicas(1), autor_id=10)
        self.assertEqual(service.apagar_playlist(GUILD, "masmorra", autor_id=10), "Masmorra")

    def test_pedido_por_texto(self):
        self.assertEqual(service.interpretar_pedido("natty toca a playlist Taverna do Javali"),
                         service.Pedido("tocar_playlist", busca="Taverna do Javali"))
        self.assertEqual(service.interpretar_pedido("natty qual a playlist?").acao, "fila")


class Cenas(ComBancoTemporario):
    def test_salvar_atualizar_carregar_apagar(self):
        service.salvar_cena(GUILD, "Floresta", {"ambientes": [{"som": "chuva", "volume": 40}]})
        service.salvar_cena(GUILD, "floresta", {"ambientes": []})  # mesmo nome atualiza
        nome, dados = service.carregar_cena(GUILD, "Floresta")
        self.assertEqual((nome, dados["ambientes"], dados["ducking"]), ("floresta", [], 60))
        self.assertEqual(len(service.listar_cenas(GUILD)), 1)
        self.assertTrue(service.apagar_cena(GUILD, "Floresta"))
        with self.assertRaises(ErroDeColecao):
            service.carregar_cena(GUILD, "Floresta")


class DescobertasPorServidor(ComBancoTemporario):
    BASE = [{"id": "x", "nome": "Firelink Shrine", "link": "https://www.youtube.com/watch?v=base1",
             "escopo": "faixa_individual", "origem": {"nome": "Dark Souls", "tipo": "jogo"},
             "temas": ["calmo"], "categorias": ["calmo"]}]

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(service, "carregar_dataset", return_value=list(self.BASE))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_grava_no_servidor_e_a_busca_acha_so_la(self):
        entrada = service.adicionar_descoberta(GUILD, "Canção do Javali", "https://youtu.be/javali1", ["taverna"])
        self.assertEqual(entrada["link"], "https://www.youtube.com/watch?v=javali1")
        self.assertEqual([m.titulo for m in service.buscar_musicas("javali", guild_id=GUILD)[0]], ["Canção do Javali"])
        self.assertEqual(service.buscar_musicas("javali", guild_id=OUTRA)[0], [])
        self.assertEqual(len(service.buscar_musicas("firelink", guild_id=OUTRA)[0]), 1)  # a base vale pra todos

    def test_nao_duplica_nem_o_que_ja_esta_na_base(self):
        service.adicionar_descoberta(GUILD, "Canção do Javali", "https://youtu.be/javali1", [])
        for link in ["https://www.youtube.com/watch?v=javali1", "https://youtu.be/base1"]:
            with self.subTest(link=link), self.assertRaises(service.MusicaJaNoDataset):
                service.adicionar_descoberta(GUILD, "x", link, [])

    def test_sem_tema_vira_nao_classificado(self):
        entrada = service.adicionar_descoberta(GUILD, "Canção", "https://youtu.be/c1", [])
        self.assertEqual(entrada["temas"], [service.NAO_CLASSIFICADO])


class CargoDeMestre(unittest.TestCase):
    def test_condutor_por_padrao_sem_acento_nem_maiuscula(self):
        with mock.patch.dict(os.environ, {"BARDO_CARGO_MESTRE": ""}):
            self.assertTrue(service.eh_mestre(["Viajante", "condutor"]))
            self.assertFalse(service.eh_mestre(["Viajante"]))

    def test_configuravel(self):
        with mock.patch.dict(os.environ, {"BARDO_CARGO_MESTRE": "Mestre"}):
            self.assertTrue(service.eh_mestre(["mestre"]))
            self.assertFalse(service.eh_mestre(["Condutor"]))


if __name__ == "__main__":
    unittest.main()
