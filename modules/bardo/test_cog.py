"""
Testes do cog do Bardo que não dependem do Discord de verdade: parar e pular
só param a MÚSICA — não saem da call nem derrubam a escuta do Echo.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from modules.bardo import cog


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


class TestPararNaoSaiDaCall(unittest.TestCase):
    def setUp(self):
        self.c = cog.BardoCog(bot=SimpleNamespace(user=None))

    def parar(self, conexao):
        guild = SimpleNamespace(id=1, voice_client=conexao)
        return asyncio.run(self.c._parar(guild))

    def test_parar_nao_desconecta(self):
        conexao = ConexaoComum()
        self.assertEqual(self.parar(conexao), "Parei ⏹️")
        conexao.stop.assert_called_once()
        conexao.disconnect.assert_not_called()

    def test_parar_com_o_echo_escutando_nao_derruba_a_escuta(self):
        conexao = ConexaoDoEcho()
        self.parar(conexao)
        conexao.stop_playing.assert_called_once()
        conexao.stop.assert_not_called()  # stop() mataria a escuta da senha
        conexao.disconnect.assert_not_called()

    def test_parar_limpa_a_fila(self):
        fila = self.c._fila(SimpleNamespace(id=1))
        with mock.patch.object(fila, "resetar") as resetar:
            self.parar(ConexaoComum())
        resetar.assert_called_once()

    def test_pular_com_o_echo_escutando_nao_derruba_a_escuta(self):
        conexao = ConexaoDoEcho()
        guild = SimpleNamespace(id=1, voice_client=conexao)
        self.c._pular(guild)
        conexao.stop_playing.assert_called_once()
        conexao.stop.assert_not_called()


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
        self.fila.repetir = True
        self.fila.adicionar(cog.service.Musica("Hope", "https://youtu.be/b"))
        resposta = self.c._pular(self.guild)
        self.assertFalse(self.fila.repetir)
        self.assertIn("repetição desligada", resposta)

    def test_fila_mostra_que_esta_repetindo(self):
        self.fila.repetir = True
        self.assertIn("🔁", self.c._descrever_fila(self.guild))


if __name__ == "__main__":
    unittest.main()
