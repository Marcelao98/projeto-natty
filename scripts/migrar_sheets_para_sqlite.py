"""Migra as abas Personagens e Missões da planilha (Google Sheets) pro SQLite.

Uso:
    python scripts/migrar_sheets_para_sqlite.py --simular   # só lê e mostra, não grava
    python scripts/migrar_sheets_para_sqlite.py             # migra (aborta se o banco já tiver dados)
    python scripts/migrar_sheets_para_sqlite.py --recriar   # backup, esvazia o banco e migra de novo

Só LÊ a planilha: nada nela é alterado nem apagado (ela fica de backup).
Último uso do gspread no projeto.
"""
import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from modules.core import storage  # noqa: E402
from modules.core.service import _chave_nome  # noqa: E402

load_dotenv()

ABA_PERSONAGENS = "Personagens"
ABA_MISSOES = "Missões"
SCOPES = [  # só leitura: a migração nunca altera a planilha
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

DATA_RE = re.compile(
    r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*$"
)
DIFICULDADES = {_chave_nome(d): d for d in ("Trivial", "Fácil", "Normal", "Difícil", "Extrema")}

# Colunas da aba Personagens (cabeçalho normalizado, ver _normalizar_cabecalho).
P_TIMESTAMP = "timestamp"
P_NOME = "nome do personagem"
P_JOGADOR = "nome do jogador"
P_LINK = "link da ficha"
P_NIVEL_INICIAL = "nivel inicial"
P_NIVEL_ATUAL = "nivel atual"
P_DISCORD_ID = "discord id"
COLUNAS_PERSONAGENS = {P_TIMESTAMP, P_NOME, P_JOGADOR, P_LINK, P_NIVEL_INICIAL, P_NIVEL_ATUAL, P_DISCORD_ID}

# Aba Missões: os títulos vêm das perguntas do Forms, então casa por trecho.
# (campo, trechos que identificam a coluna) — a primeira regra que casar vence.
REGRAS_MISSOES = [
    ("criado_em", ("timestamp", "carimbo")),
    ("nome", ("nome da missao",)),
    ("data", ("data",)),
    ("dificuldade", ("dificuldade",)),
    ("condutor_nome", ("conduziu", "condutor", "mestre")),
    ("participantes", ("participa", "personagens")),
    ("relato", ("relato", "aconteceu", "conte")),
    ("resultado", ("resultado",)),
    ("xp", ("xp",)),
    ("gold", ("gold", "ouro")),
    ("outras_recompensas", ("outras recompensas", "recompensa")),
    ("observacoes", ("observa",)),
]


class ErroMigracao(Exception):
    pass


# --- normalização (sem rede; testada em modules/core/test_migracao.py) -------

def normalizar_cabecalho(titulo: str) -> str:
    """'Nível Inicial. ' → 'nivel inicial' (sem acento, caixa, ponto final)."""
    return _chave_nome(str(titulo)).rstrip(".").strip()


def converter_data(valor: str) -> str | None:
    """'3/7/2025 14:05:09' ou '03/07/2025' (mês primeiro) → ISO 8601.
    Vazio → None. Formato desconhecido ou data impossível → ValueError."""
    valor = (valor or "").strip()
    if not valor:
        return None
    m = DATA_RE.match(valor)
    if not m:
        raise ValueError(f"data em formato desconhecido: {valor!r}")
    mes, dia, ano, hora, minuto, segundo = m.groups()
    if hora is None:
        return datetime(int(ano), int(mes), int(dia)).date().isoformat()
    momento = datetime(int(ano), int(mes), int(dia), int(hora), int(minuto), int(segundo or 0))
    return momento.isoformat(timespec="seconds")


def converter_nivel(valor: str) -> int | None:
    """'3', '3,0', ' 3 ' → 3. Vazio → None. Não numérico → ValueError."""
    valor = str(valor or "").strip()
    if not valor:
        return None
    return int(float(valor.replace(",", ".")))


def converter_discord_id(valor: str) -> str | None:
    """Tira o apóstrofo que forçava texto na planilha. Vazio → None; não numérico → ValueError."""
    valor = str(valor or "").strip().lstrip("'").strip()
    if not valor:
        return None
    if not valor.isdigit():
        raise ValueError(f"Discord ID não numérico: {valor!r}")
    return valor


def texto(valor) -> str | None:
    valor = str(valor or "").strip()
    return valor or None


# --- leitura da planilha -------------------------------------------------------

def _ler_aba(planilha, nome: str) -> list[list[str]] | None:
    import gspread

    try:
        return planilha.worksheet(nome).get_all_values()
    except gspread.WorksheetNotFound:
        return None


def ler_planilha() -> tuple[list[list[str]], list[list[str]] | None]:
    import gspread
    from google.oauth2.service_account import Credentials

    credenciais = Credentials.from_service_account_file(
        os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json"), scopes=SCOPES
    )
    planilha = gspread.authorize(credenciais).open(os.getenv("GOOGLE_SHEET_NAME", "Natty"))
    personagens = _ler_aba(planilha, ABA_PERSONAGENS)
    if personagens is None:
        raise ErroMigracao(f"A planilha não tem a aba {ABA_PERSONAGENS!r}.")
    return personagens, _ler_aba(planilha, ABA_MISSOES)


# --- montagem dos registros ----------------------------------------------------

def montar_personagens(valores: list[list[str]]) -> tuple[list[dict], list[str], list[str]]:
    """(personagens, avisos, erros). Erro = algo que impede migrar com segurança."""
    if not valores:
        return [], [], ["A aba Personagens está vazia (nem cabeçalho)."]
    cabecalho = [normalizar_cabecalho(c) for c in valores[0]]
    avisos, erros = [], []
    for faltando in (P_TIMESTAMP, P_NOME, P_JOGADOR, P_LINK, P_NIVEL_INICIAL):
        if faltando not in cabecalho:
            erros.append(f"Coluna obrigatória ausente na aba Personagens: {faltando!r}")
    ignoradas = [valores[0][i] for i, c in enumerate(cabecalho) if c and c not in COLUNAS_PERSONAGENS]
    if ignoradas:
        avisos.append(f"Colunas da aba Personagens que NÃO foram migradas: {ignoradas}")
    if erros:
        return [], avisos, erros

    def celula(linha, coluna):
        if coluna not in cabecalho:
            return ""
        i = cabecalho.index(coluna)
        return linha[i] if i < len(linha) else ""

    personagens, chaves = [], {}
    for num, linha in enumerate(valores[1:], start=2):
        if not any(str(c).strip() for c in linha):
            continue
        nome = texto(celula(linha, P_NOME))
        if not nome:
            erros.append(f"Linha {num}: personagem sem nome.")
            continue
        p = {
            "linha": num,
            "nome": nome,
            "nome_chave": _chave_nome(nome),
            "nome_jogador": texto(celula(linha, P_JOGADOR)),
            "link_ficha": texto(celula(linha, P_LINK)),
        }
        try:
            p["criado_em"] = converter_data(celula(linha, P_TIMESTAMP))
        except ValueError as exc:
            erros.append(f"Linha {num} ({nome}): {exc}")
            continue
        if p["criado_em"] is None:
            erros.append(f"Linha {num} ({nome}): sem Timestamp.")
            continue
        for campo, coluna in (("nivel_inicial", P_NIVEL_INICIAL), ("nivel_atual", P_NIVEL_ATUAL)):
            try:
                p[campo] = converter_nivel(celula(linha, coluna))
            except ValueError:
                avisos.append(
                    f"Linha {num} ({nome}): {coluna} {celula(linha, coluna)!r} não é número, fica vazio."
                )
                p[campo] = None
        try:
            p["jogador_discord_id"] = converter_discord_id(celula(linha, P_DISCORD_ID))
        except ValueError as exc:
            avisos.append(f"Linha {num} ({nome}): {exc}; fica sem vínculo.")
            p["jogador_discord_id"] = None
        if p["nome_chave"] in chaves:
            erros.append(
                f"Linha {num} ({nome}): mesmo nome da linha {chaves[p['nome_chave']]} "
                "(sem diferenciar acento e maiúscula)."
            )
            continue
        chaves[p["nome_chave"]] = num
        personagens.append(p)
    return personagens, avisos, erros


def _campo_missao(titulo: str) -> str | None:
    chave = normalizar_cabecalho(titulo)
    for campo, trechos in REGRAS_MISSOES:
        if any(t in chave for t in trechos):
            return campo
    return None


def montar_missoes(valores: list[list[str]] | None, chaves_personagens: dict[str, str]
                   ) -> tuple[list[dict], list[str], list[str]]:
    """(missões, avisos, erros). `chaves_personagens`: nome_chave → nome do personagem."""
    if not valores or len(valores) < 2:
        return [], [], []
    campos = [_campo_missao(t) for t in valores[0]]
    avisos, erros = [], []
    usados = {}
    for titulo, campo in zip(valores[0], campos):
        if campo is None:
            if str(titulo).strip():
                avisos.append(f"Coluna da aba Missões que NÃO foi migrada: {titulo!r}")
        elif campo in usados:
            erros.append(f"Aba Missões: {usados[campo]!r} e {titulo!r} caíram no mesmo campo ({campo}).")
        else:
            usados[campo] = titulo
    if "nome" not in usados:
        erros.append("Aba Missões sem coluna 'Nome da missão'.")
    if erros:
        return [], avisos, erros

    missoes, chaves = [], {}
    for num, linha in enumerate(valores[1:], start=2):
        if not any(str(c).strip() for c in linha):
            continue
        bruto = {c: (linha[i] if i < len(linha) else "") for i, c in enumerate(campos) if c}
        nome = texto(bruto.get("nome"))
        if not nome:
            erros.append(f"Missões, linha {num}: missão sem nome.")
            continue
        try:
            criado_em = converter_data(bruto.get("criado_em", "")) or storage.agora()
            data = converter_data(bruto.get("data", ""))
        except ValueError as exc:
            erros.append(f"Missões, linha {num} ({nome}): {exc}")
            continue

        observacoes = [texto(bruto.get("observacoes"))]
        dificuldade_texto = texto(bruto.get("dificuldade"))
        dificuldade = DIFICULDADES.get(_chave_nome(dificuldade_texto or "").rstrip(".").strip())  # Forms: "Difícil."
        if dificuldade_texto and not dificuldade:
            observacoes.append(f"Dificuldade original: {dificuldade_texto}")
            avisos.append(f"Missões, linha {num} ({nome}): dificuldade {dificuldade_texto!r} fica vazia (texto em observações).")

        numeros = {}
        for campo in ("xp", "gold"):
            try:
                numeros[campo] = converter_nivel(bruto.get(campo, ""))
            except ValueError:
                numeros[campo] = None
                avisos.append(f"Missões, linha {num} ({nome}): {campo} {bruto.get(campo)!r} não é número, fica vazio.")

        participantes = []
        for parte in str(bruto.get("participantes", "")).split(","):
            nome_p = parte.strip()
            if not nome_p:
                continue
            achou = _chave_nome(nome_p) in chaves_personagens
            if not achou:
                avisos.append(f"Missões, linha {num} ({nome}): participante {nome_p!r} não é personagem registrado.")
            participantes.append(nome_p)

        chave = _chave_nome(nome)
        if chave in chaves:
            erros.append(f"Missões, linha {num} ({nome}): mesmo nome da linha {chaves[chave]}.")
            continue
        chaves[chave] = num
        missoes.append({
            "linha": num,
            "dados": {
                "criado_em": criado_em,
                "nome": nome,
                "nome_chave": chave,
                "data": data,
                "dificuldade": dificuldade,
                "condutor_nome": texto(bruto.get("condutor_nome")),
                "relato": texto(bruto.get("relato")),
                "resultado": texto(bruto.get("resultado")),
                "xp": numeros["xp"],
                "gold": numeros["gold"],
                "outras_recompensas": texto(bruto.get("outras_recompensas")),
                "observacoes": "\n".join(o for o in observacoes if o) or None,
            },
            "participantes": participantes,
        })
    return missoes, avisos, erros


# --- gravação e relatório ---------------------------------------------------------

def gravar(personagens: list[dict], missoes: list[dict], recriar: bool) -> None:
    storage.inicializar()
    if storage.tem_dados():
        if not recriar:
            raise ErroMigracao(
                "O banco já tem dados. Nada foi gravado. Use --recriar pra apagar e migrar de novo "
                "(faz backup antes)."
            )
        print(f"Backup antes de recriar: {storage.fazer_backup('recriar')}")

    with storage.transacao() as con:
        if recriar:
            storage.apagar_tudo(con=con)
        ids = {}
        for p in personagens:
            if p["jogador_discord_id"]:
                storage.salvar_jogador(p["jogador_discord_id"], None, None, p["nome_jogador"], con=con)
            ids[p["nome_chave"]] = storage.inserir_personagem(
                nome=p["nome"],
                nome_chave=p["nome_chave"],
                nome_jogador=p["nome_jogador"],
                jogador_discord_id=p["jogador_discord_id"],
                link_ficha=p["link_ficha"],
                nivel_inicial=p["nivel_inicial"],
                nivel_atual=p["nivel_atual"],
                criado_em=p["criado_em"],
                con=con,
            )
        for m in missoes:
            storage.inserir_missao(
                m["dados"],
                [(ids.get(_chave_nome(n)), n) for n in m["participantes"]],
                con=con,
            )


def _tabela(linhas: list[list[str]], titulos: list[str]) -> str:
    larguras = [max(len(str(x)) for x in col) for col in zip(titulos, *linhas)]
    fmt = "  ".join(f"{{:<{w}}}" for w in larguras)
    return "\n".join(
        [fmt.format(*titulos), fmt.format(*("-" * w for w in larguras))]
        + [fmt.format(*(str(x) for x in l)) for l in linhas]
    )


def imprimir_relatorio(personagens: list[dict], missoes: list[dict]) -> None:
    jogadores = {_chave_nome(p["nome_jogador"] or "") for p in personagens}
    print(f"\nPersonagens: {len(personagens)} (de {len(jogadores)} jogadores distintos)")
    print(_tabela(
        [[p["linha"], p["nome"], p["nome_jogador"] or "-", p["criado_em"],
          "-" if p["nivel_inicial"] is None else p["nivel_inicial"],
          "-" if p["nivel_atual"] is None else p["nivel_atual"],
          p["jogador_discord_id"] or "-",
          (p["link_ficha"] or "-")[:50]]
         for p in personagens],
        ["linha", "nome", "jogador", "criado_em", "nív.ini", "nív.atual", "discord_id", "link"],
    ))
    print(f"\nMissões: {len(missoes)}")
    if missoes:
        print(_tabela(
            [[m["linha"], m["dados"]["nome"], m["dados"]["data"] or "-",
              m["dados"]["dificuldade"] or "-", m["dados"]["condutor_nome"] or "-",
              len(m["participantes"])]
             for m in missoes],
            ["linha", "nome", "data", "dificuldade", "condutor", "participantes"],
        ))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--simular", action="store_true", help="só lê a planilha e mostra; não grava")
    grupo.add_argument("--recriar", action="store_true", help="faz backup, esvazia o banco e migra de novo")
    args = parser.parse_args()

    valores_p, valores_m = ler_planilha()
    personagens, avisos_p, erros_p = montar_personagens(valores_p)
    chaves = {p["nome_chave"]: p["nome"] for p in personagens}
    missoes, avisos_m, erros_m = montar_missoes(valores_m, chaves)
    if valores_m is None:
        avisos_m.append(f"A planilha não tem a aba {ABA_MISSOES!r}; nenhuma missão migrada.")

    for aviso in avisos_p + avisos_m:
        print(f"AVISO: {aviso}")
    erros = erros_p + erros_m
    if erros:
        for erro in erros:
            print(f"ERRO: {erro}")
        sys.exit("\nNada foi gravado. Corrija a planilha (ou me avise) e rode de novo.")

    imprimir_relatorio(personagens, missoes)
    if args.simular:
        print("\n--simular: nada foi gravado.")
        return
    try:
        gravar(personagens, missoes, args.recriar)
    except (ErroMigracao, storage.BancoIlegivel) as exc:
        sys.exit(f"\n{exc}")
    print(f"\nMigrado para {storage.caminho_banco()}: {len(personagens)} personagens, {len(missoes)} missões.")
    print("A planilha não foi alterada.")


if __name__ == "__main__":
    main()
