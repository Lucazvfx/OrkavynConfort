"""Configuração central do AgroRadar, lida do ambiente (.env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        if os.getenv("VERCEL"):  # preview sem banco: SQLite efêmero (some a cada instância)
            return "sqlite:////tmp/agroradar.db"
        return f"sqlite:///{BASE_DIR / 'instance' / 'agroradar.db'}"
    # Heroku/Supabase às vezes entregam "postgres://", que o SQLAlchemy 2 não aceita.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):  # driver psycopg 3 explícito
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _engine_options(url: str) -> dict:
    if not url.startswith("postgresql"):
        return {"pool_pre_ping": True}
    from sqlalchemy.pool import NullPool
    # Serverless (Vercel) + pooler do Supabase em modo transação:
    # sem pool local (cada invocação abre/fecha) e sem prepared statements no servidor.
    return {"poolclass": NullPool, "connect_args": {"prepare_threshold": None}}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-change-me")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD") or None

    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(SQLALCHEMY_DATABASE_URI)

    # Vercel: sistema de arquivos somente leitura (exceto /tmp) e sem processo contínuo.
    ON_VERCEL = bool(os.getenv("VERCEL"))
    # Vercel Cron envia "Authorization: Bearer <CRON_SECRET>" automaticamente.
    CRON_SECRET = os.getenv("CRON_SECRET") or None
    # Preenche o banco com dados de demonstração se ele estiver vazio (primeiro deploy).
    AUTO_SEED_DEMO = _bool("AUTO_SEED_DEMO", False)
    # Site privado: exige login (senha do admin) em todas as páginas e na API.
    PRIVATE_SITE = _bool("PRIVATE_SITE", False)
    # IMEA (MT): só ligar após autorização por escrito do instituto.
    IMEA_ENABLED = _bool("IMEA_ENABLED", False)
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", bool(os.getenv("VERCEL")))

    # IA
    AI_PROVIDER = os.getenv("AI_PROVIDER", "auto").strip().lower()
    AI_TIMEOUT_SECONDS = _int("AI_TIMEOUT_SECONDS", 40)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or None
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or None
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    OLLAMA_BASE_URL = (os.getenv("OLLAMA_BASE_URL") or "").rstrip("/") or None
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    # Coleta
    HTTP_TIMEOUT_SECONDS = _int("HTTP_TIMEOUT_SECONDS", 20)
    HTTP_USER_AGENT = "AgroRadar/0.1 (+monitor de mercado pecuario)"
    RSS_FEEDS = os.getenv("RSS_FEEDS", "")
    NEWS_RETENTION_DAYS = _int("NEWS_RETENTION_DAYS", 60)
    WEATHER_FORECAST_DAYS = min(_int("WEATHER_FORECAST_DAYS", 15), 16)  # limite da Open-Meteo

    # Agendador
    SCHEDULER_ENABLED = _bool("SCHEDULER_ENABLED", True)
    SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "America/Sao_Paulo")
    BRIEFING_HOUR = _int("BRIEFING_HOUR", 6)


class TestConfig(Config):
    TESTING = True
    PRIVATE_SITE = False
    AUTO_SEED_DEMO = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SCHEDULER_ENABLED = False
    AI_PROVIDER = "rules"
    ADMIN_PASSWORD = "test"
