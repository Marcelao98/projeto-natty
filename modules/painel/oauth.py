"""Acesso cru ao OAuth2 do Discord (troca do code por token, quem é o usuário).

Único lugar do painel que fala com o Discord por HTTP. aiohttp já vem com o
discord.py, então não é dependência nova.
"""

from __future__ import annotations

import aiohttp

API = "https://discord.com/api/v10"


class ErroDeLogin(Exception):
    pass


class OAuthDiscord:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self._secret = client_secret

    async def trocar_codigo(self, code: str, redirect_uri: str) -> str:
        """code do callback → access_token. ErroDeLogin se o Discord recusar."""
        dados = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        auth = aiohttp.BasicAuth(self.client_id, self._secret)
        async with aiohttp.ClientSession() as sessao:
            async with sessao.post(f"{API}/oauth2/token", data=dados, auth=auth) as resposta:
                if resposta.status != 200:
                    raise ErroDeLogin(f"token: HTTP {resposta.status}")
                return (await resposta.json())["access_token"]

    async def buscar_usuario(self, token: str) -> dict:
        async with aiohttp.ClientSession() as sessao:
            async with sessao.get(f"{API}/users/@me", headers={"Authorization": f"Bearer {token}"}) as resposta:
                if resposta.status != 200:
                    raise ErroDeLogin(f"users/@me: HTTP {resposta.status}")
                return await resposta.json()
