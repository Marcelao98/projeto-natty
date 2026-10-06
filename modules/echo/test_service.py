"""
Testes do serviço de transcrição e detecção da senha de ativação
("NAT20, por favor"). Não baixa nem carrega o Whisper de verdade — troca
modules.echo.service._MODELO por um dublê, do mesmo jeito que o teste do
Dice troca o gerador de números aleatórios. Da raiz do projeto:
    python -m unittest discover -s modules/echo -t .
"""

import os
import sys
import tempfile
import unittest
import wave
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from modules.echo import service  # noqa: E402


class ModeloFalso:
    """Substitui o Whisper de verdade: devolve um texto fixo, sem processar áudio."""

    def __init__(self, texto="", idioma="pt", segments=None):
        self.texto = texto
        self.idioma = idioma
        self.segments = segments if segments is not None else []

    def transcribe(self, caminho, language="pt", initial_prompt=None):
        assert os.path.exists(caminho)
        self.dica_recebida = initial_prompt
        return {"text": self.texto, "language": self.idioma, "segments": self.segments}


def _wav_de_teste(caminho, segundos=1.0, sample_rate=16000):
    with wave.open(caminho, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * int(sample_rate * segundos))


class TestSenha(unittest.TestCase):
    def test_reconhece_nat20_colado(self):
        self.assertTrue(service.tem_wake_word("nat20 por favor"))

    def test_reconhece_nat20_com_espaco(self):
        self.assertTrue(service.tem_wake_word("ei, nat 20, por favor"))

    def test_reconhece_nat_vinte(self):
        self.assertTrue(service.tem_wake_word("nat vinte por favor"))

    def test_reconhece_maiusculo(self):
        self.assertTrue(service.tem_wake_word("NAT20, POR FAVOR"))

    def test_reconhece_grafias_erradas_do_whisper(self):
        # Transcrições reais do Whisper "base" pra "NAT20, por favor" (sem dica).
        for texto in ["Ok pessoal, NAA-20, por favor.", "Enheá-te 20, por favor.", "N-A-T20, por favor", "INIATE 20, por favor"]:
            with self.subTest(texto=texto):
                self.assertTrue(service.tem_wake_word(texto))

    def test_nao_reconhece_numero_sem_por_favor_nem_frase_comum(self):
        for texto in ["Consegui um N-A-T20 na rolagem.", "Tirei um natural 20 no dado.", "dano 20", "nat 15 por favor"]:
            with self.subTest(texto=texto):
                self.assertFalse(service.tem_wake_word(texto))

    def test_reconhece_no_meio_da_frase(self):
        self.assertTrue(service.tem_wake_word("então eu falei nat20 por favor e ela respondeu"))

    def test_nao_reconhece_nat20_sozinho_sem_por_favor(self):
        # Este é o caso que confundia o Whisper em teste real (virava "24.",
        # "Agunha TV") — exigir "por favor" também resolve isso na prática,
        # já que ninguém fala só "NAT20" mais, fala a frase toda.
        self.assertFalse(service.tem_wake_word("nat20"))

    def test_nao_reconhece_so_natty(self):
        self.assertFalse(service.tem_wake_word("Natty, tudo bem?"))

    def test_nao_reconhece_frase_sem_senha(self):
        self.assertFalse(service.tem_wake_word("essa espada dá 1d8 de dano"))

    def test_nao_reconhece_outro_numero(self):
        self.assertFalse(service.tem_wake_word("nat 15 por favor"))

    def test_nao_reconhece_nat20_de_jogo_sem_por_favor(self):
        # Caso real de falso positivo que a gente queria evitar: jogador
        # comentando um nat 20 de verdade, sem intenção de ativar a Natty.
        self.assertFalse(service.tem_wake_word("consegui um nat 20 na rolagem de iniciativa!"))

    def test_extrai_comando(self):
        self.assertEqual(service.extrair_comando("nat20, por favor, rola 1d20"), "rola 1d20")

    def test_extrai_comando_none_sem_senha(self):
        self.assertIsNone(service.extrair_comando("rola 1d20"))

    def test_extrai_comando_none_se_so_a_senha(self):
        self.assertIsNone(service.extrair_comando("nat20, por favor"))


class TestTranscrever(unittest.TestCase):
    def setUp(self):
        service._MODELO = None  # garante isolamento entre testes

    def tearDown(self):
        service._MODELO = None

    def test_transcrever_devolve_texto_e_duracao(self):
        service._MODELO = ModeloFalso(texto="nat20 por favor", segments=[{"start": 0.0, "end": 1.2}])
        with tempfile.NamedTemporaryFile(suffix=".wav", delete_on_close=False) as f:
            f.close()
            _wav_de_teste(f.name)
            resultado = service.transcrever(f.name)
        self.assertEqual(resultado.texto, "nat20 por favor")
        self.assertAlmostEqual(resultado.duracao_segundos, 1.2)

    def test_transcrever_sem_segmentos_nao_quebra(self):
        service._MODELO = ModeloFalso(texto="", segments=[])
        with tempfile.NamedTemporaryFile(suffix=".wav", delete_on_close=False) as f:
            f.close()
            _wav_de_teste(f.name)
            resultado = service.transcrever(f.name)
        self.assertEqual(resultado.texto, "")
        self.assertEqual(resultado.duracao_segundos, 0.0)

    def test_reconhecer_com_senha(self):
        service._MODELO = ModeloFalso(texto="nat20, por favor")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete_on_close=False) as f:
            f.close()
            _wav_de_teste(f.name)
            r = service.reconhecer(f.name)
        self.assertTrue(r.chamou_natty)
        self.assertIsNone(r.comando)

    def test_reconhecer_com_senha_e_comando(self):
        service._MODELO = ModeloFalso(texto="ok pessoal, nat20 por favor, rola iniciativa")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete_on_close=False) as f:
            f.close()
            _wav_de_teste(f.name)
            r = service.reconhecer(f.name)
        self.assertTrue(r.chamou_natty)
        self.assertEqual(r.comando, "rola iniciativa")

    def test_reconhecer_sem_senha(self):
        service._MODELO = ModeloFalso(texto="essa espada dá 1d8 de dano")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete_on_close=False) as f:
            f.close()
            _wav_de_teste(f.name)
            r = service.reconhecer(f.name)
        self.assertFalse(r.chamou_natty)
        self.assertIsNone(r.comando)


