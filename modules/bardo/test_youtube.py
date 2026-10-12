"""
Testes do youtube.py sem rede: o yt-dlp é trocado por um dublê. Cobrem a
tradução dos erros do yt-dlp (vídeo privado, idade...) e a leitura de playlist.
"""

import unittest
from unittest import mock

from modules.bardo import youtube


class YoutubeDLFalso:
    """yt_dlp.YoutubeDL que devolve `info` ou levanta `erro`."""

    def __init__(self, info=None, erro=None):
        self.info, self.erro = info, erro

    def __call__(self, opcoes):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def extract_info(self, url, download=False):
        if self.erro:
            raise self.erro
        return self.info


def com_ytdlp(info=None, erro=None):
    return mock.patch.object(youtube.yt_dlp, "YoutubeDL", YoutubeDLFalso(info, erro))


class TraduzirErro(unittest.TestCase):
    def test_mensagens_do_ytdlp(self):
        casos = {
            "ERROR: [youtube] abc: Private video. Sign in if you've been granted access": youtube.VideoPrivado,
            "ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate": youtube.RestricaoDeIdade,
            "ERROR: [youtube] abc: Join this channel to get access to members-only content": youtube.SoParaMembros,
            "ERROR: [youtube] abc: The uploader has not made this video available in your country":
                youtube.BloqueadoNaRegiao,
            "ERROR: [youtube] abc: Video unavailable. This video has been removed by the uploader":
                youtube.VideoIndisponivel,
            "ERROR: [youtube:tab] PLx: The playlist does not exist.": youtube.PlaylistIndisponivel,
        }
        for mensagem, classe in casos.items():
            with self.subTest(classe=classe.__name__):
                self.assertIs(type(youtube.traduzir_erro(Exception(mensagem))), classe)

    def test_desconhecido_vira_o_generico(self):
        erro = youtube.traduzir_erro(Exception("HTTP Error 500"))
        self.assertIs(type(erro), youtube.ErroDeMusica)

    def test_resolver_levanta_o_erro_traduzido(self):
        with com_ytdlp(erro=Exception("Private video")), self.assertRaises(youtube.VideoPrivado):
            youtube.resolver_stream("https://youtu.be/abc")

    def test_busca_vazia_e_nada_encontrado(self):
        with com_ytdlp(info={"entries": []}), self.assertRaises(youtube.NadaEncontrado) as ctx:
            youtube.buscar_stream("dugeon ambience, kobold")
        self.assertIsInstance(ctx.exception, LookupError)  # quem pegava LookupError continua pegando


class ListarPlaylist(unittest.TestCase):
    def test_lista_e_pula_privados_e_apagados(self):
        info = {"title": "Taverna", "entries": [
            {"id": "a", "title": "Canção da Taverna", "duration": 120},
            {"id": "b", "title": "[Private video]"},
            None,
            {"id": "c", "title": "[Deleted video]"},
            {"id": "d", "title": "Hidromel", "duration": None},
        ]}
        with com_ytdlp(info=info):
            resultado = youtube.listar_playlist("https://www.youtube.com/playlist?list=PLx")
        self.assertEqual(resultado, {"titulo": "Taverna", "itens": [
            {"titulo": "Canção da Taverna", "link": "https://www.youtube.com/watch?v=a", "duracao_segundos": 120},
            {"titulo": "Hidromel", "link": "https://www.youtube.com/watch?v=d", "duracao_segundos": None},
        ]})

    def test_vazia(self):
        with com_ytdlp(info={"title": "x", "entries": [{"id": "b", "title": "[Private video]"}]}):
            with self.assertRaises(youtube.NadaEncontrado):
                youtube.listar_playlist("https://www.youtube.com/playlist?list=PLx")

    def test_inexistente_e_da_playlist_nao_do_video(self):
        with com_ytdlp(erro=Exception("This video is unavailable")):
            with self.assertRaises(youtube.PlaylistIndisponivel):
                youtube.listar_playlist("https://www.youtube.com/playlist?list=PLx")


class OutrosSites(unittest.TestCase):
    def test_link_nao_suportado(self):
        erro = youtube.traduzir_erro(Exception("ERROR: Unsupported URL: https://example.com/x"))
        self.assertIs(type(erro), youtube.LinkNaoSuportado)

    def test_set_do_soundcloud_usa_a_pagina_da_faixa(self):
        info = {"title": "Taverna", "entries": [
            {"ie_key": "Soundcloud", "id": "123", "url": "https://soundcloud.com/bardo/hidromel", "title": "Hidromel"},
        ]}
        with com_ytdlp(info=info):
            itens = youtube.listar_playlist("https://soundcloud.com/bardo/sets/taverna")["itens"]
        self.assertEqual(itens[0]["link"], "https://soundcloud.com/bardo/hidromel")


if __name__ == "__main__":
    unittest.main()
