import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

MODULOS_ATIVOS = ["modules.core.cog", "modules.bardo.cog", "modules.dice.cog", "modules.socorro.cog", "modules.echo.cog"]


class Natty(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        # O Bardo ("@Natty toca <link>") e o Dice ("rolo 1d20+5") reconhecem
        # pedidos em linguagem natural, então precisam ler o conteúdo da
        # mensagem. Isso é uma Privileged Intent: precisa estar habilitada
        # também no Discord Developer Portal (Bot > Message Content Intent),
        # senão message.content chega sempre vazio.
        intents.message_content = True
        intents.voice_states = True
        # O NAT-CORE espelha os membros do servidor na tabela jogadores (entrou,
        # saiu, trocou de apelido). Também é Privileged Intent: precisa de
        # Bot > Server Members Intent ligado no Developer Portal.
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

    async def setup_hook(self):
        for modulo in MODULOS_ATIVOS:
            await self.load_extension(modulo)
        await self.tree.sync()

    async def on_ready(self):
        print(f"Natty conectada como {self.user}")


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN não encontrado no .env")
    Natty().run(TOKEN)
