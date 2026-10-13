"""
Testes do cog do Bardo que não dependem do Discord de verdade: parar e pular
só param a MÚSICA — não saem da call nem derrubam a escuta do Echo; remover,
repetir a fila, playlist, erros com motivo e sair da call vazia.
"""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from modules.bardo import cog, motor


class ConexaoComum:
    """discord.VoiceClient: stop() já é só a música."""

    def __init__(self, tocando=True):
        self.tocando = tocando
        self.stop = mock.MagicMock()
        self.disconnect = mock.AsyncMock()

    def is_playing(self):
        return self.tocando

    def is_paused(self):
        return False


class ConexaoDoEcho(ConexaoComum):
    """VoiceRecvClient: stop() para música E escuta; stop_playing() só a música."""

    def __init__(self, tocando=True):
        super().__init__(tocando)
        self.stop_playing = mock.MagicMock()


class FonteFalsa:
    """FFmpegPCMAudio de mentira: `quadros` quadros de um tom constante e depois fim."""

    def __init__(self, quadros=3, valor=1000):
        self.restantes, self.valor = quadros, valor
        self.limpa = False

    def read(self):
        if self.restantes <= 0:
            return b""
        self.restantes -= 1
        return self.valor.to_bytes(2, "little", signed=True) * (960 * 2)

    def cleanup(self):
        self.limpa = True


def com_musica(c, guild):
    """Põe uma música no mixer do servidor (sem tocar de verdade)."""
    c._mixer(guild).tocar_musica(FonteFalsa(quadros=10_000))


class TestPararNaoSaiDaCall(unittest.TestCase):
    """Parar e pular param só a CAMADA DE MÚSICA do mixer: o player segue (e a escuta do Echo, que divide a conexão)."""

    def setUp(self):
        self.c = cog.BardoCog(bot=SimpleNamespace(user=None))

    def parar(self, conexao):
        guild = SimpleNamespace(id=1, voice_client=conexao)
        com_musica(self.c, guild)
        return asyncio.run(self.c._parar(guild))

    def test_parar_nao_desconecta_nem_para_o_player(self):
        for conexao in (ConexaoComum(), ConexaoDoEcho()):
            with self.subTest(conexao=type(conexao).__name__):
                self.assertEqual(self.parar(conexao), "Parei ⏹️")
                conexao.stop.assert_not_called()  # no Echo, stop() mataria a escuta da senha
                conexao.disconnect.assert_not_called()
                self.assertIsNone(self.c._mixer(SimpleNamespace(id=1)).musica)

    def test_parar_limpa_a_fila(self):
        fila = self.c._fila(SimpleNamespace(id=1))
        with mock.patch.object(fila, "resetar") as resetar:
            self.parar(ConexaoComum())
        resetar.assert_called_once()

    def test_pular_para_so_a_musica(self):
        conexao = ConexaoDoEcho()
        guild = SimpleNamespace(id=1, voice_client=conexao)
        com_musica(self.c, guild)
        self.assertIn("Pulei", self.c._pular(guild))
        conexao.stop_playing.assert_not_called()
        conexao.stop.assert_not_called()
        self.assertIsNone(self.c._mixer(guild).musica)

    def test_sem_musica_nao_pula(self):
        self.assertEqual(self.c._pular(SimpleNamespace(id=1, voice_client=ConexaoComum())), "Não tem nada tocando.")

    def test_pausar_e_continuar_so_a_musica(self):
        guild = SimpleNamespace(id=1, voice_client=ConexaoComum())
        self.assertEqual(self.c._pausar(guild), "Não tem nada tocando.")
        com_musica(self.c, guild)
        self.assertEqual(self.c._pausar(guild), "Pausei ⏸️")
        self.assertEqual(self.c._mixer(guild).musica, "pausada")
        self.assertEqual(self.c._pausar(guild), "Não tem nada tocando.")
        self.assertEqual(self.c._continuar(guild), "Continuando ▶️")
        self.assertEqual(self.c._continuar(guild), "Não tem nada pausado.")


