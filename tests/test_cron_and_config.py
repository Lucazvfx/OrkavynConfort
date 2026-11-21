from app.config import _database_url, _engine_options


def test_cron_disabled_without_secret(client):
    assert client.get("/api/cron/rss").status_code == 503


def test_cron_requires_bearer(seeded, monkeypatch):
    seeded.config["CRON_SECRET"] = "s3gredo"
    c = seeded.test_client()
    assert c.get("/api/cron/briefing").status_code == 401
    assert c.get("/api/cron/briefing", headers={"Authorization": "Bearer errado"}).status_code == 401
    assert c.get("/api/cron/nada", headers={"Authorization": "Bearer s3gredo"}).status_code == 404
    r = c.get("/api/cron/briefing", headers={"Authorization": "Bearer s3gredo"})
    assert r.status_code == 200 and r.json["result"]["briefings"] == 7


def test_postgres_url_and_serverless_engine(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:6543/postgres")
    url = _database_url()
    assert url.startswith("postgresql+psycopg://")
    opts = _engine_options(url)
    assert opts["connect_args"] == {"prepare_threshold": None}
    assert opts["poolclass"].__name__ == "NullPool"
    assert _engine_options("sqlite:///x.db") == {"pool_pre_ping": True}


def test_auto_seed_only_when_empty():
    from app import create_app
    from app.config import TestConfig
    from app.extensions import db
    from app.models import Praca

    class AutoSeed(TestConfig):
        AUTO_SEED_DEMO = True

    app = create_app(AutoSeed)
    with app.app_context():
        assert db.session.query(Praca).count() == 10
        from app import _seed_if_empty
        _seed_if_empty(app)  # segunda chamada não duplica
        assert db.session.query(Praca).count() == 10
        db.drop_all()
