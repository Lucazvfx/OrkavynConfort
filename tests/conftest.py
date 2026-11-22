import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db as _db


class FakeResponse:
    def __init__(self, payload=None, status=200, content=b"", text=""):
        self._payload, self.status_code = payload, status
        self.content, self.text = content, text or str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHTTP:
    """Substitui requests.Session: responde por substring de URL e registra as chamadas."""
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _match(self, url, **kw):
        self.calls.append((url, kw))
        for key, resp in self.routes.items():
            if key in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise RuntimeError(f"rota não mapeada: {url}")

    get = post = _match


@pytest.fixture(autouse=True)
def _reset_login_limiter():
    from app.routes import admin_routes
    admin_routes._login_attempts.clear()
    yield
    admin_routes._login_attempts.clear()


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def session(app):
    return _db.session


@pytest.fixture()
def seeded(app):
    """Banco com dados de demonstração (40 dias úteis até hoje)."""
    from datetime import date

    import seed
    seed.RNG.seed(42)
    seed.populate(date.today(), 40, app.config)
    return app


@pytest.fixture()
def client(seeded):
    return seeded.test_client()


@pytest.fixture()
def admin_client(client):
    r = client.post("/admin/login", json={"password": "test"})
    assert r.status_code == 200
    client.csrf = r.json["csrf_token"]
    return client
