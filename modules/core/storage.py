# Acesso cru ao banco SQLite do NAT-CORE (data/natty.db). Sem regra de
# negócio: quem decide limite, dono, nome repetido etc. é o service.py.
#
# Toda escrita roda dentro de BEGIN IMMEDIATE ... COMMIT (transacao()). As
# funções aceitam `con=` pra várias escritas caberem numa transação só (a
# migração e o vínculo usam isso); sem `con`, cada uma abre a sua.
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ = Path(__file__).resolve().parents[2]
CAMINHO_PADRAO = "data/natty.db"
SCHEMA_VERSAO = 3
BACKUPS_MANTIDOS = 20

SCHEMA = """
CREATE TABLE jogadores (
    discord_id     TEXT PRIMARY KEY,
    username       TEXT,
    nome_exibicao  TEXT,
    nome           TEXT,
    criado_em      TEXT NOT NULL,
    atualizado_em  TEXT NOT NULL,
    ativo          INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1))  -- 0 = saiu do servidor
);

CREATE TABLE personagens (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em           TEXT NOT NULL,
    nome                TEXT NOT NULL,
    nome_chave          TEXT NOT NULL UNIQUE,
    nome_jogador        TEXT,
    jogador_discord_id  TEXT REFERENCES jogadores(discord_id),
    link_ficha          TEXT,
    nivel_inicial       INTEGER,
    nivel_atual         INTEGER,
    historia            TEXT  -- livre, escrita pelo jogador no registro (v3)
);
CREATE INDEX idx_personagens_jogador ON personagens(jogador_discord_id);

CREATE TABLE missoes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em            TEXT NOT NULL,
    nome                 TEXT NOT NULL,
    nome_chave           TEXT NOT NULL UNIQUE,
    data                 TEXT,
    dificuldade          TEXT CHECK (dificuldade IN ('Trivial', 'Fácil', 'Normal', 'Difícil', 'Extrema')),
    condutor_discord_id  TEXT REFERENCES jogadores(discord_id),
    condutor_nome        TEXT,
    relato               TEXT,
    resultado            TEXT,
    xp                   INTEGER,
    gold                 INTEGER,
    outras_recompensas   TEXT,
    observacoes          TEXT
);

CREATE TABLE missao_participantes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    missao_id        INTEGER NOT NULL REFERENCES missoes(id) ON DELETE CASCADE,
    personagem_id    INTEGER REFERENCES personagens(id) ON DELETE SET NULL,
    personagem_nome  TEXT NOT NULL
);
CREATE INDEX idx_participantes_missao ON missao_participantes(missao_id);
CREATE INDEX idx_participantes_personagem ON missao_participantes(personagem_id);
"""

# Migrações de schema: versão de origem → comandos que levam à versão seguinte.
MIGRACOES = {
    1: [  # v2: todos os membros do servidor na tabela jogadores
        "ALTER TABLE jogadores ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1))",
    ],
    2: [  # v3: história do personagem (os migrados da planilha ficam sem)
        "ALTER TABLE personagens ADD COLUMN historia TEXT",
    ],
}


class BancoIlegivel(Exception):
    """O arquivo do banco existe mas não dá pra confiar nele (corrompido, não é
    SQLite, versão desconhecida) ou sumiu tendo backups. Nunca recriar por cima."""


def caminho_banco() -> Path:
    caminho = Path(os.getenv("NATTY_DB_PATH") or CAMINHO_PADRAO)
    return caminho if caminho.is_absolute() else RAIZ / caminho


def pasta_backups() -> Path:
    return caminho_banco().parent / "backups"


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _abrir(caminho: Path, modo: str = "rw") -> sqlite3.Connection:
    """Conexão em autocommit (transações explícitas). modo: ro, rw ou rwc."""
    con = sqlite3.connect(
        f"{caminho.resolve().as_uri()}?mode={modo}", uri=True, timeout=5, isolation_level=None
    )
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


@contextmanager
def _conectar():
    caminho = caminho_banco()
    if not caminho.exists():
        raise FileNotFoundError(
            f"Banco não encontrado em {caminho}. Inicie a Natty ou rode "
            "scripts/migrar_sheets_para_sqlite.py."
        )
    con = _abrir(caminho)
    try:
        yield con
    finally:
        con.close()


