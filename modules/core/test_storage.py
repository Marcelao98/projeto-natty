"""
Testes do banco do NAT-CORE (storage.py), num SQLite temporário. Da raiz:
    python -m unittest discover -s modules/core -t .
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from modules.core import storage  # noqa: E402


class BancoTemporario(unittest.TestCase):
    """Cada teste ganha um data/natty.db próprio numa pasta temporária."""

    def setUp(self):
        self._pasta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._pasta.cleanup)
        self.caminho = Path(self._pasta.name) / "natty.db"
        patcher = mock.patch.dict(os.environ, {"NATTY_DB_PATH": str(self.caminho)})
        patcher.start()
        self.addCleanup(patcher.stop)
        storage.inicializar()


class TestInicializar(BancoTemporario):
    def test_cria_schema_versionado(self):
        con = sqlite3.connect(self.caminho)
        try:
            versao = con.execute("PRAGMA user_version").fetchone()[0]
            tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
        self.assertEqual(versao, storage.SCHEMA_VERSAO)
        self.assertTrue({"jogadores", "personagens", "missoes", "missao_participantes"} <= tabelas)

    def test_inicializar_de_novo_nao_apaga_dados(self):
        storage.inserir_personagem("Kael", "kael", "Kira", None, None, 1)
        storage.inicializar()
        self.assertEqual(len(storage.listar_personagens()), 1)

    def test_arquivo_corrompido_levanta_e_nao_e_tocado(self):
        self.caminho.unlink()
        lixo = b"isto nao e um banco sqlite " * 100
        self.caminho.write_bytes(lixo)
        with self.assertRaises(storage.BancoIlegivel):
            storage.inicializar()
        self.assertEqual(self.caminho.read_bytes(), lixo)

    def test_banco_sumiu_com_backups_nao_recria_vazio(self):
        storage.fazer_backup("teste")
        self.caminho.unlink()
        with self.assertRaises(storage.BancoIlegivel):
            storage.inicializar()
        self.assertFalse(self.caminho.exists())

    def test_migra_banco_v1_ate_a_versao_atual_sem_perder_dados(self):
        self.caminho.unlink()
        con = sqlite3.connect(self.caminho)
        con.executescript("""
            CREATE TABLE jogadores (discord_id TEXT PRIMARY KEY, username TEXT, nome_exibicao TEXT,
                                    nome TEXT, criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL);
            CREATE TABLE personagens (id INTEGER PRIMARY KEY AUTOINCREMENT, criado_em TEXT NOT NULL,
                                      nome TEXT NOT NULL, nome_chave TEXT NOT NULL UNIQUE,
                                      nome_jogador TEXT, jogador_discord_id TEXT REFERENCES jogadores(discord_id),
                                      link_ficha TEXT, nivel_inicial INTEGER, nivel_atual INTEGER);
            INSERT INTO jogadores VALUES ('1', 'kira', 'Kira', 'Kira', 'x', 'x');
            INSERT INTO personagens (criado_em, nome, nome_chave, jogador_discord_id, nivel_inicial)
                VALUES ('2026-09-01T20:05:32', 'Kael', 'kael', '1', 3);
            PRAGMA user_version = 1;
        """)
        con.close()
        storage.inicializar()
        j = storage.buscar_jogador("1")
        self.assertEqual((j["username"], j["ativo"]), ("kira", 1))
        p = storage.listar_personagens("1")[0]
        self.assertEqual((p["nome"], p["criado_em"], p["historia"]), ("Kael", "2026-09-01T20:05:32", None))
        self.assertTrue(any("schema-v1" in b.name for b in storage.backups()))
        con = sqlite3.connect(self.caminho)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], storage.SCHEMA_VERSAO)
        con.close()

    def test_versao_mais_nova_que_o_codigo_levanta(self):
        con = sqlite3.connect(self.caminho)
        con.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSAO + 1}")
        con.close()
        with self.assertRaises(storage.BancoIlegivel):
            storage.inicializar()


class TestBackup(BancoTemporario):
    def test_backup_tem_os_dados(self):
        storage.inserir_personagem("Kael", "kael", "Kira", None, None, 1)
        copia = storage.fazer_backup("teste")
        self.assertEqual(storage.resumo_do_arquivo(copia)["personagens"], 1)

    def test_mantem_so_os_mais_recentes(self):
        for _ in range(storage.BACKUPS_MANTIDOS + 3):
            storage.fazer_backup("teste")
        self.assertEqual(len(storage.backups()), storage.BACKUPS_MANTIDOS)

    def test_restaurar_guarda_o_arquivo_ruim(self):
        storage.inserir_personagem("Kael", "kael", "Kira", None, None, 1)
        copia = storage.fazer_backup("teste")
        self.caminho.write_bytes(b"corrompido" * 100)
        guardado = storage.restaurar_backup(copia)
        self.assertEqual(guardado.read_bytes(), b"corrompido" * 100)
        self.assertEqual(len(storage.listar_personagens()), 1)


class TestJogadores(BancoTemporario):
    def test_upsert_atualiza_e_nao_apaga_com_none(self):
        storage.salvar_jogador("1", "kira", "Kira", nome="Kira")
        storage.salvar_jogador("1", "kira_nova", None)
        j = storage.buscar_jogador("1")
        self.assertEqual((j["username"], j["nome_exibicao"], j["nome"]), ("kira_nova", "Kira", "Kira"))

    def test_retorna_o_que_aconteceu(self):
        self.assertEqual(storage.salvar_jogador("1", "kira", "Kira", ativo=True), "novo")
        self.assertIsNone(storage.salvar_jogador("1", "kira", "Kira", ativo=True))
        self.assertEqual(storage.salvar_jogador("1", "kira", "Kira", ativo=False), "atualizado")
        self.assertEqual(storage.buscar_jogador("1")["ativo"], 0)
        self.assertIsNone(storage.salvar_jogador("1", "kira", None))  # ativo=None não mexe
        self.assertEqual(storage.buscar_jogador("1")["ativo"], 0)

    def test_marcar_ausentes(self):
        for i in ("1", "2", "3"):
            storage.salvar_jogador(i, f"u{i}", None)
        self.assertEqual(storage.marcar_ausentes({"1"}), 2)
        self.assertEqual([j["discord_id"] for j in storage.listar_jogadores(somente_ativos=True)], ["1"])
        self.assertEqual(storage.marcar_ausentes({"1"}), 0)

    def test_atualizado_em_so_muda_se_algo_mudar(self):
        with mock.patch.object(storage, "agora", return_value="2026-01-01T00:00:00"):
            storage.salvar_jogador("1", "kira", "Kira")
        with mock.patch.object(storage, "agora", return_value="2026-02-02T00:00:00"):
            storage.salvar_jogador("1", "kira", "Kira")
        self.assertEqual(storage.buscar_jogador("1")["atualizado_em"], "2026-01-01T00:00:00")


class TestPersonagens(BancoTemporario):
    def test_nome_chave_unico(self):
        storage.inserir_personagem("Ícaro", "icaro", "A", None, None, 1)
        with self.assertRaises(sqlite3.IntegrityError):
            storage.inserir_personagem("icaro", "icaro", "B", None, None, 1)

    def test_inserir_cria_jogador_minimo_pra_fk(self):
        storage.inserir_personagem("Kael", "kael", "Kira", "123", None, 1)
        self.assertIsNotNone(storage.buscar_jogador("123"))

    def test_fk_ligada(self):
        with storage.transacao() as con:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO personagens (criado_em, nome, nome_chave, jogador_discord_id) "
                    "VALUES ('x', 'A', 'a', 'nao-existe')"
                )

    def test_transacao_desfaz_tudo_se_der_erro(self):
        with self.assertRaises(RuntimeError):
            with storage.transacao() as con:
                storage.inserir_personagem("Kael", "kael", "Kira", None, None, 1, con=con)
                raise RuntimeError
        self.assertEqual(storage.listar_personagens(), [])

    def test_vincular_sem_forcar_nao_sobrescreve(self):
        a = storage.inserir_personagem("A", "a", "Kira", None, None, 1)
        b = storage.inserir_personagem("B", "b", "Kira", "999", None, 1)
        storage.salvar_jogador("111", "kira", "Kira")
        self.assertEqual(storage.vincular_personagens([a, b], "111"), 1)
        self.assertEqual(storage.listar_personagens("999")[0]["nome"], "B")
        self.assertEqual(storage.vincular_personagens([b], "111", forcar=True), 1)
        self.assertEqual(len(storage.listar_personagens("111")), 2)

    def test_deletar_personagem_mantem_historico_da_missao(self):
        pid = storage.inserir_personagem("Kael", "kael", "Kira", "1", None, 1)
        mid = storage.inserir_missao(
            {"criado_em": "2026-09-03T00:00:00", "nome": "M", "nome_chave": "m", "dificuldade": "Normal"},
            [(pid, "Kael")],
        )
        self.assertTrue(storage.remover_personagem("1", "kael"))
        with storage.transacao() as con:
            linha = con.execute(
                "SELECT personagem_id, personagem_nome FROM missao_participantes WHERE missao_id = ?", (mid,)
            ).fetchone()
        self.assertEqual((linha[0], linha[1]), (None, "Kael"))

    def test_vincular_condutor_sem_forcar_nao_sobrescreve(self):
        storage.salvar_jogador("1", "a", None)
        storage.salvar_jogador("2", "b", None)
        m1 = storage.inserir_missao({"criado_em": "x", "nome": "M1", "nome_chave": "m1", "condutor_nome": "Alex"}, [])
        m2 = storage.inserir_missao({"criado_em": "x", "nome": "M2", "nome_chave": "m2",
                                     "condutor_nome": "Alex", "condutor_discord_id": "2"}, [])
        self.assertEqual(storage.vincular_condutor([m1, m2], "1"), 1)
        self.assertEqual(storage.vincular_condutor([m2], "1", forcar=True), 1)
        self.assertEqual({m["condutor_discord_id"] for m in storage.listar_missoes()}, {"1"})

    def test_dificuldade_fora_da_lista_e_recusada(self):
        with self.assertRaises(sqlite3.IntegrityError):
            storage.inserir_missao({"criado_em": "x", "nome": "M", "nome_chave": "m", "dificuldade": "Outra"}, [])


if __name__ == "__main__":
    unittest.main()
