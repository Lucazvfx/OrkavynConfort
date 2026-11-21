"""Módulo D — Orquestra o "Boletim das 6h": banco → contexto → IA/regras → daily_briefings."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from sqlalchemy import select

from ..data.pracas import STATES
from ..models import CattleCategory, DailyBriefing, NewsArticle
from ..utils import utcnow
from . import market_queries as mq
from .ai_service import BriefingContext, generate_briefing
from .ibge_service import classify_cycle
from .job_log import track_job

NEWS_WINDOW_HOURS = 24
NEWS_POOL_SIZE = 30


def recent_news(session, hours: int = NEWS_WINDOW_HOURS, limit: int = NEWS_POOL_SIZE) -> list[NewsArticle]:
    """As últimas `limit` notícias coletadas nas `hours` anteriores (pool comum a todos os estados)."""
    cutoff = utcnow() - timedelta(hours=hours)
    return list(session.scalars(select(NewsArticle).where(NewsArticle.collected_at >= cutoff)
                                .order_by(NewsArticle.published_at.desc().nulls_last(),
                                          NewsArticle.collected_at.desc())
                                .limit(limit)))


def build_context(session, uf: str, news_pool: list[NewsArticle], ref_date: date) -> BriefingContext | None:
    praca = mq.state_reference_praca(session, uf)
    if praca is None:
        return None
    boi = mq.price_with_changes(session, praca.id, CattleCategory.BOI_GORDO)
    vaca = mq.latest_quote(session, praca.id, CattleCategory.VACA_GORDA)
    china = mq.latest_quote(session, praca.id, CattleCategory.BOI_CHINA)
    sched = mq.latest_schedule(session, praca.id)
    weather = mq.latest_weather(session, praca.id)
    female = mq.latest_female_stat(session, uf) or mq.latest_female_stat(session, "BR")
    curve = mq.latest_futures_curve(session)
    nearest = curve[0] if curve else None

    # Regionais primeiro, depois nacionais; pecuária de corte tem prioridade.
    regional = [n for n in news_pool if n.uf == uf]
    national = [n for n in news_pool if n.uf == "BR"]
    ordered = sorted(regional, key=lambda n: n.category != "pecuaria_corte") + \
        sorted(national, key=lambda n: n.category != "pecuaria_corte")

    return BriefingContext(
        uf=uf, state_name=STATES.get(uf, {}).get("name", uf), praca_name=praca.name,
        ref_date=ref_date.isoformat(),
        boi_price=boi["price"], boi_change_day_pct=boi["change_day_pct"],
        boi_change_week_pct=boi["change_week_pct"],
        vaca_price=vaca.price if vaca else None, china_price=china.price if china else None,
        schedule_days=sched.days_ahead if sched else None,
        supply_level=sched.supply_level if sched else None,
        weather_title=weather.alert_title if weather else None,
        weather_precip_mm=weather.precip_total_mm if weather else None,
        weather_bias=weather.price_bias if weather else None,
        female_share=female.female_share if female else None,
        cycle_label=classify_cycle(female.female_share)["label"] if female else None,
        futures_contract=nearest.contract_code if nearest else None,
        futures_price=nearest.settlement_price if nearest else None,
        basis=round(boi["price"] - nearest.settlement_price, 2) if (nearest and boi["price"]) else None,
        headlines=[{"title": n.title, "sentiment": n.sentiment, "category": n.category,
                    "source": n.source, "uf": n.uf} for n in ordered[:12]],
    )


def generate_all(session, settings: Mapping, trigger: str = "scheduler",
                 ufs: list[str] | None = None, ref_date: date | None = None, http=None) -> list[DailyBriefing]:
    """Gera (ou regenera) o boletim do dia para cada UF. Idempotente por (data, UF)."""
    ref_date = ref_date or date.today()
    ufs = ufs or list(STATES.keys())
    results: list[DailyBriefing] = []
    with track_job(session, "briefing") as run:
        pool = recent_news(session)
        providers = []
        for uf in ufs:
            ctx = build_context(session, uf, pool, ref_date)
            if ctx is None:
                continue
            res = generate_briefing(ctx, settings, http=http)
            existing = session.scalars(select(DailyBriefing).where(
                DailyBriefing.briefing_date == ref_date, DailyBriefing.uf == uf)).first()
            row = existing or DailyBriefing(briefing_date=ref_date, uf=uf)
            row.content, row.provider, row.model = res.content, res.provider, res.model
            row.news_count = len(ctx.headlines)
            row.trigger, row.fallback_reason, row.generated_at = trigger, res.fallback_reason, utcnow()
            session.add(row)
            results.append(row)
            providers.append(f"{uf}:{res.provider}")
        session.commit()
        run.detail = f"{len(results)} boletins ({', '.join(providers)}); pool de {len(pool)} notícias"
        if any(r.fallback_reason for r in results):
            run.status = "partial"
    return results
