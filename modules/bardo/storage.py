"""Acesso cru ao banco SQLite do Bardo (data/bardo.db).

Mesmo padrão do NAT-CORE: este é o único lugar do Bardo que fala SQL, e não
tem regra de negócio (nome repetido, limite, quem pode apagar: service.py).
Banco separado do natty.db porque módulos não dividem estado: o Bardo é dono
do dele. Fica fora do git (data/*.db) — tem ids de servidor e de pessoa.

Tudo é por servidor (guild_id): playlists salvas, sons, cenas e as músicas
descobertas em mesa (a camada do servidor por cima do musicas.json global).
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CAMINHO_PADRAO = "data/bardo.db"
SCHEMA_VERSAO = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    nome        TEXT NOT NULL,
    nome_chave  TEXT NOT NULL,
    criado_por  TEXT,
    criado_em   TEXT NOT NULL,
    UNIQUE (guild_id, nome_chave)
);

CREATE TABLE IF NOT EXISTS playlist_itens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id  INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    posicao      INTEGER NOT NULL,
    titulo       TEXT NOT NULL,
    link         TEXT NOT NULL,
    duracao      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_itens_playlist ON playlist_itens(playlist_id, posicao);

CREATE TABLE IF NOT EXISTS sons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    nome        TEXT NOT NULL,
    nome_chave  TEXT NOT NULL,
    tipo        TEXT NOT NULL CHECK (tipo IN ('ambiente', 'efeito', 'musica')),
    arquivo     TEXT NOT NULL,           -- <hash>.<ext> dentro de data/som/<guild>/
    hash        TEXT NOT NULL,
    tags        TEXT NOT NULL DEFAULT '[]',
    volume      INTEGER NOT NULL DEFAULT 100 CHECK (volume BETWEEN 0 AND 100),
    loop        INTEGER NOT NULL DEFAULT 0 CHECK (loop IN (0, 1)),
    duck        INTEGER NOT NULL DEFAULT 0 CHECK (duck IN (0, 1)),
    criado_por  TEXT,
    criado_em   TEXT NOT NULL,
    UNIQUE (guild_id, nome_chave)
);

CREATE TABLE IF NOT EXISTS cenas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    nome        TEXT NOT NULL,
    nome_chave  TEXT NOT NULL,
    dados       TEXT NOT NULL,           -- JSON: música, ambientes, pads, ducking, master
    criado_por  TEXT,
    criado_em   TEXT NOT NULL,
    UNIQUE (guild_id, nome_chave)
);

CREATE TABLE IF NOT EXISTS descobertas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    video_id    TEXT NOT NULL,
    entrada     TEXT NOT NULL,           -- JSON no formato de uma faixa do musicas.json
    criado_em   TEXT NOT NULL,
    UNIQUE (guild_id, video_id)
);
"""


def caminho_banco() -> Path:
    caminho = Path(os.getenv("BARDO_DB_PATH") or CAMINHO_PADRAO)
    return caminho if caminho.is_absolute() else RAIZ / caminho


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conectar():
    """Conexão com o schema garantido; faz commit no fim (ou rollback se der erro)."""
    caminho = caminho_banco()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        if con.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSAO:
            con.executescript(SCHEMA)
            con.execute(f"PRAGMA user_version = {SCHEMA_VERSAO}")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# -- Playlists -----------------------------------------------------------------

def buscar_playlist(guild_id: int, nome_chave: str) -> dict | None:
    with conectar() as con:
        linha = con.execute(
            "SELECT * FROM playlists WHERE guild_id = ? AND nome_chave = ?", (str(guild_id), nome_chave)
        ).fetchone()
        if linha is None:
            return None
        itens = con.execute(
            "SELECT titulo, link, duracao FROM playlist_itens WHERE playlist_id = ? ORDER BY posicao", (linha["id"],)
        ).fetchall()
        return {**dict(linha), "itens": [dict(i) for i in itens]}


def salvar_playlist(guild_id: int, nome: str, nome_chave: str, itens: list[dict], criado_por: str | None) -> None:
    """Grava (ou substitui, com o mesmo nome) a playlist e os itens dela, numa transação."""
    with conectar() as con:
        con.execute("DELETE FROM playlists WHERE guild_id = ? AND nome_chave = ?", (str(guild_id), nome_chave))
        cur = con.execute(
            "INSERT INTO playlists (guild_id, nome, nome_chave, criado_por, criado_em) VALUES (?, ?, ?, ?, ?)",
            (str(guild_id), nome, nome_chave, criado_por, agora()),
        )
        con.executemany(
            "INSERT INTO playlist_itens (playlist_id, posicao, titulo, link, duracao) VALUES (?, ?, ?, ?, ?)",
            [(cur.lastrowid, i, item["titulo"], item["link"], item.get("duracao")) for i, item in enumerate(itens)],
        )


def listar_playlists(guild_id: int) -> list[dict]:
    with conectar() as con:
        return [dict(l) for l in con.execute(
            "SELECT p.nome, p.nome_chave, p.criado_por, p.criado_em, COUNT(i.id) AS quantas "
            "FROM playlists p LEFT JOIN playlist_itens i ON i.playlist_id = p.id "
            "WHERE p.guild_id = ? GROUP BY p.id ORDER BY p.nome_chave", (str(guild_id),)
        )]


def apagar_playlist(guild_id: int, nome_chave: str) -> bool:
    with conectar() as con:
        return con.execute(
            "DELETE FROM playlists WHERE guild_id = ? AND nome_chave = ?", (str(guild_id), nome_chave)
        ).rowcount > 0


