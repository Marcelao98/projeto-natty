from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from modules.dice.detector import (
    extract_coin_conditional,
    extract_coin_pattern,
    extract_conditional_reroll,
    is_roll_message,
)
from modules.dice.format import describe_coin_roll, describe_roll_compact
from modules.dice.service import roll, roll_coins

# Rolagem falada na call: a própria Natty posta "🎙️ rolo 1d20+5" no canal
# (quem converte a fala é o módulo Echo). Só mensagem dela com esse
# marcador no começo é aceita — nunca as respostas do próprio Dice ("🎲 ..."),
# então não há laço. É uma convenção de texto: o Dice não importa nada do Echo.
# Só o caractere-base do 🎙, sem o seletor de emoji (U+FE0F), que pode vir ou não.
MARCADOR_VOZ = "\U0001F399"


def _deve_ignorar(message: discord.Message, eu: Optional[discord.abc.User]) -> bool:
    """Ignora bots (Avrae, a própria Natty...), exceto a rolagem falada que a Natty posta."""
    if not message.author.bot:
        return False
    return not (eu is not None and message.author.id == eu.id and message.content.startswith(MARCADOR_VOZ))


def _responder(texto: str, exigir_pedido: bool) -> Optional[str]:
    """
    Resposta para `texto`, ou None se não for pedido de rolagem.
    Moedas primeiro: "rolo moeda se cara role 1d20" não é um 1d20 comum.
    Levanta ValueError com a mensagem de erro para o jogador.
    """
    moeda = extract_coin_pattern(texto)
    if moeda:
        return describe_coin_roll(roll_coins(moeda, extract_coin_conditional(texto)))
    if exigir_pedido and not is_roll_message(texto):
        return None
    return describe_roll_compact(roll(texto, conditional_reroll=extract_conditional_reroll(texto)))


class DiceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignora bots (a própria Natty, o Avrae...) para não rolar em cima das
        # respostas deles — menos a rolagem falada (ver MARCADOR_VOZ).
        if _deve_ignorar(message, self.bot.user):
            return
        try:
            resposta = _responder(message.content, exigir_pedido=True)
        except ValueError as e:
            await message.reply(f"❌ {e}", mention_author=False)
            return
        if resposta:
            await message.reply(resposta, mention_author=False)

    @app_commands.command(name="rolar", description="Rola dados ou moedas (ex: 1d20+5 com vantagem vs 15)")
    @app_commands.describe(dados="Ex: 1d20+5 vs CD 15, 1d8 se 8 role de novo, 3 moedas, moeda se cara role 1d20")
    async def rolar(self, interaction: discord.Interaction, dados: str):
        try:
            resposta = _responder(dados, exigir_pedido=False)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return
        await interaction.response.send_message(resposta)


async def setup(bot: commands.Bot):
    await bot.add_cog(DiceCog(bot))
