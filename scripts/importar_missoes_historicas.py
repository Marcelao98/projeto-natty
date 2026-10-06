"""Importa as missões históricas (posts do canal de missões do Discord) pro banco.

Uso:
    python scripts/importar_missoes_historicas.py                        # dry-run: só mostra
    python scripts/importar_missoes_historicas.py --decisoes d.json      # dry-run com as respostas
    python scripts/importar_missoes_historicas.py --decisoes d.json --aplicar   # grava (backup antes)

Regras:
- Missão que já existe (mesmo nome sem acento/maiúscula, ou ligada em
  "mesma_missao"): os participantes NÃO são tocados. Só preenche campos vazios
  (relato, resultado, xp, gold, outras_recompensas, observacoes e
  condutor_discord_id). Campo que já tem valor diferente é conflito: fica como
  está, a não ser que a decisão diga "arquivo".
- Missão nova: insere, com os participantes resolvidos pela tabela jogadores.
  Se uma existente tiver a mesma data e dificuldade sem bater o nome, é
  "possível mesma missão" e espera decisão.
- Data DD/MM/AAAA vira ISO; data nula espera decisão em "datas".
- "xp_nota" vai pro fim de observacoes ("Nota de XP: ...").
- Participante sem personagem registrado (ex: Lucy) é gravado só com o nome
  e listado no fim pra cadastrar depois. Jogador com mais de um personagem e
  post sem dizer qual é ambíguo: espera decisão em "personagens".
- --aplicar só grava se não houver pendência. Idempotente: a missão inserida
  passa a existir e, sem campo vazio, a segunda rodada não muda nada.

Arquivo de decisões (JSON, chaves opcionais; nomes de missão e menções são
comparados sem acento e maiúscula):
    {
      "datas":        {"O Que Sobra em Nhalor": "24/09/2026"},
      "mesma_missao": {"O Neto de Tholu": "Vovó está preocupada"},
      "personagens":  {"O Navio que Grita": {"Tavi": "Orin"}},
      "conflitos":    {"O Prefeito-Cavalo": {"relato": "manter"}}
    }
"mesma_missao" com null = é missão nova mesmo. Conflito: "manter" (fica o do
banco) ou "arquivo" (troca pelo do arquivo).
"""
import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.core import storage  # noqa: E402
from modules.core.service import _chave_nome  # noqa: E402

ARQUIVO_PADRAO = Path("data/importacao/missoes_historicas.json")
CAMPOS = ("relato", "resultado", "xp", "gold", "outras_recompensas", "observacoes")
DIFICULDADES = ("Trivial", "Fácil", "Normal", "Difícil", "Extrema")
_NAO_DECIDIU = object()


# --- conversões -----------------------------------------------------------------

def data_iso(texto: str | None) -> str | None:
    """'03/09/2026' → '2026-09-03'; vazio → None; fora do formato → ValueError."""
    if texto is None or not str(texto).strip():
        return None
    return datetime.strptime(str(texto).strip(), "%d/%m/%Y").date().isoformat()


def momento_iso(texto: str | None) -> str | None:
    """'24/09/2026 20:27' → '2026-09-24T20:27:00'; vazio → None."""
    if texto is None or not str(texto).strip():
        return None
    return datetime.strptime(str(texto).strip(), "%d/%m/%Y %H:%M").isoformat(timespec="seconds")


def _vazio(valor) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def _igual(a, b) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return str(a).strip() == str(b).strip()
    return a == b


def campos_do_arquivo(missao: dict) -> dict:
    """Os CAMPOS da missão, com texto aparado e o xp_nota no fim de observacoes."""
    campos = {}
    for chave in CAMPOS:
        valor = missao.get(chave)
        campos[chave] = (valor.strip() or None) if isinstance(valor, str) else valor
    nota = (missao.get("xp_nota") or "").strip()
    if nota:
        extra = f"Nota de XP: {nota}"
        campos["observacoes"] = f"{campos['observacoes']}\n\n{extra}" if campos["observacoes"] else extra
    return campos


# --- decisões -------------------------------------------------------------------

