"""Fixture SINTÉTICA: segue os nomes de campo vistos no código da página do IMEA,
não é uma resposta real da API (não acessada sem autorização)."""
from datetime import date

from app.models import CattleQuote, JobRun, Praca, SlaughterSchedule
from app.services.imea_service import parse_rows, save_rows, sync_imea
from tests.conftest import FakeHTTP, FakeResponse

BOI, VACA, ESCALA = "708192508809576456", "708192508809576457", "708192508809576449"
PAYLOAD = [
    {"IndicadorFinalId": BOI, "Localidade": "Centro-Sul", "Valor": 372.5, "Variacao": 0.4, "DataPublicacao": "2026-11-20T00:00:00"},
    {"IndicadorFinalId": BOI, "Localidade": "Oeste", "Valor": "368,10", "Variacao": 0.2, "DataPublicacao": "20/11/2026"},
    {"IndicadorFinalId": VACA, "Localidade": "Oeste", "Valor": 341.0, "DataPublicacao": "2026-11-20"},
    {"IndicadorFinalId": ESCALA, "Localidade": "Oeste", "Valor": 4.5, "DataPublicacao": "2026-11-20"},
    {"IndicadorFinalId": BOI, "Localidade": "Norte", "Valor": 360.0, "DataPublicacao": "2026-11-20"},  # sem praça
    {"IndicadorFinalId": "999", "Localidade": "Oeste", "Valor": 1, "DataPublicacao": "2026-11-20"},     # ignorado
]


def _pracas(session):
    session.add_all([Praca(code="MT_CUIABA", name="Cuiabá", uf="MT", latitude=0, longitude=0),
                     Praca(code="MT_PONTES_LACERDA", name="Pontes e Lacerda", uf="MT", latitude=0, longitude=0)])
    session.commit()


def test_parse_accepts_both_number_and_date_formats():
    rows = parse_rows({"data": PAYLOAD})
    assert len(rows) == 5
    oeste = next(r for r in rows if r.region == "Oeste" and r.indicator_id == BOI)
    assert oeste.value == 368.10 and oeste.ref_date == date(2026, 11, 20)


def test_save_maps_regions_and_preserves_manual(session):
    _pracas(session)
    pl = session.query(Praca).filter_by(code="MT_PONTES_LACERDA").one()
    session.add(CattleQuote(praca_id=pl.id, quote_date=date(2026, 11, 20), category="vaca_gorda", price=345, source="manual"))
    session.commit()
    res = save_rows(session, parse_rows(PAYLOAD))
    assert res.saved == 3 and res.skipped_manual == 1 and res.unmapped_regions == {"Norte"}
    assert session.query(CattleQuote).filter_by(source="imea").count() == 2
    esc = session.query(SlaughterSchedule).one()
    assert esc.days_ahead == 4.5 and esc.supply_level == "restrita" and esc.source == "imea"


def test_disabled_by_default_makes_no_request(session):
    http = FakeHTTP({})  # qualquer chamada quebraria o teste
    res = sync_imea(session, {}, http=http)
    assert res.enabled is False and http.calls == []
    assert "aguardando autorização" in session.query(JobRun).filter_by(job_name="imea").one().detail


def test_enabled_fetches_with_referer(session):
    _pracas(session)
    http = FakeHTTP({"api1.imea.com.br": FakeResponse(PAYLOAD)})
    res = sync_imea(session, {"IMEA_ENABLED": "true"}, http=http)
    assert res.saved == 4
    assert http.calls[0][1]["headers"]["Referer"].startswith("https://www.imea.com.br/")
