"""
Testes das partes sem rede dos scripts de migração e vínculo (normalização de
datas/níveis, leitura das abas, sugestão de candidatos). Da raiz:
    python -m unittest discover -s modules/core -t .
"""

import importlib.util
import os
import sqlite3
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))


def _carregar(nome):
    spec = importlib.util.spec_from_file_location(nome, RAIZ / "scripts" / f"{nome}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


migrar = _carregar("migrar_sheets_para_sqlite")
vincular = _carregar("vincular_jogadores")
importar = _carregar("importar_missoes_historicas")

CABECALHO = ["Timestamp", "Nome do personagem ", "Nome do jogador", "Link da ficha", "Nível Inicial.", "Nível Atual"]


class TestNormalizacao(unittest.TestCase):
    def test_datas_mes_primeiro(self):
        self.assertEqual(migrar.converter_data("9/1/2026 20:05:32"), "2026-09-01T20:05:32")
        self.assertEqual(migrar.converter_data("09/17/2026"), "2026-09-17")
        self.assertEqual(migrar.converter_data("9/3/2026 8:05"), "2026-09-03T08:05:00")
        self.assertIsNone(migrar.converter_data("  "))

    def test_data_invalida_levanta(self):
        for valor in ("17/09/2026", "2026-09-17", "ontem"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                migrar.converter_data(valor)

    def test_nivel(self):
        self.assertEqual(migrar.converter_nivel(" 3 "), 3)
        self.assertEqual(migrar.converter_nivel("3,0"), 3)
        self.assertIsNone(migrar.converter_nivel(""))
        with self.assertRaises(ValueError):
            migrar.converter_nivel("três")

    def test_discord_id_tira_apostrofo(self):
        self.assertEqual(migrar.converter_discord_id("'123456789012345678"), "123456789012345678")
        self.assertIsNone(migrar.converter_discord_id(""))


class TestMontarPersonagens(unittest.TestCase):
    def test_normaliza_linha(self):
        ps, avisos, erros = migrar.montar_personagens([
            CABECALHO,
            ["9/1/2026 20:05:32", "  Kael Noctis ", " Kira", "https://dicecloud.com/character/X/", "1", ""],
            ["", "", "", "", "", ""],
        ])
        self.assertEqual((avisos, erros), ([], []))
        p = ps[0]
        self.assertEqual((p["nome"], p["nome_jogador"], p["criado_em"]), ("Kael Noctis", "Kira", "2026-09-01T20:05:32"))
        self.assertEqual((p["nivel_inicial"], p["nivel_atual"], p["jogador_discord_id"]), (1, None, None))

    def test_nome_repetido_e_erro(self):
        _, _, erros = migrar.montar_personagens([
            CABECALHO,
            ["9/1/2026", "Ícaro", "A", "", "1", ""],
            ["9/2/2026", "icaro", "B", "", "1", ""],
        ])
        self.assertEqual(len(erros), 1)

    def test_coluna_desconhecida_vira_aviso(self):
        _, avisos, _ = migrar.montar_personagens([CABECALHO + ["Classe"]])
        self.assertTrue(any("Classe" in a for a in avisos))


class TestMontarMissoes(unittest.TestCase):
    CAB = ["Timestamp", "Nome da missão.", "Data da missão.", "Dificuldade", "Quem conduziu essa aventura?",
           "Quais personagens participaram desta missão?\nDigite os nomes...", "Conte o que aconteceu."]

    def test_dificuldade_com_ponto_e_outra(self):
        ms, avisos, erros = migrar.montar_missoes([
            self.CAB,
            ["9/15/2026 12:29:39", "M1", "9/3/2026", "Difícil.", "Marcelo", "Kael, Sal Dorn", "texto"],
            ["9/16/2026 12:00:00", "M2", "9/4/2026", "Outra", "Alex", "", ""],
        ], {"kael": "Kael"})
        self.assertEqual(erros, [])
        self.assertEqual(ms[0]["dados"]["dificuldade"], "Difícil")
        self.assertEqual(ms[0]["dados"]["data"], "2026-09-03")
        self.assertEqual(ms[0]["participantes"], ["Kael", "Sal Dorn"])
        self.assertIsNone(ms[1]["dados"]["dificuldade"])
        self.assertIn("Outra", ms[1]["dados"]["observacoes"])
        self.assertTrue(any("Sal Dorn" in a for a in avisos))

    def test_aba_vazia(self):
        self.assertEqual(migrar.montar_missoes(None, {}), ([], [], []))
        self.assertEqual(migrar.montar_missoes([self.CAB], {}), ([], [], []))


class TestCandidatos(unittest.TestCase):
    MEMBROS = [
        vincular.Membro("1", "meduardo98", "Mestre"),
        vincular.Membro("2", "kira_dnd", "Kira"),
        vincular.Membro("3", "kirara", "kirara"),
        vincular.Membro("4", "adr", "Adriel"),
        vincular.Membro("5", "zzz", "zzz"),
    ]

    def test_igual_vem_antes_de_parcial(self):
        self.assertEqual([m.id for m in vincular.candidatos("Kira", self.MEMBROS)], ["2", "3"])

    def test_palavra_do_nome_conta(self):
        membros = self.MEMBROS + [vincular.Membro("6", "manoel.alx", None)]
        self.assertEqual([m.id for m in vincular.candidatos("Alex Manoel", membros)], ["6"])

    def test_apelido_conta(self):
        self.assertEqual(vincular.candidatos("adriel", self.MEMBROS)[0].id, "4")

    def test_quem_saiu_vem_depois(self):
        membros = [vincular.Membro("7", "kira_velha", "Kira", ativo=False)] + self.MEMBROS
        self.assertEqual([m.id for m in vincular.candidatos("Kira", membros)][:2], ["2", "7"])

    def test_apelido_com_nome_do_personagem(self):
        membros = self.MEMBROS + [
            vincular.Membro("8", "sun_yama", "Kael | Recruta"),
            vincular.Membro("9", "usuario_x", "Aldric"),
        ]
        self.assertEqual(vincular.candidatos("Kira", membros, ["Kael Noctis", "Recruta"])[0].id, "2")
        self.assertIn("8", [m.id for m in vincular.candidatos("Kira", membros, ["Kael Noctis", "Recruta"])])
        self.assertEqual(vincular.candidatos("Isaac", membros, ["Aldric"])[0].id, "9")

    def test_sugestao_conhecida_primeiro(self):
        self.assertEqual(vincular.candidatos("Marcelo", self.MEMBROS)[0].username, "meduardo98")

    def test_achar_por_username_ou_id(self):
        self.assertEqual(vincular.achar("@Kira_DND", self.MEMBROS).id, "2")
        self.assertEqual(vincular.achar("4", self.MEMBROS).username, "adr")
        self.assertIsNone(vincular.achar("ninguem", self.MEMBROS))


class TestAgrupar(unittest.TestCase):
    def test_jogadores_e_condutores(self):
        personagens = [
            {"id": 1, "nome": "A", "nome_jogador": "Kira", "jogador_discord_id": None},
            {"id": 2, "nome": "B", "nome_jogador": "kira", "jogador_discord_id": None},
            {"id": 3, "nome": "C", "nome_jogador": "Marcelo", "jogador_discord_id": None},
        ]
        missoes = [
            {"id": 10, "nome": "M1", "condutor_nome": "marcelo", "condutor_discord_id": None},
            {"id": 11, "nome": "M2", "condutor_nome": "Alex", "condutor_discord_id": None},
        ]
        jogadores, condutores = vincular.agrupar(personagens, missoes)
        self.assertEqual([(g.nome, len(g.personagens), len(g.missoes)) for g in jogadores],
                         [("Kira", 2, 0), ("Marcelo", 1, 1)])
        self.assertEqual([(g.nome, len(g.missoes)) for g in condutores], [("Alex", 1)])


# --- importar_missoes_historicas ---------------------------------------------

from modules.core import storage  # noqa: E402
from modules.core.test_storage import BancoTemporario  # noqa: E402


def _missao_arquivo(nome, **extra):
    m = {"nome": nome, "dificuldade": "Difícil", "data": "15/09/2026", "condutor": "Mestre",
         "relato": "Relato do post.", "resultado": "Concluída.", "xp": 300, "gold": 50,
         "outras_recompensas": "Cavalos.", "observacoes": "Obs.", "viajantes_post": []}
    m.update(extra)
    return m


def _participantes(caminho):
    con = sqlite3.connect(caminho)
    try:
        return con.execute(
            "SELECT personagem_nome, personagem_id FROM missao_participantes ORDER BY id"
        ).fetchall()
    finally:
        con.close()


class TestImportarConversoes(unittest.TestCase):
    def test_datas(self):
        self.assertEqual(importar.data_iso("03/09/2026"), "2026-09-03")
        self.assertIsNone(importar.data_iso(None))
        self.assertEqual(importar.momento_iso("24/09/2026 20:27"), "2026-09-24T20:27:00")
        with self.assertRaises(ValueError):
            importar.data_iso("2026-09-03")

    def test_xp_nota_vai_pro_fim_das_observacoes(self):
        campos = importar.campos_do_arquivo(_missao_arquivo("M", xp_nota="evento com XP em dobro"))
        self.assertEqual(campos["observacoes"], "Obs.\n\nNota de XP: evento com XP em dobro")
        campos = importar.campos_do_arquivo(_missao_arquivo("M", observacoes=None, xp_nota="dobro"))
        self.assertEqual(campos["observacoes"], "Nota de XP: dobro")


class TestImportarResolucao(unittest.TestCase):
    JOGADORES = [
        {"discord_id": "1", "username": "meduardo98", "nome_exibicao": "Mestre", "nome": "Marcelo"},
        {"discord_id": "2", "username": "usuario_fox", "nome_exibicao": "Vexil [LUA]", "nome": None},
        {"discord_id": "3", "username": "sun_yama", "nome_exibicao": "Kael | Recruta", "nome": None},
        {"discord_id": "4", "username": "outro", "nome_exibicao": "Alex", "nome": None},
    ]
    PERSONAGENS = [
        {"id": 10, "nome": "Ferrugem", "jogador_discord_id": "1"},
        {"id": 11, "nome": "Knight", "jogador_discord_id": "4"},
        {"id": 12, "nome": "Gorduk", "jogador_discord_id": "4"},
        {"id": 13, "nome": "Kael Noctis", "jogador_discord_id": "3"},
        {"id": 14, "nome": "Yuji", "jogador_discord_id": "3"},
    ]

    def _resolver(self, mencao):
        return importar.resolver_jogador(mencao, self.JOGADORES, self.PERSONAGENS)

    def test_exato_parcial_e_via_personagem(self):
        r = self._resolver("mestre")
        self.assertEqual((r.como, r.jogador["discord_id"]), ("exato", "1"))
        r = self._resolver("Vexil")  # casa com "Vexil [LUA]"
        self.assertEqual((r.como, r.jogador["discord_id"]), ("parcial", "2"))
        r = self._resolver("Gorduk")  # nenhum jogador com esse nome: é personagem do 4
        self.assertEqual((r.como, r.jogador["discord_id"], r.personagem["id"]), ("via personagem", "4", 12))
        self.assertEqual(self._resolver("Ninguém").como, "não encontrado")

    def test_personagem_unico_ambiguo_e_nao_registrado(self):
        res = self._resolver("Mestre")
        self.assertEqual(importar.resolver_personagem(None, res, self.PERSONAGENS)[:2],
                         ("ok", self.PERSONAGENS[0]))
        res = self._resolver("Kael | Recruta")
        self.assertEqual(importar.resolver_personagem(None, res, self.PERSONAGENS)[0], "ambíguo")
        self.assertEqual(importar.resolver_personagem("Kael", res, self.PERSONAGENS)[2], "Kael Noctis")
        self.assertEqual(importar.resolver_personagem("Lucy", res, self.PERSONAGENS),
                         ("não encontrado", None, "Lucy"))


class TestImportarNoBanco(BancoTemporario):
    def setUp(self):
        super().setUp()
        storage.salvar_jogador("1", "meduardo98", "Mestre", nome="Marcelo")
        storage.inserir_personagem("Ferrugem", "ferrugem", "Marcelo", "1", None, 1)
        storage.inserir_missao({"criado_em": "2026-09-16T17:33:17", "nome": "Vovó  está preocupada",
                                "nome_chave": "vovo esta preocupada", "data": "2026-09-15",
                                "dificuldade": "Difícil", "condutor_nome": "Marcelo",
                                "relato": "Relato longo do Forms."}, [(None, "Kael Noctis")])

    def _planejar(self, arquivo, decisoes=None):
        return importar.planejar(arquivo, storage.listar_missoes_completas(), storage.listar_jogadores(),
                                 storage.listar_personagens(), importar.Decisoes(decisoes))

    def test_possivel_mesma_missao_bloqueia(self):
        acoes = self._planejar([_missao_arquivo("O Neto de Tholu")])
        self.assertTrue(any("possível mesma missão" in p for p in acoes[0].pendencias))

    def test_mesma_missao_so_preenche_vazio_e_conflito_espera_decisao(self):
        arquivo = [_missao_arquivo("O Neto de Tholu")]
        decisoes = {"mesma_missao": {"O Neto de Tholu": "Vovó está preocupada"}}
        acao = self._planejar(arquivo, decisoes)[0]
        self.assertEqual(acao.tipo, "atualizar")
        self.assertIn('conflito em "relato"', acao.pendencias[0])
        self.assertNotIn("relato", acao.preencher)

        decisoes["conflitos"] = {"O Neto de Tholu": {"relato": "manter"}}
        acoes = self._planejar(arquivo, decisoes)
        self.assertEqual(acoes[0].pendencias, [])
        importar.aplicar(acoes)
        m = storage.listar_missoes_completas()[0]
        self.assertEqual((m["relato"], m["xp"], m["condutor_discord_id"]), ("Relato longo do Forms.", 300, "1"))
        self.assertEqual(_participantes(self.caminho), [("Kael Noctis", None)])  # existente: intocados

    def test_decisao_arquivo_sobrescreve(self):
        decisoes = {"mesma_missao": {"O Neto de Tholu": "Vovó está preocupada"},
                    "conflitos": {"O Neto de Tholu": {"relato": "arquivo"}}}
        importar.aplicar(self._planejar([_missao_arquivo("O Neto de Tholu")], decisoes))
        self.assertEqual(storage.listar_missoes_completas()[0]["relato"], "Relato do post.")

    def test_insere_com_participantes_e_segunda_rodada_nao_duplica(self):
        arquivo = [_missao_arquivo("O Navio que Grita", data="02/10/2026", viajantes_post=[
            {"mencao": "Mestre", "personagem": None},
            {"mencao": "Mestre", "personagem": "Lucy"},
        ])]
        acoes = self._planejar(arquivo)
        self.assertEqual(acoes[0].pendencias, [])
        self.assertEqual(importar.aplicar(acoes), {"atualizadas": 0, "inseridas": 1})
        self.assertEqual(_participantes(self.caminho)[1:], [("Ferrugem", 1), ("Lucy", None)])

        de_novo = self._planejar(arquivo)
        self.assertEqual((importar.resumo(de_novo)["inserir"], importar.resumo(de_novo)["atualizar"]), (0, 0))
        self.assertEqual(importar.aplicar(de_novo), {"atualizadas": 0, "inseridas": 0})
        self.assertEqual(len(storage.listar_missoes_completas()), 2)

    def test_sem_data_espera_decisao(self):
        arquivo = [_missao_arquivo("Nhalor", data=None, postado_em="24/09/2026 20:27")]
        self.assertTrue(any("sem data" in p for p in self._planejar(arquivo)[0].pendencias))
        acao = self._planejar(arquivo, {"datas": {"nhalor": "23/09/2026"}})[0]
        self.assertEqual((acao.pendencias, acao.dados["data"]), ([], "2026-09-23"))
        self.assertEqual(acao.dados["criado_em"], "2026-09-24T20:27:00")


if __name__ == "__main__":
    unittest.main()
