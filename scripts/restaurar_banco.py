"""Restaura o banco do NAT-CORE (data/natty.db) a partir de um backup.

Uso:
    python scripts/restaurar_banco.py                 # oferece o backup mais recente
    python scripts/restaurar_banco.py --arquivo X.db  # restaura um backup específico

Pra quando a Natty não sobe com "BANCO ILEGÍVEL". O arquivo atual não é
apagado: vai pra data/natty.ilegivel-<data>.db. Pede confirmação antes.
Depois, reinicie a Natty (scripts/reiniciar_natty.ps1).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.core import storage  # noqa: E402


def _descrever(caminho: Path) -> str:
    try:
        r = storage.resumo_do_arquivo(caminho)
    except Exception as exc:
        return f"ILEGÍVEL ({exc})"
    return f"{r['jogadores']} jogadores, {r['personagens']} personagens, {r['missoes']} missões"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arquivo", type=Path, help="backup a restaurar (padrão: o mais recente)")
    args = parser.parse_args()

    atual = storage.caminho_banco()
    print(f"Banco atual: {atual}")
    print(f"  {_descrever(atual) if atual.exists() else 'NÃO EXISTE'}")

    disponiveis = storage.backups()
    if args.arquivo:
        origem = args.arquivo
    elif disponiveis:
        print("\nÚltimos backups:")
        for b in disponiveis[-5:]:
            print(f"  {b.name}: {_descrever(b)}")
        origem = disponiveis[-1]
    else:
        sys.exit(f"Nenhum backup em {storage.pasta_backups()}.")

    if not origem.exists():
        sys.exit(f"{origem} não existe.")
    print(f"\nRestaurar: {origem.name} — {_descrever(origem)}")
    try:
        resposta = input("Digite 'sim' pra restaurar: ").strip().lower()
    except EOFError:
        resposta = ""
    if resposta != "sim":
        sys.exit("Nada foi alterado.")

    guardado = storage.restaurar_backup(origem)
    if guardado:
        print(f"Arquivo anterior guardado em {guardado}")
    print(f"Restaurado: {_descrever(atual)}")
    print("Agora reinicie a Natty: powershell -ExecutionPolicy Bypass -File scripts/reiniciar_natty.ps1")


if __name__ == "__main__":
    main()
