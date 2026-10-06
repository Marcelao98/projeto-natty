"""Módulo Socorro — interface Discord.

"natty socorro" (ou "@Natty socorro") no chat, ou /socorro: a Natty se
apresenta e explica os módulos. Os textos moram em service.py.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

from modules.socorro import service

_MENCAO_RE = re.compile(r"<@[!&]?\d+>")


class SocorroCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        # Só menção de verdade (@Natty ou o cargo); "natty socorro" escrito não conta.
        if not self._mencionou_a_natty(message):
            return
        sem_mencao = _MENCAO_RE.sub(" ", message.content)
        topico = service.interpretar_pedido(sem_mencao)
        if topico is None:
            return

        await message.reply(service.texto_de_ajuda(topico), mention_author=False)

    def _mencionou_a_natty(self, message: discord.Message) -> bool:
        # Ao digitar "@Natty" o Discord também oferece o cargo automático do
        # bot, que tem o mesmo nome; as duas menções valem.
        cargo_da_natty = message.guild.self_role
        return self.bot.user in message.mentions or (
            cargo_da_natty is not None and cargo_da_natty in message.role_mentions
        )

    @app_commands.command(name="socorro", description="A Natty explica o que sabe fazer")
    @app_commands.describe(modulo="Módulo pra detalhar; sem ele, mostra a apresentação geral")
    async def socorro(
        self, interaction: discord.Interaction, modulo: Optional[Literal["dice", "bardo", "core", "voz"]] = None
    ):
        await interaction.response.send_message(service.texto_de_ajuda(modulo or "geral"))


async def setup(bot: commands.Bot):
    await bot.add_cog(SocorroCog(bot))