@contextmanager
def transacao():
    """Conexão dentro de BEGIN IMMEDIATE; COMMIT no fim, ROLLBACK se der erro."""
    with _conectar() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            yield con
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")


@contextmanager
def _escrita(con):
    if con is not None:
        yield con
    else:
        with transacao() as nova:
            yield nova


@contextmanager
def _leitura(con):
    if con is not None:
        yield con
    else:
        with _conectar() as nova:
            yield nova


# --- inicialização e backup -------------------------------------------------

def _verificar(con: sqlite3.Connection) -> None:
    """Levanta BancoIlegivel se o arquivo aberto em `con` não for confiável."""
    try:
        resultado = con.execute("PRAGMA quick_check").fetchone()[0]
        versao = con.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise BancoIlegivel(f"não consegui ler o banco: {exc}") from exc
    if resultado != "ok":
        raise BancoIlegivel(f"quick_check acusou problema: {resultado}")
    if versao > SCHEMA_VERSAO:
        raise BancoIlegivel(
            f"o banco está na versão {versao} do schema e este código só conhece até a {SCHEMA_VERSAO}"
        )


def _executar_em_transacao(con: sqlite3.Connection, comandos: list[str], versao: int) -> None:
    # executescript faria COMMIT sozinho; comando a comando fica na transação.
    con.execute("BEGIN IMMEDIATE")
    try:
        for comando in comandos:
            con.execute(comando)
        con.execute(f"PRAGMA user_version = {versao}")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def inicializar() -> None:
    """Confere o banco, cria o schema se ele for novo e aplica as migrações
    pendentes (com backup antes).

    Banco que existe e não passa na verificação → BancoIlegivel, sem tocar no
    arquivo. Banco que sumiu mas tem backups → BancoIlegivel também (criar um
    vazio esconderia a perda; restaure com scripts/restaurar_banco.py).
    """
    caminho = caminho_banco()
    if not caminho.exists() and backups():
        raise BancoIlegivel(
            f"{caminho} não existe, mas há backups em {pasta_backups()}. "
            "Não vou criar um banco vazio por cima."
        )
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = _abrir(caminho, "rwc")
    try:
        _verificar(con)
        versao = con.execute("PRAGMA user_version").fetchone()[0]
        if versao == 0:
            tabelas = con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
            if tabelas:
                raise BancoIlegivel("o arquivo tem tabelas mas não tem versão de schema")
            comandos = [c for c in SCHEMA.split(";") if c.strip()]
            _executar_em_transacao(con, comandos, SCHEMA_VERSAO)
        elif versao < SCHEMA_VERSAO:
            fazer_backup(f"schema-v{versao}")
            for origem in range(versao, SCHEMA_VERSAO):
                _executar_em_transacao(con, MIGRACOES[origem], origem + 1)
        con.execute("PRAGMA journal_mode = WAL")
    finally:
        con.close()


def backups() -> list[Path]:
    """Backups existentes, do mais antigo pro mais recente."""
    pasta = pasta_backups()
    return sorted(pasta.glob("natty-*.db")) if pasta.exists() else []


def fazer_backup(motivo: str) -> Path:
    """Cópia consistente via Connection.backup() em data/backups/; mantém os
    BACKUPS_MANTIDOS mais recentes."""
    pasta = pasta_backups()
    pasta.mkdir(parents=True, exist_ok=True)
    base = f"natty-{datetime.now():%Y%m%d-%H%M%S}-{motivo}"
    destino = pasta / f"{base}.db"
    n = 2
    while destino.exists():
        destino = pasta / f"{base}-{n}.db"
        n += 1

    with _conectar() as origem:
        copia = sqlite3.connect(destino)
        try:
            origem.backup(copia)
        finally:
            copia.close()

    for antigo in backups()[:-BACKUPS_MANTIDOS]:
        antigo.unlink()
    return destino


def resumo_do_arquivo(caminho: Path) -> dict:
    """Contagem de linhas por tabela de um arquivo de banco (aberto só pra leitura)."""
    con = _abrir(caminho, "ro")
    try:
        _verificar(con)
        return {
            t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("jogadores", "personagens", "missoes", "missao_participantes")
        }
    finally:
        con.close()


