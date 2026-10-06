import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.utils import escape_markdown

from modules.core import service

log = logging.getLogger(__name__)

CARGO_VIAJANTE = "Viajante"
ERRO_BANCO = "Deu ruim ao acessar o registro de personagens. Tenta de novo em instantes."
# Código de saída quando o banco está ilegível: o rodar_natty.bat para o loop
# em vez de reiniciar (reiniciar não conserta; restaurar_banco.py conserta).
SAIDA_BANCO_ILEGIVEL = 3


async def _atualizar_autor(user: discord.abc.User) -> None:
    """Mantém username e apelido de quem usou o comando em dia no banco.
    Falha aqui só vai pro log: não pode atrapalhar o comando."""
    try:
        await asyncio.to_thread(
            service.garantir_jogador, str(user.id), user.name, user.display_name
        )
    except Exception:
        log.exception("Falha ao atualizar o jogador %s", user.id)


def _dados_membro(membro: discord.Member) -> dict:
    # display_name já é apelido no servidor → nome global → username.
    return {"discord_id": str(membro.id), "username": membro.name, "nome_exibicao": membro.display_name}


def _data_br(iso: str) -> str:
    """'2026-10-05T19:53:40' → '05/10/2026'; vazio ou fora do formato → ''."""
    try:
        ano, mes, dia = (iso or "")[:10].split("-")
        return f"{int(dia):02d}/{int(mes):02d}/{int(ano)}"
    except ValueError:
        return ""


class CoreCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- tabela jogadores = membros do servidor -----------------------------
    # Precisa do intents.members (bot.py) e do Server Members Intent no portal.

    def _servidor(self) -> discord.Guild | None:
        """O servidor da Crossroads: GUILD_ID do .env, ou o único em que o bot está."""
        guild_id = os.getenv("GUILD_ID", "").strip()
        if guild_id:
            return self.bot.get_guild(int(guild_id))
        return self.bot.guilds[0] if len(self.bot.guilds) == 1 else None

    def _e_do_servidor(self, membro: discord.Member) -> bool:
        servidor = self._servidor()
        return not membro.bot and servidor is not None and membro.guild.id == servidor.id

    async def _chamar(self, funcao, *args) -> None:
        """Roda a função do service fora do loop; erro só vai pro log."""
        try:
            await asyncio.to_thread(funcao, *args)
        except Exception:
            log.exception("Falha em %s", funcao.__name__)

    async def cog_load(self):
        self.sincronizar_todo_dia.start()

    async def cog_unload(self):
        self.sincronizar_todo_dia.cancel()

    @tasks.loop(hours=24)
    async def sincronizar_todo_dia(self):
        """Ao subir e a cada 24h: lista completa de membros (pela API, paginada) →
        tabela jogadores. Os listeners abaixo cuidam do dia a dia; isto pega o que
        escapou enquanto a Natty estava fora do ar."""
        servidor = self._servidor()
        if servidor is None:
            log.warning("Sem servidor definido (GUILD_ID) e o bot está em %d: membros não sincronizados.",
                        len(self.bot.guilds))
            return
        try:
            membros = [_dados_membro(m) async for m in servidor.fetch_members(limit=None) if not m.bot]
            r = await asyncio.to_thread(service.sincronizar_membros, membros)
        except Exception:
            log.exception("Falha ao sincronizar os membros de %s", servidor.name)
            return
        log.info("Membros sincronizados: %s", r)

    @sincronizar_todo_dia.before_loop
    async def _esperar_conectar(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, membro: discord.Member):
        if self._e_do_servidor(membro):
            await self._chamar(service.membro_entrou, *_dados_membro(membro).values())

    @commands.Cog.listener()
    async def on_member_update(self, antes: discord.Member, depois: discord.Member):
        # Dispara também em troca de cargo: só grava se username ou apelido mudou.
        if self._e_do_servidor(depois) and (
            antes.name != depois.name or antes.display_name != depois.display_name
        ):
            await self._chamar(service.membro_entrou, *_dados_membro(depois).values())

    @commands.Cog.listener()
    async def on_user_update(self, antes: discord.User, depois: discord.User):
        # Troca de username ou nome global; o apelido vem do membro no servidor.
        if antes.name == depois.name and antes.global_name == depois.global_name:
            return
        servidor = self._servidor()
        membro = servidor.get_member(depois.id) if servidor else None
        if membro is not None and self._e_do_servidor(membro):
            await self._chamar(service.membro_entrou, *_dados_membro(membro).values())

    @commands.Cog.listener()
    async def on_member_remove(self, membro: discord.Member):
        if self._e_do_servidor(membro):
            await self._chamar(service.membro_saiu, str(membro.id))

    # --- comandos --------------------------------------------------------------

    @app_commands.command(name="oi", description="A Natty se apresenta")
    async def oi(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Oi, eu sou a Natty. Uma robô achada no lixo, totalmente inútil kkkk "
            "(porque ainda sou)."
        )
        await _atualizar_autor(interaction.user)

    @app_commands.command(
        name="registrar-personagem", description="Registra um personagem seu (ficha do DiceCloud)"
    )
    async def registrar_personagem(self, interaction: discord.Interaction):
        cargos = getattr(interaction.user, "roles", [])
        if not any(c.name == CARGO_VIAJANTE for c in cargos):
            await interaction.response.send_message(
                f"Você precisa do cargo **{CARGO_VIAJANTE}** para registrar personagens. "
                "Complete o onboarding do servidor primeiro.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_modal(RegistroModal())
        await _atualizar_autor(interaction.user)

    @app_commands.command(name="deletar-personagem", description="Deleta um personagem seu")
    @app_commands.describe(nome="Nome do personagem a deletar")
    async def deletar_personagem(self, interaction: discord.Interaction, nome: str):
        view = Confirmacao(interaction.user.id)
        await interaction.response.send_message(
            f"Tem certeza que quer deletar **{escape_markdown(nome)}**? "
            "Isso apaga o registro dele.",
            view=view,
            ephemeral=True,
        )
        await _atualizar_autor(interaction.user)
        await view.wait()
        if not view.confirmado:
            await interaction.edit_original_response(content="Deleção cancelada.", view=None)
            return

        try:
            r = await asyncio.to_thread(
                service.deletar_personagem, str(interaction.user.id), nome
            )
        except Exception:
            await interaction.edit_original_response(content=ERRO_BANCO, view=None)
            raise
        conteudo = (
            f"**{escape_markdown(nome)}** foi deletado." if r["sucesso"] else r["erro"]
        )
        await interaction.edit_original_response(content=conteudo, view=None)

    @app_commands.command(
        name="personagens", description="Lista todos os personagens registrados na Crossroads"
    )
    async def personagens(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await _atualizar_autor(interaction.user)
        try:
            lista = await asyncio.to_thread(service.listar_personagens)
        except Exception:
            await interaction.followup.send(ERRO_BANCO)
            raise

        if not lista:
            await interaction.followup.send("Ainda não há nenhum viajante nas Encruzilhadas.")
            return

        linhas = []
        for p in lista:
            nome = escape_markdown(p["nome"])
            titulo = f"[{nome}]({p['link']})" if p["link"] else nome
            nivel = p["nivel"] if p["nivel"] is not None else "?"
            jogador = f" · {escape_markdown(p['jogador'])}" if p["jogador"] else ""
            data = _data_br(p["criado_em"])
            desde = f" · desde {data}" if data else ""
            linhas.append(f"**{titulo}** — nível {nivel}{jogador}{desde}")

        n = len(lista)
        titulo = f"Existem {n} viajantes nas Encruzilhadas" if n > 1 else "Existe 1 viajante nas Encruzilhadas"
        embed = discord.Embed(title=titulo, description=_juntar_linhas(linhas), color=discord.Color.blurple())
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="registrar-missao", description="Registra uma missão que você conduziu (depois da sessão)"
    )
    @app_commands.describe(
        nome="Nome da missão",
        data="Dia em que a sessão aconteceu (DD/MM/AAAA)",
        dificuldade="Dificuldade final, decidida depois da sessão",
        xp="XP que cada personagem recebeu",
        gold="Gold que cada personagem recebeu",
        participantes="Personagens que jogaram, separados por vírgula (como em /personagens)",
    )
    @app_commands.choices(dificuldade=[app_commands.Choice(name=d, value=d) for d in service.DIFICULDADES])
    async def registrar_missao(
        self, interaction: discord.Interaction, nome: str, data: str,
        dificuldade: app_commands.Choice[str],
        xp: app_commands.Range[int, 0, 10_000_000], gold: app_commands.Range[int, 0, 10_000_000],
        participantes: str,
    ):
        cargos = getattr(interaction.user, "roles", [])
        if not any(c.name == CARGO_VIAJANTE for c in cargos):
            await interaction.response.send_message(
                f"Você precisa do cargo **{CARGO_VIAJANTE}** para registrar missões.", ephemeral=True
            )
            return
        # Confere tudo antes de abrir o formulário: ninguém escreve o relato à toa.
        try:
            r = await asyncio.to_thread(
                service.conferir_missao, nome, data, dificuldade.value, xp, gold, participantes
            )
        except Exception:
            await interaction.response.send_message(ERRO_BANCO, ephemeral=True)
            raise
        if not r["sucesso"]:
            await interaction.response.send_message(r["erro"], ephemeral=True)
            return
        await interaction.response.send_modal(
            MissaoModal(nome, data, dificuldade.value, xp, gold, participantes)
        )
        await _atualizar_autor(interaction.user)

    @app_commands.command(name="missoes", description="Lista as missões registradas na Crossroads")
    async def missoes(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await _atualizar_autor(interaction.user)
        try:
            lista = await asyncio.to_thread(service.listar_missoes)
        except Exception:
            await interaction.followup.send(ERRO_BANCO)
            raise
        if not lista:
            await interaction.followup.send("Nenhuma missão registrada ainda.")
            return

        linhas = []
        for m in reversed(lista):  # mais recentes primeiro
            data = _data_br(m["data"]) or "?"
            premio = f" · {m['xp']} XP · {m['gold']} gold" if m["xp"] is not None else ""
            quem = ", ".join(escape_markdown(p) for p in m["participantes"]) or "?"
            linhas.append(
                f"**{escape_markdown(m['nome'])}** — {data} · {m['dificuldade']} · "
                f"{escape_markdown(m['condutor'])}{premio}\n↳ {quem}"
            )
        n = len(lista)
        titulo = f"{n} missões registradas" if n > 1 else "1 missão registrada"
        embed = discord.Embed(title=titulo, description=_juntar_linhas(linhas), color=discord.Color.dark_gold())
        await interaction.followup.send(embed=embed)


def _juntar_linhas(linhas: list[str], limite: int = 4096) -> str:
    """Junta as linhas até caber na descrição do embed, com "… e mais N" no fim."""
    descricao = ""
    for i, linha in enumerate(linhas):
        resto = f"\n… e mais {len(linhas) - i}"
        if len(descricao) + len(linha) + 1 + len(resto) > limite:
            return descricao + resto
        descricao += ("\n" if descricao else "") + linha
    return descricao


class MissaoModal(discord.ui.Modal):
    """Segunda parte do /registrar-missao: os textos longos."""

    relato = discord.ui.TextInput(
        label="O que aconteceu na missão?",
        style=discord.TextStyle.paragraph,
        placeholder="Com suas próprias palavras, do tamanho que quiser.",
        max_length=service.MAX_RELATO,
    )
    resultado = discord.ui.TextInput(
        label="Resultado (opcional)", style=discord.TextStyle.paragraph,
        placeholder="Ex: Missão concluída com sucesso.", required=False, max_length=1000,
    )
    outras_recompensas = discord.ui.TextInput(
        label="Outras recompensas (opcional)", placeholder="Itens, favores, aliados...",
        required=False, max_length=500,
    )
    observacoes = discord.ui.TextInput(
        label="Observações (opcional)", style=discord.TextStyle.paragraph,
        required=False, max_length=1000,
    )

    def __init__(self, nome: str, data: str, dificuldade: str, xp: int, gold: int, participantes: str):
        super().__init__(title=f"Missão: {nome}"[:45])
        self.campos = (nome, data, dificuldade, xp, gold, participantes)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        nome, data, dificuldade, xp, gold, participantes = self.campos
        try:
            r = await asyncio.to_thread(
                service.registrar_missao,
                str(interaction.user.id), interaction.user.display_name,
                nome, data, dificuldade, xp, gold, participantes,
                self.relato.value, self.resultado.value, self.outras_recompensas.value, self.observacoes.value,
            )
        except Exception:
            await interaction.followup.send(ERRO_BANCO, ephemeral=True)
            raise
        if not r["sucesso"]:
            await interaction.followup.send(r["erro"], ephemeral=True)
            return
        await interaction.followup.send(
            f"📜 Missão **{escape_markdown(r['nome'])}** registrada ({_data_br(r['data'])}, {dificuldade}, "
            f"{xp} XP, {gold} gold).\nParticipantes: {', '.join(escape_markdown(p) for p in r['participantes'])}",
            ephemeral=True,
        )


class RegistroModal(discord.ui.Modal, title="Registrar personagem"):
    nome = discord.ui.TextInput(
        label="Nome do personagem", placeholder="Exatamente como está na ficha", max_length=100
    )
    link = discord.ui.TextInput(
        label="Link da ficha (DiceCloud)",
        placeholder="https://dicecloud.com/character/...",
        max_length=300,
    )
    # Label até 45 e placeholder até 100 caracteres (limites do Discord).
    historia = discord.ui.TextInput(
        label="História (escreva o quanto quiser)",
        style=discord.TextStyle.paragraph,
        placeholder=(
            f"Do seu jeito: uma linha já vale, ou conte tudo. Limite de "
            f"{service.MAX_HISTORIA} caracteres."
        ),
        max_length=service.MAX_HISTORIA,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Conferindo sua ficha no DiceCloud… isso pode levar até um minuto.", ephemeral=True
        )
        try:
            r = await asyncio.to_thread(
                service.registrar_personagem,
                str(interaction.user.id),
                interaction.user.display_name,
                self.nome.value,
                self.link.value,
                self.historia.value,
            )
        except Exception:
            await interaction.edit_original_response(content=ERRO_BANCO)
            raise

        if r["sucesso"]:
            conteudo = (
                f"**{escape_markdown(self.nome.value.strip())}** registrado em "
                f"{_data_br(r['criado_em'])} com nível **{r['nivel']}**!"
            )
        else:
            conteudo = r["erro"]
        await interaction.edit_original_response(content=conteudo)


class Confirmacao(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.confirmado = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmado = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()


async def setup(bot: commands.Bot):
    try:
        await asyncio.to_thread(service.preparar_banco)
    except service.BancoIlegivel as exc:
        log.critical(
            "BANCO ILEGÍVEL: %s. A Natty não vai subir pra não criar um banco vazio "
            "por cima. Rode: python scripts/restaurar_banco.py",
            exc,
        )
        raise SystemExit(SAIDA_BANCO_ILEGIVEL)
    await bot.add_cog(CoreCog(bot))
