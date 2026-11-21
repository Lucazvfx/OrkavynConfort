"""Registro único dos jobs: usado pelo agendador, pelo /admin e pelo CLI (`flask jobs run`)."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from . import briefing_service
from .ibge_service import sync_female_slaughter
from .rss_collector import collect_news
from .weather_service import update_weather


def _rss(session, settings: Mapping, **_) -> dict:
    r = collect_news(session, settings)
    return {"inserted": r.inserted, "failed_feeds": [f.name for f in r.failed], "detail": r.summary()}


def _weather(session, settings: Mapping, **_) -> dict:
    snaps = update_weather(session, settings)
    return {"snapshots": len(snaps)}


def _ibge(session, settings: Mapping, **_) -> dict:
    return {"quarters_upserted": sync_female_slaughter(session, settings)}


def _briefing(session, settings: Mapping, trigger: str = "scheduler", **_) -> dict:
    rows = briefing_service.generate_all(session, settings, trigger=trigger)
    return {"briefings": len(rows), "providers": sorted({r.provider for r in rows})}


JOBS: dict[str, Callable[..., dict]] = {
    "rss": _rss,
    "weather": _weather,
    "ibge": _ibge,
    "briefing": _briefing,
}


def run_job(name: str, session, settings: Mapping, **kwargs) -> dict:
    if name not in JOBS:
        raise KeyError(f"Job desconhecido: {name}. Opções: {', '.join(JOBS)}")
    return JOBS[name](session, settings, **kwargs)