class TestSoMencaoDeVerdade(unittest.TestCase):
    """Só @Natty (ou o cargo) chama a Natty; "natty" escrito não. Exceção: o 🎙 que ela mesma posta."""

    def setUp(self):
        self.natty = SimpleNamespace(id=1)
        self.c = cog.BardoCog(bot=SimpleNamespace(user=self.natty))
        self.cargo = SimpleNamespace(id=99)

    def falou(self, texto, mentions=(), role_mentions=(), autor_id=5):
        msg = SimpleNamespace(author=SimpleNamespace(id=autor_id), content=texto, mentions=list(mentions),
                              role_mentions=list(role_mentions), guild=SimpleNamespace(self_role=self.cargo))
        return self.c._falou_com_a_natty(msg)

    def test_mencao_e_cargo_valem(self):
        self.assertTrue(self.falou("<@1> toca Garçom", mentions=[self.natty]))
        self.assertTrue(self.falou("<@&99> pula", role_mentions=[self.cargo]))

    def test_nome_escrito_nao_vale_mais(self):
        for texto in ["natty toca Garçom", "Natty, pausa", "ei natty para"]:
            with self.subTest(texto=texto):
                self.assertFalse(self.falou(texto))

    def test_pedido_falado_da_propria_natty_vale(self):
        self.assertTrue(self.falou("🎙️ natty toca Garçom", autor_id=1))
        self.assertFalse(self.falou("🎙️ natty toca Garçom", autor_id=5))  # 🎙 de outra pessoa não


class TestRepetir(unittest.TestCase):
    """O que o cog faz com o repetir: responder o estado, repetir no fim da faixa, desligar ao pular."""

    def setUp(self):
        self.c = cog.BardoCog(bot=SimpleNamespace(user=None))
        self.guild = SimpleNamespace(id=1, voice_client=ConexaoComum())
        self.guild.voice_client.is_connected = lambda: True
        self.fila = self.c._fila(self.guild)
        self.musica = cog.service.Musica("Garçom", "https://youtu.be/a")
        self.fila.adicionar(self.musica)
        self.fila.avancar()

    def test_liga_e_diz_que_ligou(self):
        resposta = self.c._repetir(self.guild, cog.service.Pedido("repetir"))
        self.assertIn("🔁 Repetindo **Garçom**", resposta)
        self.assertTrue(self.fila.repetir)

    def test_desliga_e_diz_que_desligou(self):
        self.fila.repetir = True
        resposta = self.c._repetir(self.guild, cog.service.Pedido("repetir", repetir=False))
        self.assertIn("Repetição desligada", resposta)
        self.assertFalse(self.fila.repetir)

    def test_sem_nada_tocando_nao_liga(self):
        self.fila.resetar()
        self.assertEqual(self.c._repetir(self.guild, cog.service.Pedido("repetir")), "Não tem nada tocando pra repetir.")
        self.assertFalse(self.fila.repetir)

    def _fim_da_faixa(self, interrompida):
        repetir = mock.patch.object(self.c, "_repetir_musica", new=mock.AsyncMock()).start()
        proxima = mock.patch.object(self.c, "_tocar_proxima", new=mock.AsyncMock()).start()
        self.addCleanup(mock.patch.stopall)
        asyncio.run(self.c._depois_de_tocar(self.guild, self.musica, 0, False, interrompida))
        return repetir, proxima

    def test_ligado_e_acabou_sozinha_toca_a_mesma_de_novo(self):
        self.fila.repetir = True
        repetir, proxima = self._fim_da_faixa(interrompida=False)
        repetir.assert_awaited_once_with(self.guild, self.musica)
        proxima.assert_not_awaited()

    def test_ligado_mas_interrompida_segue_a_fila(self):
        self.fila.repetir = True
        repetir, proxima = self._fim_da_faixa(interrompida=True)
        repetir.assert_not_awaited()
        proxima.assert_awaited_once()

    def test_desligado_segue_a_fila(self):
        repetir, proxima = self._fim_da_faixa(interrompida=False)
        repetir.assert_not_awaited()
        proxima.assert_awaited_once()

    def test_repetir_resolve_url_nova_e_toca_a_mesma(self):
        mock.patch.object(cog.service, "resolver_musica", return_value={"stream_url": "x"}).start()
        tocar = mock.patch.object(self.c, "_tocar_stream").start()
        self.addCleanup(mock.patch.stopall)
        asyncio.run(self.c._repetir_musica(self.guild, self.musica))
        tocar.assert_called_once_with(self.guild, self.guild.voice_client, {"stream_url": "x"}, self.musica)

    def test_pular_desliga_o_repetir_e_avisa(self):
        com_musica(self.c, self.guild)
        self.fila.repetir = True
        self.fila.adicionar(cog.service.Musica("Hope", "https://youtu.be/b"))
        resposta = self.c._pular(self.guild)
        self.assertFalse(self.fila.repetir)
        self.assertIn("repetição desligada", resposta)

    def test_fila_mostra_que_esta_repetindo(self):
        self.fila.repetir = True
        self.assertIn("🔁", self.c._descrever_fila(self.guild))


