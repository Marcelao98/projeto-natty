"""
Testes do fluxo da senha no cog do Echo (sem Discord, sem Vosk): o que acontece
depois que o Vosk fecha uma frase do modo senha.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from modules.echo import cog


def _bardo_acha_que_e_pra_natty(natty, texto, autor=None):
    """O que o on_message do Bardo decide: a mensagem é dirigida à Natty?"""
    from modules.bardo.cog import BardoCog

    mensagem = SimpleNamespace(author=autor or natty, content=texto, mentions=[], role_mentions=[],
                               guild=SimpleNamespace(self_role=None))
    return BardoCog(bot=SimpleNamespace(user=natty))._falou_com_a_natty(mensagem)


class TestFluxoDaSenha(unittest.TestCase):
    def setUp(self):
        self.c = cog.EchoCog(bot=SimpleNamespace(loop=None))
        self.ouvinte = cog._Ouvinte(senha=None, nome="Mestre", canal_texto=SimpleNamespace(guild=None))
        self.abrir = mock.patch.object(self.c, "_abrir_comando").start()
        self.sair = mock.patch.object(self.c, "_sair_por_voz", new=mock.MagicMock(return_value="corrotina")).start()
        self.agendar = mock.patch.object(cog.asyncio, "run_coroutine_threadsafe").start()
        self.addCleanup(mock.patch.stopall)

    def ouvir(self, texto):
        self.c._fechar_frase_senha(42, self.ouvinte, texto)

    def test_senha_e_saia_sai_sem_abrir_a_rolagem(self):
        self.ouvir("nate vinte por favor saia")
        self.sair.assert_called_once_with(self.ouvinte.canal_texto)
        self.agendar.assert_called_once()  # roda no loop do bot
        self.abrir.assert_not_called()

    def test_senha_sozinha_abre_a_rolagem(self):
        self.ouvir("nate vinte por favor")
        self.abrir.assert_called_once_with(self.ouvinte)
        self.sair.assert_not_called()

    def test_senha_e_rolo_abre_a_rolagem(self):
        self.ouvir("nate vinte por favor rolo")
        self.abrir.assert_called_once_with(self.ouvinte)
        self.sair.assert_not_called()

    def test_senha_e_pare_manda_o_bardo_parar_e_continua_na_call(self):
        enviar = mock.patch.object(self.c, "_enviar").start()
        self.ouvir("nate vinte por favor pare")
        enviar.assert_called_once_with(self.ouvinte.canal_texto, f"{cog.MARCADOR_VOZ} natty para")
        self.sair.assert_not_called()  # não sai da call
        self.abrir.assert_not_called()  # nem abre janela de rolagem

    def test_senha_e_controle_do_bardo_posta_o_comando_e_continua_na_call(self):
        enviar = mock.patch.object(self.c, "_enviar").start()
        for falado, comando in [("próxima", "pula"), ("repete", "repete"), ("para de repetir", "para de repetir")]:
            with self.subTest(falado=falado):
                enviar.reset_mock()
                self.ouvir(f"nate vinte por favor {falado}")
                enviar.assert_called_once_with(self.ouvinte.canal_texto, f"{cog.MARCADOR_VOZ} natty {comando}")
        self.sair.assert_not_called()
        self.abrir.assert_not_called()

    def test_pare_chega_no_bardo_como_parar(self):
        # Ponta a ponta com o Bardo de verdade: o texto postado vira Pedido("parar").
        from modules.bardo import service as bardo
        from modules.bardo.cog import _deve_ignorar

        natty = SimpleNamespace(id=1, bot=True)
        texto = f"{cog.MARCADOR_VOZ} natty para"
        self.assertFalse(_deve_ignorar(SimpleNamespace(author=natty, content=texto), natty))
        self.assertTrue(_bardo_acha_que_e_pra_natty(natty, texto))  # sem @: o 🎙 basta
        self.assertEqual(bardo.interpretar_pedido(texto).acao, "parar")

    def test_saia_sem_senha_nao_faz_nada(self):
        for texto in ["saia", "sai", "[unk]", ""]:
            with self.subTest(texto=texto):
                self.ouvir(texto)
        self.abrir.assert_not_called()
        self.sair.assert_not_called()


class TestSoODonoDaSessao(unittest.TestCase):
    """Só a voz de quem mandou "@Natty escuta" é processada; a dos outros é descartada antes do Vosk."""

    def setUp(self):
        self.c = cog.EchoCog(bot=SimpleNamespace(loop=None))
        self.criar = mock.patch.object(cog.service, "_criar_reconhecedor_vosk").start()
        self.processar = mock.patch.object(cog.service, "processar_chunk_vosk", return_value=None).start()
        self.addCleanup(mock.patch.stopall)

    def falar(self, user, ssrc=7):
        dado = SimpleNamespace(pcm=b"\x10\x00" * 1920, packet=SimpleNamespace(ssrc=ssrc))
        self.c._on_audio(user, dado, mock.MagicMock(), 42)

    def test_voz_do_dono_e_processada(self):
        self.falar(SimpleNamespace(id=42, bot=False, display_name="Marcelo"))
        self.assertIn(42, self.c._ouvintes)
        self.processar.assert_called_once()

    def test_voz_de_outra_pessoa_e_descartada(self):
        self.falar(SimpleNamespace(id=99, bot=False, display_name="Outro"))
        self.assertEqual(self.c._ouvintes, {})
        self.criar.assert_not_called()
        self.processar.assert_not_called()
        self.assertEqual(self.c._diag["outros"], 1)

    def test_audio_sem_dono_conhecido_e_descartado(self):
        self.falar(None)
        self.assertEqual(self.c._ouvintes, {})
        self.processar.assert_not_called()

    def test_sem_dono_definido_ouve_todo_mundo(self):
        # Compatibilidade: _on_audio sem dono (ex: testes antigos) não filtra.
        dado = SimpleNamespace(pcm=b"\x10\x00" * 1920, packet=SimpleNamespace(ssrc=7))
        self.c._on_audio(SimpleNamespace(id=99, bot=False, display_name="Outro"), dado, mock.MagicMock())
        self.assertIn(99, self.c._ouvintes)


class TestEscriba(unittest.TestCase):
    """Grava um .wav por pessoa (todo mundo), para, PERGUNTA se transcreve, e só transcreve com "sim"."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        self.c = cog.EchoCog(bot=SimpleNamespace(loop=None, user=SimpleNamespace(id=1)))
        self.pasta = Path(tempfile.mkdtemp())
        mock.patch.object(cog, "PASTA_SESSOES", self.pasta).start()
        mock.patch.object(cog.service, "_criar_reconhecedor_vosk").start()
        mock.patch.object(cog.service, "processar_chunk_vosk", return_value=None).start()
        self.processar = mock.patch.object(self.c, "_processar_escriba", new=mock.AsyncMock()).start()
        self.canal = mock.MagicMock()
        self.canal.send = mock.AsyncMock()
        self.canal.guild.id = 10
        self.canal.guild.voice_client = mock.MagicMock(spec=cog.voice_recv.VoiceRecvClient)
        self.addCleanup(mock.patch.stopall)

    def falar(self, user_id, nome, pacotes=10):
        user = SimpleNamespace(id=user_id, bot=False, display_name=nome)
        for _ in range(pacotes):
            self.c._on_audio(user, SimpleNamespace(pcm=b"\x10\x00" * 1920, packet=SimpleNamespace(ssrc=user_id)),
                             self.canal, 42)

    def mandar(self, texto):
        """Mensagem com @Natty de verdade, no canal de teste."""
        msg = SimpleNamespace(author=SimpleNamespace(bot=False), mentions=[self.c.bot.user], role_mentions=[],
                              guild=self.canal.guild, content=texto, channel=self.canal)
        self.canal.guild.self_role = None
        cog.asyncio.run(self.c.on_message(msg))

    def ultima_resposta(self):
        return self.canal.send.call_args.args[0]

    def gravar_e_parar(self):
        async def cenario():
            await self.c._iniciar_escriba(self.canal)
            self.falar(42, "Mestre")
            await self.c._parar_escriba(self.canal)
        cog.asyncio.run(cenario())

    def test_gatilhos_de_texto(self):
        iniciar = mock.patch.object(self.c, "_iniciar_escriba", new=mock.AsyncMock()).start()
        parar = mock.patch.object(self.c, "_parar_escriba", new=mock.AsyncMock()).start()
        avulso = mock.patch.object(self.c, "_transcrever_ultima_sessao", new=mock.AsyncMock()).start()
        for texto in ["@Natty, grava a sessão", "@Natty grava", "@Natty começa a gravar"]:
            self.mandar(texto)
        for texto in ["@Natty, para de gravar", "@Natty pare a gravação", "@Natty parar gravação"]:
            self.mandar(texto)
        self.mandar("@Natty, transcreve a sessão")
        self.assertEqual(iniciar.await_count, 3)
        self.assertEqual(parar.await_count, 3)  # "para de gravar" ganha mesmo tendo "gravar" na frase
        self.assertEqual(avulso.await_count, 1)

    def test_grava_todo_mundo_com_marcas(self):
        async def cenario():
            await self.c._iniciar_escriba(self.canal)
            self.falar(42, "Mestre")            # o dono
            self.falar(7, "Ana Ñ")              # não é o dono: gravada mesmo assim
            self.c._escriba_ultimo[42] -= cog.ESCRIBA_PAUSA_MARCA_SEGUNDO + 1  # pausa
            self.falar(42, "Mestre")
            await self.c._parar_escriba(self.canal)

        cog.asyncio.run(cenario())
        import json
        sessao = next(self.pasta.iterdir())
        self.assertEqual(sorted(p.name for p in sessao.glob("*.wav")), ["ana-n-7.wav", "mestre-42.wav"])
        nomes = json.loads((sessao / "nomes.json").read_text(encoding="utf-8"))
        self.assertEqual(nomes, {"mestre-42.wav": "Mestre", "ana-n-7.wav": "Ana Ñ"})
        marcas = json.loads((sessao / "marcas.json").read_text(encoding="utf-8"))
        self.assertEqual([m[0] for m in marcas["mestre-42.wav"]], [0.0, 10 * 320 / 16000])
        import wave as _wave
        with _wave.open(str(sessao / "mestre-42.wav")) as w:
            self.assertEqual((w.getnchannels(), w.getframerate(), w.getnframes()), (1, 16000, 20 * 320))

    def test_parar_pergunta_e_nao_transcreve_sozinha(self):
        self.gravar_e_parar()
        self.processar.assert_not_awaited()
        self.assertIn(10, self.c.sessao_pendente_transcricao)
        self.assertIn("Gravação encerrada", self.ultima_resposta())
        self.assertIn("@Natty, sim", self.ultima_resposta())
        self.assertFalse(self.c._escriba_ativa)

    def test_sim_transcreve(self):
        self.gravar_e_parar()
        pasta = self.c.sessao_pendente_transcricao[10][0]
        self.mandar("@Natty, sim")
        self.processar.assert_awaited_once()
        self.assertEqual(self.processar.await_args.args[1], pasta)
        self.assertNotIn(10, self.c.sessao_pendente_transcricao)

    def test_depois_so_limpa(self):
        self.gravar_e_parar()
        self.mandar("@Natty, depois")
        self.processar.assert_not_awaited()
        self.assertNotIn(10, self.c.sessao_pendente_transcricao)
        self.assertIn("transcreve a sessão", self.ultima_resposta())

    def test_pergunta_vencida_nao_dispara_nada(self):
        self.gravar_e_parar()
        pasta, quando = self.c.sessao_pendente_transcricao[10]
        self.c.sessao_pendente_transcricao[10] = (pasta, quando - cog.ESCRIBA_CONFIRMACAO_SEGUNDO - 1)
        avulso = mock.patch.object(self.c, "_transcrever_ultima_sessao", new=mock.AsyncMock()).start()
        self.mandar("@Natty, sim")
        self.processar.assert_not_awaited()
        avulso.assert_not_awaited()  # "sim" sozinho não é nenhum outro comando
        self.assertNotIn(10, self.c.sessao_pendente_transcricao)

    def test_outro_comando_nao_mexe_na_pergunta(self):
        self.gravar_e_parar()
        mock.patch.object(cog.service, "_carregar_vosk").start()
        self.mandar("@Natty socorro voz")
        self.processar.assert_not_awaited()
        self.assertIn(10, self.c.sessao_pendente_transcricao)

    def test_transcreve_a_sessao_acha_a_ultima_sem_ata(self):
        self.gravar_e_parar()
        self.c.sessao_pendente_transcricao.clear()  # ex: disseram "depois"
        pasta = next(self.pasta.iterdir())
        self.mandar("@Natty, transcreve a sessão")
        self.processar.assert_awaited_once()
        self.assertEqual(self.processar.await_args.args[1], pasta)

    def test_mesma_sessao_nao_transcreve_duas_vezes(self):
        self.gravar_e_parar()
        pasta = self.c.sessao_pendente_transcricao.pop(10)[0]
        self.c._escriba_transcrevendo.add(pasta)  # já rodando
        self.mandar("@Natty, transcreve a sessão")
        self.processar.assert_not_awaited()
        self.assertIn("Não achei nenhuma sessão", self.ultima_resposta())

    def test_uma_transcricao_por_vez(self):
        """Duas pedidas juntas: a segunda espera a primeira acabar (não disputam a CPU)."""
        import threading as _threading

        mock.patch.object(self.c, "_processar_escriba", new=cog.EchoCog._processar_escriba.__get__(self.c)).start()
        rodando, maximo = [0], [0]
        trava = _threading.Lock()

        def transcrever_falso(pasta, inicio, progresso=None):
            with trava:
                rodando[0] += 1
                maximo[0] = max(maximo[0], rodando[0])
            cog.time.sleep(0.05)
            with trava:
                rodando[0] -= 1
            return None

        mock.patch.object(cog.service, "transcrever_sessao", side_effect=transcrever_falso).start()
        a, b = self.pasta / "a", self.pasta / "b"

        async def cenario():
            await self.c._comecar_transcricao(self.canal, a)
            await self.c._comecar_transcricao(self.canal, b)
            while self.c._escriba_transcrevendo:
                await cog.asyncio.sleep(0.01)

        cog.asyncio.run(cenario())
        self.assertEqual(maximo[0], 1)
        textos = [c.args[0] for c in self.canal.send.call_args_list]
        self.assertTrue(any("Na fila" in x for x in textos))

    def test_transcreve_a_sessao_sem_nada_gravado(self):
        self.mandar("@Natty, transcreve a sessão")
        self.processar.assert_not_awaited()
        self.assertIn("Não achei nenhuma sessão", self.ultima_resposta())

    def test_parar_sem_ninguem_falar_nao_pergunta(self):
        async def cenario():
            await self.c._iniciar_escriba(self.canal)
            await self.c._parar_escriba(self.canal)

        cog.asyncio.run(cenario())
        self.assertNotIn(10, self.c.sessao_pendente_transcricao)
        self.assertIn("ninguém falou", self.ultima_resposta())

    def test_sem_estar_na_call_nao_liga(self):
        self.canal.guild.voice_client = None
        cog.asyncio.run(self.c._iniciar_escriba(self.canal))
        self.assertFalse(self.c._escriba_ativa)
        self.assertIn("@Natty escuta", self.ultima_resposta())

    def test_sair_da_call_preserva_o_audio_sem_transcrever(self):
        guild = SimpleNamespace(id=1, voice_client=mock.MagicMock(spec=cog.voice_recv.VoiceRecvClient))
        guild.voice_client.disconnect = mock.AsyncMock()

        async def cenario():
            await self.c._iniciar_escriba(self.canal)
            self.falar(42, "Mestre")
            await self.c._desligar(guild)

        cog.asyncio.run(cenario())
        sessao = next(self.pasta.iterdir())
        for arquivo in ("mestre-42.wav", "nomes.json", "marcas.json"):
            self.assertTrue((sessao / arquivo).exists())  # dá pra "transcreve a sessão" depois
        self.processar.assert_not_awaited()
        self.assertFalse(self.c._escriba_ativa)


