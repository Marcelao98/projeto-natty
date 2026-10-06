"""Copia TODOS os membros do servidor (sem bots) pra tabela jogadores do banco.

Uso:
    python scripts/sincronizar_membros.py

Cria os novos, atualiza username e apelido dos existentes e marca ativo=0 em
quem saiu (ninguém é apagado). Rode antes do vincular_jogadores.py.
A Natty também faz isso sozinha toda vez que conecta (on_ready do core).

Precisa do "Server Members Intent" ligado no portal do Discord.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from modules.core import service, storage  # noqa: E402

load_dotenv()

AJUDA_INTENT = """
O Discord recusou a lista de membros: o "Server Members Intent" está desligado.
Pra ligar:
  1. https://discord.com/developers/applications → escolha a aplicação da Natty
  2. Aba "Bot" → seção "Privileged Gateway Intents"
  3. Ligue "Server Members Intent" e clique em "Save Changes"
Depois rode este script de novo.
"""


class IntentDesligado(Exception):
    pass


async def _buscar_membros(token: str, guild_id: int | None) -> tuple[str, list[dict]]:
    """(nome do servidor, membros sem bots), buscando TODOS pela API (paginado)."""
    import discord

    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True
    # Sem chunk na partida: a lista vem do fetch_members, não do cache.
    client = discord.Client(intents=intents, chunk_guilds_at_startup=False)
    resultado: dict = {}

    @client.event
    async def on_ready():
        try:
            if guild_id:
                guild = client.get_guild(guild_id)
                if guild is None:
                    raise RuntimeError(f"O bot não está no servidor GUILD_ID={guild_id}.")
            elif len(client.guilds) == 1:
                guild = client.guilds[0]
            else:
                nomes = ", ".join(f"{g.name} ({g.id})" for g in client.guilds)
                raise RuntimeError(
                    f"O bot está em {len(client.guilds)} servidores; defina GUILD_ID no .env. Servidores: {nomes}"
                )
            membros = [m async for m in guild.fetch_members(limit=None)]
            resultado["servidor"] = guild.name
            resultado["membros"] = [
                {"discord_id": str(m.id), "username": m.name, "nome_exibicao": m.display_name}
                for m in membros if not m.bot
            ]
        except discord.Forbidden as exc:
            resultado["erro"] = IntentDesligado(str(exc))
        except Exception as exc:
            resultado["erro"] = exc
        finally:
            await client.close()

    try:
        await client.start(token)
    except discord.PrivilegedIntentsRequired as exc:
        raise IntentDesligado() from exc
    except discord.LoginFailure as exc:
        raise RuntimeError("O Discord recusou o DISCORD_TOKEN do .env (token inválido?).") from exc
    if "erro" in resultado:
        raise resultado["erro"]
    return resultado["servidor"], resultado["membros"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        sys.exit("DISCORD_TOKEN não está no .env.")
    guild_id = os.getenv("GUILD_ID", "").strip()

    print("Conectando ao Discord pra buscar os membros…")
    try:
        servidor, membros = asyncio.run(_buscar_membros(token, int(guild_id) if guild_id else None))
    except IntentDesligado:
        sys.exit(AJUDA_INTENT)
    except Exception as exc:  # nunca imprime o token; só a mensagem do erro
        sys.exit(f"Não consegui buscar os membros: {exc}")
    print(f"Servidor: {servidor} — {len(membros)} membros (sem bots)")

    storage.inicializar()
    try:
        r = service.sincronizar_membros(membros)
    except ValueError as exc:
        sys.exit(str(exc))

    print(f"\nNovos: {r['novos']} · Atualizados: {r['atualizados']} · Saíram: {r['saíram']} · Total no servidor: {r['total']}")

    jogadores = storage.listar_jogadores()
    larg_id = max((len(j["discord_id"]) for j in jogadores), default=2)
    larg_user = max((len(j["username"] or "") for j in jogadores), default=8)
    for titulo, ativo in (("No servidor", 1), ("Saíram (continuam no banco)", 0)):
        grupo = [j for j in jogadores if j["ativo"] == ativo]
        if not grupo:
            continue
        print(f"\n{titulo} ({len(grupo)}):")
        print(f"  {'ID'.ljust(larg_id)}  {'username'.ljust(larg_user)}  apelido")
        for j in grupo:
            print(f"  {j['discord_id'].ljust(larg_id)}  {(j['username'] or '-').ljust(larg_user)}  {j['nome_exibicao'] or '-'}")


if __name__ == "__main__":
    main()
