"""
Testes do mixer com PCM sintético (e ffmpeg de verdade onde faz sentido):
soma, volume com rampa, fim da música, pausa, ducking, limiter, loop de
ambiente, e que um stream lento não trava a mistura.
"""

import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from modules.bardo import mixer as m


class Tom:
    """Fonte tipo FFmpegPCMAudio: `quadros` quadros com amostra constante `valor` (int16)."""

    def __init__(self, quadros=10_000, valor=8000, atraso=0.0):
        self.restantes, self.valor, self.atraso = quadros, valor, atraso
        self.limpa = False

    def read(self):
        if self.atraso:
            time.sleep(self.atraso)
        if self.restantes <= 0:
            return b""
        self.restantes -= 1
        return int(self.valor).to_bytes(2, "little", signed=True) * (m.AMOSTRAS * m.CANAIS)

    def cleanup(self):
        self.limpa = True


def nivel(dados: bytes) -> float:
    """Valor médio (int16) do quadro."""
    return float(np.frombuffer(dados, dtype="<i2").astype(np.float32).mean())


def ler_ate(mixer, condicao, limite=200):
    """Lê quadros até `condicao(quadro)`; dá tempo pra thread leitora encher o buffer."""
    for _ in range(limite):
        q = mixer.read()
        if condicao(q):
            return q
        time.sleep(0.005)
    raise AssertionError("condição não aconteceu")


class Basico(unittest.TestCase):
    def test_ocioso_da_silencio_e_depois_para(self):
        mx = m.MixerSource()
        mx.ativo = True
        for _ in range(m.QUADROS_OCIOSO_ANTES_DE_PARAR):
            self.assertEqual(mx.read(), m.SILENCIO)
        self.assertEqual(mx.read(), b"")
        self.assertFalse(mx.ativo)

    def test_quadro_tem_o_tamanho_do_discord(self):
        mx = m.MixerSource()
        mx.tocar_musica(Tom())
        self.assertEqual(len(ler_ate(mx, lambda q: nivel(q) != 0)), m.BYTES_POR_QUADRO == 3840 and 3840)

    def test_volume_da_musica_com_rampa(self):
        mx = m.MixerSource()
        mx.volume(m.MUSICA, 1.0)
        mx.tocar_musica(Tom(valor=8000))
        ler_ate(mx, lambda q: abs(nivel(q) - 8000) < 2)
        mx.volume(m.MUSICA, 0.5)
        rampa = np.frombuffer(mx.read(), dtype="<i2")
        self.assertGreater(rampa[0], rampa[-2])  # desce dentro do quadro, sem degrau
        self.assertAlmostEqual(nivel(mx.read()), 4000, delta=2)


class FimEPausa(unittest.TestCase):
    def test_fim_da_musica_avisa_uma_vez(self):
        avisos = []
        mx = m.MixerSource()
        mx.tocar_musica(Tom(quadros=5), ao_terminar=lambda: avisos.append(1))
        ler_ate(mx, lambda q: avisos != [])
        for _ in range(5):
            mx.read()
        self.assertEqual(avisos, [1])
        self.assertIsNone(mx.musica)

    def test_parar_musica_avisa_e_some(self):
        avisos = []
        mx = m.MixerSource()
        fonte = Tom()
        mx.tocar_musica(fonte, ao_terminar=lambda: avisos.append(1))
        ler_ate(mx, lambda q: nivel(q) > 0)
        mx.parar_musica()
        self.assertIsNone(mx.musica)  # o espelho muda na hora (o loop lê ele)
        ler_ate(mx, lambda q: avisos == [1])
        self.assertEqual(nivel(mx.read()), 0)
        time.sleep(0.05)
        self.assertTrue(fonte.limpa)  # o ffmpeg é fechado

    def test_trocar_de_musica_nao_avisa_o_fim_da_velha(self):
        avisos = []
        mx = m.MixerSource()
        mx.tocar_musica(Tom(valor=1000), ao_terminar=lambda: avisos.append("velha"))
        ler_ate(mx, lambda q: nivel(q) > 0)
        mx.tocar_musica(Tom(valor=3000), ao_terminar=lambda: avisos.append("nova"))
        ler_ate(mx, lambda q: abs(nivel(q) - 1500) < 2)  # bus de música começa em 50%
        self.assertEqual(avisos, [])
        self.assertEqual(mx.musica, "tocando")

    def test_pausa_nao_consome_a_fonte(self):
        mx = m.MixerSource()
        fonte = Tom(quadros=10_000)
        mx.tocar_musica(fonte)
        ler_ate(mx, lambda q: nivel(q) > 0)
        mx.pausar_musica(True)
        for _ in range(3):
            mx.read()
        time.sleep(0.05)
        restantes = fonte.restantes
        for _ in range(100):
            self.assertEqual(nivel(mx.read()), 0)
        time.sleep(0.05)
        self.assertEqual(fonte.restantes, restantes)
        mx.pausar_musica(False)
        ler_ate(mx, lambda q: nivel(q) > 0)