class TestRemover(unittest.TestCase):
    def setUp(self):
        self.c = cog.BardoCog(bot=SimpleNamespace(user=None))
        self.guild = SimpleNamespace(id=1)
        self.fila = self.c._fila(self.guild)
        self.fila.tocando = cog.service.Musica("Atual", "https://youtu.be/0")
        self.fila.adicionar_varias([cog.service.Musica("Garçom", "https://youtu.be/a"),
                                    cog.service.Musica("Hope", "https://youtu.be/b")])

    def test_tira_e_diz_qual(self):
        self.assertEqual(self.c._remover(self.guild, 2), "Tirei **Hope** da fila 🗑️")
        self.assertEqual([m.titulo for m in self.fila.proximas], ["Garçom"])

    def test_posicao_que_nao_existe(self):
        self.assertIn("não existe a posição 5", self.c._remover(self.guild, 5))

    def test_sem_posicao_pergunta(self):
        self.assertIn("Qual delas?", self.c._remover(self.guild, None))

    def test_fila_vazia(self):
        self.fila.limpar()
        self.assertIn("vazia", self.c._remover(self.guild, 1))


class TestRepetirFila(unittest.TestCase):
    def setUp(self):
        self.c = cog.BardoCog(bot=SimpleNamespace(user=None))
        self.guild = SimpleNamespace(id=1, voice_client=None)
        self.fila = self.c._fila(self.guild)
        self.fila.tocando = cog.service.Musica("Garçom", "https://youtu.be/a")
        self.fila.adicionar(cog.service.Musica("Hope", "https://youtu.be/b"))

    def test_liga_e_diz_quantas(self):
        resposta = self.c._repetir(self.guild, cog.service.Pedido("repetir", alvo="fila"))
        self.assertIn("Repetindo a fila (2 músicas)", resposta)
        self.assertTrue(self.fila.repetir_fila)
        self.assertIn("repetindo a fila", self.c._descrever_fila(self.guild))

    def test_pular_nao_desliga_o_repetir_da_fila(self):
        self.fila.repetir_fila = True
        self.guild.voice_client = ConexaoComum()
        com_musica(self.c, self.guild)
        self.c._pular(self.guild)
        self.assertTrue(self.fila.repetir_fila)

    def test_slash_repetir(self):
        escolha = lambda valor: SimpleNamespace(value=valor)  # noqa: E731
        self.assertEqual(cog._pedido_de_repetir(None), cog.service.Pedido("repetir"))
        self.assertEqual(cog._pedido_de_repetir(escolha("faixa")), cog.service.Pedido("repetir"))
        self.assertEqual(cog._pedido_de_repetir(escolha("fila")), cog.service.Pedido("repetir", alvo="fila"))
        self.assertEqual(cog._pedido_de_repetir(escolha("desligar")), cog.service.Pedido("repetir", repetir=False))

    def test_falha_nao_volta_pro_fim_da_fila(self):
        """Vídeo que não toca não pode ficar rodando na fila em loop pra sempre."""
        self.fila.repetir_fila = True
        self.fila.tocando = None
        self.fila.limpar()
        self.fila.adicionar_varias([cog.service.Musica("Privado", "https://youtu.be/p"),
                                    cog.service.Musica("Hope", "https://youtu.be/b")])
        conexao = ConexaoComum()
        conexao.is_connected = lambda: True
        self.guild.voice_client = conexao

        def resolver(link):
            if link.endswith("/p"):
                raise cog.service.VideoPrivado("Private video")
            return {"stream_url": link}

        mock.patch.object(cog.service, "resolver_musica", side_effect=resolver).start()
        mock.patch.object(self.c, "_tocar_stream").start()
        avisar = mock.patch.object(self.c, "_avisar", new=mock.AsyncMock()).start()
        self.addCleanup(mock.patch.stopall)
        tocou = asyncio.run(self.c._tocar_proxima(self.guild))
        self.assertEqual(tocou.titulo, "Hope")
        self.assertEqual(self.fila.proximas, ())  # a privada não voltou pro fim
        avisar.assert_any_await(self.guild, "Não consegui tocar **Privado** (o vídeo é privado), pulei.")


