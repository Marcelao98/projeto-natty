"""Módulo Bardo — interface Discord.

Só traduz mensagem em linguagem natural → chamada de service.py, e cuida da
parte que é inerentemente Discord (conectar em canal de voz, tocar o
áudio, pausar, volume, passar pra próxima da fila quando uma música acaba).
Nenhuma lógica de reconhecimento de pedido mora aqui.

Dois jeitos de pedir, como no Dice: em linguagem natural ("@Natty toca
<link>", "natty pula", "@Natty volume 30") ou pelos slash commands
(/tocar, /pular, /fila, /limpar-fila, /remover, /repetir, /pausar,
/continuar, /parar, /volume), que não dependem de menção nem da Message
Content Intent.

Quando todo mundo sai da call, a Natty sai também (depois de
SEGUNDOS_ANTES_DE_SAIR) — menos com o Echo escutando, que decide sozinho.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import escape_markdown

from modules.bardo import service
from modules.bardo.motor import ControleBardo, MotorBardo, _duracao, _echo_escutando, _eh_mestre, _pessoas_no_canal

log = logging.getLogger(__name__)

# Pedido falado na call: a própria Natty posta "🎙️ natty toca <o que ouviu>"
# no canal (quem transcreve a fala é o módulo Echo). Mesma convenção do Dice:
# só mensagem dela com esse marcador no começo é aceita — as respostas do
# Bardo nunca começam assim, então não há laço. O Bardo não importa nada do Echo.
# Só o caractere-base do 🎙, sem o seletor de emoji (U+FE0F), que pode vir ou não.
MARCADOR_VOZ = "\U0001F399"


def _deve_ignorar(message: discord.Message, eu: discord.abc.User | None) -> bool:
    """Ignora bots (a própria Natty, o Avrae...), exceto o pedido falado que a Natty posta."""
    if not message.author.bot:
        return False
    return not (eu is not None and message.author.id == eu.id and message.content.startswith(MARCADOR_VOZ))


class BardoCog(MotorBardo, commands.Cog):
    """Comandos de texto e slash do Bardo; o player em si mora no MotorBardo (motor.py)."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)

    async def cog_load(self):
        # O painel web (e qualquer outra "superfície") fala com o Bardo por
        # aqui, sem importar o módulo: bot.controles["bardo"].
        if not hasattr(self.bot, "controles"):
            self.bot.controles = {}
        self.bot.controles["bardo"] = ControleBardo(self)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if _deve_ignorar(message, self.bot.user) or message.guild is None:
            return
        # Reply à pergunta "era essa?" é a resposta dela — com ou sem @ (dá
        # pra responder no Discord com a menção desligada). Só reply conta.
        respondendo_a = message.reference.message_id if message.reference else None
        if service.eh_resposta_da_pendencia(message.guild.id, respondendo_a):
            await self._responder_pendencia(message)
            return
        if not self._falou_com_a_natty(message):
            return

        pedido = service.interpretar_pedido(message.content)
        if pedido is None:
            return

        guild = message.guild
        if pedido.acao == "tocar" and not pedido.link and not pedido.busca:
            # "@Natty toca" com um arquivo de áudio anexado: toca o anexo.
            anexo = next((a for a in message.attachments if (a.content_type or "").startswith("audio/")), None)
            if anexo is not None:
                pedido = service.Pedido("tocar", link=anexo.url)
        if pedido.acao == "tocar":
            if pedido.link:
                async with message.channel.typing():
                    resposta = await self._tocar(guild, message.author, message.channel, pedido.link)
            elif pedido.busca:
                async with message.channel.typing():
                    resposta = await self._tocar_busca(guild, message.author, message.channel, pedido.busca)
            else:
                resposta = (
                    "Me manda o link do YouTube, ou descreve o que quer ouvir "
                    '(ex: "@Natty toca triste e bloodborne").'
                )
        elif pedido.acao == "tocar_playlist":
            async with message.channel.typing():
                resposta = await self._tocar_playlist_salva(guild, message.author, message.channel, pedido.busca)
        elif pedido.acao == "pular":
            resposta = self._pular(guild)
        elif pedido.acao == "fila":
            resposta = self._descrever_fila(guild)
        elif pedido.acao == "limpar_fila":
            resposta = self._limpar_fila(guild)
        elif pedido.acao == "remover":
            resposta = self._remover(guild, pedido.posicao)
        elif pedido.acao == "pausar":
            resposta = self._pausar(guild)
        elif pedido.acao == "continuar":
            resposta = self._continuar(guild)
        elif pedido.acao == "repetir":
            resposta = self._repetir(guild, pedido)
        elif pedido.acao == "parar":
            resposta = await self._parar(guild)
        else:  # volume
            resposta = self._mudar_volume(guild, pedido)

        enviada = await message.reply(resposta, mention_author=False)
        # Se esse pedido abriu um "era essa?", a pergunta está nesta mensagem:
        # só reply a ela vai contar como resposta.
        service.registrar_pergunta_da_pendencia(guild.id, enviada.id)

    def _falou_com_a_natty(self, message: discord.Message) -> bool:
        """
        Só menção de verdade: @Natty ou o cargo automático dela (o Discord
        oferece os dois ao digitar "@Natty"). Escrever "natty" sem @ não conta
        mais — evitava que conversa normal da mesa virasse comando.

        Exceção: o pedido falado que a própria Natty posta com 🎙 (Echo →
        "🎙️ natty toca X"). O marcador já diz que é pra ela.
        """
        if message.author.id == getattr(self.bot.user, "id", None) and message.content.startswith(MARCADOR_VOZ):
            return True
        cargo_da_natty = message.guild.self_role
        return self.bot.user in message.mentions or (
            cargo_da_natty is not None and cargo_da_natty in message.role_mentions
        )

    @app_commands.command(
        name="tocar", description="Toca um link (vídeo ou playlist do YouTube) ou uma busca no dataset (ou põe na fila)"
    )
    @app_commands.describe(pedido="Link (YouTube, SoundCloud, Bandcamp...; vídeo ou playlist), ou uma busca: triste e bloodborne")
    @app_commands.guild_only()
    async def tocar(self, interaction: discord.Interaction, pedido: str):
        # Resolver o link no yt-dlp passa fácil dos 3s que o Discord dá pra responder.
        await interaction.response.defer(thinking=True)
        link = service.extrair_link(pedido)
        if link:
            resposta = await self._tocar(interaction.guild, interaction.user, interaction.channel, link)
        else:
            resposta = await self._tocar_busca(interaction.guild, interaction.user, interaction.channel, pedido)
        enviada = await interaction.followup.send(resposta, wait=True)
        service.registrar_pergunta_da_pendencia(interaction.guild.id, enviada.id)  # se abriu um "era essa?"

    @app_commands.command(name="pular", description="Pula pra próxima música da fila")
    @app_commands.guild_only()
    async def pular(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._pular(interaction.guild))

    @app_commands.command(name="fila", description="Mostra a música tocando e as próximas")
    @app_commands.guild_only()
    async def fila(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._descrever_fila(interaction.guild))

    @app_commands.command(name="limpar-fila", description="Tira todas as músicas da fila (a atual continua)")
    @app_commands.guild_only()
    async def limpar_fila(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._limpar_fila(interaction.guild))

    @app_commands.command(name="remover", description="Tira uma música da fila")
    @app_commands.describe(posicao="Posição na fila (1 = a próxima; veja em /fila)")
    @app_commands.guild_only()
    async def remover(self, interaction: discord.Interaction, posicao: app_commands.Range[int, 1, service.MAX_FILA]):
        await interaction.response.send_message(self._remover(interaction.guild, posicao))

    @app_commands.command(name="repetir", description="Repete a música atual ou a fila inteira")
    @app_commands.describe(modo="O que repetir; sem escolher, liga/desliga a repetição da música atual")
    @app_commands.choices(
        modo=[
            app_commands.Choice(name="a música atual", value="faixa"),
            app_commands.Choice(name="a fila inteira", value="fila"),
            app_commands.Choice(name="desligar", value="desligar"),
        ]
    )
    @app_commands.guild_only()
    async def repetir(self, interaction: discord.Interaction, modo: app_commands.Choice[str] | None = None):
        await interaction.response.send_message(self._repetir(interaction.guild, _pedido_de_repetir(modo)))

    playlist = app_commands.Group(name="playlist", description="Playlists salvas do servidor", guild_only=True)

    @playlist.command(name="salvar", description="Salva a fila atual (a que toca + as próximas) como playlist")
    @app_commands.describe(nome="Nome da playlist", substituir="Se já existir uma com esse nome, troca por esta")
    async def playlist_salvar(self, interaction: discord.Interaction, nome: str, substituir: bool = False):
        fila = self._fila(interaction.guild)
        musicas = [m for m in (fila.tocando, *fila.proximas) if m is not None]
        try:
            nome, quantas = await asyncio.to_thread(
                service.salvar_playlist, interaction.guild.id, nome, musicas, interaction.user.id, substituir
            )
        except service.ErroDeColecao as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(f"💾 Salvei a playlist **{escape_markdown(nome)}** ({quantas} músicas).")
        self._notificar(interaction.guild.id)

    @playlist.command(name="tocar", description="Põe uma playlist salva na fila")
    @app_commands.describe(nome="Nome da playlist (veja em /playlist listar)")
    async def playlist_tocar(self, interaction: discord.Interaction, nome: str):
        await interaction.response.defer(thinking=True)
        resposta = await self._tocar_playlist_salva(interaction.guild, interaction.user, interaction.channel, nome)
        await interaction.followup.send(resposta)

    @playlist.command(name="listar", description="Lista as playlists salvas do servidor")
    async def playlist_listar(self, interaction: discord.Interaction):
        playlists = await asyncio.to_thread(service.listar_playlists, interaction.guild.id)
        if not playlists:
            texto = "Nenhuma playlist salva ainda. Monta a fila e usa `/playlist salvar`."
        else:
            texto = "📃 Playlists:\n" + "\n".join(
                f"• **{escape_markdown(p['nome'])}** ({p['quantas']} músicas)" for p in playlists
            )
        await interaction.response.send_message(texto)

    @playlist.command(name="ver", description="Mostra as músicas de uma playlist salva")
    async def playlist_ver(self, interaction: discord.Interaction, nome: str):
        try:
            nome, musicas = await asyncio.to_thread(service.carregar_playlist, interaction.guild.id, nome)
        except service.ErroDeColecao as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        linhas = [f"📃 **{escape_markdown(nome)}** ({len(musicas)} músicas):"]
        linhas += [f"{i}. {escape_markdown(m.titulo)}{_duracao(m)}" for i, m in enumerate(musicas[:20], start=1)]
        if len(musicas) > 20:
            linhas.append(f"… e mais {len(musicas) - 20}")
        await interaction.response.send_message("\n".join(linhas))

    @playlist.command(name="apagar", description="Apaga uma playlist salva (quem criou ou o cargo de mestre)")
    async def playlist_apagar(self, interaction: discord.Interaction, nome: str):
        mestre = _eh_mestre(interaction.user)
        try:
            nome = await asyncio.to_thread(
                service.apagar_playlist, interaction.guild.id, nome, interaction.user.id, mestre
            )
        except service.ErroDeColecao as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(f"🗑️ Apaguei a playlist **{escape_markdown(nome)}**.")
        self._notificar(interaction.guild.id)

    @app_commands.command(name="pausar", description="Pausa a música")
    @app_commands.guild_only()
    async def pausar(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._pausar(interaction.guild))

    @app_commands.command(name="continuar", description="Continua a música pausada")
    @app_commands.guild_only()
    async def continuar(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._continuar(interaction.guild))

    @app_commands.command(name="parar", description="Para a música e limpa a fila (continua no canal de voz)")
    @app_commands.guild_only()
    async def parar(self, interaction: discord.Interaction):
        await interaction.response.send_message(await self._parar(interaction.guild))

    @app_commands.command(name="volume", description="Muda o volume da música (0 a 100)")
    @app_commands.describe(nivel="Volume de 0 a 100; sem valor, mostra o volume atual")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, nivel: app_commands.Range[int, 0, 100] | None = None):
        pedido = service.Pedido("volume", volume=nivel)
        await interaction.response.send_message(self._mudar_volume(interaction.guild, pedido))

    async def _responder_pendencia(self, message: discord.Message) -> None:
        """Mensagem pra Natty que não é pedido: se tem pergunta "era essa?" em aberto neste canal, é a resposta."""
        pendencia = service.pendencia_do_servidor(message.guild.id)  # já some se venceu
        if pendencia is None or pendencia["canal_id"] != message.channel.id:
            return

        temas = service.interpretar_resposta_de_pendencia(message.content)
        service.limpar_pendencia(message.guild.id)
        titulo = escape_markdown(pendencia["titulo"])
        if temas is None:
            await message.reply(f"Ok, não guardei **{titulo}** 👍", mention_author=False)
            return

        try:
            entrada = await asyncio.to_thread(
                service.adicionar_descoberta, message.guild.id, pendencia["titulo"], pendencia["link"], temas
            )
        except service.MusicaJaNoDataset as e:
            await message.reply(
                f"**{escape_markdown(e.musica['nome'])}** já estava no dataset, deixei como está.",
                mention_author=False,
            )
            return
        except Exception:
            log.exception("Bardo: falha ao gravar descoberta %s", pendencia["link"])
            await message.reply("Não consegui salvar no dataset, deu erro aqui 😕", mention_author=False)
            return

        if entrada["temas"] == [service.NAO_CLASSIFICADO]:
            detalhe = 'como "não classificado" (sem temas por enquanto)'
        else:
            detalhe = "com os temas " + ", ".join(entrada["temas"])
        await message.reply(f"Adicionei **{titulo}** ao dataset {detalhe} 🎉", mention_author=False)

    async def cog_unload(self):
        for guild_id in list(self._saidas):
            self._cancelar_saida(guild_id)
        getattr(self.bot, "controles", {}).pop("bardo", None)

    @commands.Cog.listener()
    async def on_voice_state_update(self, membro: discord.Member, antes: discord.VoiceState, depois: discord.VoiceState):
        """Alguém entrou/saiu de um canal: se a call da Natty esvaziou, agenda a saída; se voltou gente, cancela.

        A própria Natty (re)conectou — queda e volta, ou o Echo trocou a
        conexão: o mixer volta a tocar na conexão nova, sem perder a música.
        """
        if membro.id == getattr(self.bot.user, "id", None) and depois.channel is not None:
            mixer = self._mixers.get(membro.guild.id)
            if mixer is not None and (mixer.musica or mixer.ambientes):
                asyncio.get_running_loop().call_later(
                    1.0, lambda: self._garantir_player(membro.guild, membro.guild.voice_client))
            return
        if membro.bot:
            return
        guild = membro.guild
        voice_client = guild.voice_client
        if voice_client is None or voice_client.channel is None:
            return
        canal = voice_client.channel
        if canal not in (antes.channel, depois.channel):
            return
        if service.deve_sair_do_canal(_pessoas_no_canal(canal), _echo_escutando(voice_client)):
            if guild.id not in self._saidas:
                self._saidas[guild.id] = asyncio.create_task(self._sair_se_continuar_vazio(guild))
        else:
            self._cancelar_saida(guild.id)


def _pedido_de_repetir(modo: app_commands.Choice[str] | None) -> service.Pedido:
    """Opção do /repetir → Pedido("repetir")."""
    valor = modo.value if modo else None
    if valor == "desligar":
        return service.Pedido("repetir", repetir=False)
    return service.Pedido("repetir", alvo="fila" if valor == "fila" else None)


async def setup(bot: commands.Bot):
    await bot.add_cog(BardoCog(bot))