class Decisoes:
    def __init__(self, dados: dict | None = None):
        dados = dados or {}
        self.datas = self._por_chave(dados.get("datas"))
        self.mesma_missao = self._por_chave(dados.get("mesma_missao"))
        self.personagens = {k: self._por_chave(v) for k, v in self._por_chave(dados.get("personagens")).items()}
        self.conflitos = self._por_chave(dados.get("conflitos"))

    @staticmethod
    def _por_chave(d) -> dict:
        return {_chave_nome(k): v for k, v in (d or {}).items()}

    def data(self, missao: str):
        return self.datas.get(_chave_nome(missao))

    def mesma(self, missao: str):
        return self.mesma_missao.get(_chave_nome(missao), _NAO_DECIDIU)

    def personagem(self, missao: str, mencao: str):
        return self.personagens.get(_chave_nome(missao), {}).get(_chave_nome(mencao))

    def conflito(self, missao: str, campo: str):
        return (self.conflitos.get(_chave_nome(missao)) or {}).get(campo)


# --- resolução de jogador e personagem ---------------------------------------------

@dataclass
class Resolucao:
    jogador: dict | None
    como: str  # exato | parcial | via personagem | ambíguo | não encontrado
    personagem: dict | None = None  # quando veio "via personagem"
    candidatos: list = field(default_factory=list)


def _nomes(jogador: dict) -> list[str]:
    return [_chave_nome(jogador[k]) for k in ("username", "nome_exibicao") if jogador.get(k)]


def resolver_jogador(mencao: str, jogadores: list[dict], personagens: list[dict]) -> Resolucao:
    """Menção do post (nome de exibição) → jogador. Tenta, nesta ordem: igual ao
    username ou apelido; contido num deles (ou contendo, 3+ letras); e, se nada
    bater, igual ao nome de um personagem registrado (o dono é o jogador)."""
    chave = _chave_nome(mencao)
    exatos = [j for j in jogadores if chave in _nomes(j)]
    if len(exatos) == 1:
        return Resolucao(exatos[0], "exato")
    if exatos:
        return Resolucao(None, "ambíguo", candidatos=exatos)

    parciais = [
        j for j in jogadores
        if any((len(chave) >= 3 and chave in n) or (len(n) >= 3 and n in chave) for n in _nomes(j))
    ]
    if len(parciais) == 1:
        return Resolucao(parciais[0], "parcial")
    if parciais:
        return Resolucao(None, "ambíguo", candidatos=parciais)

    donos = [p for p in personagens if _chave_nome(p["nome"]) == chave and p["jogador_discord_id"]]
    if len(donos) == 1:
        jogador = next((j for j in jogadores if j["discord_id"] == donos[0]["jogador_discord_id"]), None)
        if jogador:
            return Resolucao(jogador, "via personagem", personagem=donos[0])
    return Resolucao(None, "não encontrado")


def _bate_personagem(chave: str, personagem: dict) -> bool:
    nome = _chave_nome(personagem["nome"])
    return chave == nome or chave in nome.split() or (len(chave) >= 3 and chave in nome)


def resolver_personagem(nome_post: str | None, res: Resolucao, personagens: list[dict]) -> tuple:
    """(status, personagem ou None, nome a gravar). status: ok | ambíguo |
    não encontrado | sem jogador | sem nome."""
    if res.jogador is None:
        return ("sem jogador", None, nome_post)
    do_jogador = [p for p in personagens if p["jogador_discord_id"] == res.jogador["discord_id"]]
    if nome_post:
        chave = _chave_nome(nome_post)
        exatos = [p for p in do_jogador if _chave_nome(p["nome"]) == chave]
        achados = exatos or [p for p in do_jogador if _bate_personagem(chave, p)]
        if len(achados) == 1:
            return ("ok", achados[0], achados[0]["nome"])
        if achados:
            return ("ambíguo", None, nome_post)
        return ("não encontrado", None, nome_post)
    if res.personagem:
        return ("ok", res.personagem, res.personagem["nome"])
    if len(do_jogador) == 1:
        return ("ok", do_jogador[0], do_jogador[0]["nome"])
    if do_jogador:
        return ("ambíguo", None, None)
    return ("sem nome", None, None)


# --- plano ----------------------------------------------------------------------

@dataclass
class Participante:
    mencao: str
    jogador: str
    como: str
    status: str
    personagem_id: int | None
    personagem_nome: str | None
    opcoes: list[str] = field(default_factory=list)


@dataclass
class Acao:
    nome: str
    tipo: str  # atualizar | inserir
    banco: dict | None = None
    preencher: dict = field(default_factory=dict)
    sobrescrever: dict = field(default_factory=dict)
    conflitos: list = field(default_factory=list)  # (campo, banco, arquivo, decisão)
    dados: dict | None = None
    participantes: list = field(default_factory=list)
    condutor: Resolucao | None = None
    pendencias: list = field(default_factory=list)
    avisos: list = field(default_factory=list)