class TestErrosComMotivo(unittest.TestCase):
    def setUp(self):
        self.c = cog.BardoCog(bot=SimpleNamespace(user=None))
        self.guild = SimpleNamespace(id=1, voice_client=None)
        self.membro = SimpleNamespace(voice=SimpleNamespace(channel=object()))
        self.addCleanup(mock.patch.stopall)

    def test_video_com_restricao_de_idade(self):
        mock.patch.object(cog.service, "resolver_musica",
                          side_effect=cog.service.RestricaoDeIdade("Sign in to confirm your age")).start()
        resposta = asyncio.run(self.c._tocar(self.guild, self.membro, None, "https://youtu.be/x"))
        self.assertEqual(resposta, "Não consigo tocar essa (o vídeo tem restrição de idade (precisa de login)).")

    def test_erro_desconhecido_continua_generico(self):
        mock.patch.object(cog.service, "resolver_musica", side_effect=RuntimeError("boom")).start()
        with self.assertLogs(motor.log, "ERROR"):
            resposta = asyncio.run(self.c._tocar(self.guild, self.membro, None, "https://youtu.be/x"))
        self.assertEqual(resposta, "Não consegui pegar essa música. Confere o link?")

    def test_busca_livre_sem_resultado_nao_gera_traceback(self):
        mock.patch.object(cog.service, "resolver_por_busca_livre",
                          side_effect=cog.service.NadaEncontrado("nada")).start()
        with self.assertNoLogs(motor.log, "WARNING"):
            resposta = asyncio.run(self.c._tocar_do_youtube(self.guild, self.membro, None, "kobold"))
        self.assertIn('Não achei nada pra "kobold"', resposta)


