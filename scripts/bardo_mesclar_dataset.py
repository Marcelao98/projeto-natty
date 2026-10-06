"""Mescla um arquivo de staging (bardo_extrair_playlist.py) no musicas.json.

Pula faixa que já existe no dataset: mesmo vídeo do YouTube, mesmo id, ou
mesmo nome dentro da mesma origem (a faixa pode estar lá com outro upload).
As categorias das faixas novas saem dos temas, via vocabulario.json — igual
ao scripts/categorizar_musicas.py.

Uso:
  python scripts/bardo_mesclar_dataset.py staging/hollow_knight.json --dry-run
  python scripts/bardo_mesclar_dataset.py staging/hollow_knight.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.bardo.service import (  # noqa: E402
    _DATASET_PATH, _normalizar, carregar_vocabulario, categorias_dos_temas, formatar_dataset, video_id,
)

_CAMPOS_OBRIGATORIOS = {"id", "nome", "link", "escopo", "origem", "temas"}


def _chave_nome(m: dict) -> tuple[str, str]:
    return _normalizar(m["origem"]["nome"]), _normalizar(m["nome"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("staging", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="só mostra o que entraria")
    args = parser.parse_args()

    dataset = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    novas = json.loads(args.staging.read_text(encoding="utf-8"))["musicas"]

    videos = {video_id(m["link"]) for m in dataset["musicas"]}
    ids = {m["id"] for m in dataset["musicas"]}
    nomes = {_chave_nome(m) for m in dataset["musicas"]}
    vocabulario = carregar_vocabulario()

    entram, puladas = [], []
    for m in novas:
        faltando = _CAMPOS_OBRIGATORIOS - m.keys()
        if faltando:
            sys.exit(f"Faixa {m.get('id', '?')} sem os campos {sorted(faltando)}.")
        video = video_id(m["link"])
        if video in videos or m["id"] in ids or _chave_nome(m) in nomes:
            puladas.append(m)
            continue
        m["categorias"] = categorias_dos_temas(m["temas"], vocabulario)
        m.setdefault("comentario_pessoal", "")
        videos.add(video)
        ids.add(m["id"])
        nomes.add(_chave_nome(m))
        entram.append(m)

    sem_tema = [m for m in entram if m["temas"] == ["não classificado"]]
    print(f"{args.staging}: {len(novas)} no staging, {len(entram)} entram, {len(puladas)} já existiam.")
    for m in puladas:
        print(f"  = pulada (duplicada): {m['nome']}")
    print(f"  {len(sem_tema)} entram como 'não classificado'.")
    for m in sem_tema:
        print(f"  ? {m['nome']}")

    if args.dry_run:
        print("(dry-run: nada foi gravado)")
        return
    dataset["musicas"].extend(entram)
    _DATASET_PATH.write_text(formatar_dataset(dataset), encoding="utf-8")
    print(f"Dataset agora com {len(dataset['musicas'])} faixas.")


if __name__ == "__main__":
    main()