# -- Cenas -----------------------------------------------------------------------

def salvar_cena(guild_id: int, nome: str, nome_chave: str, dados: dict, criado_por: str | None) -> None:
    with conectar() as con:
        con.execute(
            "INSERT INTO cenas (guild_id, nome, nome_chave, dados, criado_por, criado_em) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (guild_id, nome_chave) DO UPDATE SET nome = excluded.nome, dados = excluded.dados",
            (str(guild_id), nome, nome_chave, json.dumps(dados, ensure_ascii=False), criado_por, agora()),
        )


def buscar_cena(guild_id: int, nome_chave: str) -> dict | None:
    with conectar() as con:
        linha = con.execute(
            "SELECT * FROM cenas WHERE guild_id = ? AND nome_chave = ?", (str(guild_id), nome_chave)
        ).fetchone()
    return None if linha is None else {**dict(linha), "dados": json.loads(linha["dados"])}


def listar_cenas(guild_id: int) -> list[dict]:
    with conectar() as con:
        return [dict(l) for l in con.execute(
            "SELECT nome, nome_chave, criado_em FROM cenas WHERE guild_id = ? ORDER BY nome_chave", (str(guild_id),)
        )]


def apagar_cena(guild_id: int, nome_chave: str) -> bool:
    with conectar() as con:
        return con.execute(
            "DELETE FROM cenas WHERE guild_id = ? AND nome_chave = ?", (str(guild_id), nome_chave)
        ).rowcount > 0


# -- Sons --------------------------------------------------------------------------

_CAMPOS_DO_SOM = ("nome", "nome_chave", "tipo", "arquivo", "hash", "tags", "volume", "loop", "duck", "criado_por")


def _som(linha) -> dict:
    som = dict(linha)
    som["tags"] = json.loads(som["tags"])
    som["loop"], som["duck"] = bool(som["loop"]), bool(som["duck"])
    return som


def inserir_som(guild_id: int, som: dict) -> int:
    valores = {**som, "tags": json.dumps(som.get("tags", []), ensure_ascii=False),
               "loop": int(som.get("loop", False)), "duck": int(som.get("duck", False))}
    with conectar() as con:
        return con.execute(
            f"INSERT INTO sons (guild_id, {', '.join(_CAMPOS_DO_SOM)}, criado_em) "
            f"VALUES (?, {', '.join('?' * len(_CAMPOS_DO_SOM))}, ?)",
            (str(guild_id), *(valores.get(c) for c in _CAMPOS_DO_SOM), agora()),
        ).lastrowid


def buscar_som(guild_id: int, nome_chave: str) -> dict | None:
    with conectar() as con:
        linha = con.execute(
            "SELECT * FROM sons WHERE guild_id = ? AND nome_chave = ?", (str(guild_id), nome_chave)
        ).fetchone()
    return None if linha is None else _som(linha)


def som_com_hash(guild_id: int, hash_: str) -> dict | None:
    with conectar() as con:
        linha = con.execute("SELECT * FROM sons WHERE guild_id = ? AND hash = ?", (str(guild_id), hash_)).fetchone()
    return None if linha is None else _som(linha)


def listar_sons(guild_id: int, tipo: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM sons WHERE guild_id = ?", [str(guild_id)]
    if tipo:
        sql, args = sql + " AND tipo = ?", args + [tipo]
    with conectar() as con:
        return [_som(l) for l in con.execute(sql + " ORDER BY tipo, nome_chave", args)]


def atualizar_som(guild_id: int, nome_chave: str, campos: dict) -> bool:
    permitidos = {k: v for k, v in campos.items() if k in ("volume", "loop", "duck", "tags", "tipo")}
    if not permitidos:
        return False
    if "tags" in permitidos:
        permitidos["tags"] = json.dumps(permitidos["tags"], ensure_ascii=False)
    for k in ("loop", "duck"):
        if k in permitidos:
            permitidos[k] = int(permitidos[k])
    with conectar() as con:
        return con.execute(
            f"UPDATE sons SET {', '.join(f'{k} = ?' for k in permitidos)} WHERE guild_id = ? AND nome_chave = ?",
            (*permitidos.values(), str(guild_id), nome_chave),
        ).rowcount > 0


def apagar_som(guild_id: int, nome_chave: str) -> dict | None:
    """Apaga o registro e devolve ele (quem chama apaga o arquivo, se ninguém mais usa)."""
    som = buscar_som(guild_id, nome_chave)
    if som is not None:
        with conectar() as con:
            con.execute("DELETE FROM sons WHERE guild_id = ? AND nome_chave = ?", (str(guild_id), nome_chave))
    return som


# -- Descobertas em mesa (camada do servidor por cima do musicas.json) ----------

def inserir_descoberta(guild_id: int, video_id: str, entrada: dict) -> bool:
    """Grava; False se o vídeo já estava nas descobertas deste servidor."""
    with conectar() as con:
        return con.execute(
            "INSERT OR IGNORE INTO descobertas (guild_id, video_id, entrada, criado_em) VALUES (?, ?, ?, ?)",
            (str(guild_id), video_id, json.dumps(entrada, ensure_ascii=False), agora()),
        ).rowcount > 0


def listar_descobertas(guild_id: int) -> list[dict]:
    with conectar() as con:
        return [json.loads(l["entrada"]) for l in con.execute(
            "SELECT entrada FROM descobertas WHERE guild_id = ? ORDER BY id", (str(guild_id),)
        )]
