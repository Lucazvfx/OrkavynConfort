"""Consultas de mercado reutilizáveis (base para os cálculos da Etapa 2)."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from ..models import (
    CattleQuote, FemaleSlaughterStat, FuturesQuote, Praca, SlaughterSchedule, WeatherSnapshot,
)


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or not old:
        return None
    return round((new - old) / old * 100, 2)


def latest_quote(session, praca_id: int, category: str, on_or_before: date | None = None) -> CattleQuote | None:
    stmt = select(CattleQuote).where(CattleQuote.praca_id == praca_id, CattleQuote.category == category)
    if on_or_before:
        stmt = stmt.where(CattleQuote.quote_date <= on_or_before)
    return session.scalars(stmt.order_by(CattleQuote.quote_date.desc()).limit(1)).first()


def price_with_changes(session, praca_id: int, category: str) -> dict:
    """Preço atual + variação vs. cotação anterior (dia) e vs. ≥7 dias corridos antes (semana)."""
    current = latest_quote(session, praca_id, category)
    if not current:
        return {"price": None, "date": None, "change_day_pct": None, "change_week_pct": None}
    prev = latest_quote(session, praca_id, category, current.quote_date - timedelta(days=1))
    week = latest_quote(session, praca_id, category, current.quote_date - timedelta(days=7))
    return {
        "price": current.price, "date": current.quote_date,
        "change_day_pct": pct_change(current.price, prev.price if prev else None),
        "change_week_pct": pct_change(current.price, week.price if week else None),
    }


def latest_schedule(session, praca_id: int) -> SlaughterSchedule | None:
    return session.scalars(select(SlaughterSchedule).where(SlaughterSchedule.praca_id == praca_id)
                           .order_by(SlaughterSchedule.ref_date.desc()).limit(1)).first()


def latest_weather(session, praca_id: int) -> WeatherSnapshot | None:
    return session.scalars(select(WeatherSnapshot).where(WeatherSnapshot.praca_id == praca_id)
                           .order_by(WeatherSnapshot.fetched_at.desc()).limit(1)).first()


def latest_female_stat(session, uf: str) -> FemaleSlaughterStat | None:
    return session.scalars(select(FemaleSlaughterStat).where(FemaleSlaughterStat.uf == uf)
                           .order_by(FemaleSlaughterStat.year.desc(), FemaleSlaughterStat.quarter.desc())
                           .limit(1)).first()


def latest_futures_curve(session) -> list[FuturesQuote]:
    last_date = session.scalar(select(func.max(FuturesQuote.quote_date)))
    if not last_date:
        return []
    return list(session.scalars(select(FuturesQuote).where(FuturesQuote.quote_date == last_date)
                                .order_by(FuturesQuote.maturity_month)))


def state_reference_praca(session, uf: str) -> Praca | None:
    praca = session.scalars(select(Praca).where(Praca.uf == uf, Praca.active.is_(True))
                            .order_by(Praca.is_state_reference.desc(), Praca.id).limit(1)).first()
    return praca