class TestPlaylist(unittest.TestCase):
    def setUp(self):
        self.c = cog.BardoCog(bot=SimpleNamespace(user=None))
        self.guild = SimpleNamespace(id=1, voice_client=None)
        self.membro = SimpleNamespace(voice=SimpleNamespace(channel=object()))
        self.addCleanup(mock.patch.stopall)

    def test_poe_a_playlist_na_fila_e_toca_a_primeira(self):
        musicas = [cog.service.Musica(f"Faixa {n}", f"https://youtu.be/{n}") for n in range(3)]
        mock.patch.object(cog.service, "listar_playlist", return_value=("Taverna", musicas)).start()
        enfileirar = mock.patch.object(self.c, "_enfileirar", new=mock.AsyncMock(return_value="Tocando **Faixa 0** 🎵")).start()
        resposta = asyncio.run(self.c._tocar(self.guild, self.membro, None,
                                             "https://www.youtube.com/playlist?list=PLx"))
        self.assertEqual(resposta, "📃 Playlist **Taverna**: Tocando **Faixa 0** 🎵")
        self.assertEqual(enfileirar.await_args.args[3], musicas)

    def test_playlist_privada(self):
        mock.patch.object(cog.service, "listar_playlist",
                          side_effect=cog.service.PlaylistIndisponivel("does not exist")).start()
        resposta = asyncio.run(self.c._tocar(self.guild, self.membro, None,
                                             "https://www.youtube.com/playlist?list=PLx"))
        self.assertEqual(resposta, "Não consegui abrir essa playlist (a playlist não existe ou é privada).")


class Pessoa(SimpleNamespace):
    def __init__(self, bot=False):
        super().__init__(bot=bot)


class TestSairDaCallVazia(unittest.TestCase):
    def setUp(self):
        self.c = cog.BardoCog(bot=SimpleNamespace(user=None))
        self.canal = SimpleNamespace(members=[Pessoa(bot=True)])  # só a Natty
        self.conexao = ConexaoComum()
        self.conexao.channel = self.canal
        self.guild = SimpleNamespace(id=1, voice_client=self.conexao)
        self.c._fila(self.guild).tocando = cog.service.Musica("Garçom", "https://youtu.be/a")

    def sair(self):
        return asyncio.run(self.c._sair_se_continuar_vazio(self.guild, espera=0))

    def test_sai_e_limpa_a_fila(self):
        self.assertTrue(self.sair())
        self.conexao.disconnect.assert_awaited_once()
        self.assertIsNone(self.c._fila(self.guild).tocando)

    def test_alguem_voltou_nao_sai(self):
        self.canal.members.append(Pessoa())
        self.assertFalse(self.sair())
        self.conexao.disconnect.assert_not_awaited()

    def test_com_o_echo_escutando_nao_sai(self):
        conexao = ConexaoDoEcho()
        conexao.channel = self.canal
        self.guild.voice_client = conexao
        self.assertFalse(self.sair())
        conexao.disconnect.assert_not_awaited()

    def test_listener_agenda_e_cancela(self):
        async def cenario():
            membro = SimpleNamespace(id=5, bot=False, guild=self.guild)
            fora = SimpleNamespace(channel=None)
            dentro = SimpleNamespace(channel=self.canal)
            await self.c.on_voice_state_update(membro, dentro, fora)  # a última pessoa saiu
            tarefa = self.c._saidas[1]
            self.canal.members.append(Pessoa())
            await self.c.on_voice_state_update(membro, fora, dentro)  # voltou
            await asyncio.sleep(0)
            return tarefa

        tarefa = asyncio.run(cenario())
        self.assertTrue(tarefa.done())
        self.assertNotIn(1, self.c._saidas)
        self.conexao.disconnect.assert_not_awaited()

    def test_listener_ignora_outro_canal(self):
        async def cenario():
            membro = SimpleNamespace(id=5, bot=False, guild=self.guild)
            outro = SimpleNamespace(channel=SimpleNamespace(members=[]))
            await self.c.on_voice_state_update(membro, outro, SimpleNamespace(channel=None))

        asyncio.run(cenario())
        self.assertNotIn(1, self.c._saidas)


