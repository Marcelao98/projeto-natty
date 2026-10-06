"""Preenche o campo 'categorias' de cada faixa do dataset do Bardo.

As categorias saem dos temas crus da faixa, segundo
modules/bardo/dataset/vocabulario.json. Categorias que já estão na faixa
são mantidas (dá pra acrescentar à mão, ex: "taverna" numa faixa que o
vocabulário não pegou); pra tirar uma, apaga à mão no musicas.json.

Rodar de novo sempre que mexer no vocabulário ou acrescentar faixas.
Uso: python scripts/categorizar_musicas.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.bardo.service import (  # noqa: E402
    _DATASET_PATH, carregar_vocabulario, categorias_dos_temas, formatar_dataset,
)


def main() -> None:
    dataset = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    vocabulario = carregar_vocabulario()
    sem_categoria = []
    for m in dataset["musicas"]:
        m["categorias"] = sorted(set(m.get("categorias", [])) | set(categorias_dos_temas(m["temas"], vocabulario)))
        if not m["categorias"]:
            sem_categoria.append(m["nome"])
    _DATASET_PATH.write_text(formatar_dataset(dataset), encoding="utf-8")

    print(f"{len(dataset['musicas'])} faixas categorizadas; {len(sem_categoria)} sem nenhuma categoria.")
    for nome in sem_categoria:
        print(f"  - {nome}")


if __name__ == "__main__":
    main()
