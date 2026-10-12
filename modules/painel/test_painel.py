"""
Testes do painel web, sem Discord nem rede: bot, servidor, membros, Bardo
(bot.controles["bardo"]) e OAuth são dublês; o aiohttp roda de verdade
(test client). Da raiz:
    python -m unittest discover -s modules/painel -t .
"""

import asyncio
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from aiohttp.test_utils import TestClient, TestServer

from modules.painel import service, web
from modules.painel.oauth import ErroDeLogin

USUARIO = {"id": "42", "username": "aldric", "global_name": "Aldric", "avatar": None}


class Guild(SimpleNamespace):
    def get_member(self, user_id):
        return self.membros.get(user_id)


class Bot(SimpleNamespace):
    def get_guild(self, guild_id):
        return next((g for g in self.guilds if g.id == guild_id), None)


class ControleFalso:
    def __init__(self):
        self.assinantes, self.comandos = [], []
        self.volume = 50

    def assinar(self, f):
        self.assinantes.append(f)

    def cancelar(self, f):
        self.assinantes.remove(f)

    def pode_controlar(self, membro):
        return membro.mestre

    def estado(self, guild):
        return {"conectado": True, "tocando": None, "proximas": [], "volume": self.volume}

    def publicar(self, guild_id):
        for f in list(self.assinantes):
            f(guild_id)

    async def executar(self, guild, membro, comando, args):
        self.comandos.append((comando, args))
        if comando == "volume":
            self.volume = args["nivel"]
            self.publicar(guild.id)
        return {"ok": True, "texto": f"feito: {comando}"}


class OAuthFalso:
    client_id = "999"

    async def trocar_codigo(self, code, redirect_uri):
        if code != "bom":
            raise ErroDeLogin("recusado")
        return "token"

    async def buscar_usuario(self, token):
        return dict(USUARIO)


class ServicoDoPainel(unittest.TestCase):
    def test_sessao_vence_e_encerra(self):
        sessoes = service.Sessoes(duracao=10)
        token = sessoes.criar({"id": "42"}, agora=100)
        self.assertEqual(sessoes.obter(token, agora=105), {"id": "42"})
        self.assertIsNone(sessoes.obter(token, agora=111))
        token = sessoes.criar({"id": "42"})
        sessoes.encerrar(token)
        self.assertIsNone(sessoes.obter(token))
        self.assertIsNone(sessoes.obter(None))

    def test_state_uma_vez_so_e_com_prazo(self):
        estados = service.EstadosOAuth(duracao=10)
        state = estados.novo(agora=100)
        self.assertTrue(estados.consumir(state, agora=105))
        self.assertFalse(estados.consumir(state, agora=105))  # reusado
        velho = estados.novo(agora=100)
        self.assertFalse(estados.consumir(velho, agora=200))  # vencido
        self.assertFalse(estados.consumir("inventado"))

    def test_url_de_autorizacao(self):
        q = parse_qs(urlsplit(service.url_de_autorizacao("999", "http://localhost:8710/auth/callback", "abc")).query)
        self.assertEqual(q["scope"], ["identify guilds"])
        self.assertEqual(q["state"], ["abc"])
        self.assertEqual(q["redirect_uri"], ["http://localhost:8710/auth/callback"])

    def test_origem(self):
        self.assertTrue(service.origem_valida("http://localhost:8710", "http://localhost:8710/"))
        self.assertFalse(service.origem_valida("http://malvado.com", "http://localhost:8710"))
        self.assertFalse(service.origem_valida(None, "http://localhost:8710"))

    def test_guild_id(self):
        self.assertEqual(service.ler_guild_id("123"), 123)
        for ruim in (None, "", "12a", "1" * 21, "-1"):
            self.assertIsNone(service.ler_guild_id(ruim))


