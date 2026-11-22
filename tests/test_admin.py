from datetime import date, timedelta

from app.models import CattleQuote, FuturesQuote, SlaughterSchedule


def post(c, url, payload):
    return c.post(url, json=payload, headers={"X-CSRF-Token": c.csrf})


def test_requires_login_and_csrf(client):
    assert client.get("/admin/api/status").status_code == 401
    assert client.post("/admin/login", json={"password": "errada"}).status_code == 401
    r = client.post("/admin/login", json={"password": "test"})
    assert r.status_code == 200
    # sem CSRF => 403
    assert client.post("/admin/api/quotes/cattle", json={"praca": "RO_VILHENA", "boi_gordo": 300}).status_code == 403


def test_login_rate_limit(client):
    for _ in range(5):
        client.post("/admin/login", json={"password": "x"})
    assert client.post("/admin/login", json={"password": "test"}).status_code == 429


def test_admin_disabled_without_password(seeded):
    seeded.config["ADMIN_PASSWORD"] = None
    assert seeded.test_client().post("/admin/login", json={"password": ""}).status_code == 503


def test_cattle_quote_upsert_and_dashboard_reflects(admin_client, session):
    today = date.today().isoformat()
    r = post(admin_client, "/admin/api/quotes/cattle",
             {"praca": "RO_VILHENA", "date": today, "boi_gordo": "333,50", "vaca_gorda": 310})
    assert r.status_code == 200 and r.json["saved"] == ["boi_gordo", "vaca_gorda"]
    post(admin_client, "/admin/api/quotes/cattle", {"praca": "RO_VILHENA", "date": today, "boi_gordo": 334})
    rows = session.query(CattleQuote).filter_by(quote_date=date.today(), category="boi_gordo").all()
    assert len([q for q in rows if q.praca.code == "RO_VILHENA"]) == 1
    k = admin_client.get("/api/kpis?praca=RO_VILHENA").json
    assert k["prices"]["boi_gordo"]["price"] == 334 and k["prices"]["boi_gordo"]["source"] == "manual"


def test_sanity_bounds_and_future_date(admin_client):
    r = post(admin_client, "/admin/api/quotes/cattle", {"praca": "RO_VILHENA", "boi_gordo": 3100})
    assert r.status_code == 422 and "fora da faixa" in r.json["details"][0]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = post(admin_client, "/admin/api/quotes/cattle", {"praca": "RO_VILHENA", "date": tomorrow, "boi_gordo": 300})
    assert r.status_code == 400


def test_schedule_derives_supply(admin_client, session):
    r = post(admin_client, "/admin/api/schedules", {"praca": "PA_MARABA", "days_ahead": 3.5})
    assert r.status_code == 200 and r.json["supply_level"] == "restrita"
    s = session.query(SlaughterSchedule).filter_by(ref_date=date.today(), source="manual").one()
    assert s.days_ahead == 3.5


def test_futures_contract_parsing(admin_client, session):
    r = post(admin_client, "/admin/api/futures",
             {"contracts": [{"contract": "bgiz26", "settlement": 320.1}, {"contract": "BGIF27", "settlement": 318}]})
    assert r.status_code == 200 and r.json["saved"] == ["BGIZ26", "BGIF27"]
    f = session.query(FuturesQuote).filter_by(contract_code="BGIF27", quote_date=date.today()).one()
    assert f.maturity_month == date(2027, 1, 1)
    bad = post(admin_client, "/admin/api/futures", {"contracts": [{"contract": "XYZ", "settlement": 300}]})
    assert bad.status_code == 422


def test_female_slaughter_manual(admin_client):
    r = post(admin_client, "/admin/api/female-slaughter",
             {"uf": "RO", "year": 2026, "quarter": 3, "total_head": 1000, "cows_head": 380, "heifers_head": 90})
    assert r.status_code == 200 and r.json["female_share"] == 47.0
    assert admin_client.get("/api/cycle?uf=RO").json["latest"]["label"] == "3T26"


def test_run_job_manually(admin_client, monkeypatch):
    from app.services import jobs
    monkeypatch.setitem(jobs.JOBS, "rss", lambda s, cfg, **kw: {"inserted": 3, "trigger": kw.get("trigger")})
    r = post(admin_client, "/admin/api/jobs/rss/run", {})
    assert r.status_code == 200 and r.json["result"] == {"inserted": 3, "trigger": "manual"}
    assert post(admin_client, "/admin/api/jobs/nada/run", {}).status_code == 404


def test_briefing_job_runs_with_rules(admin_client):
    r = post(admin_client, "/admin/api/jobs/briefing/run", {})
    assert r.status_code == 200 and r.json["result"]["providers"] == ["rules"]


def test_status(admin_client):
    s = admin_client.get("/admin/api/status").json
    assert len(s["pracas"]) == 10 and len(s["contracts_to_fill"]) == 4


def test_schedule_from_abate_date_counts_business_days(admin_client, session):
    from app.utils import business_days_between
    d = date.today()
    abate = d + timedelta(days=7)
    r = post(admin_client, "/admin/api/schedules", {"praca": "RO_VILHENA", "date": d.isoformat(), "abate_date": abate.isoformat()})
    assert r.status_code == 200 and r.json["days_ahead"] == business_days_between(d, abate)
    bad = post(admin_client, "/admin/api/schedules", {"praca": "RO_VILHENA", "abate_date": d.isoformat()})
    assert bad.status_code == 422
    empty = post(admin_client, "/admin/api/schedules", {"praca": "RO_VILHENA"})
    assert empty.status_code == 422 and "data do abate" in empty.json["details"][0]


def test_national_reference_when_praca_has_no_schedule(admin_client, session):
    from app.models import Praca
    session.add(Praca(code="BR_MEDIA", name="Média nacional", uf="BR", latitude=0, longitude=0, active=False))
    session.query(SlaughterSchedule).filter(SlaughterSchedule.praca.has(code="PA_MARABA")).delete(synchronize_session=False)
    session.commit()
    post(admin_client, "/admin/api/schedules", {"praca": "BR_MEDIA", "days_ahead": 5.77})
    k = admin_client.get("/api/kpis?praca=PA_MARABA").json
    assert k["schedule"]["days_ahead"] is None
    assert k["schedule"]["national_reference"]["days_ahead"] == 5.77
    assert "BR_MEDIA" not in [p["code"] for s in admin_client.get("/api/pracas").json["states"] for p in s["pracas"]]


def test_recent_and_delete_entry(admin_client, session):
    r = admin_client.get("/admin/api/recent?praca=RO_VILHENA")
    assert r.status_code == 200 and r.json["entries"]
    e = next(x for x in r.json["entries"] if x["kind"] == "cattle")
    assert post(admin_client, "/admin/api/entries/delete", {"kind": "cattle", "id": e["id"]}).status_code == 200
    assert session.get(CattleQuote, e["id"]) is None
    assert post(admin_client, "/admin/api/entries/delete", {"kind": "cattle", "id": e["id"]}).status_code == 404
    assert post(admin_client, "/admin/api/entries/delete", {"kind": "x", "id": 1}).status_code == 422
    # exige CSRF
    assert admin_client.post("/admin/api/entries/delete", json={"kind": "cattle", "id": 1}).status_code == 403