def _descrever(jogador: dict | None) -> str:
    if not jogador:
        return "?"
    apelido = jogador.get("nome_exibicao")
    return f"@{jogador['username']}" + (f" ({apelido})" if apelido and apelido != jogador["username"] else "")


def _condutor_nome(jogador: dict, banco: list[dict]) -> str:
    """O nome que as missões antigas já usam pra esse condutor; senão o do jogador."""
    usado = next((m["condutor_nome"] for m in banco
                  if m["condutor_discord_id"] == jogador["discord_id"] and m["condutor_nome"]), None)
    return usado or jogador.get("nome") or jogador.get("nome_exibicao") or jogador["username"]


def planejar(arquivo: list[dict], banco: list[dict], jogadores: list[dict],
             personagens: list[dict], decisoes: Decisoes) -> list[Acao]:
    por_chave = {m["nome_chave"]: m for m in banco}
    casadas_por_nome = {_chave_nome(m["nome"]) for m in arquivo} & set(por_chave)
    vistas = set()
    acoes = []

    for m in arquivo:
        nome = m["nome"]
        chave = _chave_nome(nome)
        decidido = decisoes.mesma(nome)
        if chave in vistas:
            acao = Acao(nome, "inserir")
            acao.pendencias.append("nome repetido no arquivo")
            acoes.append(acao)
            continue
        vistas.add(chave)

        if decidido is None:
            existente = None
        elif decidido is not _NAO_DECIDIU:
            existente = por_chave.get(_chave_nome(decidido))
            if existente is None:
                acao = Acao(nome, "atualizar")
                acao.pendencias.append(f'"mesma_missao" aponta pra «{decidido}», que não existe no banco')
                acoes.append(acao)
                continue
        else:
            existente = por_chave.get(chave)

        condutor = resolver_jogador(m.get("condutor") or "", jogadores, personagens)
        if existente:
            acoes.append(_planejar_atualizacao(m, existente, condutor, decisoes))
        else:
            acao = _planejar_insercao(m, banco, jogadores, personagens, condutor, decisoes)
            if decidido is _NAO_DECIDIU:
                for b in banco:
                    if (b["nome_chave"] not in casadas_por_nome and b["data"] == acao.dados["data"]
                            and b["dificuldade"] == m.get("dificuldade")):
                        acao.pendencias.append(
                            f"possível mesma missão que «{b['nome']}» (id {b['id']}, {b['data']}, "
                            f"{b['dificuldade']}): diga em \"mesma_missao\" se é a mesma ou null se é nova"
                        )
            acoes.append(acao)
    return acoes


def _planejar_atualizacao(m: dict, existente: dict, condutor: Resolucao, decisoes: Decisoes) -> Acao:
    acao = Acao(m["nome"], "atualizar", banco=existente, condutor=condutor)
    for campo, valor in campos_do_arquivo(m).items():
        atual = existente[campo]
        if _vazio(valor) or _igual(atual, valor):
            continue
        if _vazio(atual):
            acao.preencher[campo] = valor
            continue
        decisao = decisoes.conflito(m["nome"], campo)
        acao.conflitos.append((campo, atual, valor, decisao))
        if decisao == "arquivo":
            acao.sobrescrever[campo] = valor
        elif decisao != "manter":
            acao.pendencias.append(f'conflito em "{campo}": decida "manter" ou "arquivo"')

    if condutor.jogador:
        if _vazio(existente["condutor_discord_id"]):
            acao.preencher["condutor_discord_id"] = condutor.jogador["discord_id"]
        elif existente["condutor_discord_id"] != condutor.jogador["discord_id"]:
            acao.avisos.append(
                f"condutor no banco ({existente['condutor_discord_id']}) diferente do post "
                f"({_descrever(condutor.jogador)}); mantido o do banco"
            )
    elif _vazio(existente["condutor_discord_id"]):
        acao.avisos.append(f"condutor «{m.get('condutor')}» não encontrado; fica sem vínculo")

    try:
        data = data_iso(m.get("data"))
    except ValueError:
        data = m.get("data")
    if data and existente["data"] and data != existente["data"]:
        acao.avisos.append(f"data diferente: banco {existente['data']}, post {data} (mantida a do banco)")
    if m.get("dificuldade") and m["dificuldade"] != existente["dificuldade"]:
        acao.avisos.append(
            f"dificuldade diferente: banco {existente['dificuldade']}, post {m['dificuldade']} (mantida a do banco)"
        )
    if _chave_nome(m["nome"]) != existente["nome_chave"]:
        acao.avisos.append(f"o nome no banco continua «{existente['nome']}»")
    return acao


