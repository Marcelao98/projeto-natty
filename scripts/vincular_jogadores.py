"""Vincula os personagens antigos (vindos da planilha, sem Discord ID) e os
condutores das missões aos membros do servidor. Interativo, sem Discord: os
candidatos vêm da tabela jogadores (rode scripts/sincronizar_membros.py antes).

Uso:
    python scripts/vincular_jogadores.py            # só o que ainda está sem vínculo
    python scripts/vincular_jogadores.py --forcar   # também refaz vínculos já existentes

Ao confirmar: grava o campo `nome` do jogador, o jogador_discord_id dos
personagens e o condutor_discord_id das missões cujo condutor bate com o nome.
Condutores que não batem com nenhum jogador são perguntados em seguida.
Mostra o resumo e só grava depois de confirmar (com backup antes).
"""
import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.core import storage  # noqa: E402
from modules.core.service import _chave_nome  # noqa: E402

MAX_CANDIDATOS = 5
# Nome do jogador na planilha → username no Discord, já conhecidos (pede confirmação igual).
SUGESTOES = {"marcelo": "meduardo98"}


@dataclass
class Membro:
    id: str
    username: str | None
    nome_exibicao: str | None
    ativo: bool = True

    @classmethod
    def da_linha(cls, linha: dict) -> "Membro":
        return cls(linha["discord_id"], linha["username"], linha["nome_exibicao"], bool(linha["ativo"]))

    def descricao(self) -> str:
        texto = f"@{self.username or '?'}"
        if self.nome_exibicao and self.nome_exibicao != self.username:
            texto += f" ({self.nome_exibicao})"
        return texto + f"  id {self.id}" + ("" if self.ativo else "  (saiu)")


@dataclass
class Grupo:
    nome: str                                   # como aparece nos registros (primeira grafia)
    personagens: list[dict] = field(default_factory=list)
    missoes: list[dict] = field(default_factory=list)   # em que esse nome é o condutor


# --- sugestão de candidatos ---------------------------------------------------------

def _pontuar(chave: str, membro: Membro) -> int:
    """3 = igual, 2 = começa com, 1 = um contém o outro ou uma palavra do nome
    (3+ letras) aparece no campo, 0 = nada."""
    palavras = [p for p in chave.split() if len(p) >= 3]
    melhor = 0
    for campo in (membro.username, membro.nome_exibicao):
        alvo = _chave_nome(campo or "")
        if not alvo or not chave:
            continue
        if alvo == chave:
            pontos = 3
        elif alvo.startswith(chave) or chave.startswith(alvo):
            pontos = 2
        elif chave in alvo or (len(alvo) >= 3 and alvo in chave) or any(p in alvo for p in palavras):
            pontos = 1
        else:
            pontos = 0
        melhor = max(melhor, pontos)
    return melhor


def candidatos(nome: str, membros: list[Membro], personagens: list[str] = ()) -> list[Membro]:
    """Até MAX_CANDIDATOS membros parecidos com `nome` ou com o nome de um dos
    `personagens` dele (muita gente usa o personagem como apelido no servidor),
    ativos antes de quem saiu, a sugestão conhecida primeiro."""
    chave = _chave_nome(nome)
    chaves = [chave] + [_chave_nome(p) for p in personagens]
    pontuados = sorted(
        ((max(_pontuar(c, m) for c in chaves), m) for m in membros),
        key=lambda pm: (-pm[0], not pm[1].ativo, (pm[1].username or "").casefold()),
    )
    lista = [m for pontos, m in pontuados if pontos > 0]
    sugerido = SUGESTOES.get(chave)
    if sugerido:
        conhecido = next((m for m in membros if (m.username or "").casefold() == sugerido.casefold()), None)
        if conhecido:
            lista = [conhecido] + [m for m in lista if m.id != conhecido.id]
    return lista[:MAX_CANDIDATOS]


def agrupar(personagens: list[dict], missoes: list[dict]) -> tuple[list[Grupo], list[Grupo]]:
    """(jogadores, condutores sem jogador de mesmo nome), agrupados por nome sem
    diferenciar acento e maiúscula. Missão cujo condutor tem o mesmo nome de um
    jogador vai junto com ele."""
    grupos: dict[str, Grupo] = {}
    for p in personagens:
        nome = p["nome_jogador"] or "(sem nome de jogador)"
        grupos.setdefault(_chave_nome(nome), Grupo(nome)).personagens.append(p)
    condutores: dict[str, Grupo] = {}
    for m in missoes:
        chave = _chave_nome(m["condutor_nome"])
        if chave in grupos:
            grupos[chave].missoes.append(m)
        else:
            condutores.setdefault(chave, Grupo(m["condutor_nome"])).missoes.append(m)

    def ordem(g):
        return _chave_nome(g.nome)
    return sorted(grupos.values(), key=ordem), sorted(condutores.values(), key=ordem)


# --- interação ----------------------------------------------------------------------

