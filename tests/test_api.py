def test_dashboard_has_every_module(client):
    r = client.get("/api/dashboard?praca=MT_CUIABA")
    assert r.status_code == 200
    d = r.json
    assert d["praca"]["code"] == "MT_CUIABA"
    assert set(d["kpis"]["prices"]) == {"boi_gordo", "vaca_gorda", "boi_china"}
    assert d["kpis"]["is_demo"] is True and d["kpis"]["freshness"]["stale"] is False
    assert {"bezerro", "milho", "farelo_soja"} <= set(d["trade"]["items"])
    assert len(d["futures"]["contracts"]) == 4
    assert d["cycle"]["uf"] == "MT" and d["cycle"]["interpretation"]["phase"]
    assert d["weather"]["alert"]["code"] in {"dry", "neutral", "wet"}
    assert d["briefing"]["uf"] == "MT" and d["news"]


def test_default_praca_and_errors(client):
    assert client.get("/api/kpis").json["praca"] == "RO_VILHENA"
    r = client.get("/api/kpis?praca=XX_NADA")
    assert r.status_code == 404 and "não encontrada" in r.json["error"]
    assert client.get("/api/cycle?uf=AM").status_code == 404


def test_trade_ratio_consistency(client):
    t = client.get("/api/trade?praca=SP_ARACATUBA").json
    calf = t["items"]["bezerro"]
    assert abs(calf["arrobas_per_calf"] * calf["calves_per_boi_18"] - 18) < 0.05


def test_basis_equals_physical_minus_settlement(client):
    f = client.get("/api/futures?praca=RO_VILHENA").json
    c = f["contracts"][0]
    assert c["basis_rs"] == round(f["physical"] - c["settlement"], 2)
    assert f["history"]["average_rs"] is not None


def test_heatmap_covers_all_states(client):
    states = client.get("/api/heatmap").json["states"]
    assert {s["uf"] for s in states} == {"RO", "MT", "MS", "GO", "SP", "PA", "TO"}
    ro = next(s for s in states if s["uf"] == "RO")
    assert len(ro["pracas"]) == 2 and ro["default_praca"] == "RO_VILHENA"


def test_news_filters(client):
    pa = client.get("/api/news?uf=PA").json
    assert pa["total"] > 0 and all(n["uf"] in ("PA", "BR") for n in pa["items"])
    neg = client.get("/api/news?sentiment=negativo").json
    assert all(n["sentiment"] == "negativo" for n in neg["items"])
    assert client.get("/api/news?q=Marabá").json["total"] >= 1
    assert client.get("/api/news?per_page=5&page=2").json["per_page"] == 5


def test_history_and_dates_are_iso(client):
    h = client.get("/api/history?praca=GO_GOIANIA&days=30").json
    assert h["prices"]["boi_gordo"][0]["date"].count("-") == 2


def test_simulator_endpoint_projects_price_from_b3(client):
    r = client.post("/api/simulator", json={"praca": "RO_VILHENA", "peso_atual_arroba": 17,
                                            "gmd_kg": 0.9, "dias": 45, "custo_diario": 12})
    assert r.status_code == 200
    assert r.json["price_projection"]["method"].startswith("B3")
    assert r.json["result"]["arrobas_hoje"] == 17.0


def test_simulator_validation_error(client):
    r = client.post("/api/simulator", json={"praca": "RO_VILHENA", "peso_atual_kg": 480,
                                            "gmd_kg": 9, "dias": 30, "custo_diario": 10})
    assert r.status_code == 422 and any("gmd_kg" in e for e in r.json["details"])