class TestTranscreverPCM(unittest.TestCase):
    def setUp(self):
        service._MODELO = None

    def tearDown(self):
        service._MODELO = None

    def test_transcrever_pcm_grava_wav_e_chama_modelo(self):
        service._MODELO = ModeloFalso(texto="nat20 por favor")
        pcm = b"\x00\x00" * 48000 * 2  # 1s de silêncio, estéreo, 48kHz (16-bit)
        resultado = service.transcrever_pcm(pcm, sample_rate=48000, canais=2)
        self.assertEqual(resultado.texto, "nat20 por favor")


class ReconhecedorFalso:
    """
    Substitui o vosk.KaldiRecognizer (sem o modelo de 31MB): a frase
    "termina" depois de `pacotes_por_frase` chamadas de AcceptWaveform, e
    aí Result() devolve o texto fixo.
    """

    def __init__(self, texto="net vinte por favor", pacotes_por_frase=3):
        self.texto = texto
        self.pacotes_por_frase = pacotes_por_frase
        self.recebido = []

    def AcceptWaveform(self, pcm):
        self.recebido.append(pcm)
        return len(self.recebido) % self.pacotes_por_frase == 0

    def Result(self):
        import json

        return json.dumps({"text": self.texto})


def _pcm_discord(segundos=0.02, esquerda=1000, direita=3000):
    """PCM como o Discord entrega: 48kHz, estéreo, 16-bit (20ms por pacote)."""
    import struct

    amostras = int(48000 * segundos)
    return struct.pack(f"<{amostras * 2}h", *([esquerda, direita] * amostras))


