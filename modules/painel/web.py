"""Painel web — rotas aiohttp. Só validam a entrada e chamam service/controles.

Roda no mesmo loop asyncio do bot (aiohttp já vem com o discord.py): enxerga
o estado direto, sem IPC nem segunda porta. Escuta só em 127.0.0.1.

Rotas:
  GET  /                      página (static/index.html)
  GET  /auth/login            → Discord (OAuth2 identify + guilds, com state)
  GET  /auth/callback         ← Discord; cria a sessão (cookie HttpOnly, SameSite=Lax)
  POST /auth/logout
  GET  /api/me                quem está logado
  GET  /api/guilds            servidores em comum com a Natty (+ se pode controlar)
  GET  /ws?guild=<id>         WebSocket: estado do Bardo ao vivo
  POST /api/g/{id}/cmd        comando pro Bardo (etapa 5)

Autorização é conferida AO VIVO no bot (membro do servidor; cargo de mestre
pra comandar) a cada requisição e a cada mensagem do WebSocket — a lista de
servidores do OAuth fica velha.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from aiohttp import WSMsgType, web

from modules.painel import service
from modules.painel.oauth import ErroDeLogin

log = logging.getLogger(__name__)

PASTA_STATIC = Path(__file__).parent / "static"
COOKIE = "natty_sessao"
COOKIE_STATE = "natty_state"

CHAVE_BOT = web.AppKey("bot", object)
CHAVE_CONFIG = web.AppKey("config", object)
CHAVE_OAUTH = web.AppKey("oauth", object)
CHAVE_SESSOES = web.AppKey("sessoes", service.Sessoes)
CHAVE_ESTADOS = web.AppKey("estados", service.EstadosOAuth)


@dataclass
class ConfigPainel:
    base_url: str          # ex: http://localhost:8710 (o redirect do OAuth é base_url + /auth/callback)
    cookie_seguro: bool = False  # True só atrás de HTTPS

    @property
    def redirect_uri(self) -> str:
        return self.base_url.rstrip("/") + "/auth/callback"


def criar_app(bot, config: ConfigPainel, oauth) -> web.Application:
    """`oauth` tem client_id, trocar_codigo(code, redirect_uri) e buscar_usuario(token) (oauth.OAuthDiscord)."""
    app = web.Application(middlewares=[_cabecalhos_de_seguranca], client_max_size=1024 * 1024)
    app[CHAVE_BOT], app[CHAVE_CONFIG], app[CHAVE_OAUTH] = bot, config, oauth
    app[CHAVE_SESSOES], app[CHAVE_ESTADOS] = service.Sessoes(), service.EstadosOAuth()
    app.router.add_get("/", _pagina)
    app.router.add_get("/auth/login", _login)
    app.router.add_get("/auth/callback", _callback)
    app.router.add_post("/auth/logout", _logout)
    app.router.add_get("/api/me", _me)
    app.router.add_get("/api/guilds", _guilds)
    app.router.add_get("/ws", _ws)
    app.router.add_post("/api/g/{guild_id}/cmd", _cmd)
    app.router.add_static("/static", PASTA_STATIC, show_index=False, follow_symlinks=False)
    return app


@web.middleware
async def _cabecalhos_de_seguranca(request, handler):
    resposta = await handler(request)
    resposta.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' https://cdn.discordapp.com data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    )
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("Referrer-Policy", "no-referrer")
    return resposta


# -- Auxiliares -------------------------------------------------------------------

def _usuario(request) -> dict | None:
    return request.app[CHAVE_SESSOES].obter(request.cookies.get(COOKIE))


def _exigir_usuario(request) -> dict:
    usuario = _usuario(request)
    if usuario is None:
        raise web.HTTPUnauthorized(text=json.dumps({"erro": "faça login"}), content_type="application/json")
    return usuario


def _exigir_origem(request) -> None:
    if not service.origem_valida(request.headers.get("Origin"), request.app[CHAVE_CONFIG].base_url):
        raise web.HTTPForbidden(text=json.dumps({"erro": "origem não permitida"}), content_type="application/json")


def _controle(request, nome: str = "bardo"):
    return getattr(request.app[CHAVE_BOT], "controles", {}).get(nome)


def _guild_e_membro(request, usuario: dict, guild_id_texto: str | None):
    """(guild, membro) se a Natty está no servidor e o usuário é membro dele AGORA; senão 403/404."""
    guild_id = service.ler_guild_id(guild_id_texto)
    guild = request.app[CHAVE_BOT].get_guild(guild_id) if guild_id else None
    if guild is None:
        raise web.HTTPNotFound(text=json.dumps({"erro": "servidor não encontrado"}), content_type="application/json")
    membro = guild.get_member(int(usuario["id"]))
    if membro is None:
        raise web.HTTPForbidden(text=json.dumps({"erro": "você não está nesse servidor"}),
                                content_type="application/json")
    return guild, membro


def _pode_controlar(request, membro) -> bool:
    controle = _controle(request)
    return bool(controle and controle.pode_controlar(membro))


# -- Página e login -----------------------------------------------------------------

async def _pagina(request):
    return web.FileResponse(PASTA_STATIC / "index.html")


async def _login(request):
    state = request.app[CHAVE_ESTADOS].novo()
    url = service.url_de_autorizacao(request.app[CHAVE_OAUTH].client_id, request.app[CHAVE_CONFIG].redirect_uri, state)
    resposta = web.HTTPFound(url)
    # O state também vai num cookie: o callback tem que voltar no MESMO navegador.
    resposta.set_cookie(COOKIE_STATE, state, max_age=service.SEGUNDOS_DO_STATE, httponly=True, samesite="Lax",
                        secure=request.app[CHAVE_CONFIG].cookie_seguro, path="/auth")
    raise resposta


async def _callback(request):
    state = request.query.get("state")
    if state != request.cookies.get(COOKIE_STATE) or not request.app[CHAVE_ESTADOS].consumir(state):
        raise web.HTTPBadRequest(text="Login expirou ou veio de outro lugar. Volta e tenta de novo.")
    code = request.query.get("code")
    if not code:
        raise web.HTTPBadRequest(text="O Discord não autorizou o login.")
    oauth = request.app[CHAVE_OAUTH]
    try:
        token = await oauth.trocar_codigo(code, request.app[CHAVE_CONFIG].redirect_uri)
        usuario = service.resumo_do_usuario(await oauth.buscar_usuario(token))
    except ErroDeLogin:
        log.warning("Painel: login recusado pelo Discord", exc_info=True)
        raise web.HTTPBadGateway(text="O Discord recusou o login. Tenta de novo.")
    sessao = request.app[CHAVE_SESSOES].criar(usuario)
    resposta = web.HTTPFound("/")
    resposta.set_cookie(COOKIE, sessao, max_age=service.SEGUNDOS_DE_SESSAO, httponly=True, samesite="Lax",
                        secure=request.app[CHAVE_CONFIG].cookie_seguro, path="/")
    resposta.del_cookie(COOKIE_STATE, path="/auth")
    log.info("Painel: login de %s", usuario["id"])
    raise resposta


async def _logout(request):
    _exigir_origem(request)
    request.app[CHAVE_SESSOES].encerrar(request.cookies.get(COOKIE))
    resposta = web.json_response({"ok": True})
    resposta.del_cookie(COOKIE, path="/")
    return resposta


# -- API ------------------------------------------------------------------------------

async def _me(request):
    return web.json_response(_exigir_usuario(request))


async def _guilds(request):
    usuario = _exigir_usuario(request)
    guilds = []
    for guild in request.app[CHAVE_BOT].guilds:
        membro = guild.get_member(int(usuario["id"]))
        if membro is not None:
            guilds.append({"id": str(guild.id), "nome": guild.name, "pode_controlar": _pode_controlar(request, membro)})
    return web.json_response(guilds)


async def _cmd(request):
    _exigir_origem(request)
    usuario = _exigir_usuario(request)
    guild, membro = _guild_e_membro(request, usuario, request.match_info["guild_id"])
    try:
        dados = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text=json.dumps({"erro": "JSON inválido"}), content_type="application/json")
    resultado = await _executar(request, guild, membro, dados)
    return web.json_response(resultado, status=resultado.pop("_status", 200))


async def _executar(request, guild, membro, dados) -> dict:
    """Comando vindo do painel (POST ou WebSocket). Na etapa 4 o painel é só leitura."""
    return {"ok": False, "texto": "O painel ainda é só leitura.", "_status": 403}


# -- WebSocket ------------------------------------------------------------------------

async def _ws(request):
    _exigir_origem(request)
    usuario = _exigir_usuario(request)
    guild, membro = _guild_e_membro(request, usuario, request.query.get("guild"))
    controle = _controle(request)

    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=64 * 1024)
    await ws.prepare(request)
    if controle is None:
        await ws.send_json({"tipo": "erro", "texto": "O Bardo não está carregado."})
        await ws.close()
        return ws

    loop = asyncio.get_running_loop()
    mudou = asyncio.Event()

    def ao_mudar(guild_id: int) -> None:
        # Pode ser chamado fora do loop (thread do player): sempre via call_soon_threadsafe.
        if guild_id == guild.id:
            loop.call_soon_threadsafe(mudou.set)

    async def enviar_estado() -> None:
        await ws.send_json({"tipo": "estado", "estado": controle.estado(guild),
                            "pode_controlar": controle.pode_controlar(membro)})

    async def empurrar() -> None:
        while not ws.closed:
            await mudou.wait()
            mudou.clear()  # várias mudanças seguidas viram um envio só
            await enviar_estado()

    controle.assinar(ao_mudar)
    empurrador = asyncio.create_task(empurrar())
    try:
        await enviar_estado()
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            # Autorização de novo a cada mensagem: saiu do servidor/perdeu o cargo = fim.
            membro = guild.get_member(int(usuario["id"]))
            if membro is None or request.app[CHAVE_SESSOES].obter(request.cookies.get(COOKIE)) is None:
                await ws.close(code=4403, message=b"sem acesso")
                break
            try:
                dados = json.loads(msg.data)
            except json.JSONDecodeError:
                await ws.send_json({"tipo": "resposta", "ok": False, "texto": "Mensagem inválida."})
                continue
            if dados.get("cmd") == "estado":
                await enviar_estado()
                continue
            resultado = await _executar(request, guild, membro, dados)
            resultado.pop("_status", None)
            await ws.send_json({"tipo": "resposta", "id": dados.get("id"), **resultado})
    finally:
        controle.cancelar(ao_mudar)
        empurrador.cancel()
    return ws