class Mistura(unittest.TestCase):
    def test_ambiente_soma_com_musica_e_faz_fade(self):
        mx = m.MixerSource()
        mx.volume(m.MUSICA, 1.0)
        mx.tocar_musica(Tom(valor=1000))
        mx.tocar_ambiente("chuva", lambda: Tom(valor=2000), ganho=0.5, fade_s=0.1)
        q = ler_ate(mx, lambda q: abs(nivel(q) - 2000) < 3)  # 1000 + 2000×0.5
        self.assertTrue(q)
        mx.parar_ambiente("chuva", fade_s=0.1)
        ler_ate(mx, lambda q: abs(nivel(q) - 1000) < 2)
        self.assertEqual(mx.ambientes, {})

    def test_ambiente_em_loop_reabre_a_fonte(self):
        aberturas = []

        def fabrica():
            aberturas.append(1)
            return Tom(quadros=3, valor=1000)
        mx = m.MixerSource()
        mx.tocar_ambiente("taverna", fabrica, ganho=1.0, fade_s=0)
        for _ in range(60):
            mx.read()
            time.sleep(0.002)
        self.assertGreater(len(aberturas), 2)

    def test_efeito_toca_uma_vez_sem_esperar(self):
        mx = m.MixerSource()
        amostras = np.full((m.AMOSTRAS * 2, 2), 0.25, np.float32)
        mx.disparar_efeito(amostras, ganho=1.0)
        self.assertAlmostEqual(nivel(mx.read()), 0.25 * 32767, delta=2)  # já no primeiro quadro
        self.assertAlmostEqual(nivel(mx.read()), 0.25 * 32767, delta=2)
        self.assertEqual(nivel(mx.read()), 0)
        self.assertEqual(mx.read(), m.SILENCIO)  # e saiu do mixer

    def test_ducking_abaixa_a_musica_e_solta_devagar(self):
        mx = m.MixerSource()
        mx.volume(m.MUSICA, 1.0)
        mx.ducking(0.5)
        mx.tocar_musica(Tom(valor=4000))
        ler_ate(mx, lambda q: abs(nivel(q) - 4000) < 2)
        mx.disparar_efeito(np.zeros((m.AMOSTRAS * 25, 2), np.float32), duck=True)  # 0,5 s de efeito mudo
        niveis = [nivel(mx.read()) for _ in range(25)]
        self.assertLess(niveis[-1], 2100)           # chegou perto de 50%
        self.assertLess(niveis[3], niveis[0])      # ataque rápido
        soltura = [nivel(mx.read()) for _ in range(10)]
        self.assertLess(soltura[-1], 3600)          # soltura lenta: ainda não voltou
        self.assertGreater(soltura[-1], soltura[0])

    def test_limiter_nao_estoura(self):
        mx = m.MixerSource()
        mx.volume(m.MUSICA, 1.0)
        mx.tocar_musica(Tom(valor=30000))
        for i in range(4):
            mx.tocar_ambiente(str(i), lambda: Tom(valor=30000), ganho=1.0, fade_s=0)
        q = np.frombuffer(ler_ate(mx, lambda q: nivel(q) > 31000), dtype="<i2")
        self.assertLessEqual(int(q.max()), 32767)
        x = np.array([[0.5, -0.7], [1.5, -3.0]], np.float32)
        y = m.limiter(x)
        self.assertTrue(np.array_equal(y[0], x[0]))  # abaixo do limiar não mexe
        self.assertTrue((np.abs(y) <= 1.0).all())

    def test_stream_lento_nao_trava_a_mistura(self):
        mx = m.MixerSource()
        mx.tocar_musica(Tom(atraso=0.5))  # rede travada
        mx.disparar_efeito(np.full((m.AMOSTRAS * 5, 2), 0.1, np.float32))
        inicio = time.perf_counter()
        quadros = [mx.read() for _ in range(5)]
        self.assertLess(time.perf_counter() - inicio, 0.05)
        self.assertTrue(all(nivel(q) > 0 for q in quadros))  # o efeito toca mesmo assim

    def test_mistura_cabe_no_tempo(self):
        mx = m.MixerSource()
        mx.tocar_musica(Tom())
        for i in range(6):
            mx.tocar_ambiente(str(i), lambda: Tom(), ganho=0.3, fade_s=0)
        ler_ate(mx, lambda q: nivel(q) != 0)
        time.sleep(0.1)
        inicio = time.perf_counter()
        for _ in range(50):
            mx.read()
        self.assertLess((time.perf_counter() - inicio) / 50, 0.005)  # bem menos que os 20 ms do quadro

    def test_parar_tudo(self):
        avisos = []
        mx = m.MixerSource()
        mx.tocar_musica(Tom(), ao_terminar=lambda: avisos.append(1))
        mx.tocar_ambiente("chuva", lambda: Tom(), fade_s=0)
        ler_ate(mx, lambda q: nivel(q) != 0)
        mx.parar_tudo()
        self.assertEqual(nivel(mx.read()), 0)
        self.assertEqual((mx.musica, mx.ambientes, avisos), (None, {}, []))


@unittest.skipUnless(shutil.which("ffmpeg"), "precisa do ffmpeg")
class ComFFmpeg(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wav = str(Path(tmp.name) / "tom.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
                        "-ar", "44100", "-ac", "1", self.wav], check=True)

    def test_decodificar_vira_48k_estereo(self):
        amostras = m.decodificar_arquivo(self.wav)
        self.assertEqual(amostras.shape[1], 2)
        self.assertAlmostEqual(len(amostras) / m.TAXA, 0.5, delta=0.03)
        self.assertGreater(float(np.abs(amostras).max()), 0.05)

    def test_ffmpeg_de_verdade_como_musica(self):
        import discord
        avisos = []
        mx = m.MixerSource()
        mx.volume(m.MUSICA, 1.0)
        mx.tocar_musica(discord.FFmpegPCMAudio(self.wav, options="-vn"), ao_terminar=lambda: avisos.append(1))
        picos = []
        for _ in range(400):
            q = mx.read()
            picos.append(int(np.abs(np.frombuffer(q, dtype="<i2")).max()) if q else 0)
            if avisos:
                break
            time.sleep(0.003)
        self.assertEqual(avisos, [1])
        self.assertGreater(max(picos), 1500)


if __name__ == "__main__":
    unittest.main()