class TestControleDoPainel(unittest.TestCase):
    """bot.controles["bardo"]: estado em JSON simples e eventos a cada mudança."""

    def setUp(self):
        self.bot = SimpleNamespace(user=None)
        self.c = cog.BardoCog(bot=self.bot)
        asyncio.run(self.c.cog_load())
        self.controle = self.bot.controles["bardo"]
        self.conexao = ConexaoComum()
        self.conexao.is_connected = lambda: True
        self.conexao.channel = SimpleNamespace(name="Taverna")
        self.conexao.source = None
        self.guild = SimpleNamespace(id=1, voice_client=self.conexao)

    def test_estado(self):
        fila = self.c._fila(self.guild)
        fila.tocando = cog.service.Musica("Garçom", "https://youtu.be/a", 90)
        fila.adicionar(cog.service.Musica("Hope", "https://youtu.be/b"))
        com_musica(self.c, self.guild)
        self.c._mixer(self.guild).pausar_musica(True)
        estado = self.controle.estado(self.guild)
        self.assertEqual(estado["tocando"], {"titulo": "Garçom", "link": "https://youtu.be/a", "duracao": 90})
        self.assertEqual([m["titulo"] for m in estado["proximas"]], ["Hope"])
        self.assertTrue(estado["conectado"] and estado["pausado"])
        self.assertEqual((estado["canal"], estado["volume"]), ("Taverna", 50))
        json.dumps(estado)  # vai pro painel como JSON

    def test_cada_mudanca_publica(self):
        recebidos = []
        self.controle.assinar(recebidos.append)
        self.c._mudar_volume(self.guild, cog.service.Pedido("volume", volume=30))
        self.c._fila(self.guild).adicionar(cog.service.Musica("Hope", "https://youtu.be/b"))
        self.c._limpar_fila(self.guild)
        asyncio.run(self.c._parar(self.guild))
        self.assertEqual(recebidos, [1, 1, 1])
        self.controle.cancelar(recebidos.append)
        self.c._mudar_volume(self.guild, cog.service.Pedido("volume", volume=40))
        self.assertEqual(len(recebidos), 3)

    def test_assinante_quebrado_nao_atrapalha(self):
        self.controle.assinar(lambda gid: 1 / 0)
        with self.assertLogs("modules.bardo.eventos", "ERROR"):
            self.assertIn("Volume em 30%", self.c._mudar_volume(self.guild, cog.service.Pedido("volume", volume=30)))

    def test_mestre(self):
        cargo = lambda nome: SimpleNamespace(name=nome)  # noqa: E731
        dono = SimpleNamespace(id=7, guild=SimpleNamespace(owner_id=7), roles=[])
        condutor = SimpleNamespace(id=8, guild=SimpleNamespace(owner_id=7), roles=[cargo("Condutor")])
        viajante = SimpleNamespace(id=9, guild=SimpleNamespace(owner_id=7), roles=[cargo("Viajante")])
        self.assertTrue(self.controle.pode_controlar(dono))
        self.assertTrue(self.controle.pode_controlar(condutor))
        self.assertFalse(self.controle.pode_controlar(viajante))