class TestResample16kMono(unittest.TestCase):
    def test_pacote_de_20ms_vira_320_amostras(self):
        saida = service.resample_para_16k_mono(_pcm_discord(0.02))
        self.assertEqual(len(saida), 320 * 2)  # 16kHz * 20ms, mono, 16-bit

    def test_um_segundo_vira_16000_amostras(self):
        self.assertEqual(len(service.resample_para_16k_mono(_pcm_discord(1.0))) // 2, 16000)

    def test_estereo_vira_mono_pela_media(self):
        import struct

        saida = service.resample_para_16k_mono(_pcm_discord(0.02, esquerda=1000, direita=3000))
        amostras = struct.unpack(f"<{len(saida) // 2}h", saida)
        self.assertTrue(all(abs(a - 2000) <= 1 for a in amostras[5:]))

    def test_vazio_continua_vazio(self):
        self.assertEqual(service.resample_para_16k_mono(b""), b"")


class TestProcessarChunkVosk(unittest.TestCase):
    def test_none_enquanto_a_frase_esta_em_andamento(self):
        r = ReconhecedorFalso(pacotes_por_frase=3)
        self.assertIsNone(service.processar_chunk_vosk(r, b"\x00\x00"))
        self.assertIsNone(service.processar_chunk_vosk(r, b"\x00\x00"))

    def test_devolve_o_texto_quando_o_vosk_fecha_a_frase(self):
        r = ReconhecedorFalso(texto="net vinte por favor", pacotes_por_frase=2)
        service.processar_chunk_vosk(r, b"\x00\x00")
        self.assertEqual(service.processar_chunk_vosk(r, b"\x00\x00"), "net vinte por favor")

    def test_repassa_o_audio_sem_mexer(self):
        r = ReconhecedorFalso()
        service.processar_chunk_vosk(r, b"\x01\x02")
        self.assertEqual(r.recebido, [b"\x01\x02"])

    def test_texto_do_vosk_passa_pela_regex_da_senha(self):
        # As frases de senha da grammar (FRASES_VOSK) têm que bater na regex...
        senhas = [f for f in service.FRASES_VOSK if f.endswith("vinte por favor")]
        self.assertEqual(len(senhas), len(service.PALAVRAS_PARECIDAS_COM_NAT))
        for frase in senhas:
            with self.subTest(frase=frase):
                self.assertTrue(service.tem_wake_word(frase))
        # ...e o resto — fala fora da lista e as palavras de depois da senha
        # ("saia", "rolo") sozinhas — não.
        for texto in ["[unk]", "[unk] vinte por favor", "vinte por favor", "[unk] por favor", "nathan vinte",
                      *service.PALAVRAS_DEPOIS_DA_SENHA]:
            with self.subTest(texto=texto):
                self.assertFalse(service.tem_wake_word(texto))


class TestAcaoDepoisDaSenha(unittest.TestCase):
    def test_saia_na_mesma_frase_sai(self):
        for texto in ["nate vinte por favor saia", "nate vinte por favor sai", "[unk] nate vinte por favor sair",
                      "nate vinte por favor [unk] saia"]:
            with self.subTest(texto=texto):
                self.assertTrue(service.tem_wake_word(texto))
                self.assertEqual(service.acao_depois_da_senha(texto), "sair")

    def test_senha_sozinha_ou_rolo_abre_a_rolagem(self):
        for texto in ["nate vinte por favor", "nate vinte por favor rolo", "nate vinte por favor [unk]",
                      "nate vinte por favor nate vinte por favor"]:
            with self.subTest(texto=texto):
                self.assertEqual(service.acao_depois_da_senha(texto), "rolar")

    def test_saia_sem_senha_nao_e_nada(self):
        self.assertFalse(service.tem_wake_word("saia"))

    def test_pare_na_mesma_frase_para_a_musica(self):
        for texto in ["nate vinte por favor pare", "nate vinte por favor para", "nate vinte por favor parar",
                      "[unk] nate vinte por favor [unk] pare"]:
            with self.subTest(texto=texto):
                self.assertEqual(service.acao_depois_da_senha(texto), "parar_musica")
        # Na grammar da senha — senão vira "[unk]" e some, como o "dê".
        for palavra in ["pare", "para", "parar"]:
            self.assertIn(palavra, service.FRASES_VOSK)
        self.assertFalse(service.tem_wake_word("para"))  # sozinho não é nada

    def test_controles_do_bardo_por_voz(self):
        casos = {  # o que vem depois da senha -> o que vai depois de "natty" pro Bardo
            "próxima": "pula", "pula": "pula", "pular": "pula",
            "repete": "repete", "repetir": "repete", "repita": "repete",
            "pausa": "pausa", "continua": "continua",
            "para de repetir": "para de repetir", "pare de repetir": "para de repetir",
        }
        for falado, comando in casos.items():
            with self.subTest(falado=falado):
                texto = f"[unk] nate vinte por favor {falado}"
                self.assertEqual(service.acao_depois_da_senha(texto), "bardo")
                self.assertEqual(service.comando_do_bardo_por_voz(texto), comando)

    def test_para_de_repetir_nao_vira_parar_a_musica(self):
        # As duas começam com "para": a frase inteira tem que ganhar.
        self.assertEqual(service.acao_depois_da_senha("nate vinte por favor para de repetir"), "bardo")
        self.assertEqual(service.acao_depois_da_senha("nate vinte por favor para"), "parar_musica")
        self.assertIsNone(service.comando_do_bardo_por_voz("nate vinte por favor para"))

    def test_controles_estao_na_grammar_da_senha(self):
        # Fora da grammar viram "[unk]" e somem (como o "dê"). "loop" e "proxima" sem
        # acento não existem no vocabulário do modelo — por isso não estão aqui.
        for palavra in service.COMANDOS_DO_BARDO_POR_VOZ:
            self.assertIn(palavra, service.FRASES_VOSK)
        for frase in service.FRASES_PARAR_DE_REPETIR:
            self.assertIn(frase, service.FRASES_VOSK)
        self.assertNotIn("loop", service.FRASES_VOSK)

    def test_controle_sem_senha_nao_e_nada(self):
        for texto in ["pula", "próxima", "continuar", "repete"]:
            with self.subTest(texto=texto):
                self.assertFalse(service.tem_wake_word(texto))
                self.assertIsNone(service.comando_do_bardo_por_voz(texto))

    def test_todo_controle_falado_e_entendido_pelo_bardo_de_verdade(self):
        from modules.bardo import service as bardo

        esperado = {"pula": ("pular", None), "repete": ("repetir", None), "pausa": ("pausar", None),
                    "continua": ("continuar", None), "para de repetir": ("repetir", False)}
        for comando, (acao, repetir) in esperado.items():
            with self.subTest(comando=comando):
                pedido = bardo.interpretar_pedido(f"🎙️ natty {comando}")
                self.assertEqual(pedido.acao, acao)
                if acao == "repetir":
                    self.assertEqual(pedido.repetir, repetir)

    def test_musica_na_mesma_frase_pede_musica(self):
        self.assertEqual(service.acao_depois_da_senha("nate vinte por favor música"), "musica")
        self.assertEqual(service.acao_depois_da_senha("[unk] nate vinte por favor [unk] música"), "musica")


class TestPedidoDeMusica(unittest.TestCase):
    def test_musica_na_janela_da_rolagem(self):
        # "NAT20, por favor" → 👂 → "música": a grammar da rolagem tem a palavra.
        self.assertIn("música", service.PALAVRAS_COMANDO_DADO)
        self.assertTrue(service.escolheu_musica("música"))
        self.assertTrue(service.escolheu_musica("[unk] música"))
        self.assertFalse(service.escolheu_musica("dado vinte"))
        self.assertFalse(service.escolheu_musica(""))

    def test_limpa_o_que_o_whisper_ouviu(self):
        casos = {
            "Garçom.": "Garçom",
            "Toca Song of Storms.": "Song of Storms",
            "Natty, toca a música triste e épica!": "triste e épica",
            "coloca Bloodborne": "Bloodborne",
            "Música combate.": "combate",                 # call real: o "música" vazou pro pedido
            "a música Garçom": "Garçom",
            "  Ragnar the Red  ": "Ragnar the Red",
        }
        for ouvido, esperado in casos.items():
            with self.subTest(ouvido=ouvido):
                self.assertEqual(service.limpar_pedido_de_musica(ouvido), esperado)

    def test_vazio_ou_so_pontuacao_e_none(self):
        for ouvido in ["", "   ", "...", "Toca.", "Natty, toca"]:
            with self.subTest(ouvido=ouvido):
                self.assertIsNone(service.limpar_pedido_de_musica(ouvido))

    def test_pedido_falado_chega_no_bardo_como_pedido_de_tocar(self):
        # Ponta a ponta com o Bardo DE VERDADE: o texto que o Echo posta
        # ("🎙️ natty toca <pedido>") passa pelo filtro do on_message do Bardo,
        # é dirigido à Natty e vira Pedido("tocar", busca=...).
        from types import SimpleNamespace

        from modules.bardo import service as bardo
        from modules.bardo.cog import _deve_ignorar
        from modules.echo.cog import MARCADOR_VOZ

        natty = SimpleNamespace(id=1, bot=True)
        for ouvido, busca in {"Song of Storms.": "Song of Storms", "Toca triste e épica": "triste e épica"}.items():
            with self.subTest(ouvido=ouvido):
                texto = f"{MARCADOR_VOZ} natty toca {service.limpar_pedido_de_musica(ouvido)}"
                self.assertFalse(_deve_ignorar(SimpleNamespace(author=natty, content=texto), natty))
                from modules.echo.test_cog import _bardo_acha_que_e_pra_natty
                self.assertTrue(_bardo_acha_que_e_pra_natty(natty, texto))  # sem @: o 🎙 basta
                pedido = bardo.interpretar_pedido(texto)
                self.assertEqual((pedido.acao, pedido.busca, pedido.link), ("tocar", busca, None))

    def test_bardo_continua_ignorando_bots_sem_o_marcador(self):
        from types import SimpleNamespace

        from modules.bardo.cog import _deve_ignorar

        natty = SimpleNamespace(id=1, bot=True)
        self.assertTrue(_deve_ignorar(SimpleNamespace(author=natty, content="Tocando **X** 🎵"), natty))
        self.assertTrue(_deve_ignorar(SimpleNamespace(author=SimpleNamespace(id=2, bot=True),
                                                      content="🎙️ natty toca X"), natty))
        self.assertFalse(_deve_ignorar(SimpleNamespace(author=SimpleNamespace(id=3, bot=False),
                                                       content="natty toca X"), natty))

    def test_transcrever_pcm_repassa_a_dica_pro_whisper(self):
        modelo = ModeloFalso(texto="Garçom")
        service._MODELO = modelo
        self.addCleanup(setattr, service, "_MODELO", None)
        service.transcrever_pcm(b"\x00\x00" * 4800, dica=None)
        self.assertIsNone(modelo.dica_recebida)
        service.transcrever_pcm(b"\x00\x00" * 4800)
        self.assertEqual(modelo.dica_recebida, service.DICA_WHISPER)  # padrão continua o da senha


class SegmentoFalso:
    def __init__(self, start, texto, end=None, palavras=None):
        self.start = start
        self.end = start + 1.0 if end is None else end
        self.text = texto
        # palavras: [(start, end, palavra)]; sem elas, uma "palavra" = o segmento todo
        self.words = [SimpleNamespace(start=s, end=e, word=w) for s, e, w in
                      (palavras or [(self.start, self.end, texto)])]


class FasterWhisperFalso:
    """Substitui o faster-whisper: segmentos fixos por arquivo (pela duração do áudio)."""

    def __init__(self, segmentos_por_duracao):
        self.segmentos_por_duracao = segmentos_por_duracao  # nº de amostras -> [(start, end, texto)]
        self.chamadas = []

    def transcribe(self, audio, language=None, vad_filter=False, hotwords=None, condition_on_previous_text=True,
                   beam_size=5, word_timestamps=False):
        self.chamadas.append({"tipo": type(audio).__name__, "language": language, "vad_filter": vad_filter,
                              "hotwords": hotwords, "contexto": condition_on_previous_text,
                              "beam_size": beam_size, "palavras": word_timestamps})
        segmentos = self.segmentos_por_duracao[len(audio)]
        # gerador, como o de verdade; 4º item opcional = palavras
        return (SegmentoFalso(s[0], s[2], s[1], s[3] if len(s) > 3 else None) for s in segmentos), {}


class TestEscriba(unittest.TestCase):
    def setUp(self):
        from pathlib import Path

        self.pasta = Path(tempfile.mkdtemp())
        self.addCleanup(setattr, service, "_MODELO_ESCRIBA", None)

    def _wav(self, nome, segundos, pasta=None):
        with wave.open(str((pasta or self.pasta) / nome), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * int(16000 * segundos))

    def test_nome_arquivo_seguro(self):
        self.assertEqual(service.nome_arquivo_seguro("João Ññ/x"), "joao-nn-x")
        self.assertEqual(service.nome_arquivo_seguro("Mestre do Jogo!"), "mestre-do-jogo")
        self.assertEqual(service.nome_arquivo_seguro("🎲🎲"), "pessoa")

    def test_horario_real_usa_a_ultima_marca(self):
        # .wav = fala colada com fala: 0-3s falou às 100s, a partir de 3s falou às 200s.
        marcas = [[0.0, 100.0], [3.0, 200.0]]
        self.assertEqual(service.horario_real(1.0, marcas), 101.0)
        self.assertEqual(service.horario_real(5.0, marcas), 202.0)
        self.assertEqual(service.horario_real(7.0, []), 7.0)

    def test_modelo_e_multilingue(self):
        # "distil-*" é só inglês; a mesa fala português.
        self.assertNotIn("distil", service.NOME_MODELO_ESCRIBA)

    def test_ata_em_ordem_cronologica_com_paragrafos(self):
        import json
        import time as _time

        inicio = 1_000_000.0
        self._wav("mestre-1.wav", 7)  # o arquivo "a" vem antes em ordem alfabética...
        self._wav("ana-2.wav", 2)
        (self.pasta / "nomes.json").write_text(json.dumps({"mestre-1.wav": "Mestre", "ana-2.wav": "Ana"}))
        (self.pasta / "marcas.json").write_text(json.dumps({
            "mestre-1.wav": [[0.0, inicio + 0], [4.0, inicio + 60]],  # volta a falar 1 min depois
            "ana-2.wav": [[0.0, inicio + 10]],
        }))
        # A pausa de 1 min divide o .wav do Mestre em 2 blocos (4s e 3s), que vão
        # JUNTOS num pacote de 8s (4s + 1s de silêncio + 3s): o bloco 2 começa aos
        # 5s do pacote, e cada palavra volta pro horário do bloco dela.
        modelo = FasterWhisperFalso({
            16000 * 8: [
                (0.5, 2.0, "Vocês entram na taverna."),
                (2.5, 3.8, "Está cheia."),                  # 0.5s depois: mesmo parágrafo
                (5.5, 6.5, "O taverneiro olha pra vocês."),  # bloco 2 (1 min depois): parágrafo novo
            ],
            16000 * 2: [(0.2, 1.5, " Eu peço uma cerveja. ")],
        })
        service._MODELO_ESCRIBA = modelo

        linhas = service.transcrever_sessao(self.pasta, inicio).read_text(encoding="utf-8").splitlines()
        self.assertEqual([l.split("] ", 1)[1] for l in linhas], [
            "Mestre: Vocês entram na taverna. Está cheia.",
            "Ana: Eu peço uma cerveja.",             # 10s — entre as falas do Mestre
            "Mestre: O taverneiro olha pra vocês.",  # 60s
        ])
        self.assertEqual(linhas[2][1:9], _time.strftime("%H:%M:%S", _time.localtime(inicio + 60.5)))
        # Array (não caminho: o PyAV 19 quebra o faster-whisper), português fixo, VAD e os termos da campanha.
        self.assertEqual(len(modelo.chamadas), 2)  # 1 pacote do Mestre (2 blocos) + 1 da Ana
        for chamada in modelo.chamadas:
            self.assertEqual(chamada["tipo"], "ndarray")
            self.assertEqual(chamada["language"], "pt")  # None = encoder roda 2x (detecção de idioma)
            self.assertTrue(chamada["vad_filter"])
            self.assertEqual(chamada["hotwords"], service.TERMOS_DA_CAMPANHA)
            self.assertFalse(chamada["contexto"])  # com contexto o turbo repetiu e pulou o final
            self.assertEqual(chamada["beam_size"], 1)  # 1 hipótese: 2-3x mais rápido que o padrão (5)
            self.assertTrue(chamada["palavras"])  # horário por palavra: é o que devolve cada uma pro bloco
        self.assertIn("Nhalor", service.TERMOS_DA_CAMPANHA)

    def test_retoma_de_onde_parou(self):
        """Caiu no meio (ex: falta de RAM): a 2ª tentativa não refaz o que já foi transcrito."""
        self._wav("a.wav", 1)
        self._wav("b.wav", 2)
        self._wav("c.wav", 3)

        class CaiNoTerceiro(FasterWhisperFalso):
            def transcribe(self, audio, **kw):
                if len(self.chamadas) == 2:
                    raise RuntimeError("mkl_malloc: failed to allocate memory")
                return super().transcribe(audio, **kw)

        segs = {16000: [(0.1, 0.5, "um")], 32000: [(0.1, 0.5, "dois")], 48000: [(0.1, 0.5, "três")]}
        service._MODELO_ESCRIBA = CaiNoTerceiro(segs)
        with self.assertRaises(RuntimeError):
            service.transcrever_sessao(self.pasta, 0.0)
        self.assertTrue((self.pasta / service.ARQUIVO_PARCIAL).exists())
        self.assertFalse((self.pasta / "ata.txt").exists())

        segunda = FasterWhisperFalso(segs)
        service._MODELO_ESCRIBA = segunda
        ata = service.transcrever_sessao(self.pasta, 0.0)
        self.assertEqual(len(segunda.chamadas), 1)  # só o c.wav
        textos = [l.split(": ", 1)[1] for l in ata.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(textos), ["dois", "três", "um"])
        self.assertFalse((self.pasta / service.ARQUIVO_PARCIAL).exists())  # some quando a ata fica pronta

    def test_parcial_com_linha_cortada(self):
        caminho = self.pasta / service.ARQUIVO_PARCIAL
        caminho.write_text('{"pacote": "a.wav:0.000-1.000", "falas": [[1.0, 2.0, "Ana", "oi"]]}\n{"pacote": "b.w',
                           encoding="utf-8")
        self.assertEqual(service._ler_parcial(caminho), {"a.wav:0.000-1.000": [(1.0, 2.0, "Ana", "oi")]})

    def test_agrupar_blocos(self):
        blocos = [(0, 2), (2, 5), (5, 30), (30, 31), (31, 100), (100, 101)]
        self.assertEqual(service.agrupar_blocos(blocos, max_s=28.0, silencio=1.0), [
            [(0, 2), (2, 5)],     # 2 + 1 + 3 = 6s; somar o de 25s daria 32
            [(5, 30), (30, 31)],  # 25 + 1 + 1 = 27s
            [(31, 100)],          # maior que 28s: vai sozinho
            [(100, 101)],
        ])
        self.assertEqual(service.agrupar_blocos([]), [])

    def test_falas_por_bloco_divide_segmento_que_atravessa_o_silencio(self):
        # pacote: bloco A (wav 10-12s) na posição 0, silêncio, bloco B (wav 40-43s) na posição 3
        pecas = [(0.0, 10.0, 2.0), (3.0, 40.0, 3.0)]
        segmento = SegmentoFalso(0.2, "eu ataco. Ele foge.", 4.5, [
            (0.2, 0.6, " eu"), (0.7, 1.5, " ataco."),       # bloco A
            (3.1, 3.5, " Ele"), (3.6, 4.5, " foge."),        # bloco B
        ])
        self.assertEqual(service.falas_por_bloco([segmento], pecas), [
            (10.2, 11.5, "eu ataco."),
            (40.1, 41.5, "Ele foge."),
        ])
        # palavra que começa no silêncio entre os blocos vai pro bloco seguinte
        no_vao = SegmentoFalso(2.5, "oi", 3.4, [(2.5, 3.4, " oi")])
        self.assertEqual(service.falas_por_bloco([no_vao], pecas), [(40.0, 40.4, "oi")])

    def test_juntar_em_paragrafos(self):
        falas = [
            (0.0, 2.0, "Mestre", "a"), (3.0, 4.0, "Mestre", "b"),   # pausa 1s: junta
            (20.0, 21.0, "Mestre", "c"),                             # pausa 16s: novo
            (21.5, 22.0, "Ana", "d"),                                # outra pessoa: novo
            (22.5, 23.0, "Mestre", "e"),                             # Ana no meio: novo
        ]
        self.assertEqual(service.juntar_em_paragrafos(falas), [
            (0.0, "Mestre", "a b"), (20.0, "Mestre", "c"), (21.5, "Ana", "d"), (22.5, "Mestre", "e"),
        ])

    def test_paragrafo_nao_passa_de_60s(self):
        # narração sem pausa: falas de 25s coladas, sempre o Mestre
        falas = [(i * 25.0, i * 25.0 + 24.0, "Mestre", str(i)) for i in range(5)]
        # 0-24, 25-49 cabem (49s); 50-74 passaria de 60s → novo; idem depois
        self.assertEqual(service.juntar_em_paragrafos(falas), [
            (0.0, "Mestre", "0 1"), (50.0, "Mestre", "2 3"), (100.0, "Mestre", "4"),
        ])
        self.assertEqual(service.DURACAO_MAX_PARAGRAFO_SEGUNDO, 60.0)

    def test_blocos_de_fala(self):
        # marcas: [posição no .wav, horário real]
        marcas = [[0.0, 100.0], [3.0, 104.0], [5.0, 160.0], [8.0, 163.5]]
        # 0→3: pausa real 1s (junta) · 3→5: pausa 54s (corta) · 5→8: pausa 0.5s (junta)
        self.assertEqual(service.blocos_de_fala(marcas, 10.0), [(0.0, 5.0), (5.0, 10.0)])
        self.assertEqual(service.blocos_de_fala([], 6.0), [(0.0, 6.0)])
        self.assertEqual(service.blocos_de_fala([[0.0, 1.0]], 0.0), [])

    def test_sem_marcas_usa_o_inicio(self):
        self._wav("x-1.wav", 1)
        service._MODELO_ESCRIBA = FasterWhisperFalso({16000: [(0.0, 0.5, "oi")]})
        ata = service.transcrever_sessao(self.pasta, 1_000_000.0)
        self.assertIn("] x-1: oi", ata.read_text(encoding="utf-8"))

    def test_sem_fala_devolve_none(self):
        self._wav("x-1.wav", 1)
        service._MODELO_ESCRIBA = FasterWhisperFalso({16000: [(0.0, 0.5, "   ")]})
        self.assertIsNone(service.transcrever_sessao(self.pasta, 0.0))
        self.assertFalse((self.pasta / "ata.txt").exists())

    def test_sessao_esperando_transcricao_acha_a_ultima_sem_ata(self):
        import os as _os

        antiga, nova, transcrita, vazia = (self.pasta / n for n in
                                           ("2026-10-01-20h00", "2026-10-02-21h30", "2026-10-02-22h00", "2026-10-02-23h00"))
        for p in (antiga, nova, transcrita, vazia):
            p.mkdir()
        self._wav("a.wav", 0.1, antiga)
        self._wav("a.wav", 0.1, nova)
        self._wav("a.wav", 0.1, transcrita)
        (transcrita / "ata.txt").write_text("já transcrita")
        for i, p in enumerate((antiga, nova, transcrita, vazia)):
            _os.utime(p, (1000 + i, 1000 + i))
        self.assertEqual(service.sessao_esperando_transcricao(self.pasta), nova)  # não a com ata, não a sem áudio
        self.assertIsNone(service.sessao_esperando_transcricao(self.pasta / "nao-existe"))
        # a que já está transcrevendo (ou na fila) não é escolhida de novo
        self.assertEqual(service.sessao_esperando_transcricao(self.pasta, ignorar={nova}), antiga)

    def test_progresso_a_cada_10_porcento(self):
        # 10 pessoas com 1s cada: cada arquivo é 10% da fala total
        for i in range(10):
            self._wav(f"p{i}.wav", 1)
        service._MODELO_ESCRIBA = FasterWhisperFalso({16000: [(0.1, 0.9, "oi")]})
        avisos = []
        service.transcrever_sessao(self.pasta, 0.0, lambda pct, feito, total: avisos.append((pct, feito, total)))
        self.assertEqual([a[0] for a in avisos], [10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
        self.assertEqual(avisos[-1][1:], (10.0, 10.0))

    def test_usa_um_nucleo_fisico_por_thread(self):
        self.assertGreaterEqual(service.ESCRIBA_CPU_THREADS, 1)

    def test_inicio_da_pasta(self):
        from pathlib import Path
        import time as _time

        esperado = _time.mktime(_time.strptime("2026-10-02-21h30", "%Y-%m-%d-%Hh%M"))
        self.assertEqual(service.inicio_da_pasta(Path("2026-10-02-21h30")), esperado)
        self.assertEqual(service.inicio_da_pasta(Path("qualquer")), 0.0)


class TestGramaticaVosk(unittest.TestCase):
    def test_palavras_de_depois_da_senha_estao_na_grammar(self):
        # Fora da grammar a palavra vira "[unk]" e some (foi o que aconteceu com o "dê").
        for palavra in ["saia", "sai", "sair", "rolo"]:
            self.assertIn(palavra, service.FRASES_VOSK)

    def test_tem_unk_pra_nao_forcar_fala_qualquer_a_virar_senha(self):
        self.assertIn("[unk]", service.FRASES_VOSK)

    def test_nao_usa_nat_que_nao_existe_no_vocabulario(self):
        self.assertFalse(any(f.split()[0] == "nat" for f in service.FRASES_VOSK))

    def test_sem_o_modelo_explica_onde_baixar(self):
        from pathlib import Path
        from unittest import mock

        with mock.patch.object(service, "PASTA_MODELO_VOSK", Path("nao-existe")), \
                mock.patch.object(service, "_MODELO_VOSK", None):
            with self.assertRaisesRegex(FileNotFoundError, "alphacephei"):
                service._carregar_vosk()


class TestNormalizarComandoDado(unittest.TestCase):
    """Fala (como o Vosk escreve) -> texto que o Dice entende."""

    CASOS = {
        # básico
        "rola dado vinte mais cinco com vantagem": "rolo 1d20+5 com vantagem",
        "[unk] dois dados seis mais três": "rolo 2d6+3",
        "[unk] dado vinte com desvantagem": "rolo 1d20 com desvantagem",
        "rola dado oito menos um": "rolo 1d8-1",
        "quatro dado seis": "rolo 4d6",                      # plural ouvido como singular
        "dados vinte": "rolo 1d20",                          # e o contrário
        "rola dado cem": "rolo 1d100",
        "dado vinte vantagem": "rolo 1d20 com vantagem",     # sem "com"
        "dado vinte com vantagem mais dois": "rolo 1d20+2 com vantagem",  # bônus depois do complemento
        "dado vinte contra quinze mais cinco": "rolo 1d20+5 contra 15",
        # vários termos e números grandes
        "dado vinte mais dado seis mais três": "rolo 1d20+1d6+3",
        "dado vinte mais vinte e cinco": "rolo 1d20+25",
        "dado vinte mais cinco mais dois": "rolo 1d20+5+2",
        # CD
        "dado vinte mais cinco contra quinze": "rolo 1d20+5 contra 15",
        "dado vinte dificuldade dezoito": "rolo 1d20 contra 18",
        "dado vinte com vantagem e contra vinte dois": "rolo 1d20 com vantagem contra 22",  # "e" engolido
        # explosivo
        "dois dado seis explosivo": "rolo 2d6!",
        # filtros
        "quatro dado seis tirando menores": "rolo 4d6 tiro 1",       # como o Vosk ouviu "tirando o menor"
        "quatro dados seis tirando o menor": "rolo 4d6 tiro 1",
        "quatro dados seis tiro os dois menores": "rolo 4d6 tiro 2",
        "quatro dado seis mantendo os treze maiores": "rolo 4d6 mantenho 3",  # "três" ouvido "treze"
        "dois dados vinte mantenho o maior": "rolo 2d20 mantenho 1",
        # teste por dado
        "dez dados oito maior que cinco": "rolo 10d8 maior que 5",
        "cinco dados vinte maior ou igual a dez": "rolo 5d20 maior ou igual a 10",
        "seis dados seis menor que três": "rolo 6d6 menor que 3",
        "vinte dados seis igual a seis": "rolo 20d6 igual a 6",
        # reroll condicional
        "dado oito se oito rola de novo": "rolo 1d8 se 8 role de novo",
        "dado oito se cair oito rola novamente": "rolo 1d8 se 8 role de novo",
        "dado vinte se vinte rola dado cem": "rolo 1d20 se 20 role 1d100",
        "dois dados seis se o dado seis der seis rola dado oito": "rolo 2d6 se o d6 der 6 role 1d8",
        # moedas
        "treze moedas": "rolo 3 moedas",                     # "três" ouvido "treze"
        "rola moeda": "rolo 1 moeda",
        "moeda setenta por cento de cara": "rolo 1 moeda 70% de cara",
        "três moedas se duas caras rola dado seis": "rolo 3 moedas se 2 caras role 1d6",
        "moeda se cara rola dado vinte mais cinco com vantagem contra quinze":
            "rolo 1 moeda se 1 cara role 1d20+5 com vantagem contra 15",
        # "dados seis" ouvido como "dezesseis" (call real), "dados oito" como "dezoito"
        "role cinco dezesseis maior três": "rolo 5d6 maior que 3",
        "dois dezoito mais três": "rolo 2d8+3",
        "dado dezesseis": "rolo 1d6",
        "dado vinte mais dezesseis": "rolo 1d20+16",         # bônus continua 16
        "dado vinte contra dezoito": "rolo 1d20 contra 18",  # CD continua 18
        # nome do teste
        "teste de ataque dado vinte mais sete": "teste de ataque: rolo 1d20+7",
        "dado vinte mais quatro teste de percepção": "teste de percepção: rolo 1d20+4",
        # tudo junto
        "teste de ataque rola dado vinte mais cinco com vantagem contra quinze se vinte rola dado oito":
            "teste de ataque: rolo 1d20+5 com vantagem contra 15 se 20 role 1d8",
    }

    def test_casos(self):
        for falado, esperado in self.CASOS.items():
            with self.subTest(falado=falado):
                self.assertEqual(service.normalizar_comando_dado(falado), esperado)

    def test_rejeita_o_que_nao_e_rolagem_completa(self):
        for falado in [
            "", "[unk]", "com", "um",                   # lixo curto (fala fora do tema)
            # O que chegou em call real quando a fala era "um dê vinte":
            "rola vinte", "vinte um", "vinte", "oito",
            "dado sete", "dado vinte e cinco",           # d7/d25 não são dados de mesa
            "dado vinte mais",                           # bônus sem número
            "dado vinte [unk] cinco",                    # algo não entendido no meio
            "dado vinte com vantagem com desvantagem",   # complemento repetido
            "dado vinte contra",                         # CD sem número
            "quatro dados seis tirando",                 # filtro sem quanto
            "dado oito se oito",                         # reroll sem o que rolar
            "dado vinte teste de arcanismo",             # perícia fora do vocabulário
            "moeda se cara",                             # condicional sem rolagem
            "teste de ataque três moedas",               # teste não combina com moeda
            "um d vinte",                                # formato antigo: "d" saiu da grammar
        ]:
            with self.subTest(falado=falado):
                self.assertIsNone(service.normalizar_comando_dado(falado))

    def test_treze_so_vira_tres_em_quantidade(self):
        self.assertEqual(service.normalizar_comando_dado("treze dados seis"), "rolo 3d6")
        self.assertEqual(service.normalizar_comando_dado("dado vinte contra treze"), "rolo 1d20 contra 13")
        self.assertEqual(service.normalizar_comando_dado("dado vinte mais treze"), "rolo 1d20+13")

    def test_toda_palavra_dos_casos_esta_na_grammar(self):
        palavras = set(service.PALAVRAS_COMANDO_DADO)
        for falado in self.CASOS:
            for palavra in falado.split():
                if palavra != "[unk]":
                    self.assertIn(palavra, palavras, falado)

    def test_grammar_usa_dado_e_nao_a_letra(self):
        self.assertIn("dado", service.PALAVRAS_COMANDO_DADO)
        for letra in ["d", "dê"]:
            self.assertNotIn(letra, service.PALAVRAS_COMANDO_DADO)


class TestJuntarPedacosVosk(unittest.TestCase):
    """Rolagem falada com respiração no meio: o Vosk fecha uma frase a cada pausa."""

    def test_junta_os_pedacos_de_uma_rolagem_longa(self):
        # Como chegou em call real, cortado: "dado vinte" ... "se vinte rola dado cem".
        texto = service.juntar_pedacos_vosk(["[unk] dado vinte", "se vinte rola [unk]", "dado cem"])
        self.assertEqual(texto, "dado vinte se vinte rola dado cem")
        self.assertEqual(service.normalizar_comando_dado(texto), "rolo 1d20 se 20 role 1d100")

    def test_ignora_pedacos_vazios_e_so_ruido(self):
        self.assertEqual(service.juntar_pedacos_vosk(["", "[unk]", "dado oito", ""]), "dado oito")
        self.assertEqual(service.juntar_pedacos_vosk([]), "")


class TestRolagemFaladaChegaNoDice(unittest.TestCase):
    """
    Ponta a ponta com o Dice DE VERDADE: o texto que o Echo posta no canal
    ("🎙️ " + rolagem) passa pelo mesmo caminho do on_message do Dice
    (_responder) e tem o efeito certo — não basta o Dice "aceitar".
    """

    def setUp(self):
        from modules.dice import detector
        from modules.dice import service as dice

        self.detector, self.dice = detector, dice

    def _mensagem(self, falado):
        rolagem = service.normalizar_comando_dado(falado)
        self.assertIsNotNone(rolagem, falado)
        return f"🎙️ {rolagem}"  # exatamente o que o cog.py do Echo posta

    def _rolar(self, falado):
        import random

        mensagem = self._mensagem(falado)
        self.assertTrue(self.detector.is_roll_message(mensagem), mensagem)
        self.assertIsNone(self.detector.extract_coin_pattern(mensagem), mensagem)
        reroll = self.detector.extract_conditional_reroll(mensagem)
        return self.dice.roll(mensagem, rng=random.Random(1), conditional_reroll=reroll), reroll

    def test_basico_sem_efeito_colateral(self):
        esperados = {
            "rola dado vinte mais cinco com vantagem": ("1d20+5", "vantagem"),
            "[unk] dois dados seis mais três": ("2d6+3", None),
            "[unk] dado vinte com desvantagem": ("1d20", "desvantagem"),
            "rola dado oito menos um": ("1d8-1", None),
            "dado vinte mais dado seis mais três": ("1d20+1d6+3", None),
        }
        for falado, (expressao, modificador) in esperados.items():
            with self.subTest(falado=falado):
                r, reroll = self._rolar(falado)
                self.assertEqual(r.expressao, expressao)
                self.assertEqual(r.modificador, modificador)
                self.assertIsNone(r.dc)  # nada na mensagem pode virar CD por acidente
                self.assertIsNone(r.threshold)
                self.assertIsNone(reroll)

    def test_cd(self):
        r, _ = self._rolar("dado vinte com vantagem e contra vinte dois")
        self.assertEqual((r.dc, r.modificador), (22, "vantagem"))
        self.assertIn(r.resultado, ("sucesso", "falha", "crítico"))

    def test_explosivo(self):
        r, _ = self._rolar("dois dado seis explosivo")
        self.assertEqual(r.expressao, "2d6!")

    def test_filtros(self):
        r, _ = self._rolar("quatro dados seis tirando o menor")
        self.assertEqual((r.termos[0].filtro, r.termos[0].filtro_qtd), ("t", 1))
        r, _ = self._rolar("quatro dado seis mantendo os treze maiores")
        self.assertEqual((r.termos[0].filtro, r.termos[0].filtro_qtd), ("m", 3))

    def test_teste_por_dado(self):
        for falado, (operador, valor) in {
            "dez dados oito maior que cinco": (">", 5),
            "cinco dados vinte maior ou igual a dez": (">=", 10),
            "seis dados seis menor que três": ("<", 3),
            "vinte dados seis igual a seis": ("=", 6),
        }.items():
            with self.subTest(falado=falado):
                r, _ = self._rolar(falado)
                self.assertEqual((r.threshold.operador, r.threshold.valor), (operador, valor))

    def test_reroll(self):
        _, reroll = self._rolar("dado oito se oito rola de novo")
        self.assertEqual((reroll.trigger_value, reroll.reroll_notation), (8, None))
        _, reroll = self._rolar("dado vinte se vinte rola dado cem")
        self.assertEqual((reroll.trigger_value, reroll.reroll_notation), (20, "1d100"))
        _, reroll = self._rolar("dois dados seis se o dado seis der seis rola dado oito")
        self.assertEqual((reroll.trigger_die, reroll.trigger_value, reroll.reroll_notation), (6, 6, "1d8"))

    def test_nome_do_teste(self):
        r, _ = self._rolar("teste de ataque dado vinte mais sete")
        self.assertEqual(r.teste, "ataque")

    def test_tudo_junto(self):
        r, reroll = self._rolar(
            "teste de ataque rola dado vinte mais cinco com vantagem contra quinze se vinte rola dado oito"
        )
        self.assertEqual((r.teste, r.expressao, r.modificador, r.dc), ("ataque", "1d20+5", "vantagem", 15))
        self.assertEqual((reroll.trigger_value, reroll.reroll_notation), (20, "1d8"))

    def test_moedas(self):
        import random

        for falado, (qtd, peso, caras, rolagem) in {
            "treze moedas": (3, 0.5, None, None),
            "moeda setenta por cento de cara": (1, 0.7, None, None),
            "três moedas se duas caras rola dado seis": (3, 0.5, 2, "1d6"),
            "moeda se cara rola dado vinte mais cinco com vantagem contra quinze": (1, 0.5, 1, "1d20+5"),
        }.items():
            with self.subTest(falado=falado):
                mensagem = self._mensagem(falado)
                moeda = self.detector.extract_coin_pattern(mensagem)
                self.assertEqual(moeda, {"count": qtd, "bias": peso})
                condicional = self.detector.extract_coin_conditional(mensagem)
                if caras is None:
                    self.assertIsNone(condicional)
                    continue
                self.assertEqual(condicional["target_heads"], caras)
                # O que vem depois de "role" é rolável pelo Dice (e com os complementos).
                r = self.dice.roll(condicional["reroll"], rng=random.Random(1))
                self.assertEqual(r.expressao, rolagem)
                self.dice.roll_coins(moeda, condicional, rng=random.Random(1))  # não levanta

    def test_toda_saida_dos_casos_passa_pelo_dice_sem_erro(self):
        import random

        from modules.dice.cog import _responder

        for falado, esperado in TestNormalizarComandoDado.CASOS.items():
            if esperado is None:
                continue
            with self.subTest(falado=falado):
                random.seed(1)
                resposta = _responder(f"🎙️ {esperado}", exigir_pedido=True)
                self.assertIsNotNone(resposta)
                self.assertFalse(resposta.startswith("🎙"))  # a resposta do Dice nunca dispara o Dice de novo

    def test_dice_aceita_a_mensagem_da_natty_so_com_o_marcador(self):
        from types import SimpleNamespace

        from modules.dice.cog import _deve_ignorar
        from modules.echo.cog import MARCADOR_VOZ

        natty = SimpleNamespace(id=1, bot=True)
        outro_bot = SimpleNamespace(id=2, bot=True)
        pessoa = SimpleNamespace(id=3, bot=False)

        def msg(autor, texto):
            return SimpleNamespace(author=autor, content=texto)

        self.assertFalse(_deve_ignorar(msg(natty, f"{MARCADOR_VOZ} rolo 1d20"), natty))
        self.assertFalse(_deve_ignorar(msg(natty, "\U0001F399 rolo 1d20"), natty))  # sem o U+FE0F
        self.assertTrue(_deve_ignorar(msg(natty, "🎲 1d20 [17] = **17**"), natty))  # resposta do próprio Dice
        self.assertTrue(_deve_ignorar(msg(outro_bot, f"{MARCADOR_VOZ} rolo 1d20"), natty))  # Avrae etc.
        self.assertFalse(_deve_ignorar(msg(pessoa, "rolo 1d20"), natty))


class TestTemVoz(unittest.TestCase):
    def test_silencio_nao_e_voz(self):
        self.assertFalse(service.tem_voz(b"\x00\x00" * 320))
        self.assertFalse(service.tem_voz(b""))

    def test_fala_e_voz(self):
        import struct

        self.assertTrue(service.tem_voz(struct.pack("<320h", *([3000, -3000] * 160))))


if __name__ == "__main__":
    unittest.main()
