"""Exporta tracklists de playlists do YouTube para data/<nome>_tracklist.txt.

Formato de cada linha: titulo|||video_id (UTF-8).
Uso: python scripts/exportar_tracklists.py
"""
from pathlib import Path

import yt_dlp

PLAYLISTS = {
    "umineko": "PLWCkhGoFcFiykjjC8UtB20DoVMWgVyQIL",
    "subahibi": "PLkxF_HGSsNJbJaTi_PYIjJJD_kokUzNiU",
    "elden_ring": "PLTmJuovQUxPuSYfrtCgpsLwQOeRXSkFzp",
    "bloodborne": "PLCLeSTzz6trY_Qn_8vMnqO9TbqesAM4x6",
    "fe3h": "PLzXrrIvqJ7v7pqgKkvzfceZBC9iY3WR5R",
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def exportar(nome: str, playlist_id: str) -> int:
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    opts = {"extract_flat": "in_playlist", "quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    linhas = [
        f"{e.get('title')}|||{e.get('id')}"
        for e in info.get("entries") or []
        if e and e.get("id")
    ]
    destino = DATA_DIR / f"{nome}_tracklist.txt"
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return len(linhas)


if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    for nome, playlist_id in PLAYLISTS.items():
        try:
            total = exportar(nome, playlist_id)
            print(f"{nome}: {total} faixas -> data/{nome}_tracklist.txt")
        except Exception as erro:
            print(f"{nome}: FALHOU ({erro})")