class Web(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.controle = ControleFalso()
        self.mestre = SimpleNamespace(id=42, mestre=True)
        self.guild = Guild(id=1, name="Crossroads", membros={42: self.mestre})
        self.outra = Guild(id=2, name="Outro", membros={})
        self.bot = Bot(guilds=[self.guild, self.outra], controles={"bardo": self.controle})
        self.config = web.ConfigPainel("http://placeholder")
        self.client = TestClient(TestServer(web.criar_app(self.bot, self.config, OAuthFalso())))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.config.base_url = str(self.client.make_url("")).rstrip("/")
        self.origem = {"Origin": self.config.base_url}

    async def logar(self, code="bom"):
        r = await self.client.get("/auth/login", allow_redirects=False)
        self.assertEqual(r.status, 302)
        state = parse_qs(urlsplit(r.headers["Location"]).query)["state"][0]
        return await self.client.get(f"/auth/callback?code={code}&state={state}", allow_redirects=False)

    async def test_sem_login_e_401(self):
        self.assertEqual((await self.client.get("/api/me")).status, 401)
        self.assertEqual((await self.client.get("/api/guilds")).status, 401)

    async def test_login_completo(self):
        r = await self.logar()
        self.assertEqual((r.status, r.headers["Location"]), (302, "/"))
        self.assertIn("HttpOnly", r.headers.getall("Set-Cookie")[0])
        me = await (await self.client.get("/api/me")).json()
        self.assertEqual(me, {"id": "42", "nome": "Aldric", "avatar": None})
        guilds = await (await self.client.get("/api/guilds")).json()
        self.assertEqual(guilds, [{"id": "1", "nome": "Crossroads", "pode_controlar": True}])  # só onde é membro

    async def test_callback_sem_state_valido(self):
        r = await self.client.get("/auth/callback?code=bom&state=inventado", allow_redirects=False)
        self.assertEqual(r.status, 400)
        self.assertEqual((await self.client.get("/api/me")).status, 401)

    async def test_discord_recusou(self):
        self.assertEqual((await self.logar(code="ruim")).status, 502)

    async def test_logout_precisa_da_origem(self):
        await self.logar()
        self.assertEqual((await self.client.post("/auth/logout")).status, 403)
        self.assertEqual((await self.client.post("/auth/logout", headers=self.origem)).status, 200)
        self.assertEqual((await self.client.get("/api/me")).status, 401)

    async def test_websocket_manda_o_estado_e_as_mudancas(self):
        await self.logar()
        ws = await self.client.ws_connect("/ws?guild=1", headers=self.origem)
        primeira = await ws.receive_json(timeout=2)
        self.assertEqual((primeira["tipo"], primeira["estado"]["volume"], primeira["pode_controlar"]),
                         ("estado", 50, True))
        self.controle.volume = 70
        self.controle.publicar(1)  # mudou pelo Discord
        self.controle.publicar(2)  # outro servidor: não manda
        segunda = await ws.receive_json(timeout=2)
        self.assertEqual(segunda["estado"]["volume"], 70)
        await ws.close()
        await asyncio.sleep(0)
        self.assertEqual(self.controle.assinantes, [])  # largou a assinatura

    async def test_websocket_recusa_origem_estranha_e_quem_nao_e_membro(self):
        await self.logar()
        r = await self.client.get("/ws?guild=1", headers={"Origin": "http://malvado.com"})
        self.assertEqual(r.status, 403)
        r = await self.client.get("/ws?guild=2", headers=self.origem)
        self.assertEqual(r.status, 403)
        r = await self.client.get("/ws?guild=999", headers=self.origem)
        self.assertEqual(r.status, 404)

    async def test_sem_login_nem_abre_o_websocket(self):
        self.assertEqual((await self.client.get("/ws?guild=1", headers=self.origem)).status, 401)

    async def test_pagina_e_cabecalhos(self):
        r = await self.client.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        self.assertEqual((await self.client.get("/static/app.js")).status, 200)
        self.assertEqual((await self.client.get("/static/../web.py")).status, 404)


if __name__ == "__main__":
    unittest.main()
