"""Acesso cru ao YouTube via yt-dlp.

Espelha o papel de `modules/core/sheets.py`: é a única peça do Bardo que
fala com um sistema externo (aqui, extrai a URL de áudio direto de um vídeo
do YouTube). Nenhuma lógica de negócio mora aqui, só a chamada crua.

Os erros do yt-dlp saem daqui já traduzidos em ErroDeMusica (vídeo privado,
com restrição de idade, indisponível...), pra quem chama poder dizer à mesa
o motivo em vez de um "deu erro" genérico.
"""

from __future__ import annotations

import yt_dlp

_YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "skip_download": True,
}

# Playlist: só a lista (título, id, duração), sem resolver o áudio de cada
# vídeo — cada um é resolvido na hora de tocar, como qualquer item da fila.
_YDL_OPTS_PLAYLIST = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": "in_playlist",
}


class ErroDeMusica(Exception):
    """Não deu pra tocar, por um motivo que dá pra explicar pra mesa (`motivo`)."""

    motivo = "deu erro no YouTube"

    def __init__(self, detalhe: str = ""):
        super().__init__(detalhe or self.motivo)


class VideoPrivado(ErroDeMusica):
    motivo = "o vídeo é privado"


class RestricaoDeIdade(ErroDeMusica):
    motivo = "o vídeo tem restrição de idade (precisa de login)"


class SoParaMembros(ErroDeMusica):
    motivo = "o vídeo é só pra membros do canal"


class BloqueadoNaRegiao(ErroDeMusica):
    motivo = "o vídeo está bloqueado no nosso país"


class VideoIndisponivel(ErroDeMusica):
    motivo = "o vídeo não existe mais ou está indisponível"


class PlaylistIndisponivel(ErroDeMusica):
    motivo = "a playlist não existe ou é privada"


class NadaEncontrado(ErroDeMusica, LookupError):
    motivo = "a busca não trouxe nenhum resultado"


# Trecho da mensagem do yt-dlp → erro. A ordem importa: a mensagem de vídeo
# privado também diz "unavailable".
_TRADUCOES: list[tuple[tuple[str, ...], type[ErroDeMusica]]] = [
    (("private video", "video is private"), VideoPrivado),
    (("confirm your age", "age-restricted", "age restricted", "inappropriate for some users"), RestricaoDeIdade),
    (("members-only", "members only", "join this channel"), SoParaMembros),
    (("available in your country", "geo restrict", "blocked it in your country"), BloqueadoNaRegiao),
    (("playlist does not exist", "playlist is private", "unviewable playlist"), PlaylistIndisponivel),
    (("video unavailable", "is unavailable", "has been removed", "does not exist", "no longer available"),
     VideoIndisponivel),
]


def traduzir_erro(erro: Exception) -> ErroDeMusica:
    """Erro do yt-dlp → ErroDeMusica com o motivo; o genérico quando não reconhece."""
    if isinstance(erro, ErroDeMusica):
        return erro
    texto = str(erro).lower()
    for trechos, classe in _TRADUCOES:
        if any(t in texto for t in trechos):
            return classe(str(erro))
    return ErroDeMusica(str(erro))


def resolver_stream(url: str) -> dict:
    """Resolve uma URL do YouTube na URL de áudio direto + metadados.

    Levanta ErroDeMusica (ou uma subclasse) se o vídeo não existir, estiver
    bloqueado, etc. — quem chama decide como tratar.
    """
    info = _extrair(url)
    return {
        "titulo": info.get("title") or "música desconhecida",
        "stream_url": info["url"],
        "duracao_segundos": info.get("duration"),
        # O FFmpeg precisa mandar os mesmos headers pra URL de áudio.
        "http_headers": info.get("http_headers") or {},
    }


def buscar_stream(texto: str) -> dict:
    """Busca `texto` no YouTube e resolve o primeiro resultado.

    Mesmo retorno de resolver_stream(), mais "link": o link de watch do
    vídeo, que (ao contrário da stream_url) não expira. Levanta
    NadaEncontrado se a busca não trouxer nada.
    """
    # "ytsearch1:" é a pseudo-URL de busca do yt-dlp (primeiro resultado).
    info = _extrair(f"ytsearch1:{texto}")
    return {
        "titulo": info.get("title") or "música desconhecida",
        "link": f"https://www.youtube.com/watch?v={info['id']}",
        "stream_url": info["url"],
        "duracao_segundos": info.get("duration"),
        "http_headers": info.get("http_headers") or {},
    }


def listar_playlist(url: str) -> dict:
    """Lista os vídeos de uma playlist, sem resolver o áudio deles.

    Devolve {"titulo": str, "itens": [{"titulo", "link", "duracao_segundos"}]}
    na ordem da playlist, sem os vídeos apagados ou privados. Levanta
    PlaylistIndisponivel se ela não existir e NadaEncontrado se vier vazia.
    """
    try:
        with yt_dlp.YoutubeDL(_YDL_OPTS_PLAYLIST) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        erro = traduzir_erro(e)
        # Numa playlist, "não existe"/"indisponível" é da playlist, não de um vídeo.
        if type(erro) in (ErroDeMusica, VideoIndisponivel):
            erro = PlaylistIndisponivel(str(e))
        raise erro from e
    return _itens_da_playlist(info, url)


def _itens_da_playlist(info: dict, url: str) -> dict:
    itens = []
    for e in info.get("entries") or []:
        if not e or not e.get("id"):
            continue
        titulo = e.get("title") or ""
        if titulo in ("[Private video]", "[Deleted video]"):
            continue
        itens.append({
            "titulo": titulo or "música desconhecida",
            "link": f"https://www.youtube.com/watch?v={e['id']}",
            "duracao_segundos": e.get("duration"),
        })
    if not itens:
        raise NadaEncontrado(f"playlist vazia: {url!r}")
    return {"titulo": info.get("title") or "playlist", "itens": itens}


def _extrair(url: str) -> dict:
    try:
        with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise traduzir_erro(e) from e
    if "entries" in info:  # playlist ou busca: pega o primeiro item
        entradas = [e for e in info["entries"] if e]
        if not entradas:
            raise NadaEncontrado(f"nada encontrado para {url!r}")
        info = entradas[0]
    return info
