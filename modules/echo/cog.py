"""
Módulo Echo — interface Discord.

Entra no canal de voz quando chamada por texto ("@Natty escuta"), sai com
"@Natty tampe os ouvidos" ou, por voz, "NAT20, por favor, saia". Durante a call:

1. Modo senha: o Vosk (grammar restrita) ouve cada pessoa esperando
   "NAT20, por favor".
2. Senha ouvida → modo comando: a Natty responde "👂 fala a rolagem" e, por
   JANELA_COMANDO_SEGUNDO, um segundo reconhecedor ouve aquela pessoa com o
   vocabulário de dados ("rola dado vinte mais cinco com vantagem").
3. A rolagem é convertida pro texto do Dice e postada como resposta ao
   "👂 fala a rolagem": "🎙️ rolo 1d20+5 com vantagem". O on_message do Dice
   reage sozinho (ele aceita mensagem da Natty que comece com 🎙) — o Echo
   não importa nada do Dice. O nome de quem rolou fica no aviso, nunca no
   texto da rolagem (ver _responder_aviso).

4. "NAT20, por favor, música" (ou "música" na janela da rolagem) → grava o
   pedido (PCM cru, sem Vosk), transcreve com Whisper quando a pessoa para
   de falar e posta "🎙️ natty toca <pedido>" — o Bardo reage sozinho (ele
   também aceita mensagem da Natty que comece com 🎙), sem import entre eles.

O áudio recebido chega cifrado com DAVE; dave.py decifra (ver lá). Tudo vai
pro log com o prefixo [echo] — ver README.md, seção "Log de diagnóstico".
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import traceback
import wave
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import discord
from discord.ext import commands, voice_recv
from discord.utils import escape_markdown

from modules.echo import dave, service

# "tampe os ouvidos", "tampa o ouvido", "tapa os ouvidos" etc — tolerante a
# variação de gênero/número, sem exigir acento certo.
_FRASE_SAIR_RE = re.compile(r"tam?p(?:a|e|em)\s+os?\s+ouvidos?", re.IGNORECASE)

# Silêncio que fecha a frase da senha. O Vosk só fecha frase quando "ouve" o
# silêncio depois dela — mas na pausa o Discord PARA de mandar pacotes, então
# ele não ouve nada e a frase ficava aberta até a pessoa voltar a falar: o
# começo da rolagem era engolido pela senha ("nate vinte por favor nate
# vinte"). Quem fecha agora é a vigia, contando o tempo sem pacote com voz.
SILENCIO_FIM_SENHA_SEGUNDO = 0.5
# Depois da senha, quanto tempo a pessoa tem pra COMEÇAR a falar a rolagem.
JANELA_COMANDO_SEGUNDO = 5.0
# Depois que ela começou, quanto silêncio fecha a rolagem (sem esperar a janela).
# Rolagem longa ("dado vinte... se vinte rola... dado cem") tem respiração no
# meio — e o Vosk devolve um "fim de frase" a cada respiração. Em call real,
# fechar no primeiro deles cortou "dado vinte se vinte rola dado cem" em
# "dado vinte". Por isso os pedaços se acumulam e quem fecha é só este silêncio.
SILENCIO_FIM_COMANDO_SEGUNDO = 1.2
# Teto absoluto do modo comando, mesmo com fala contínua.
COMANDO_MAXIMO_SEGUNDO = 10.0
# Pedido de música (Whisper, vocabulário aberto): o Whisper não é streaming,
# então o áudio é gravado e transcrito de uma vez quando a pessoa termina.
# Mesma lógica de tempo do comando, com mais folga pra nome comprido.
JANELA_MUSICA_SEGUNDO = 5.0
SILENCIO_FIM_MUSICA_SEGUNDO = 1.5
MUSICA_MAXIMO_SEGUNDO = 10.0
INTERVALO_VIGIA_SEGUNDO = 0.2
# Com áudio chegando, imprime os contadores de diagnóstico nesse intervalo.
INTERVALO_DIAGNOSTICO_SEGUNDO = 5.0

SAMPLE_RATE = 48000  # formato que o discord-ext-voice-recv entrega
CANAIS = 2

# O Dice só aceita mensagem da Natty que comece com isso (ver MARCADOR_VOZ no
# cog do Dice). Mensagens do Echo que NÃO são rolagem usam outro emoji (👂).
MARCADOR_VOZ = "🎙️"

# Escriba: áudio (.wav por pessoa) e ata (.txt) de cada sessão. logs/ fica fora do git.
PASTA_SESSOES = Path(__file__).parent.parent.parent / "logs" / "sessoes"
# Pausa a partir da qual a volta da fala vira uma "marca" de horário no .wav
# (o Discord não manda pacote no silêncio — ver service.horario_real).
ESCRIBA_PAUSA_MARCA_SEGUNDO = 0.3
# Depois de "para de gravar", quanto tempo a pergunta "quer que eu transcreva
# agora?" fica valendo. Depois disso, some calada (a gravação continua lá).
ESCRIBA_CONFIRMACAO_SEGUNDO = 15 * 60

# Comandos de texto da Escriba (sempre com @Natty de verdade):
#   "@Natty, grava a sessão" / "grava" / "começa a gravar"
#   "@Natty, para de gravar" / "pare a gravação" / "parar gravação"
#   "@Natty, transcreve a sessão" (a última gravação sem ata)
#   e, depois de parar, "@Natty, sim" / "@Natty, depois"
_PARAR_GRAVACAO_RE = re.compile(r"\bpar[ae]r?\b.*\bgrava", re.IGNORECASE)
_GRAVAR_RE = re.compile(r"\b(?:grava|grave|gravar)\b", re.IGNORECASE)
_TRANSCREVER_RE = re.compile(r"\btranscrev", re.IGNORECASE)
_CONFIRMA_RE = re.compile(r"\b(?:sim|pode|transcrev\w*)\b", re.IGNORECASE)
_RECUSA_RE = re.compile(r"\b(?:depois|n[ãa]o)\b", re.IGNORECASE)


@dataclass
class _Ouvinte:
    """Estado de uma pessoa na call: o reconhecedor da senha e, se aberto, o do comando."""

    senha: object  # vosk.KaldiRecognizer
    nome: str
    canal_texto: discord.abc.Messageable
    senha_ultimo_audio: float = 0.0  # último pacote com voz numa frase da senha ainda aberta; 0 = nenhuma aberta
    comando: object = None  # KaldiRecognizer do modo comando, ou None
    comando_aberto_em: float = 0.0
    comando_ultimo_audio: float = 0.0  # 0 = ainda não falou nada no modo comando
    comando_pedacos: list = None  # frases que o Vosk já fechou dentro deste comando
    musica_pcm: bytearray = None  # gravando pedido de música (PCM cru do Discord), ou None
    musica_aberto_em: float = 0.0
    musica_ultimo_audio: float = 0.0  # 0 = ainda não falou nada no pedido de música
    aviso: object = None  # Future do "👂 fala a rolagem, Fulano!" — a rolagem responde a ele


class EchoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Chave: id do usuário; ou ("ssrc", n) quando o voice_recv ainda não
        # sabe de quem é o áudio — melhor ouvir sem dono que descartar.
        self._ouvintes: dict = {}
        # _on_audio roda na thread do voice_recv; a vigia e o "tampe os
        # ouvidos" mexem nos ouvintes no loop do bot.
        self._ouvintes_lock = threading.Lock()
        self._vigia_task: asyncio.Task | None = None
        # Um pedido de música por vez no Whisper: o modelo é um só e a CPU também.
        self._whisper_lock = asyncio.Lock()
        # Escriba (ata da sessão): grava um .wav por pessoa enquanto ligada e
        # só transcreve no fim. Mexido na thread do voice_recv (gravar) e no
        # loop do bot (ligar/desligar) — sempre com _ouvintes_lock.
        self._escriba_ativa = False
        self._escriba_pasta: Path | None = None
        self._escriba_inicio: float = 0.0
        self._escriba_arquivos: dict = {}  # chave -> (wave.Wave_write, nome do .wav), aberto enquanto grava
        self._escriba_nomes: dict = {}     # nome do arquivo .wav -> nome de exibição
        self._escriba_marcas: dict = {}    # nome do arquivo .wav -> [[posição em s, horário real], ...]
        self._escriba_ultimo: dict = {}    # chave -> time.monotonic() do último pacote
        # guild.id -> (pasta, quando perguntou) — "quer que eu transcreva agora?" em aberto
        self.sessao_pendente_transcricao: dict = {}
        # Uma transcrição por vez: duas juntas disputam a CPU e as duas demoram
        # (02/10/2026: duas sessões rodando ao mesmo tempo por mais de 2h).
        self._escriba_fila = asyncio.Lock()
        self._escriba_transcrevendo: set = set()  # pastas transcrevendo ou na fila
        self._diag: dict[str, int] = defaultdict(int)
        self._diag_lock = threading.Lock()
        self._ultimo_diag = 0.0

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Entrar/sair da call é gatilho de texto simples, separado da senha
        # de voz de propósito: a senha ("NAT20, por favor") é o que ativa uma
        # resposta DURANTE a call, não o comando pra ela entrar ou sair.
        if message.author.bot:
            return
        # Ao digitar "@Natty" o Discord também oferece o cargo automático do
        # bot, que tem o mesmo nome; as duas menções valem (igual Bardo/Socorro).
        cargo_da_natty = message.guild.self_role if message.guild else None
        if self.bot.user not in message.mentions and (
            cargo_da_natty is None or cargo_da_natty not in message.role_mentions
        ):
            return

        conteudo = message.content.lower()

        if _FRASE_SAIR_RE.search(conteudo):
            await self._parar_de_escutar(message)
            return

        # Escriba (só por texto). A ordem importa:
        # 1. Resposta à pergunta "quer que eu transcreva agora?" (se aberta).
        if await self._responder_confirmacao_escriba(message, conteudo):
            return
        # 2. "para de gravar" ANTES de "grava" (a frase contém "gravar").
        if _PARAR_GRAVACAO_RE.search(conteudo):
            await self._parar_escriba(message.channel)
            return
        # 3. "transcreve a sessão": transcreve a última gravação sem ata.
        if _TRANSCREVER_RE.search(conteudo):
            await self._transcrever_ultima_sessao(message.channel)
            return
        # 4. "grava a sessão" / "começa a gravar".
        if _GRAVAR_RE.search(conteudo):
            await self._iniciar_escriba(message.channel)
            return

        if "escuta" not in conteudo:
            return

        voice_state = message.author.voice
        if not voice_state or not voice_state.channel:
            await message.reply("Entra num canal de voz primeiro.")
            return

        # Carrega o modelo antes de entrar na call (~1s): se faltar a pasta
        # do modelo, avisa aqui em vez de ficar surda calada.
        try:
            await asyncio.to_thread(service._carregar_vosk)
        except Exception as e:
            print(f"[echo] Vosk não carregou: {e!r}", flush=True)
            await message.reply(f"não consigo escutar: {e}. (ver modules/echo/README.md)")
            return

        voice_client = message.guild.voice_client
        if voice_client is None:
            voice_client = await voice_state.channel.connect(cls=voice_recv.VoiceRecvClient)
        elif not isinstance(voice_client, voice_recv.VoiceRecvClient):
            # Bardo já pode ter conectado com um VoiceClient comum, que não
            # recebe áudio. Reconecta com a classe que escuta.
            channel = voice_client.channel
            await voice_client.disconnect(force=True)
            voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)

        canal_texto = message.channel
        # Quem mandou "escuta" é o dono da sessão: só a voz dele é processada.
        # Outro "@Natty escuta" troca o dono (cai aqui de novo e reinicia a escuta).
        dono = message.author
        if voice_client.is_listening():
            voice_client.stop_listening()
        with self._ouvintes_lock:
            self._ouvintes.clear()
        voice_client.listen(
            voice_recv.BasicSink(lambda user, data: self._on_audio(user, data, canal_texto, dono.id)),
            after=self._escuta_terminou,
        )
        print(f"[echo] escutando em #{voice_state.channel.name} (Vosk), só a voz de {dono.id}", flush=True)
        await message.reply(
            f'👂 Escutando **só você**, {escape_markdown(dono.display_name)} '
            '(outra pessoa assume mandando "@Natty escuta").\n'
            'Fala **"NAT20, por favor"** pra eu prestar atenção, e depois:\n'
            '🎲 **rolagem** (depois do 👂): "dado vinte mais cinco com vantagem contra quinze", '
            '"quatro dados seis tirando o menor", "três moedas" — fala "dado vinte", não "um dê vinte"\n'
            '🎵 **música**: "NAT20, por favor, música" → (depois do 🎵) o nome dela, ex: "Song of Storms"\n'
            '⏯️ **controlar a música**, na mesma frase da senha: "…, **próxima**" · "…, **pare**" · '
            '"…, **pausa**" · "…, **continua**" · "…, **repete**" · "…, **para de repetir**"\n'
            '🙈 **sair**: "NAT20, por favor, **saia**" (ou manda "@Natty, tampe os ouvidos")\n'
            '📝 **ata da sessão** (por texto): `@Natty, grava a sessão` · `@Natty, para de gravar`\n'
            '-# Faz uma pausinha depois da senha. Ajuda completa: `@Natty socorro voz`.'
        )

        if self._vigia_task is None or self._vigia_task.done():
            self._vigia_task = asyncio.create_task(self._vigiar())

    async def _parar_de_escutar(self, message: discord.Message):
        """"@Natty, tampe os ouvidos" (texto)."""
        if await self._desligar(message.guild):
            await message.reply("tampando os ouvidos! 🙈 saindo da call.")
        else:
            await message.reply("eu nem tava escutando. 👂")

    async def _sair_por_voz(self, canal_texto: discord.abc.Messageable):
        """"NAT20, por favor, saia" (voz): o mesmo que o "tampe os ouvidos"."""
        guild = getattr(canal_texto, "guild", None)
        if guild is not None and await self._desligar(guild):
            await canal_texto.send("tampando os ouvidos! 🙈 saindo da call.")

    async def _desligar(self, guild: discord.Guild) -> bool:
        """Para de escutar e sai da call. False se não estava escutando."""
        voice_client = guild.voice_client
        if voice_client is None or not isinstance(voice_client, voice_recv.VoiceRecvClient):
            return False

        if self._escriba_ativa:
            # Fecha os .wav (com nomes.json e marcas.json) mas NÃO transcreve:
            # transcrever só com pedido explícito. O áudio fica preservado pra
            # "@Natty, transcreve a sessão" depois.
            pasta, _ = self._fechar_gravacao_escriba()
            print(f"[echo] Escriba: call encerrada com gravação ativa, áudio preservado em {pasta}", flush=True)

        if self._vigia_task is not None:
            self._vigia_task.cancel()
            self._vigia_task = None

        voice_client.stop_listening()
        with self._ouvintes_lock:
            self._ouvintes.clear()
        await voice_client.disconnect(force=True)
        print("[echo] saí da call", flush=True)
        return True

    @staticmethod
    def _escuta_terminou(erro):
        if erro:
            print(f"[echo] a escuta parou por erro: {erro!r}", flush=True)
        else:
            print("[echo] a escuta terminou", flush=True)

    def _contar(self, chave: str, n: int = 1):
        with self._diag_lock:
            self._diag[chave] += n

    def _enviar(self, canal: discord.abc.Messageable, texto: str):
        """Agenda uma mensagem no loop do bot — funciona de qualquer thread. Devolve o Future."""
        return asyncio.run_coroutine_threadsafe(
            canal.send(texto, allowed_mentions=discord.AllowedMentions.none()), self.bot.loop
        )

    def _responder_aviso(self, ouvinte: _Ouvinte, texto: str):
        """
        Responde ao "👂 fala a rolagem, Fulano!". É assim que o nome de quem
        rolou aparece: ele NÃO pode ir no texto da rolagem, porque o Dice lê a
        mensagem inteira — um apelido "Dis" ou "Vant" viraria desvantagem/vantagem.
        """
        aviso, canal = ouvinte.aviso, ouvinte.canal_texto

        async def responder():
            try:
                mensagem = await asyncio.wrap_future(aviso)
                await mensagem.reply(texto, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                await canal.send(texto, allowed_mentions=discord.AllowedMentions.none())

        asyncio.run_coroutine_threadsafe(responder(), self.bot.loop)

    def _on_audio(
        self, user, data: voice_recv.VoiceData, canal_texto: discord.abc.Messageable, dono_id: int | None = None
    ):
        # Roda na thread de leitura do voice_recv, um pacote (20ms) por vez —
        # já fora do loop do bot, então o Vosk processa aqui mesmo, sem
        # to_thread (custa ~0.4ms por pacote, medido).
        self._contar("pacotes")
        if user is not None and user.bot:
            return
        if not data.pcm:
            self._contar("sem_pcm")
            return
        if user is None:
            self._contar("sem_usuario")
            chave = ("ssrc", data.packet.ssrc)
        else:
            chave = user.id

        try:
            if self._escriba_ativa:
                # A Escriba grava TODO MUNDO (é a ata da mesa), antes do filtro
                # do dono; senha e comandos continuam só do dono, logo abaixo.
                self._gravar_para_escriba(chave, user, data.pcm)

            if dono_id is not None and (user is None or user.id != dono_id):
                # Só a voz de quem mandou "escuta". O Discord já entrega o áudio de
                # cada pessoa separado; aqui o dos outros é descartado antes do
                # Vosk — com 4 pessoas na call, a fala dos outros virava centenas
                # de frases de ruído ("favor", "rolo", "sai") e gastava CPU à toa.
                # Sem dono conhecido (SSRC ainda sem usuário) também descarta: não
                # dá pra saber se é o dono, e o dave.py descobre o dono em instantes.
                self._contar("outros")
                return

            pcm_16k = service.resample_para_16k_mono(data.pcm, SAMPLE_RATE, CANAIS)
            with self._ouvintes_lock:
                ouvinte = self._ouvintes.get(chave)
                if ouvinte is None:
                    nome = escape_markdown(user.display_name) if user is not None else "alguém"
                    ouvinte = self._ouvintes[chave] = _Ouvinte(
                        service._criar_reconhecedor_vosk(), nome, canal_texto
                    )
                if ouvinte.musica_pcm is not None:
                    # Pedido de música: só grava. O PCM cru (48kHz estéreo) é o
                    # que o transcrever_pcm espera; o Vosk não entra aqui.
                    ouvinte.musica_pcm.extend(data.pcm)
                    if service.tem_voz(pcm_16k):
                        ouvinte.musica_ultimo_audio = time.monotonic()
                    return
                if ouvinte.comando is not None:
                    # Só pacote com voz conta como "começou a falar": o rabo
                    # silencioso do "por favor" ainda chega aqui.
                    if service.tem_voz(pcm_16k):
                        ouvinte.comando_ultimo_audio = time.monotonic()
                    texto = service.processar_chunk_vosk(ouvinte.comando, pcm_16k)
                    if texto:
                        # Fim de frase do Vosk = só uma respiração: guarda e continua ouvindo.
                        ouvinte.comando_pedacos.append(texto)
                    return
                if service.tem_voz(pcm_16k):
                    ouvinte.senha_ultimo_audio = time.monotonic()
                texto = service.processar_chunk_vosk(ouvinte.senha, pcm_16k)
                if texto is not None:
                    self._fechar_frase_senha(chave, ouvinte, texto)
        except Exception:
            # Um pacote ruim não pode derrubar a thread de leitura do voice_recv.
            print("[echo] erro processando áudio:", flush=True)
            traceback.print_exc()

    def _fechar_frase_senha(self, chave, ouvinte: _Ouvinte, texto: str):
        """Uma frase do modo senha terminou (pelo Vosk ou pela vigia). Chamar com _ouvintes_lock."""
        ouvinte.senha_ultimo_audio = 0.0
        self._contar("frases")
        if not texto or texto == "[unk]":
            return  # ruído ou fala fora da grammar
        senha = service.tem_wake_word(texto)
        # Log de calibração: o que o Vosk achou que ouviu.
        print(f"[echo] {chave}: senha={senha}: {texto!r}", flush=True)
        if not senha:
            return
        acao = service.acao_depois_da_senha(texto)
        if acao == "sair":
            # "NAT20, por favor, saia": sem janela de rolagem. Roda no loop do bot
            # (desconectar é async), e não aqui — aqui segura _ouvintes_lock.
            asyncio.run_coroutine_threadsafe(self._sair_por_voz(ouvinte.canal_texto), self.bot.loop)
            return
        if acao == "musica":
            self._abrir_musica(ouvinte)  # "NAT20, por favor, música"
            return
        if acao == "bardo":
            # "NAT20, por favor, próxima/repete/pausa/continua/para de repetir":
            # o Bardo já entende por texto — mesmo caminho do "pare".
            comando = service.comando_do_bardo_por_voz(texto)
            self._contar("bardo")
            self._enviar(ouvinte.canal_texto, f"{MARCADOR_VOZ} natty {comando}")
            return
        if acao == "parar_musica":
            # "NAT20, por favor, pare": o Bardo para a música e a Natty continua
            # na call, escutando. Mesmo caminho do pedido de música: texto no canal.
            self._contar("parar_musica")
            self._enviar(ouvinte.canal_texto, f"{MARCADOR_VOZ} natty para")
            return
        self._abrir_comando(ouvinte)  # senha sozinha, "rolo" ou qualquer outra coisa

    def _abrir_comando(self, ouvinte: _Ouvinte):
        """Senha ouvida: troca pro reconhecedor de comando. Chamar com _ouvintes_lock."""
        ouvinte.comando = service._criar_reconhecedor_comando_vosk()
        ouvinte.comando_aberto_em = time.monotonic()
        ouvinte.comando_ultimo_audio = 0.0
        ouvinte.comando_pedacos = []
        self._contar("senhas")
        ouvinte.aviso = self._enviar(ouvinte.canal_texto, f"👂 fala a rolagem, {ouvinte.nome}!")

    def _fechar_comando(self, chave, ouvinte: _Ouvinte, ultimo_pedaco: str):
        """Fim do modo comando (a vigia viu silêncio ou o tempo acabou). Chamar com _ouvintes_lock."""
        texto = service.juntar_pedacos_vosk(ouvinte.comando_pedacos + [ultimo_pedaco])
        ouvinte.comando = None
        ouvinte.comando_pedacos = None
        if service.escolheu_musica(texto):
            # "NAT20, por favor" → 👂 → "música": era pedido de música, não rolagem.
            print(f"[echo] {chave}: comando {texto!r} -> música", flush=True)
            self._abrir_musica(ouvinte)
            return
        rolagem = service.normalizar_comando_dado(texto)
        print(f"[echo] {chave}: comando {texto!r} -> {rolagem!r}", flush=True)
        if rolagem:
            self._contar("rolagens")
            # Só a rolagem, sem nome: é esse texto que o Dice vai ler.
            self._responder_aviso(ouvinte, f"{MARCADOR_VOZ} {rolagem}")
        elif texto and texto != "[unk]":
            self._responder_aviso(ouvinte, f"👂 não entendi a rolagem (ouvi: \"{texto}\").")
        else:
            self._responder_aviso(ouvinte, "👂 não ouvi nenhuma rolagem.")

    def _abrir_musica(self, ouvinte: _Ouvinte):
        """Começa a gravar o pedido de música. Chamar com _ouvintes_lock (qualquer thread)."""
        ouvinte.musica_pcm = bytearray()
        ouvinte.musica_aberto_em = time.monotonic()
        ouvinte.musica_ultimo_audio = 0.0
        self._contar("pedidos_musica")
        ouvinte.aviso = self._enviar(ouvinte.canal_texto, f"🎵 fala a música, {ouvinte.nome}!")
        # Carrega o Whisper enquanto a pessoa fala: a primeira carga leva segundos.
        asyncio.run_coroutine_threadsafe(asyncio.to_thread(service._carregar_modelo), self.bot.loop)

    # --- Escriba (ata da sessão: grava tudo, transcreve no fim) ---------------

    def _gravar_para_escriba(self, chave, user, pcm_48k: bytes):
        """
        Grava o áudio cru de uma pessoa pra Escriba, num .wav por pessoa (16kHz
        mono). Sem transcrever nada agora — só grava. Chamar de qualquer thread.

        O Discord só manda pacote enquanto a pessoa fala, então o .wav é fala
        colada com fala: a cada volta depois de uma pausa, guarda uma marca
        [posição no arquivo, horário real] pra ata sair com o horário certo
        (service.horario_real).
        """
        pcm_16k = service.resample_para_16k_mono(pcm_48k, SAMPLE_RATE, CANAIS)
        if not pcm_16k:
            return
        agora = time.monotonic()
        with self._ouvintes_lock:
            if not self._escriba_ativa:
                return  # desligou entre o check no _on_audio e aqui
            aberto = self._escriba_arquivos.get(chave)
            if aberto is None:
                nome = user.display_name if user is not None else "alguém"
                sufixo = str(chave) if isinstance(chave, int) else f"ssrc{chave[1]}"
                arquivo = f"{service.nome_arquivo_seguro(nome)}-{sufixo}.wav"
                writer = wave.open(str(self._escriba_pasta / arquivo), "wb")
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(service.TAXA_VOSK)
                aberto = self._escriba_arquivos[chave] = (writer, arquivo)
                self._escriba_nomes[arquivo] = nome
                self._escriba_marcas[arquivo] = []
            writer, arquivo = aberto
            ultimo = self._escriba_ultimo.get(chave)
            if ultimo is None or agora - ultimo > ESCRIBA_PAUSA_MARCA_SEGUNDO:
                self._escriba_marcas[arquivo].append([writer.getnframes() / service.TAXA_VOSK, time.time()])
            self._escriba_ultimo[chave] = agora
            writer.writeframes(pcm_16k)

    def _fechar_gravacao_escriba(self) -> tuple[Path | None, bool]:
        """
        Desliga a gravação: fecha os .wav e escreve nomes.json e marcas.json na
        pasta (o suficiente pra transcrever depois, até à mão). Devolve (pasta,
        se tinha algum áudio).
        """
        with self._ouvintes_lock:
            self._escriba_ativa = False
            arquivos = dict(self._escriba_arquivos)
            nomes, marcas = dict(self._escriba_nomes), dict(self._escriba_marcas)
            self._escriba_arquivos.clear()
            self._escriba_nomes.clear()
            self._escriba_marcas.clear()
            self._escriba_ultimo.clear()
        for writer, _ in arquivos.values():
            writer.close()
        pasta = self._escriba_pasta
        if arquivos and pasta is not None:
            (pasta / "nomes.json").write_text(json.dumps(nomes, ensure_ascii=False, indent=1), encoding="utf-8")
            (pasta / "marcas.json").write_text(json.dumps(marcas), encoding="utf-8")
        return pasta, bool(arquivos)

    async def _iniciar_escriba(self, canal_texto: discord.abc.Messageable):
        guild = getattr(canal_texto, "guild", None)
        voice_client = guild.voice_client if guild else None
        if voice_client is None or not isinstance(voice_client, voice_recv.VoiceRecvClient):
            await canal_texto.send('Preciso estar ouvindo a call primeiro — manda "@Natty escuta".')
            return
        if self._escriba_ativa:
            await canal_texto.send("📝 Já estou gravando pra transcrever depois.")
            return
        pasta = PASTA_SESSOES / time.strftime(service.FORMATO_PASTA_SESSAO)
        pasta.mkdir(parents=True, exist_ok=True)
        with self._ouvintes_lock:
            self._escriba_pasta = pasta
            self._escriba_inicio = time.time()
            self._escriba_arquivos.clear()
            self._escriba_nomes.clear()
            self._escriba_marcas.clear()
            self._escriba_ultimo.clear()
            self._escriba_ativa = True
        print(f"[echo] Escriba: gravando em {pasta}", flush=True)
        await canal_texto.send(
            "🔴 Gravando a sessão — **todo mundo na call**. Pra parar: `@Natty, para de gravar`."
        )

    async def _parar_escriba(self, canal_texto: discord.abc.Messageable):
        """Para de gravar e PERGUNTA se transcreve agora (não transcreve sozinha)."""
        if not self._escriba_ativa:
            await canal_texto.send("🛑 Não estava gravando.")
            return
        minutos = max(1, round((time.time() - self._escriba_inicio) / 60))
        pasta, teve_audio = self._fechar_gravacao_escriba()
        if not teve_audio:
            await canal_texto.send(f"🛑 Gravação encerrada ({minutos} min) — ninguém falou nada, não tem o que transcrever.")
            return
        guild = getattr(canal_texto, "guild", None)
        if guild is not None:
            self.sessao_pendente_transcricao[guild.id] = (pasta, time.time())
        print(f"[echo] Escriba: parei de gravar ({pasta}), perguntando se transcreve", flush=True)
        await canal_texto.send(
            f"🛑 Gravação encerrada ({minutos} min). Quer que eu transcreva agora? "
            "`@Natty, sim` ou `@Natty, depois`."
        )

    async def _responder_confirmacao_escriba(self, message: discord.Message, conteudo: str) -> bool:
        """
        Se há "quer que eu transcreva agora?" aberto nesta guild, trata "sim"
        (dispara a transcrição) ou "depois/não" (só limpa). True se tratou a
        mensagem. Pergunta com mais de 15 min some calada. Qualquer outra
        coisa ("@Natty escuta") não mexe na pergunta e segue o fluxo normal.
        """
        guild = message.guild
        pendente = self.sessao_pendente_transcricao.get(guild.id) if guild else None
        if pendente is None:
            return False
        pasta, perguntou_em = pendente
        if time.time() - perguntou_em > ESCRIBA_CONFIRMACAO_SEGUNDO:
            del self.sessao_pendente_transcricao[guild.id]
            return False
        if _RECUSA_RE.search(conteudo):
            del self.sessao_pendente_transcricao[guild.id]
            await message.channel.send(
                "Ok, fica gravado. Quando quiser, chama `@Natty, transcreve a sessão`."
            )
            return True
        if _CONFIRMA_RE.search(conteudo):
            del self.sessao_pendente_transcricao[guild.id]
            await self._comecar_transcricao(message.channel, pasta)
            return True
        return False

    async def _transcrever_ultima_sessao(self, canal_texto: discord.abc.Messageable):
        """"@Natty, transcreve a sessão": a gravação mais recente que ainda não tem ata."""
        if self._escriba_ativa:
            await canal_texto.send("🔴 Ainda estou gravando — manda `@Natty, para de gravar` primeiro.")
            return
        pasta = service.sessao_esperando_transcricao(PASTA_SESSOES, ignorar=self._escriba_transcrevendo)
        if pasta is None:
            await canal_texto.send("Não achei nenhuma sessão gravada esperando transcrição.")
            return
        guild = getattr(canal_texto, "guild", None)
        if guild is not None:
            self.sessao_pendente_transcricao.pop(guild.id, None)
        await self._comecar_transcricao(canal_texto, pasta)

    async def _comecar_transcricao(self, canal_texto: discord.abc.Messageable, pasta: Path):
        if pasta in self._escriba_transcrevendo:
            await canal_texto.send("📝 Essa sessão já está sendo transcrita (ou na fila).")
            return
        tem_outra = bool(self._escriba_transcrevendo)  # a trava só é pega quando a tarefa roda
        self._escriba_transcrevendo.add(pasta)
        if tem_outra:
            print(f"[echo] Escriba: na fila {pasta}", flush=True)
            await canal_texto.send("📝 Na fila: termino a transcrição que está rodando e já começo esta.")
        else:
            await canal_texto.send("📝 Transcrevendo (pode levar alguns minutos)...")
        asyncio.create_task(self._processar_escriba(canal_texto, pasta, service.inicio_da_pasta(pasta)))

    async def _processar_escriba(self, canal_texto: discord.abc.Messageable, pasta: Path, inicio: float):
        try:
            async with self._escriba_fila:
                await self._transcrever_escriba(canal_texto, pasta, inicio)
        finally:
            self._escriba_transcrevendo.discard(pasta)

    async def _transcrever_escriba(self, canal_texto: discord.abc.Messageable, pasta: Path, inicio: float):
        print(f"[echo] Escriba: transcrevendo {pasta}", flush=True)
        t = time.monotonic()

        def progresso(porcento, feito_s, total_s):
            # roda na thread da transcrição; print é seguro
            passou = time.monotonic() - t
            falta = passou / feito_s * (total_s - feito_s) if feito_s else 0
            print(
                f"[echo] Escriba: {pasta.name} {porcento}% "
                f"({feito_s / 60:.0f} de {total_s / 60:.0f} min de fala, "
                f"{passou / 60:.0f} min rodando, ~{falta / 60:.0f} min pra acabar)",
                flush=True,
            )

        try:
            caminho_ata = await asyncio.to_thread(service.transcrever_sessao, pasta, inicio, progresso)
        except Exception:
            print("[echo] erro transcrevendo a Escriba:", flush=True)
            traceback.print_exc()
            await canal_texto.send(
                f"📝 Deu erro transcrevendo — os áudios continuam em `{pasta}`, dá pra tentar de novo à mão."
            )
            return
        print(f"[echo] Escriba: transcrição de {pasta.name} levou {time.monotonic() - t:.0f}s -> {caminho_ata}", flush=True)
        if caminho_ata is None:
            await canal_texto.send("📝 Não consegui transcrever nada (sem fala nos áudios?).")
            return
        await canal_texto.send(f"📝 Pronto! Ata salva em `{caminho_ata}`.")

    async def _pedir_musica(self, chave, ouvinte: _Ouvinte, pcm: bytes, falou: bool):
        """
        Transcreve o pedido gravado com Whisper e posta "🎙️ natty toca <pedido>"
        — o on_message do Bardo reage como se alguém tivesse digitado (ele
        aceita mensagem da Natty que comece com 🎙). O Echo não importa o Bardo.
        """
        if not falou or not pcm:
            self._responder_aviso(ouvinte, "🎵 não ouvi nenhum pedido de música.")
            return
        inicio = time.monotonic()
        try:
            async with self._whisper_lock:
                # Bloqueante (segundos de CPU): numa thread, senão trava o bot inteiro.
                # dica=None: a dica da senha ("NAT20, por favor.") atrapalharia o nome da música.
                resultado = await asyncio.to_thread(service.transcrever_pcm, pcm, SAMPLE_RATE, CANAIS, idioma=None, dica=None)
        except Exception:
            print("[echo] erro ao transcrever pedido de música:", flush=True)
            traceback.print_exc()
            self._responder_aviso(ouvinte, "🎵 não entendi o pedido de música.")
            return
        busca = service.limpar_pedido_de_musica(resultado.texto)
        print(
            f"[echo] {chave}: música {len(pcm) / (SAMPLE_RATE * CANAIS * 2):.1f}s, transcrita em "
            f"{time.monotonic() - inicio:.1f}s: {resultado.texto!r} -> {busca!r}",
            flush=True,
        )
        if busca is None:
            self._responder_aviso(ouvinte, "🎵 não entendi o pedido de música.")
            return
        self._contar("musicas")
        self._responder_aviso(ouvinte, f"{MARCADOR_VOZ} natty toca {busca}")

    async def _vigiar(self):
        """
        A cada 0.2s: fecha a frase da senha quando a pessoa para de falar,
        fecha modos comando que acabaram (parou de falar, ou a janela passou
        sem fala) e imprime o diagnóstico. Precisa existir porque, quando
        ninguém fala, o Discord para de mandar pacotes — e sem pacote nem o
        Vosk percebe a pausa, nem o _on_audio roda pra ver que o tempo acabou.
        """
        while True:
            await asyncio.sleep(INTERVALO_VIGIA_SEGUNDO)
            try:
                agora = time.monotonic()
                with self._ouvintes_lock:
                    for chave, o in list(self._ouvintes.items()):
                        if o.musica_pcm is not None:
                            aberto_ha = agora - o.musica_aberto_em
                            if o.musica_ultimo_audio:
                                acabou = (agora - o.musica_ultimo_audio > SILENCIO_FIM_MUSICA_SEGUNDO
                                          or aberto_ha > MUSICA_MAXIMO_SEGUNDO)
                            else:
                                acabou = aberto_ha > JANELA_MUSICA_SEGUNDO
                            if acabou:
                                pcm, o.musica_pcm = bytes(o.musica_pcm), None
                                asyncio.create_task(self._pedir_musica(chave, o, pcm, bool(o.musica_ultimo_audio)))
                            continue
                        if o.comando is None:
                            # Frase da senha aberta e a pessoa parou de falar: fecha já.
                            if o.senha_ultimo_audio and agora - o.senha_ultimo_audio > SILENCIO_FIM_SENHA_SEGUNDO:
                                self._fechar_frase_senha(chave, o, service.finalizar_vosk(o.senha))
                            continue
                        aberto_ha = agora - o.comando_aberto_em
                        if o.comando_ultimo_audio:
                            acabou = (agora - o.comando_ultimo_audio > SILENCIO_FIM_COMANDO_SEGUNDO
                                      or aberto_ha > COMANDO_MAXIMO_SEGUNDO)
                        else:
                            acabou = aberto_ha > JANELA_COMANDO_SEGUNDO
                        if acabou:
                            self._fechar_comando(chave, o, service.finalizar_vosk(o.comando))
                self._imprimir_diagnostico(agora)
            except Exception:
                print("[echo] erro na vigia:", flush=True)
                traceback.print_exc()

    def _imprimir_diagnostico(self, agora: float):
        if agora - self._ultimo_diag < INTERVALO_DIAGNOSTICO_SEGUNDO:
            return
        self._ultimo_diag = agora
        with self._diag_lock:
            cog = dict(self._diag)
            self._diag.clear()
        stats_dave = dave.estatisticas()
        if cog or stats_dave:
            print(f"[echo] diagnóstico 5s: sink={cog} dave={stats_dave}", flush=True)


async def setup(bot: commands.Bot):
    dave.aplicar()  # sem isso o áudio recebido chega cifrado (ver dave.py)
    await bot.add_cog(EchoCog(bot))