def _planejar_insercao(m: dict, banco: list[dict], jogadores: list[dict], personagens: list[dict],
                       condutor: Resolucao, decisoes: Decisoes) -> Acao:
    nome = m["nome"]
    acao = Acao(nome, "inserir", condutor=condutor)

    data = None
    try:
        data = data_iso(m.get("data")) or data_iso(decisoes.data(nome))
    except ValueError as exc:
        acao.pendencias.append(f"data inválida: {exc}")
    if data is None and not acao.pendencias:
        postado = f" (postado em {m['postado_em']})" if m.get("postado_em") else ""
        acao.pendencias.append(f'sem data{postado}: informe em "datas" (DD/MM/AAAA)')

    if m.get("dificuldade") not in DIFICULDADES:
        acao.pendencias.append(f"dificuldade inválida: {m.get('dificuldade')!r}")
    if condutor.jogador is None:
        acao.pendencias.append(f"condutor «{m.get('condutor')}» não encontrado ({condutor.como})")

    for v in m.get("viajantes_post") or []:
        mencao = v.get("mencao") or ""
        res = resolver_jogador(mencao, jogadores, personagens)
        nome_post = decisoes.personagem(nome, mencao) or v.get("personagem")
        status, personagem, nome_gravado = resolver_personagem(nome_post, res, personagens)
        opcoes = []
        if status == "ambíguo" and res.jogador:
            opcoes = [p["nome"] for p in personagens if p["jogador_discord_id"] == res.jogador["discord_id"]]
        acao.participantes.append(Participante(
            mencao, _descrever(res.jogador), res.como, status,
            personagem["id"] if personagem else None, nome_gravado, opcoes,
        ))
        if status == "ambíguo":
            acao.pendencias.append(
                f"«{mencao}» tem mais de um personagem ({', '.join(opcoes) or '?'}): "
                f'diga qual em "personagens"'
            )
        elif status == "sem jogador":
            acao.pendencias.append(f"«{mencao}» não bate com nenhum jogador ({res.como})")
        elif status == "sem nome":
            acao.pendencias.append(f"«{mencao}» não tem personagem registrado e o post não diz o nome")

    dados = {
        "criado_em": momento_iso(m.get("postado_em")) or storage.agora(),
        "nome": nome,
        "nome_chave": _chave_nome(nome),
        "data": data,
        "dificuldade": m.get("dificuldade"),
        "condutor_discord_id": condutor.jogador["discord_id"] if condutor.jogador else None,
        "condutor_nome": _condutor_nome(condutor.jogador, banco) if condutor.jogador else m.get("condutor"),
    }
    dados.update(campos_do_arquivo(m))
    acao.dados = dados
    return acao


# --- saída ----------------------------------------------------------------------

def _curto(valor, n: int = 70) -> str:
    texto = " ".join(str(valor).split())
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def imprimir(acoes: list[Acao]) -> None:
    for i, a in enumerate(acoes, 1):
        print(f"\n[{i}] {a.nome} — {a.tipo.upper()}"
              + (f" (id {a.banco['id']}, «{a.banco['nome']}»)" if a.banco else ""))
        if a.tipo == "atualizar":
            for campo, valor in a.preencher.items():
                print(f"    preenche {campo}: {_curto(valor)}")
            for campo, atual, novo, decisao in a.conflitos:
                dica = " — o texto do arquivo está contido no do banco" \
                    if isinstance(atual, str) and isinstance(novo, str) and novo.strip() in atual else ""
                print(f"    CONFLITO {campo} [{decisao or 'sem decisão'}]{dica}")
                print(f"        banco   ({len(str(atual))} car.): {_curto(atual)}")
                print(f"        arquivo ({len(str(novo))} car.): {_curto(novo)}")
            if not a.preencher and not a.sobrescrever:
                print("    nada a preencher")
        elif a.dados:
            d = a.dados
            print(f"    data {d['data'] or '?'} · {d['dificuldade']} · condutor {d['condutor_nome']} "
                  f"({_descrever(a.condutor.jogador) if a.condutor else '?'}) · xp {d['xp']} · gold {d['gold']}")
            print(f"    {'menção':<16} {'jogador':<32} {'como':<15} personagem")
            for p in a.participantes:
                alvo = {"ok": f"{p.personagem_nome} (id {p.personagem_id})",
                        "não encontrado": f"{p.personagem_nome} — NÃO REGISTRADO (fica sem id)",
                        "ambíguo": f"AMBÍGUO: {' / '.join(p.opcoes)}",
                        }.get(p.status, p.status.upper())
                print(f"    {p.mencao:<16} {p.jogador:<32} {p.como:<15} {alvo}")
        if a.condutor and a.tipo == "atualizar" and "condutor_discord_id" in a.preencher:
            print(f"    condutor → {_descrever(a.condutor.jogador)} ({a.condutor.como})")
        for aviso in a.avisos:
            print(f"    aviso: {aviso}")
        for pendencia in a.pendencias:
            print(f"    PENDENTE: {pendencia}")


