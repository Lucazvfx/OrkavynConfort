from app.models import FemaleSlaughterStat
from app.services.ibge_service import build_url, classify_cycle, parse_sidra, sync_female_slaughter
from tests.conftest import FakeHTTP, FakeResponse

HEADER = {"NC": "Nível Territorial (Código)", "V": "Valor",
          "D1C": "Brasil e Unidade da Federação (Código)", "D1N": "Brasil e Unidade da Federação",
          "D2C": "Variável (Código)", "D2N": "Variável",
          "D3C": "Trimestre (Código)", "D3N": "Trimestre",
          "D4C": "Tipo de rebanho bovino (Código)", "D4N": "Tipo de rebanho bovino"}


def row(terr, period, herd, value):
    return {"D1C": terr, "D1N": "x", "D2N": "Animais abatidos", "D3C": period, "D3N": "p",
            "D4N": herd, "V": value}


ROWS = [HEADER,
        row("1", "202601", "Total", "1000"), row("1", "202601", "Bois", "500"),
        row("1", "202601", "Novilhos", "80"), row("1", "202601", "Vacas", "350"),
        row("1", "202601", "Novilhas", "70"),
        row("11", "202601", "Total", "200"), row("11", "202601", "Vacas", "X"),  # sigilo
        row("11", "202601", "Novilhas", "-")]


def test_parse_and_share():
    recs = {(r.uf, r.year, r.quarter): r for r in parse_sidra(ROWS)}
    br = recs[("BR", 2026, 1)]
    assert br.total_head == 1000 and br.cows_head == 350
    assert br.female_share == 42.0
    assert recs[("RO", 2026, 1)].female_share is None  # dados sigilosos => sem share


def test_parse_ignores_non_total_aux_dimension():
    header = {**HEADER, "D5N": "Referência temporal"}
    rows = [header, {**row("1", "202601", "Total", "1000"), "D5N": "Total do trimestre"},
            {**row("1", "202601", "Total", "333"), "D5N": "1º mês"},
            {**row("1", "202601", "Vacas", "450"), "D5N": "Total do trimestre"}]
    rec = parse_sidra(rows)[0]
    assert rec.total_head == 1000 and rec.female_share == 45.0


def test_cycle_thresholds():
    assert classify_cycle(46)["phase"] == "liquidacao"
    assert classify_cycle(45)["phase"] == "equilibrio"
    assert classify_cycle(40)["phase"] == "equilibrio"
    assert classify_cycle(39.9)["phase"] == "retencao"
    assert classify_cycle(None)["phase"] == "indefinido"


def test_sync_upserts(session):
    http = FakeHTTP({"sidra": FakeResponse(ROWS)})
    assert sync_female_slaughter(session, {}, http=http) == 1
    assert sync_female_slaughter(session, {}, http=http) == 1  # idempotente
    assert session.query(FemaleSlaughterStat).count() == 1
    assert "/t/1092/" in build_url() and "/c18/all" in build_url()