def restaurar_backup(origem: Path) -> Path | None:
    """Põe `origem` no lugar do banco. O arquivo atual (e -wal/-shm) é movido
    pra data/natty.ilegivel-<data>.db, nunca apagado. Retorna esse caminho."""
    caminho = caminho_banco()
    guardado = None
    if caminho.exists():
        guardado = caminho.with_name(f"{caminho.stem}.ilegivel-{datetime.now():%Y%m%d-%H%M%S}.db")
        caminho.rename(guardado)
        for sufixo in ("-wal", "-shm"):
            extra = Path(f"{caminho}{sufixo}")
            if extra.exists():
                extra.rename(Path(f"{guardado}{sufixo}"))

    fonte = _abrir(origem, "ro")
    destino = _abrir(caminho, "rwc")
    try:
        fonte.backup(destino)
        _verificar(destino)
    finally:
        fonte.close()
        destino.close()
    return guardado


# --- jogadores --------------------------------------------------------------

def salvar_jogador(discord_id: str, username: str | None, nome_exibicao: str | None,
                   nome: str | None = None, ativo: bool | None = None, con=None) -> str | None:
    """Insere ou atualiza o jogador. Campo None não apaga o que já está gravado
    (jogador novo sem `ativo` nasce ativo); atualizado_em só muda quando algum
    campo muda. Retorna "novo", "atualizado" ou None (nada mudou)."""
    ativo_int = None if ativo is None else int(bool(ativo))
    with _escrita(con) as c:
        existia = c.execute(
            "SELECT 1 FROM jogadores WHERE discord_id = ?", (discord_id,)
        ).fetchone() is not None
        momento = agora()
        cursor = c.execute(
            """
            INSERT INTO jogadores (discord_id, username, nome_exibicao, nome, criado_em, atualizado_em, ativo)
            VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, 1))
            ON CONFLICT(discord_id) DO UPDATE SET
                username = COALESCE(excluded.username, jogadores.username),
                nome_exibicao = COALESCE(excluded.nome_exibicao, jogadores.nome_exibicao),
                nome = COALESCE(excluded.nome, jogadores.nome),
                ativo = COALESCE(?, jogadores.ativo),
                atualizado_em = excluded.atualizado_em
            WHERE COALESCE(excluded.username, jogadores.username) IS NOT jogadores.username
               OR COALESCE(excluded.nome_exibicao, jogadores.nome_exibicao) IS NOT jogadores.nome_exibicao
               OR COALESCE(excluded.nome, jogadores.nome) IS NOT jogadores.nome
               OR COALESCE(?, jogadores.ativo) IS NOT jogadores.ativo
            """,
            (discord_id, username, nome_exibicao, nome, momento, momento, ativo_int, ativo_int, ativo_int),
        )
    if cursor.rowcount == 0:
        return None
    return "atualizado" if existia else "novo"


def listar_jogadores(somente_ativos: bool = False, con=None) -> list[dict]:
    """Jogadores (membros do servidor) ordenados por username."""
    sql = "SELECT * FROM jogadores"
    if somente_ativos:
        sql += " WHERE ativo = 1"
    with _leitura(con) as c:
        return [dict(l) for l in c.execute(sql + " ORDER BY lower(username), discord_id")]


def marcar_saida(discord_id: str, con=None) -> bool:
    """ativo=0 (saiu do servidor). True se mudou alguma coisa."""
    with _escrita(con) as c:
        return c.execute(
            "UPDATE jogadores SET ativo = 0, atualizado_em = ? WHERE discord_id = ? AND ativo = 1",
            (agora(), discord_id),
        ).rowcount > 0


def marcar_ausentes(ids_presentes: set[str], con=None) -> int:
    """ativo=0 em quem está ativo no banco e não está em `ids_presentes`. Retorna quantos."""
    with _escrita(con) as c:
        ativos = [r[0] for r in c.execute("SELECT discord_id FROM jogadores WHERE ativo = 1")]
        ausentes = [i for i in ativos if i not in ids_presentes]
        momento = agora()
        c.executemany(
            "UPDATE jogadores SET ativo = 0, atualizado_em = ? WHERE discord_id = ?",
            [(momento, i) for i in ausentes],
        )
        return len(ausentes)


def buscar_jogador(discord_id: str, con=None) -> dict | None:
    with _leitura(con) as c:
        linha = c.execute("SELECT * FROM jogadores WHERE discord_id = ?", (discord_id,)).fetchone()
    return dict(linha) if linha else None