class TestFluxoDaMusica(unittest.TestCase):
    def setUp(self):
        self.c = cog.EchoCog(bot=SimpleNamespace(loop=None))
        self.ouvinte = cog._Ouvinte(senha=None, nome="Mestre", canal_texto=mock.MagicMock())
        self.agendar = mock.patch.object(cog.asyncio, "run_coroutine_threadsafe").start()
        self.addCleanup(mock.patch.stopall)

    def test_senha_e_musica_comeca_a_gravar(self):
        abrir = mock.patch.object(self.c, "_abrir_musica").start()
        comando = mock.patch.object(self.c, "_abrir_comando").start()
        self.c._fechar_frase_senha(42, self.ouvinte, "nate vinte por favor música")
        abrir.assert_called_once_with(self.ouvinte)
        comando.assert_not_called()

    def test_musica_na_janela_da_rolagem_troca_pra_gravar(self):
        abrir = mock.patch.object(self.c, "_abrir_musica").start()
        responder = mock.patch.object(self.c, "_responder_aviso").start()
        self.ouvinte.comando_pedacos = ["[unk] música"]
        self.c._fechar_comando(42, self.ouvinte, "")
        abrir.assert_called_once_with(self.ouvinte)
        responder.assert_not_called()  # nada de "não entendi a rolagem"

    def test_gravando_acumula_o_pcm_cru_e_nao_usa_o_vosk(self):
        mock.patch.object(cog.service, "_criar_reconhecedor_vosk").start()
        processar = mock.patch.object(cog.service, "processar_chunk_vosk").start()
        self.c._abrir_musica(self.ouvinte)
        self.c._ouvintes[42] = self.ouvinte
        usuario = SimpleNamespace(id=42, bot=False, display_name="Mestre")
        pacote = b"\x10\x00" * 1920  # 20ms, 48kHz estéreo
        for _ in range(3):
            self.c._on_audio(usuario, SimpleNamespace(pcm=pacote, packet=SimpleNamespace(ssrc=7)), None)
        self.assertEqual(bytes(self.ouvinte.musica_pcm), pacote * 3)
        processar.assert_not_called()

    def _pedir(self, texto_do_whisper, falou=True, pcm=b"\x00\x00" * 4800):
        responder = mock.patch.object(self.c, "_responder_aviso").start()
        transcrever = mock.patch.object(
            cog.service, "transcrever_pcm", return_value=SimpleNamespace(texto=texto_do_whisper)
        ).start()
        cog.asyncio.run(self.c._pedir_musica(42, self.ouvinte, pcm, falou))
        return responder, transcrever

    def test_pedido_transcrito_vira_natty_toca(self):
        responder, transcrever = self._pedir("Toca Song of Storms.")
        responder.assert_called_once_with(self.ouvinte, f"{cog.MARCADOR_VOZ} natty toca Song of Storms")
        # PCM cru do Discord, sem a dica da senha.
        args, kwargs = transcrever.call_args
        self.assertEqual(args[1:], (cog.SAMPLE_RATE, cog.CANAIS))
        self.assertIsNone(kwargs["dica"])

    def test_whisper_vazio_responde_que_nao_entendeu(self):
        responder, _ = self._pedir("")
        responder.assert_called_once_with(self.ouvinte, "🎵 não entendi o pedido de música.")

    def test_sem_fala_nem_chama_o_whisper(self):
        responder, transcrever = self._pedir("qualquer coisa", falou=False)
        transcrever.assert_not_called()
        responder.assert_called_once_with(self.ouvinte, "🎵 não ouvi nenhum pedido de música.")


if __name__ == "__main__":
    unittest.main()