class TestComandosDoPainel(TestControleDoPainel):
    """ControleBardo.executar: mesmo caminho do Discord, com argumentos validados."""

    def setUp(self):
        super().setUp()
        self.mestre = SimpleNamespace(id=7, guild=SimpleNamespace(owner_id=7), roles=[], voice=None)
        self.c._fila(self.guild).tocando = cog.service.Musica("Garçom", "https://youtu.be/a")

    def executar(self, comando, args=None, membro=None):
        return asyncio.run(self.controle.executar(self.guild, membro or self.mestre, comando, args or {}))

    def test_sem_cargo_recusa(self):
        viajante = SimpleNamespace(id=9, guild=SimpleNamespace(owner_id=7), roles=[])
        self.assertFalse(self.executar("pular", membro=viajante)["ok"])

    def test_volume(self):
        self.assertTrue(self.executar("volume", {"nivel": 30})["ok"])
        self.assertEqual(self.c._volume(self.guild), 30)
        for ruim in (101, -1, "30", 2.5, True, None):
            with self.subTest(nivel=ruim):
                self.assertFalse(self.executar("volume", {"nivel": ruim})["ok"])

    def test_repetir_liga_explicito(self):
        self.assertTrue(self.executar("repetir", {"modo": "fila"})["ok"])
        self.assertTrue(self.c._fila(self.guild).repetir_fila)
        self.executar("repetir", {"modo": "fila"})  # ligar de novo continua ligado (não alterna)
        self.assertTrue(self.c._fila(self.guild).repetir_fila)
        self.executar("repetir", {"modo": "desligar"})
        self.assertFalse(self.c._fila(self.guild).repetir_fila)
        self.assertFalse(self.executar("repetir", {"modo": "tudo"})["ok"])

    def test_remover_e_desconhecido(self):
        self.assertFalse(self.executar("remover", {"posicao": 0})["ok"])
        self.assertFalse(self.executar("apagar_tudo")["ok"])
        self.assertFalse(self.executar("tocar", {"pedido": "   "})["ok"])

    def test_tocar_usa_a_call_da_natty(self):
        tocar = mock.patch.object(self.c, "_tocar_busca", new=mock.AsyncMock(return_value="Tocando **X** 🎵")).start()
        self.addCleanup(mock.patch.stopall)
        resultado = self.executar("tocar", {"pedido": "taverna"})
        self.assertEqual(resultado["texto"], "Tocando X 🎵")
        pedinte = tocar.await_args.args[1]
        self.assertIs(pedinte.voice.channel, self.conexao.channel)
        self.assertIsNone(tocar.await_args.args[2])  # sem canal de texto


class ConexaoQueToca(ConexaoComum):
    """VoiceClient com play(): guarda a fonte e diz se está tocando."""

    def __init__(self):
        super().__init__(tocando=False)
        self.source = None
        self.play = mock.MagicMock(side_effect=self._play)
        self.is_connected = lambda: True

    def _play(self, fonte, after=None):
        self.source, self.tocando = fonte, True


class TestMixerNaConexao(unittest.TestCase):
    def setUp(self):
        self.c = cog.BardoCog(bot=SimpleNamespace(user=SimpleNamespace(id=1)))
        self.conexao = ConexaoQueToca()
        self.guild = SimpleNamespace(id=1, voice_client=self.conexao)

    def test_toca_o_mixer_uma_vez_so(self):
        self.c._garantir_player(self.guild, self.conexao)
        self.c._garantir_player(self.guild, self.conexao)
        self.conexao.play.assert_called_once()
        self.assertIs(self.conexao.source, self.c._mixer(self.guild))

    def test_conexao_nova_recebe_o_mesmo_mixer(self):
        self.c._garantir_player(self.guild, self.conexao)
        nova = ConexaoQueToca()  # caiu e voltou / o Echo trocou a conexão
        self.c._garantir_player(self.guild, nova)
        self.assertIs(nova.source, self.c._mixer(self.guild))

    def test_outra_fonte_tocando_cede_pro_mixer_sem_derrubar_a_escuta(self):
        conexao = ConexaoQueToca()
        conexao.stop_playing = mock.MagicMock(side_effect=lambda: setattr(conexao, "tocando", False))
        conexao.source, conexao.tocando = object(), True
        self.c._garantir_player(self.guild, conexao)
        conexao.stop_playing.assert_called_once()
        conexao.stop.assert_not_called()
        self.assertIs(conexao.source, self.c._mixer(self.guild))

    def test_tocar_stream_poe_a_musica_no_mixer_com_o_volume(self):
        self.c._volumes[1] = 30
        with mock.patch.object(motor.discord, "FFmpegPCMAudio", return_value=FonteFalsa()):
            self.c._tocar_stream(self.guild, self.conexao, {"stream_url": "x"}, cog.service.Musica("Garçom", "l"))
        mixer = self.c._mixer(self.guild)
        self.assertEqual(mixer.musica, "tocando")
        self.assertIs(self.conexao.source, mixer)
        mixer.read()  # aplica os comandos
        self.assertAlmostEqual(mixer._ganho_bus["musica"], 0.3)


if __name__ == "__main__":
    unittest.main()
