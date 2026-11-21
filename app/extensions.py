"""Extensões Flask compartilhadas (evita import circular)."""
import os

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# DB_SCHEMA isola as tabelas do AgroRadar num schema próprio do Postgres
# (ex.: "agroradar" dentro de um projeto Supabase compartilhado). Vazio = schema padrão.
DB_SCHEMA = os.getenv("DB_SCHEMA") or None


class Base(DeclarativeBase):
    metadata = MetaData(schema=DB_SCHEMA)


db = SQLAlchemy(model_class=Base)
