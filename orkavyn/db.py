"""
Backend — persistência.

Dois modos, escolhidos automaticamente:
  * Supabase (vários celulares, dados compartilhados) — quando SUPABASE_URL e SUPABASE_KEY
    estão configurados (variável de ambiente ou .streamlit/secrets.toml). O acesso é só por
    funções do banco (RPC) protegidas por um código de acesso da equipe.
  * SQLite local (um aparelho só) — quando não há configuração.
Consultas SQLite sempre parametrizadas.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pandas as pd

from .config import DB_PATH, OBSERVADOR_EXEMPLO, obter_segredo


COLUNAS_BANCO = [
    "id", "data_hora", "observador", "lote", "pasto", "n_animais",
    "temperatura", "umidade", "fr", "locomocao", "observacoes",
]


def conectar() -> sqlite3.Connection:
    """Abre uma conexão com o banco SQLite do projeto."""
    return sqlite3.connect(DB_PATH)


def _sqlite_criar_tabelas() -> None:
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


def _sqlite_inserir_observacao(d: dict) -> None:
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


def _sqlite_inserir_varias(linhas: list[dict]) -> None:
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


def _sqlite_carregar_observacoes() -> pd.DataFrame:
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


def _sqlite_excluir_observacao(obs_id: int) -> None:
    with closing(conectar()) as con, con:
        con.execute("DELETE FROM observacoes WHERE id = ?", (int(obs_id),))


def _sqlite_apagar_exemplos() -> int:
    """Remove só os registros fictícios de exemplo. Devolve quantos foram."""
    with closing(conectar()) as con, con:
        cur = con.execute(
            "DELETE FROM observacoes WHERE observador = ?", (OBSERVADOR_EXEMPLO,)
        )
        return cur.rowcount


# =============================================================================
# Supabase (via API REST/RPC) e escolha do modo
# =============================================================================

class ErroBanco(Exception):
    """Falha ao falar com o banco (mensagem já em linguagem simples)."""


class CodigoInvalido(ErroBanco):
    """O código de acesso da equipe não confere."""


def modo() -> str:
    """"supabase" se houver URL e chave configuradas; senão "sqlite"."""
    return "supabase" if obter_segredo("SUPABASE_URL") and obter_segredo("SUPABASE_KEY") else "sqlite"


def _rpc(funcao: str, corpo: dict):
    """Chama uma função do Supabase (POST /rest/v1/rpc/<funcao>) e devolve o JSON."""
    import requests  # já vem junto com o Streamlit

    url = obter_segredo("SUPABASE_URL").rstrip("/")
    chave = obter_segredo("SUPABASE_KEY")
    try:
        r = requests.post(
            f"{url}/rest/v1/rpc/{funcao}", json=corpo, timeout=20,
            headers={"apikey": chave, "Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
        )
    except requests.RequestException as e:
        raise ErroBanco("Sem conexão com o banco de dados. Confira a internet e tente de novo.") from e
    if r.ok:
        return r.json()
    try:
        erro = r.json()
    except ValueError:
        erro = {}
    if erro.get("code") == "28000" or "codigo_invalido" in str(erro.get("message", "")):
        raise CodigoInvalido("Código de acesso incorreto.")
    raise ErroBanco(f"O banco recusou a operação (erro {r.status_code}). {erro.get('message', '')}".strip())


def criar_tabelas() -> None:
    if modo() == "sqlite":
        _sqlite_criar_tabelas()  # no Supabase as tabelas já existem (ver supabase/schema.sql)


def verificar_codigo(codigo: str) -> bool:
    """Confere o código de acesso (no modo SQLite não há código: sempre liberado)."""
    if modo() == "sqlite":
        return True
    return bool(_rpc("verificar_codigo", {"p_codigo": codigo or ""}))


def inserir_varias(linhas: list[dict], codigo: str | None = None) -> None:
    if modo() == "sqlite":
        _sqlite_inserir_varias(linhas)
    else:
        _rpc("inserir_varias", {"p_codigo": codigo or "", "p_linhas": linhas})


def inserir_observacao(d: dict, codigo: str | None = None) -> None:
    if modo() == "sqlite":
        _sqlite_inserir_observacao(d)
    else:
        inserir_varias([d], codigo)


def carregar_observacoes(codigo: str | None = None) -> pd.DataFrame:
    if modo() == "sqlite":
        return _sqlite_carregar_observacoes()
    linhas = _rpc("listar_observacoes", {"p_codigo": codigo or ""})
    df = pd.DataFrame(linhas, columns=COLUNAS_BANCO)
    df["data_hora"] = pd.to_datetime(df["data_hora"])
    for c in ("temperatura", "umidade"):
        df[c] = pd.to_numeric(df[c])
    return df


def excluir_observacao(obs_id: int, codigo: str | None = None) -> None:
    """No Supabase a exclusão é "suave" (guarda a data em excluido_em): dá para recuperar."""
    if modo() == "sqlite":
        _sqlite_excluir_observacao(obs_id)
    else:
        _rpc("excluir_observacao", {"p_codigo": codigo or "", "p_id": int(obs_id)})


def apagar_exemplos(codigo: str | None = None) -> int:
    if modo() == "sqlite":
        return _sqlite_apagar_exemplos()
    return int(_rpc("apagar_exemplos", {"p_codigo": codigo or "", "p_observador": OBSERVADOR_EXEMPLO}))