# --- personagens ------------------------------------------------------------

def contar_personagens(discord_id: str, con=None) -> int:
    with _leitura(con) as c:
        return c.execute(
            "SELECT count(*) FROM personagens WHERE jogador_discord_id = ?", (discord_id,)
        ).fetchone()[0]


def existe_personagem(nome_chave: str, con=None) -> bool:
    with _leitura(con) as c:
        return c.execute(
            "SELECT 1 FROM personagens WHERE nome_chave = ?", (nome_chave,)
        ).fetchone() is not None


def personagem_do_jogador(discord_id: str, nome_chave: str, con=None) -> bool:
    with _leitura(con) as c:
        return c.execute(
            "SELECT 1 FROM personagens WHERE nome_chave = ? AND jogador_discord_id = ?",
            (nome_chave, discord_id),
        ).fetchone() is not None


def inserir_personagem(nome: str, nome_chave: str, nome_jogador: str | None,
                       jogador_discord_id: str | None, link_ficha: str | None,
                       nivel_inicial: int | None, nivel_atual: int | None = None,
                       criado_em: str | None = None, historia: str | None = None,
                       con=None) -> int:
    """Insere o personagem (e a linha mínima do jogador, se faltar, pra FK). Retorna o id.
    Nome repetido → sqlite3.IntegrityError."""
    with _escrita(con) as c:
        if jogador_discord_id is not None:
            momento = agora()
            c.execute(
                "INSERT OR IGNORE INTO jogadores (discord_id, criado_em, atualizado_em) VALUES (?, ?, ?)",
                (jogador_discord_id, momento, momento),
            )
        cursor = c.execute(
            """
            INSERT INTO personagens (criado_em, nome, nome_chave, nome_jogador, jogador_discord_id,
                                     link_ficha, nivel_inicial, nivel_atual, historia)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (criado_em or agora(), nome, nome_chave, nome_jogador, jogador_discord_id,
             link_ficha, nivel_inicial, nivel_atual, historia),
        )
        return cursor.lastrowid


def remover_personagem(discord_id: str, nome_chave: str, con=None) -> bool:
    """Apaga o personagem se ele for de `discord_id`. True se apagou."""
    with _escrita(con) as c:
        cursor = c.execute(
            "DELETE FROM personagens WHERE nome_chave = ? AND jogador_discord_id = ?",
            (nome_chave, discord_id),
        )
        return cursor.rowcount > 0


def listar_personagens(discord_id: str | None = None, con=None) -> list[dict]:
    """Todos os personagens (ou só os de `discord_id`), ordenados por nome_chave."""
    sql = "SELECT * FROM personagens"
    params: tuple = ()
    if discord_id is not None:
        sql += " WHERE jogador_discord_id = ?"
        params = (discord_id,)
    with _leitura(con) as c:
        return [dict(l) for l in c.execute(sql + " ORDER BY nome_chave", params)]


def atualizar_niveis(niveis: dict[int, int], con=None) -> None:
    """Grava nivel_atual por id de personagem."""
    with _escrita(con) as c:
        c.executemany(
            "UPDATE personagens SET nivel_atual = ? WHERE id = ?",
            [(nivel, pid) for pid, nivel in niveis.items()],
        )


def vincular_personagens(ids: list[int], discord_id: str, forcar: bool = False, con=None) -> int:
    """Preenche jogador_discord_id nos personagens `ids`. Sem `forcar`, só nos que
    ainda estão sem vínculo. Retorna quantos foram alterados."""
    sql = "UPDATE personagens SET jogador_discord_id = ? WHERE id = ?"
    if not forcar:
        sql += " AND jogador_discord_id IS NULL"
    with _escrita(con) as c:
        return sum(c.execute(sql, (discord_id, pid)).rowcount for pid in ids)


# --- missões (só o que a migração e o vínculo precisam por enquanto) ---------

def listar_missoes(con=None) -> list[dict]:
    """id, nome, condutor_nome e condutor_discord_id de cada missão."""
    with _leitura(con) as c:
        return [dict(l) for l in c.execute(
            "SELECT id, nome, condutor_nome, condutor_discord_id FROM missoes ORDER BY data, id"
        )]


def existe_missao(nome_chave: str, con=None) -> bool:
    with _leitura(con) as c:
        return c.execute("SELECT 1 FROM missoes WHERE nome_chave = ?", (nome_chave,)).fetchone() is not None


def listar_participantes(con=None) -> dict[int, list[str]]:
    """{missao_id: [nomes dos personagens, na ordem do registro]}."""
    participantes: dict[int, list[str]] = {}
    with _leitura(con) as c:
        for l in c.execute("SELECT missao_id, personagem_nome FROM missao_participantes ORDER BY id"):
            participantes.setdefault(l["missao_id"], []).append(l["personagem_nome"])
    return participantes


def listar_missoes_completas(con=None) -> list[dict]:
    """Todas as colunas de cada missão, por data e id."""
    with _leitura(con) as c:
        return [dict(l) for l in c.execute("SELECT * FROM missoes ORDER BY data, id")]


# Colunas que preencher_missao/sobrescrever_missao aceitam (nome de coluna não
# pode ser parâmetro no SQL, então só passa o que estiver aqui).
CAMPOS_EDITAVEIS_MISSAO = (
    "relato", "resultado", "xp", "gold", "outras_recompensas", "observacoes", "condutor_discord_id",
)


def preencher_missao(missao_id: int, campos: dict, con=None) -> list[str]:
    """Grava cada campo só se ele estiver vazio (NULL ou texto em branco) no
    banco; o que já tem valor nunca é tocado. Retorna as colunas preenchidas."""
    preenchidos = []
    with _escrita(con) as c:
        for coluna, valor in campos.items():
            if coluna not in CAMPOS_EDITAVEIS_MISSAO:
                raise ValueError(f"coluna não editável: {coluna}")
            cursor = c.execute(
                f"UPDATE missoes SET {coluna} = ? WHERE id = ? "
                f"AND ({coluna} IS NULL OR TRIM({coluna}) = '')",
                (valor, missao_id),
            )
            if cursor.rowcount:
                preenchidos.append(coluna)
    return preenchidos


def sobrescrever_missao(missao_id: int, campos: dict, con=None) -> None:
    """Troca o valor mesmo que já exista. Só pra decisão explícita de quem roda."""
    with _escrita(con) as c:
        for coluna, valor in campos.items():
            if coluna not in CAMPOS_EDITAVEIS_MISSAO:
                raise ValueError(f"coluna não editável: {coluna}")
            c.execute(f"UPDATE missoes SET {coluna} = ? WHERE id = ?", (valor, missao_id))


def vincular_condutor(missao_ids: list[int], discord_id: str, forcar: bool = False, con=None) -> int:
    """Preenche condutor_discord_id nas missões `missao_ids`. Sem `forcar`, só nas
    que ainda estão sem condutor vinculado. Retorna quantas foram alteradas."""
    sql = "UPDATE missoes SET condutor_discord_id = ? WHERE id = ?"
    if not forcar:
        sql += " AND condutor_discord_id IS NULL"
    with _escrita(con) as c:
        return sum(c.execute(sql, (discord_id, mid)).rowcount for mid in missao_ids)


def inserir_missao(dados: dict, participantes: list[tuple[int | None, str]], con=None) -> int:
    """Insere a missão (`dados` com as colunas de missoes, sem id) e os
    participantes [(personagem_id ou None, nome no momento)]. Retorna o id."""
    colunas = list(dados)
    with _escrita(con) as c:
        cursor = c.execute(
            f"INSERT INTO missoes ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))})",
            [dados[k] for k in colunas],
        )
        missao_id = cursor.lastrowid
        c.executemany(
            "INSERT INTO missao_participantes (missao_id, personagem_id, personagem_nome) VALUES (?, ?, ?)",
            [(missao_id, pid, nome) for pid, nome in participantes],
        )
        return missao_id


# --- manutenção ---------------------------------------------------------------

def tem_dados(con=None) -> bool:
    with _leitura(con) as c:
        return any(
            c.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()
            for t in ("jogadores", "personagens", "missoes")
        )


def apagar_tudo(con=None) -> None:
    """Esvazia todas as tabelas (usado só pela migração com --recriar, depois de backup)."""
    with _escrita(con) as c:
        for tabela in ("missao_participantes", "missoes", "personagens", "jogadores"):
            c.execute(f"DELETE FROM {tabela}")
        c.execute("DELETE FROM sqlite_sequence")
