"""
Testes do serviço do NAT-CORE (registro, deleção, listagem, sincronização),
com banco temporário e DiceCloud falso. Da raiz:
    python -m unittest discover -s modules/core -t .
"""

import gzip
import io
import json
import os
import sys
import unittest
import urllib.error
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from modules.core import service, storage  # noqa: E402
from modules.core.test_storage import BancoTemporario  # noqa: E402

LINK = "https://dicecloud.com/character/JpXWudBMRj6XK2AM7/Kael"
HISTORIA = "Chegou a Veyra num barril."


class ComDiceCloudFalso(BancoTemporario):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(service, "consultar_ficha_dicecloud", return_value={"nivel": 3})
        self.dicecloud = patcher.start()
        self.addCleanup(patcher.stop)


class RespostaFalsa:
    """O que urlopen devolve: context manager com read() e headers."""

    def __init__(self, dados):
        self.corpo = json.dumps(dados).encode()
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.corpo


def erro_http(codigo, corpo="", gzip_=False):
    dados, headers = corpo.encode(), {}
    if gzip_:  # a API real compacta o erro quando a Natty pede gzip
        dados, headers = gzip.compress(dados), {"Content-Encoding": "gzip"}
    return urllib.error.HTTPError(service.DICECLOUD_API_URL, codigo, "erro", headers, io.BytesIO(dados))


NAO_EXISTE = '{"error": "Permission denied", "reason": "Permission denied: No such document exists"}'


FICHA_KAEL = {
    "creatures": [{"name": "Kael Noctis"}],
    "creatureVariables": [{"level": {"value": 4}}],
}


class TestConsultarFicha(unittest.TestCase):
    """Respostas copiadas da API real (2026-10-05)."""

    def _consultar(self, *respostas, link=LINK, nome="Kael Noctis"):
        with mock.patch.object(service.urllib.request, "urlopen", side_effect=respostas) as urlopen:
            r = service.consultar_ficha_dicecloud(link, nome)
        return r, urlopen.call_count

    def test_ficha_certa(self):
        self.assertEqual(self._consultar(RespostaFalsa(FICHA_KAEL)), ({"nivel": 4}, 1))

    def test_link_quebrado_barra_sem_ir_na_api(self):
        for link in (
            "https://dicecloud.com/character/zzzz",                 # curto demais
            "https://dicecloud.com/character/HY5hKSMDxMF7kDzT8XX",  # comprido demais
            "https://dicecloud.com/character/HY5hKSMDxMF7kDz01",    # 0 e 1 não existem
        ):
            with self.subTest(link=link):
                self.assertEqual(self._consultar(link=link), ({"erro": "inexistente"}, 0))

    def test_id_que_nao_existe_nao_tenta_de_novo(self):
        self.assertEqual(self._consultar(erro_http(400, NAO_EXISTE)), ({"erro": "inexistente"}, 1))

    def test_id_que_nao_existe_com_erro_compactado(self):
        # Achado no ensaio com a API real: sem descompactar, virava "privada".
        self.assertEqual(self._consultar(erro_http(400, NAO_EXISTE, gzip_=True)),
                         ({"erro": "inexistente"}, 1))

    def test_ficha_privada(self):
        self.assertEqual(self._consultar(erro_http(403, '{"error": "Permission denied"}')),
                         ({"erro": "privada"}, 1))

    def test_dicecloud_fora_do_ar_tenta_de_novo(self):
        r, chamadas = self._consultar(erro_http(500), erro_http(500))
        self.assertEqual((r, chamadas), ({"erro": "indisponivel"}, service.DICECLOUD_TENTATIVAS))

    def test_timeout_e_depois_responde(self):
        self.assertEqual(self._consultar(TimeoutError(), RespostaFalsa(FICHA_KAEL)), ({"nivel": 4}, 2))

    def test_nome_diferente_devolve_o_nome_da_ficha(self):
        r, _ = self._consultar(RespostaFalsa(FICHA_KAEL), nome="Outro Nome")
        self.assertEqual(r, {"erro": "nome", "nome_ficha": "Kael Noctis"})

    def test_nome_ignora_acento_e_maiuscula(self):
        r, _ = self._consultar(RespostaFalsa(FICHA_KAEL), nome="  KAËL noctis ")
        self.assertEqual(r, {"nivel": 4})

    def test_ficha_sem_classe(self):
        r, _ = self._consultar(RespostaFalsa({"creatures": [{"name": "Kael Noctis"}]}))
        self.assertEqual(r, {"erro": "sem_nivel"})

    def test_ids_reais_do_banco_passam_no_formato(self):
        for char_id in ("HY5hKSMDxMF7kDzT8", "2KAPBpExZfktkNiQa", "unrjmqdZzQ8L6pN7a"):
            with self.subTest(char_id=char_id):
                self.assertRegex(char_id, service.DICECLOUD_ID_RE)


