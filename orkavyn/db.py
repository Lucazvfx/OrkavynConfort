"""Backend — persistência em SQLite (consultas sempre parametrizadas)."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pandas as pd

from .config import DB_PATH, OBSERVADOR_EXEMPLO


COLUNAS_BANCO = [
    "id", "data_hora", "observador", "lote", "pasto", "n_animais",
    "temperatura", "umidade", "fr", "locomocao", "observacoes",
]


def conectar() -> sqlite3.Connection:
    """Abre uma conexão com o banco SQLite do projeto."""
    return sqlite3.connect(DB_PATH)


def criar_tabelas() -> None:
    """Cria a tabela na primeira execução (não faz nada se já existir)."""
    with closing(conectar()) as con, con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS observacoes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                data_hora   TEXT    NOT NULL,
                observador  TEXT,
                lote        TEXT    NOT NULL,
                pasto       TEXT    NOT NULL,
                n_animais   INTEGER NOT NULL CHECK (n_animais >= 1),
                temperatura REAL    NOT NULL CHECK (temperatura BETWEEN -5 AND 50),
                umidade     REAL    NOT NULL CHECK (umidade BETWEEN 0 AND 100),
                fr          INTEGER NOT NULL CHECK (fr BETWEEN 5 AND 200),
                locomocao   INTEGER NOT NULL CHECK (locomocao BETWEEN 1 AND 5),
                observacoes TEXT
            )
            """
        )


def inserir_observacao(d: dict) -> None:
    """Grava uma observação (consulta parametrizada)."""
    with closing(conectar()) as con, con:
        con.execute(
            """
            INSERT INTO observacoes
                (data_hora, observador, lote, pasto, n_animais,
                 temperatura, umidade, fr, locomocao, observacoes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                d["data_hora"], d["observador"], d["lote"], d["pasto"],
                d["n_animais"], d["temperatura"], d["umidade"], d["fr"],
                d["locomocao"], d["observacoes"],
            ),
        )


def inserir_varias(linhas: list[dict]) -> None:
    """Grava várias observações de uma vez (usado nos dados de exemplo)."""
    with closing(conectar()) as con, con:
        con.executemany(
            """
            INSERT INTO observacoes
                (data_hora, observador, lote, pasto, n_animais,
                 temperatura, umidade, fr, locomocao, observacoes)
            VALUES (:data_hora, :observador, :lote, :pasto, :n_animais,
                    :temperatura, :umidade, :fr, :locomocao, :observacoes)
            """,
            linhas,
        )


def carregar_observacoes() -> pd.DataFrame:
    """Lê todas as observações do banco como DataFrame (sem cálculos)."""
    with closing(conectar()) as con:
        df = pd.read_sql_query(
            "SELECT id, data_hora, observador, lote, pasto, n_animais, "
            "temperatura, umidade, fr, locomocao, observacoes "
            "FROM observacoes ORDER BY data_hora DESC, id DESC",
            con,
        )
    df["data_hora"] = pd.to_datetime(df["data_hora"])
    return df


def excluir_observacao(obs_id: int) -> None:
    with closing(conectar()) as con, con:
        con.execute("DELETE FROM observacoes WHERE id = ?", (int(obs_id),))


def apagar_exemplos() -> int:
    """Remove só os registros fictícios de exemplo. Devolve quantos foram."""
    with closing(conectar()) as con, con:
        cur = con.execute(
            "DELETE FROM observacoes WHERE observador = ?", (OBSERVADOR_EXEMPLO,)
        )
        return cur.rowcount
