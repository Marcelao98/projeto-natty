"""Painel web — sobe o servidor aiohttp junto com a Natty (cog só de ciclo de vida).

Liga só se DISCORD_CLIENT_SECRET estiver no .env. Escuta em 127.0.0.1 na
porta NATTY_PAINEL_PORT (padrão 8710). A URL que o navegador usa (e que vai
no redirect do OAuth, cadastrado no Developer Portal) é NATTY_PAINEL_URL,
padrão http://localhost:<porta>.
"""

from __future__ import annotations

import logging
import os

from aiohttp import web
from discord.ext import commands

from modules.painel import service
from modules.painel.oauth import OAuthDiscord
from modules.painel.web import ConfigPainel, criar_app

log = logging.getLogger(__name__)


class _OAuthDoBot(OAuthDiscord):
    """Client id vem do próprio bot (application_id), a não ser que o .env diga outro."""

    def __init__(self, bot, secret: str):
        super().__init__(os.getenv("DISCORD_CLIENT_ID") or "", secret)
        self._bot = bot

    @property
    def client_id(self) -> str:
        return self._client_id or str(self._bot.application_id)

    @client_id.setter
    def client_id(self, valor: str) -> None:
        self._client_id = valor


class PainelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._runner: web.AppRunner | None = None

    async def cog_load(self):
        secret = os.getenv("DISCORD_CLIENT_SECRET")
        if not secret:
            log.info("Painel desligado (sem DISCORD_CLIENT_SECRET no .env)")
            return
        porta = int(os.getenv("NATTY_PAINEL_PORT") or service.PORTA_PADRAO)
        base_url = os.getenv("NATTY_PAINEL_URL") or f"http://localhost:{porta}"
        app = criar_app(self.bot, ConfigPainel(base_url, cookie_seguro=base_url.startswith("https://")),
                        _OAuthDoBot(self.bot, secret))
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", porta).start()
        print(f"[painel] no ar em {base_url}", flush=True)

    async def cog_unload(self):
        if self._runner is not None:
            await self._runner.cleanup()


async def setup(bot: commands.Bot):
    await bot.add_cog(PainelCog(bot))