class TestExtrairIdDiceCloud(unittest.TestCase):
    def test_com_e_sem_nome_no_fim(self):
        casos = {
            "dicecloud.com/character/JpXWudBMRj6XK2AM7": "JpXWudBMRj6XK2AM7",
            "https://dicecloud.com/character/JpXWudBMRj6XK2AM7": "JpXWudBMRj6XK2AM7",
            "https://dicecloud.com/character/JpXWudBMRj6XK2AM7/": "JpXWudBMRj6XK2AM7",
            "https://dicecloud.com/character/HY5hKSMDxMF7kDzT8/Kael-Noctis": "HY5hKSMDxMF7kDzT8",
            "https://www.dicecloud.com/character/abc123?tab=stats": "abc123",
            "  https://dicecloud.com/character/abc123  ": "abc123",
        }
        for link, esperado in casos.items():
            with self.subTest(link=link):
                self.assertEqual(service._extrair_id_dicecloud(link), esperado)

    def test_dnd_beyond_e_lixo_sao_pulados(self):
        for link in ("https://www.dndbeyond.com/characters/170568115", "", None, "dicecloud.com/character/"):
            with self.subTest(link=link):
                self.assertIsNone(service._extrair_id_dicecloud(link))


class TestGarantirJogador(BancoTemporario):
    def test_cria_e_atualiza_apelido(self):
        service.garantir_jogador("1", "meduardo98", "Marcelo")
        service.garantir_jogador("1", "meduardo98", "Marcelão")
        j = storage.buscar_jogador("1")
        self.assertEqual((j["username"], j["nome_exibicao"]), ("meduardo98", "Marcelão"))


class TestMembros(BancoTemporario):
    def _membro(self, i, username, apelido):
        return {"discord_id": i, "username": username, "nome_exibicao": apelido}

    def test_sincronizar_cria_atualiza_e_marca_quem_saiu(self):
        storage.salvar_jogador("1", "kira", "Kira", nome="Kira")
        storage.salvar_jogador("2", "natan", "Natan")
        storage.salvar_jogador("3", "isaac", "Isaac")
        r = service.sincronizar_membros([
            self._membro("1", "kira", "Kira Nova"),   # mudou o apelido
            self._membro("2", "natan", "Natan"),      # igual
            self._membro("4", "novo", "Novo"),        # entrou
        ])
        self.assertEqual(r, {"novos": 1, "atualizados": 1, "saíram": 1, "total": 3})
        kira = storage.buscar_jogador("1")
        self.assertEqual((kira["nome_exibicao"], kira["nome"]), ("Kira Nova", "Kira"))  # nome intocado
        self.assertEqual(storage.buscar_jogador("3")["ativo"], 0)  # saiu, mas não foi apagado

    def test_quem_volta_conta_como_atualizado(self):
        storage.salvar_jogador("1", "kira", "Kira", ativo=False)
        r = service.sincronizar_membros([self._membro("1", "kira", "Kira")])
        self.assertEqual((r["atualizados"], storage.buscar_jogador("1")["ativo"]), (1, 1))

    def test_lista_vazia_nao_mexe_em_nada(self):
        storage.salvar_jogador("1", "kira", "Kira")
        with self.assertRaises(ValueError):
            service.sincronizar_membros([])
        self.assertEqual(storage.buscar_jogador("1")["ativo"], 1)

    def test_entrou_e_saiu(self):
        service.membro_entrou("1", "kira", "Kira")
        service.membro_saiu("1")
        self.assertEqual(storage.buscar_jogador("1")["ativo"], 0)
        service.garantir_jogador("1", "kira", "Kira")  # usou um comando: está no servidor
        self.assertEqual(storage.buscar_jogador("1")["ativo"], 1)


