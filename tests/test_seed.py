from datetime import date

import seed
from app.data.b3 import next_contracts
from app.extensions import db
from app.models import (
    CattleQuote, DailyBriefing, FemaleSlaughterStat, FuturesQuote, InputQuote, NewsArticle,
    Praca, SlaughterSchedule, WeatherSnapshot,
)
from app.services import briefing_service


def test_next_contracts_rolls_after_last_trading_day():
    assert [c for c, _ in next_contracts(date(2026, 11, 20))] == ["BGIX26", "BGIZ26", "BGIF27", "BGIG27"]
    assert next_contracts(date(2026, 12, 31))[0][0] == "BGIZ26"  # quinta = último dia útil
    assert next_contracts(date(2027, 1, 30))[0][0] == "BGIG27"   # sábado após o vencimento de F27


def test_full_seed_populates_every_module(app):
    today = date(2026, 11, 21)
    days = seed.business_days_back(today, 30)
    pracas = seed.seed_pracas()
    seed.seed_market_series(pracas, days)
    db.session.flush()
    seed.seed_futures(days, pracas["SP_ARACATUBA"])
    seed.seed_female_slaughter(today)
    seed.seed_weather(pracas, today)
    seed.seed_news()
    db.session.commit()
    briefs = briefing_service.generate_all(db.session, {"AI_PROVIDER": "rules"}, trigger="seed", ref_date=today)

    assert db.session.query(Praca).count() == 10
    assert db.session.query(CattleQuote).count() == 10 * 30 * 3
    assert db.session.query(InputQuote).count() > 0
    assert db.session.query(SlaughterSchedule).count() == 10 * 30
    assert db.session.query(FuturesQuote).count() == 30 * 4
    assert db.session.query(WeatherSnapshot).count() == 10
    assert db.session.query(NewsArticle).count() == len(seed.DEMO_NEWS)
    last = db.session.query(FemaleSlaughterStat).filter_by(uf="BR").order_by(
        FemaleSlaughterStat.year.desc(), FemaleSlaughterStat.quarter.desc()).first()
    assert (last.year, last.quarter) == (2026, 2)
    assert len(briefs) == 7 and db.session.query(DailyBriefing).count() == 7
    # regenerar no mesmo dia não duplica
    briefing_service.generate_all(db.session, {"AI_PROVIDER": "rules"}, ref_date=today)
    assert db.session.query(DailyBriefing).count() == 7
