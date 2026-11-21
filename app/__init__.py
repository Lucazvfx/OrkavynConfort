"""Application factory do AgroRadar."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import click
from flask import Flask, jsonify
from flask.json.provider import DefaultJSONProvider

from .config import Config
from .extensions import db

log = logging.getLogger(__name__)


class IsoJSONProvider(DefaultJSONProvider):
    """Datas em ISO 8601 (o padrão do Flask é RFC 822) e acentos preservados."""
    ensure_ascii = False
    sort_keys = False

    @staticmethod
    def default(o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__, instance_path=str(Path(__file__).resolve().parent.parent / "instance"))
    app.config.from_object(config_class)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(hours=12))
    app.json = IsoJSONProvider(app)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    if app.config.get("SECRET_KEY") == "dev-insecure-change-me" and not (app.debug or app.testing):
        log.warning("SECRET_KEY padrão em uso: defina SECRET_KEY no .env antes de expor o /admin.")

    db.init_app(app)
    with app.app_context():
        from . import models  # noqa: F401  (registra as tabelas no metadata)

        # Sem Alembic por enquanto: create_all é idempotente (não altera colunas existentes).
        db.create_all()

    from .routes.admin_routes import bp as admin_bp
    from .routes.api_routes import bp as api_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    _register_cli(app)
    # O agendador NÃO sobe aqui: seed, testes e `flask jobs` também chamam create_app.
    # Quem serve a aplicação (run.py / wsgi.py) chama init_scheduler explicitamente.
    return app


def _register_cli(app: Flask) -> None:
    @app.cli.group()
    def jobs():
        """Executa jobs manualmente (alternativa ao agendador via cron do SO)."""

    @jobs.command("run")
    @click.argument("name")
    def run(name):
        from .services.jobs import run_job
        click.echo(run_job(name, db.session, app.config, trigger="manual"))

    @jobs.command("list")
    def list_jobs():
        from .services.jobs import JOBS
        click.echo(", ".join(JOBS))
