"""Atualiza o nível atual dos personagens no banco (data/natty.db) a partir do DiceCloud.

Uso: python scripts/sincronizar_niveis.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.core.service import sincronizar_niveis_atuais  # noqa: E402


def main():
    r = sincronizar_niveis_atuais()
    print(
        f"{r['atualizados']} atualizados, {r['pulados']} pulados (não DiceCloud), "
        f"{len(r['falhas'])} falharam"
    )
    for nome in r["falhas"]:
        print(f"  - falhou: {nome}")


if __name__ == "__main__":
    main()