def resumo(acoes: list[Acao]) -> dict:
    sem_personagem = [(a.nome, p.personagem_nome or p.mencao) for a in acoes
                      for p in a.participantes if p.personagem_id is None and p.status == "não encontrado"]
    return {
        "atualizar": sum(1 for a in acoes if a.tipo == "atualizar" and (a.preencher or a.sobrescrever)),
        "inserir": sum(1 for a in acoes if a.tipo == "inserir"),
        "sem_personagem": sem_personagem,
        "pendencias": [(a.nome, p) for a in acoes for p in a.pendencias],
    }


def aplicar(acoes: list[Acao]) -> dict:
    """Grava tudo numa transação (backup antes). Retorna as contagens reais."""
    print(f"\nBackup: {storage.fazer_backup('importar-missoes')}")
    atualizadas = inseridas = 0
    with storage.transacao() as con:
        for a in acoes:
            if a.tipo == "atualizar":
                feitos = storage.preencher_missao(a.banco["id"], a.preencher, con=con)
                if a.sobrescrever:
                    storage.sobrescrever_missao(a.banco["id"], a.sobrescrever, con=con)
                atualizadas += bool(feitos or a.sobrescrever)
            else:
                storage.inserir_missao(
                    a.dados, [(p.personagem_id, p.personagem_nome) for p in a.participantes], con=con
                )
                inseridas += 1
    return {"atualizadas": atualizadas, "inseridas": inseridas}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arquivo", type=Path, default=ARQUIVO_PADRAO, help=f"padrão: {ARQUIVO_PADRAO}")
    parser.add_argument("--decisoes", type=Path, help="JSON com as respostas às pendências")
    parser.add_argument("--aplicar", action="store_true", help="grava (sem isso é só dry-run)")
    args = parser.parse_args()

    if not args.arquivo.exists():
        sys.exit(f"Arquivo não encontrado: {args.arquivo}")
    missoes = json.loads(args.arquivo.read_text(encoding="utf-8"))["missoes"]
    decisoes = Decisoes(json.loads(args.decisoes.read_text(encoding="utf-8")) if args.decisoes else None)

    storage.inicializar()
    acoes = planejar(
        missoes, storage.listar_missoes_completas(), storage.listar_jogadores(),
        storage.listar_personagens(), decisoes,
    )
    print(f"{'APLICAR' if args.aplicar else 'DRY-RUN (nada é gravado)'}: {len(missoes)} missões em {args.arquivo}")
    imprimir(acoes)
    r = resumo(acoes)

    print("\n=== Resumo ===")
    print(f"Missões a atualizar (campos vazios preenchidos): {r['atualizar']}")
    print(f"Missões a inserir: {r['inserir']}")
    print(f"Participantes sem personagem vinculado: {len(r['sem_personagem'])}")
    for missao, nome in r["sem_personagem"]:
        print(f"  - {nome} (em «{missao}») → cadastrar depois")
    print(f"Pendências: {len(r['pendencias'])}")
    for missao, p in r["pendencias"]:
        print(f"  - «{missao}»: {p}")

    if not args.aplicar:
        print("\nDry-run: nada foi gravado.")
        return
    if r["pendencias"]:
        sys.exit("\nHá pendências: nada foi gravado. Responda no arquivo de --decisoes e rode de novo.")
    feito = aplicar(acoes)
    print(f"Pronto: {feito['atualizadas']} missões atualizadas, {feito['inseridas']} inseridas, "
          f"{len(r['sem_personagem'])} participantes sem personagem vinculado.")


if __name__ == "__main__":
    main()
