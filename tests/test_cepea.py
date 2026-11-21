from datetime import date
from pathlib import Path

import pytest

from app.models import CattleQuote, InputQuote, JobRun, Praca
from app.services.cepea_service import (
    CepeaError, parse_brl, parse_indicator_table, save_indicator, sync_cepea,
)
from tests.conftest import FakeHTTP, FakeResponse

FIXTURE = (Path(__file__).parent / "fixtures" / "cepea_boi.html").read_text(encoding="utf-8")


def test_parse_real_page():
    rows = parse_indicator_table(FIXTURE)
    assert len(rows) == 15
    assert rows[-1] == (date(2026, 11, 19), 395.50)   # último valor publicado na página real
    assert rows == sorted(rows)                        # do mais antigo ao mais recente


def test_parse_brl():
    assert parse_brl("3.412,55") == 3412.55
    assert parse_brl("R$ 395,50") == 395.5
    assert parse_brl("-") is None


def test_detects_block_and_layout_change():
    with pytest.raises(CepeaError, match="Cloudflare"):
        parse_indicator_table("<title>Attention Required! | Cloudflare</title>")
    with pytest.raises(CepeaError, match="layout"):
        parse_indicator_table("<table><tr><td>nada</td></tr></table>")


def _pracas(session):
    session.add_all([Praca(code="SP_ARACATUBA", name="Araçatuba", uf="SP", latitude=0, longitude=0),
                     Praca(code="MS_CAMPO_GRANDE", name="Campo Grande", uf="MS", latitude=0, longitude=0)])
    session.commit()


def test_manual_entry_is_never_overwritten(session):
    _pracas(session)
    sp = session.query(Praca).filter_by(code="SP_ARACATUBA").one()
    session.add(CattleQuote(praca_id=sp.id, quote_date=date(2026, 11, 19), category="boi_gordo",
                            price=401.0, source="manual"))
    session.commit()
    res = save_indicator(session, "boi_gordo_sp", parse_indicator_table(FIXTURE))
    assert res.skipped_manual == 1 and res.saved == 14
    q = session.query(CattleQuote).filter_by(quote_date=date(2026, 11, 19)).one()
    assert q.price == 401.0 and q.source == "manual"
    assert session.query(CattleQuote).filter_by(source="cepea").count() == 14


def test_sync_isolates_failures(session):
    _pracas(session)
    http = FakeHTTP({
        "boi-gordo.aspx": FakeResponse(text=FIXTURE),
        "bezerro.aspx": FakeResponse(status=403, text="blocked"),
        "milho.aspx": ConnectionError("timeout"),
    })
    r = sync_cepea(session, {}, http=http, pause=0)
    assert [i.key for i in r.failed] == ["bezerro_ms", "milho"]
    assert "403" in r.failed[0].error
    assert session.query(CattleQuote).filter_by(source="cepea").count() == 15
    assert session.query(InputQuote).count() == 0
    assert session.query(JobRun).filter_by(job_name="cepea").one().status == "partial"


def test_real_series_replaces_demo_series(session):
    _pracas(session)
    sp = session.query(Praca).filter_by(code="SP_ARACATUBA").one()
    # série fictícia antiga + um dia de vaca (outra série, deve ficar)
    session.add_all([CattleQuote(praca_id=sp.id, quote_date=date(2026, 9, d), category="boi_gordo",
                                 price=320.0, source="seed") for d in range(1, 6)])
    session.add(CattleQuote(praca_id=sp.id, quote_date=date(2026, 9, 1), category="vaca_gorda", price=300.0, source="seed"))
    session.commit()
    save_indicator(session, "boi_gordo_sp", parse_indicator_table(FIXTURE))
    boi = session.query(CattleQuote).filter_by(praca_id=sp.id, category="boi_gordo").all()
    assert {q.source for q in boi} == {"cepea"} and len(boi) == 15
    assert session.query(CattleQuote).filter_by(category="vaca_gorda").count() == 1
