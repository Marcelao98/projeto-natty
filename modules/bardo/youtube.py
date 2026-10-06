"""Acesso cru ao YouTube via yt-dlp.

Espelha o papel de `modules/core/sheets.py`: é a única peça do Bardo que
fala com um sistema externo (aqui, extrai a URL de áudio direto de um vídeo
do YouTube). Nenhuma lógica de negócio mora aqui, só a chamada crua.
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


def resolver_stream(url: str) -> dict:
    """Resolve uma URL do YouTube na URL de áudio direto + metadados.

    Levanta a exceção do yt-dlp se o vídeo não existir, estiver bloqueado,
    etc. — quem chama decide como tratar.
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
    vídeo, que (ao contrário da stream_url) não expira. Levanta LookupError
    se a busca não trouxer nada.
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


def _extrair(url: str) -> dict:
    with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)
    if "entries" in info:  # playlist ou busca: pega o primeiro item
        entradas = [e for e in info["entries"] if e]
        if not entradas:
            raise LookupError(f"nada encontrado para {url!r}")
        info = entradas[0]
    return info