def perguntar(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        sys.exit("\nEntrada encerrada; nada foi gravado.")


def _resumo_grupo(grupo: Grupo) -> str:
    partes = []
    if grupo.personagens:
        partes.append(f"{len(grupo.personagens)} personagem(ns): " + ", ".join(
            p["nome"] + (f" [já vinculado a {p['jogador_discord_id']}]" if p["jogador_discord_id"] else "")
            for p in grupo.personagens))
    if grupo.missoes:
        partes.append(f"condutor de {len(grupo.missoes)} missão(ões): " + ", ".join(
            m["nome"] + (f" [já vinculada a {m['condutor_discord_id']}]" if m["condutor_discord_id"] else "")
            for m in grupo.missoes))
    return " · ".join(partes)


def achar(texto: str, membros: list[Membro]) -> Membro | None:
    """Membro pelo ID ou username exato (com ou sem @)."""
    alvo = texto.lstrip("@").casefold()
    return next((m for m in membros if m.id == texto or (m.username or "").casefold() == alvo), None)


def escolher(grupo: Grupo, membros: list[Membro]) -> Membro | None:
    print(f"\n=== {grupo.nome} — {_resumo_grupo(grupo)}")
    opcoes = candidatos(grupo.nome, membros, [p["nome"] for p in grupo.personagens])
    sugerido = SUGESTOES.get(_chave_nome(grupo.nome))
    for i, m in enumerate(opcoes, start=1):
        marca = "  ← sugestão" if sugerido and (m.username or "").casefold() == sugerido.casefold() else ""
        print(f"  {i}. {m.descricao()}{marca}")
    if not opcoes:
        print("  (nenhum membro parecido)")
    while True:
        r = perguntar("Número, outro username ou ID, ? lista todos (Enter pula): ")
        if not r:
            return None
        if r == "?":
            for m in membros:
                print(f"     {m.descricao()}")
            continue
        if r.isdigit() and 1 <= int(r) <= len(opcoes):
            return opcoes[int(r) - 1]
        achado = achar(r, membros)
        if achado:
            return achado
        print(f"  {r!r} não está na tabela jogadores. Se a pessoa entrou agora, rode sincronizar_membros.py.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--forcar", action="store_true", help="também mostra e refaz vínculos já existentes")
    args = parser.parse_args()

    storage.inicializar()
    membros = [Membro.da_linha(j) for j in storage.listar_jogadores() if j["username"]]
    if not membros:
        sys.exit("A tabela jogadores está vazia. Rode antes: python scripts/sincronizar_membros.py")

    personagens = [p for p in storage.listar_personagens() if args.forcar or p["jogador_discord_id"] is None]
    missoes = [
        m for m in storage.listar_missoes()
        if m["condutor_nome"] and (args.forcar or m["condutor_discord_id"] is None)
    ]
    jogadores, condutores = agrupar(personagens, missoes)
    if not jogadores and not condutores:
        print("Nada sem vínculo. (Use --forcar pra refazer vínculos.)")
        return
    print(f"{len(membros)} membros na tabela. Pra vincular: {len(personagens)} personagens de "
          f"{len(jogadores)} jogadores e {len(missoes)} missões.")

    print("\n--- Jogadores ---")
    escolhas = [(g, m) for g in jogadores if (m := escolher(g, membros))]
    if condutores:
        print("\n--- Condutores que não batem com nenhum jogador acima ---")
        escolhas += [(g, m) for g in condutores if (m := escolher(g, membros))]
    if not escolhas:
        print("\nNinguém escolhido; nada foi gravado.")
        return

    print("\nResumo:")
    for g, m in escolhas:
        print(f"  {g.nome} -> @{m.username} -> {m.id} -> {len(g.personagens)} personagem(ns), "
              f"{len(g.missoes)} missão(ões) como condutor")
    escolhidos = [g for g, _ in escolhas]
    pulados = [g.nome for g in jogadores + condutores if g not in escolhidos]
    if pulados:
        print(f"  Pulados: {', '.join(pulados)}")
    if perguntar("\nGravar? Digite 'sim' pra confirmar: ").lower() != "sim":
        sys.exit("Nada foi gravado.")

    print(f"Backup: {storage.fazer_backup('vincular')}")
    n_personagens = n_missoes = 0
    with storage.transacao() as con:
        for g, m in escolhas:
            if g.personagens:  # condutor sem personagem não ganha `nome` de jogador
                storage.salvar_jogador(m.id, None, None, nome=g.nome, con=con)
            n_personagens += storage.vincular_personagens(
                [p["id"] for p in g.personagens], m.id, forcar=args.forcar, con=con
            )
            n_missoes += storage.vincular_condutor(
                [x["id"] for x in g.missoes], m.id, forcar=args.forcar, con=con
            )
    print(f"Pronto: {n_personagens} personagens e {n_missoes} missões vinculados.")

    sem_condutor = [m for m in storage.listar_missoes() if m["condutor_nome"] and not m["condutor_discord_id"]]
    if sem_condutor:
        print("\nMissões com condutor ainda sem correspondência:")
        for m in sem_condutor:
            print(f"  {m['nome']} (condutor: {m['condutor_nome']})")


if __name__ == "__main__":
    main()