class TestRegistrar(ComDiceCloudFalso):
    def test_registra_com_discord_id(self):
        r = service.registrar_personagem("1", "Kira", "Kael", LINK, HISTORIA)
        self.assertEqual((r["sucesso"], r["nivel"]), (True, 3))
        p = storage.listar_personagens("1")[0]
        self.assertEqual((p["nome"], p["nome_jogador"], p["nivel_inicial"]), ("Kael", "Kira", 3))

    def test_grava_historia_e_data_de_criacao(self):
        r = service.registrar_personagem("1", "Kira", "Kael", LINK, "  Chegou a Veyra num barril.  ")
        p = storage.listar_personagens("1")[0]
        self.assertEqual(p["historia"], "Chegou a Veyra num barril.")
        self.assertEqual(p["criado_em"], r["criado_em"])
        self.assertRegex(r["criado_em"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

    def test_historia_de_uma_linha_vale(self):
        self.assertTrue(service.registrar_personagem("1", "Kira", "Kael", LINK, "Órfão.")["sucesso"])

    def test_historia_no_limite_exato_vale(self):
        historia = "a" * service.MAX_HISTORIA
        self.assertTrue(service.registrar_personagem("1", "Kira", "Kael", LINK, historia)["sucesso"])

    def test_historia_vazia_nao_grava_nem_vai_no_dicecloud(self):
        for vazia in ("", "   \n  ", None):
            with self.subTest(historia=vazia):
                r = service.registrar_personagem("1", "Kira", "Kael", LINK, vazia)
                self.assertEqual(r["erro"], service.ERRO_HISTORIA_VAZIA)
                self.assertIn("uma linha", r["erro"])
        self.dicecloud.assert_not_called()
        self.assertEqual(storage.listar_personagens(), [])

    def test_historia_acima_do_limite_diz_o_tamanho(self):
        r = service.registrar_personagem("1", "Kira", "Kael", LINK, "a" * (service.MAX_HISTORIA + 1))
        self.assertIn(str(service.MAX_HISTORIA + 1), r["erro"])
        self.assertIn("o quanto quiser", r["erro"])
        self.dicecloud.assert_not_called()

    def test_limite_de_dois_por_jogador(self):
        service.registrar_personagem("1", "Kira", "A", LINK, HISTORIA)
        service.registrar_personagem("1", "Kira", "B", LINK, HISTORIA)
        r = service.registrar_personagem("1", "Kira", "C", LINK, HISTORIA)
        self.assertFalse(r["sucesso"])
        self.assertIn("limite", r["erro"])

    def test_quem_ja_tem_tres_migrados_nao_registra_mais(self):
        for nome in ("A", "B", "C"):
            storage.inserir_personagem(nome, nome.lower(), "Kira", "1", None, 1)
        self.assertFalse(service.registrar_personagem("1", "Kira", "D", LINK, HISTORIA)["sucesso"])

    def test_nome_repetido_ignora_acento_e_maiuscula(self):
        service.registrar_personagem("1", "Kira", "Ícaro", LINK, HISTORIA)
        r = service.registrar_personagem("2", "Natan", "  icaro ", LINK, HISTORIA)
        self.assertFalse(r["sucesso"])
        self.assertIn("Já existe", r["erro"])

    def test_link_que_nao_e_dicecloud(self):
        r = service.registrar_personagem("1", "Kira", "Kael", "https://www.dndbeyond.com/characters/1", HISTORIA)
        self.assertEqual(r["erro"], service.ERRO_LINK)
        self.dicecloud.assert_not_called()

    def test_ficha_que_nao_existe_nao_grava(self):
        self.dicecloud.return_value = {"erro": "inexistente"}
        r = service.registrar_personagem("1", "Kira", "Kael", LINK, HISTORIA)
        self.assertEqual(r["erro"], service.ERROS_FICHA["inexistente"])
        self.assertIn("não existe", r["erro"])
        self.assertEqual(storage.listar_personagens(), [])

    def test_nome_diferente_mostra_o_nome_da_ficha(self):
        self.dicecloud.return_value = {"erro": "nome", "nome_ficha": "Kael Noctis"}
        r = service.registrar_personagem("1", "Kira", "Kael", LINK, HISTORIA)
        self.assertIn("**Kael Noctis**", r["erro"])

    def test_cada_motivo_tem_mensagem(self):
        for motivo, mensagem in service.ERROS_FICHA.items():
            with self.subTest(motivo=motivo):
                self.dicecloud.return_value = {"erro": motivo, "nome_ficha": "X"}
                r = service.registrar_personagem("1", "Kira", "Kael", LINK, HISTORIA)
                self.assertEqual(r["erro"], mensagem.format(nome_ficha="X"))

    def test_confere_de_novo_depois_do_dicecloud(self):
        # Outro registro com o mesmo nome entra enquanto o DiceCloud responde.
        def entra_outro(*_):
            storage.inserir_personagem("Kael", "kael", "Natan", "2", None, 1)
            return {"nivel": 3}
        self.dicecloud.side_effect = entra_outro
        r = service.registrar_personagem("1", "Kira", "Kael", LINK, HISTORIA)
        self.assertFalse(r["sucesso"])
        self.assertEqual(len(storage.listar_personagens()), 1)


class TestRegistrarLinkFalso(BancoTemporario):
    """Sem dublê do DiceCloud: o link falso é barrado antes de qualquer rede."""

    def test_link_falso_nao_grava_nem_vai_na_api(self):
        with mock.patch.object(service.urllib.request, "urlopen") as urlopen:
            r = service.registrar_personagem(
                "1", "Kira", "Kael", "https://dicecloud.com/character/fichafalsa123"
            , HISTORIA)
        urlopen.assert_not_called()
        self.assertEqual(r["erro"], service.ERROS_FICHA["inexistente"])
        self.assertEqual(storage.listar_personagens(), [])


class TestDeletar(ComDiceCloudFalso):
    def test_so_o_dono_deleta(self):
        service.registrar_personagem("1", "Kira", "Kael", LINK, HISTORIA)
        self.assertFalse(service.deletar_personagem("2", "Kael")["sucesso"])
        self.assertEqual(len(storage.listar_personagens()), 1)
        self.assertTrue(service.deletar_personagem("1", "kael")["sucesso"])
        self.assertEqual(storage.listar_personagens(), [])

    def test_faz_backup_antes_de_apagar(self):
        service.registrar_personagem("1", "Kira", "Kael", LINK, HISTORIA)
        service.deletar_personagem("1", "Kael")
        backup = storage.backups()[-1]
        self.assertIn("deletar", backup.name)
        self.assertEqual(storage.resumo_do_arquivo(backup)["personagens"], 1)

    def test_personagem_inexistente_nao_faz_backup(self):
        self.assertFalse(service.deletar_personagem("1", "Ninguém")["sucesso"])
        self.assertEqual(storage.backups(), [])


class TestListar(BancoTemporario):
    def test_ordem_alfabetica_e_nivel_atual_ou_inicial(self):
        d = "2026-09-01T20:05:32"
        storage.inserir_personagem("Zé", "ze", "A", "1", "", 1, nivel_atual=4, criado_em=d)
        storage.inserir_personagem("Ana", "ana", None, None, None, 2, criado_em=d)
        storage.inserir_personagem("Bia", "bia", "B", "2", None, None, criado_em=d)
        self.assertEqual(service.listar_personagens(), [
            {"nome": "Ana", "jogador": "", "link": "", "nivel": 2, "criado_em": d},
            {"nome": "Bia", "jogador": "B", "link": "", "nivel": None, "criado_em": d},
            {"nome": "Zé", "jogador": "A", "link": "", "nivel": 4, "criado_em": d},
        ])
        self.assertEqual([p["nome"] for p in service.listar_personagens(1)], ["Zé"])


class TestSincronizar(BancoTemporario):
    def test_atualiza_pula_e_registra_falha(self):
        storage.inserir_personagem("A", "a", None, None, LINK, 1, nivel_atual=2)
        storage.inserir_personagem("B", "b", None, None, "https://www.dndbeyond.com/characters/1", 1)
        storage.inserir_personagem("C", "c", None, None, LINK, 1, nivel_atual=7)
        niveis = {"A": 5, "C": None}

        def falso(link):
            return niveis.pop(next(iter(niveis)))
        with mock.patch.object(service, "DICECLOUD_PARALELO", 1), \
             mock.patch.object(service, "buscar_nivel_atual_dicecloud", side_effect=falso):
            r = service.sincronizar_niveis_atuais()
        self.assertEqual(r, {"atualizados": 1, "pulados": 1, "falhas": ["C"]})
        niveis_atuais = {p["nome"]: p["nivel_atual"] for p in storage.listar_personagens()}
        self.assertEqual(niveis_atuais, {"A": 5, "B": None, "C": 7})


HOJE = date(2026, 10, 5)


class TestMissoes(BancoTemporario):
    def setUp(self):
        super().setUp()
        storage.salvar_jogador("1", "meduardo98", "Mestre", nome="Marcelo")
        storage.inserir_personagem("Aldric", "aldric", None, None, None, 1)
        storage.inserir_personagem("Ed Brandt", "ed rothtaylor", None, None, None, 1)
        storage.inserir_personagem("Tomas Vale", "tomas vale", None, None, None, 1)

    def _registrar(self, **muda):
        args = {"condutor_discord_id": "1", "condutor_nome": "Mestre", "nome": "O Navio que Grita",
                "data": "02/10/2026", "dificuldade": "Difícil", "xp": 5000, "gold": 1000,
                "participantes": "aldric, Ed Brandt", "relato": "Ferro pediu ajuda.", "hoje": HOJE}
        args.update(muda)
        return service.registrar_missao(**args)

    def test_registra_com_condutor_e_participantes(self):
        r = self._registrar(resultado="  Concluída. ", observacoes="   ")
        self.assertEqual((r["sucesso"], r["data"], r["participantes"]), (True, "2026-10-02", ["Aldric", "Ed Brandt"]))
        m = storage.listar_missoes_completas()[0]
        self.assertEqual((m["condutor_discord_id"], m["condutor_nome"], m["xp"], m["resultado"], m["observacoes"]),
                         ("1", "Marcelo", 5000, "Concluída.", None))
        self.assertEqual(service.listar_missoes()[0]["participantes"], ["Aldric", "Ed Brandt"])

    def test_separar_participantes(self):
        self.assertEqual(service.separar_participantes("Aldric, aldric ;Ed  Brandt\n\n,"),
                         ["Aldric", "Ed Brandt"])

    def test_personagem_nao_registrado_sugere_o_parecido(self):
        r = self._registrar(participantes="Aldric, Ed Brant, Lucy")
        self.assertFalse(r["sucesso"])
        self.assertIn("**Ed Brant** (você quis dizer **Ed Brandt**?)", r["erro"])
        self.assertIn("**Lucy**", r["erro"])
        self.assertEqual(storage.listar_missoes_completas(), [])

    def test_nome_repetido_data_e_campos_invalidos(self):
        self._registrar()
        casos = {
            "Já existe": {"nome": "o navio que GRITA"},
            "DD/MM/AAAA": {"nome": "B", "data": "2026-10-02"},
            "futuro": {"nome": "C", "data": "06/10/2026"},
            "Dificuldade inválida": {"nome": "D", "dificuldade": "Média"},
            "inteiros": {"nome": "E", "xp": -1},
            "pelo menos um": {"nome": "F", "participantes": " , "},
            "relato é obrigatório": {"nome": "G", "relato": "  "},
        }
        for trecho, muda in casos.items():
            with self.subTest(trecho=trecho):
                r = self._registrar(**muda)
                self.assertFalse(r["sucesso"])
                self.assertIn(trecho, r["erro"])
        self.assertEqual(len(storage.listar_missoes_completas()), 1)

    def test_conferir_nao_grava_nada(self):
        r = service.conferir_missao("X", "01/10/2026", "Normal", 1, 1, "Aldric", hoje=HOJE)
        self.assertTrue(r["sucesso"])
        self.assertEqual(storage.listar_missoes_completas(), [])

    def test_condutor_fora_da_tabela_grava_sem_vinculo(self):
        r = self._registrar(condutor_discord_id="999", condutor_nome="Visitante")
        m = storage.listar_missoes_completas()[0]
        self.assertTrue(r["sucesso"])
        self.assertEqual((m["condutor_discord_id"], m["condutor_nome"]), (None, "Visitante"))


if __name__ == "__main__":
    unittest.main()
