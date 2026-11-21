"""Utilitários de data/texto usados por vários serviços."""
from __future__ import annotations

import unicodedata
from datetime import date, datetime, timedelta, timezone


def utcnow() -> datetime:
    """Datetime UTC *naive* — convenção única do banco (SQLite não guarda fuso)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_text(text: str) -> str:
    """Minúsculas e sem acentos, para casamento de palavras-chave."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def is_business_day(d: date) -> bool:
    # Feriados não são considerados; suficiente para séries de demonstração.
    return d.weekday() < 5


def last_business_day(d: date) -> date:
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def business_days_back(end: date, count: int) -> list[date]:
    """Lista crescente com `count` dias úteis terminando em `end` (inclusive, se útil)."""
    days: list[date] = []
    cursor = last_business_day(end)
    while len(days) < count:
        if is_business_day(cursor):
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))
