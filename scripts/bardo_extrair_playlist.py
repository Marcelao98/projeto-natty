"""Extrai uma playlist do YouTube para um arquivo de staging do Bardo.

Cada faixa sai no formato do musicas.json, com temas ["não classificado"]
pra serem tagueados à mão antes do merge (scripts/bardo_mesclar_dataset.py).
O nome da faixa é limpo do lixo comum de título do YouTube: prefixo
"<Jogo> OST - ", numeração ("01 "), "【Audio】" e o parêntese
"(... Original Soundtrack)".

Uso:
  python scripts/bardo_extrair_playlist.py <url da playlist> \
      --origem-nome "Hollow Knight" --origem-tipo jogo \
      --saida staging/hollow_knight.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yt_dlp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.bardo.service import NAO_CLASSIFICADO, slug  # noqa: E402

_TITULOS_INDISPONIVEIS = {"[deleted video]", "[private video]"}


def limpar_titulo(titulo: str) -> str:
    """Tira do título do YouTube o que não é nome da faixa."""
    t = re.sub(r"【[^】]*】", "", titulo)
    # "(NieR:Automata Original Soundtrack)" — às vezes sem o ")" de fechar.
    t = re.sub(r"\([^()]*Original Soundtrack[^()]*(\)|$)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^.*?\bOST\s*-\s*", "", t)
    t = re.sub(r"^\d{1,3}\s+", "", t.strip())
    return re.sub(r"\s{2,}", " ", t).strip(" -")


def listar_playlist(url: str) -> list[tuple[str, str]]:
    """(título, video_id) de cada vídeo disponível da playlist, em ordem."""
    opts = {"extract_flat": "in_playlist", "quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return [
        (e.get("title") or "", e["id"])
        for e in info.get("entries") or []
        if e and e.get("id") and (e.get("title") or "").lower() not in _TITULOS_INDISPONIVEIS
    ]


def montar_faixas(videos: list[tuple[str, str]], origem_nome: str, origem_tipo: str) -> list[dict]:
    faixas, ids = [], set()
    for titulo, video_id in videos:
        nome = limpar_titulo(titulo) or titulo
        # "White Defender (Hollow Knight: Hidden Dreams)" não repete a origem no id.
        base = f"{slug(origem_nome)}-{slug(nome).replace(slug(origem_nome) + '-', '')}"
        id_, n = base, 2
        while id_ in ids:  # mesma faixa em dois arranjos/álbuns
            id_, n = f"{base}-{n}", n + 1
        ids.add(id_)
        faixas.append({
            "id": id_,
            "nome": nome,
            "link": f"https://www.youtube.com/watch?v={video_id}",
            "escopo": "faixa_individual",
            "origem": {"nome": origem_nome, "tipo": origem_tipo},
            "temas": [NAO_CLASSIFICADO],
            "comentario_pessoal": "",
        })
    return faixas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--origem-nome", required=True)
    parser.add_argument("--origem-tipo", required=True, help="jogo, anime, visual novel...")
    parser.add_argument("--saida", required=True, type=Path)
    args = parser.parse_args()

    faixas = montar_faixas(listar_playlist(args.url), args.origem_nome, args.origem_tipo)
    if not faixas:
        sys.exit("Nenhuma faixa disponível na playlist.")
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    staging = {
        "_comentario": f"Staging do Bardo: {args.origem_nome}. Troque 'não classificado' "
                       "por 2-5 temas por faixa e rode scripts/bardo_mesclar_dataset.py.",
        "musicas": faixas,
    }
    args.saida.write_text(json.dumps(staging, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(faixas)} faixas -> {args.saida}")


if __name__ == "__main__":
    main()
