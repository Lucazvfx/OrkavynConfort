"""Extensões Flask compartilhadas (evita import circular)."""
import os

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

def resolve_schema() -> str | None:
    """DB_SCHEMA isola as tabelas num schema próprio do Postgres (ex.: "agroradar" num
    projeto Supabase compartilhado). Só vale com Postgres: SQLite não tem schemas."""
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith(("postgres://", "postgresql")):
        return None
    return os.getenv("DB_SCHEMA") or None


DB_SCHEMA = resolve_schema()


class Base(DeclarativeBase):
    metadata = MetaData(schema=DB_SCHEMA)


db = SQLAlchemy(model_class=Base)
