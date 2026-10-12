"""Painel web — lógica pura: sessões, anti-CSRF do OAuth, origem, comandos.

O painel é uma *superfície* (como o Discord), não uma capacidade: não toca
música nem guarda nada do Bardo. Ele fala com os módulos por
`bot.controles["<módulo>"]` e só valida o que entra. Sem discord.py aqui.
"""

from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode, urlsplit

DISCORD_AUTORIZAR = "https://discord.com/oauth2/authorize"
ESCOPOS = "identify guilds"
SEGUNDOS_DE_SESSAO = 7 * 24 * 3600
SEGUNDOS_DO_STATE = 600
PORTA_PADRAO = 8710


class Sessoes:
    """Sessões em memória (somem quando a Natty reinicia — aí é só logar de novo)."""

    def __init__(self, duracao: float = SEGUNDOS_DE_SESSAO):
        self._duracao = duracao
        self._sessoes: dict[str, dict] = {}

    def criar(self, usuario: dict, agora: float | None = None) -> str:
        token = secrets.token_urlsafe(32)
        self._sessoes[token] = {"usuario": usuario, "expira": (agora or time.time()) + self._duracao}
        return token

    def obter(self, token: str | None, agora: float | None = None) -> dict | None:
        """O usuário da sessão, ou None (sem token, desconhecido ou vencido)."""
        sessao = self._sessoes.get(token or "")
        if sessao is None:
            return None
        if (agora or time.time()) > sessao["expira"]:
            self._sessoes.pop(token, None)
            return None
        return sessao["usuario"]

    def encerrar(self, token: str | None) -> None:
        self._sessoes.pop(token or "", None)


class EstadosOAuth:
    """O `state` do OAuth: gerado no login, aceito uma vez só no callback, vence em 10 min."""

    def __init__(self, duracao: float = SEGUNDOS_DO_STATE):
        self._duracao = duracao
        self._estados: dict[str, float] = {}

    def novo(self, agora: float | None = None) -> str:
        agora = agora or time.time()
        self._estados = {s: t for s, t in self._estados.items() if t > agora}  # limpa os vencidos
        state = secrets.token_urlsafe(24)
        self._estados[state] = agora + self._duracao
        return state

    def consumir(self, state: str | None, agora: float | None = None) -> bool:
        expira = self._estados.pop(state or "", None)
        return expira is not None and (agora or time.time()) <= expira


def url_de_autorizacao(client_id: str, redirect_uri: str, state: str) -> str:
    return DISCORD_AUTORIZAR + "?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "scope": ESCOPOS,
        "redirect_uri": redirect_uri,
        "state": state,
        "prompt": "none",
    })


def origem(url: str) -> str:
    """'http://localhost:8710/x' → 'http://localhost:8710'."""
    partes = urlsplit(url)
    return f"{partes.scheme}://{partes.netloc}".lower()


def origem_valida(cabecalho_origin: str | None, base_url: str) -> bool:
    """O WebSocket/POST veio da página do próprio painel? (Sem Origin = recusa.)"""
    return bool(cabecalho_origin) and cabecalho_origin.lower().rstrip("/") == origem(base_url)


def resumo_do_usuario(dados: dict) -> dict:
    """/users/@me do Discord → o pouco que o painel guarda."""
    avatar = dados.get("avatar")
    return {
        "id": str(dados["id"]),
        "nome": dados.get("global_name") or dados.get("username") or "?",
        "avatar": f"https://cdn.discordapp.com/avatars/{dados['id']}/{avatar}.png?size=64" if avatar else None,
    }


def ler_guild_id(texto: str | None) -> int | None:
    """Id de servidor vindo da URL: só dígitos, senão None."""
    if not texto or not texto.isdigit() or len(texto) > 20:
        return None
    return int(texto)
