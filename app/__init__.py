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
    # Na Vercel só /tmp é gravável; localmente usa ./instance.
    instance = "/tmp/agroradar-instance" if config_class.ON_VERCEL else str(Path(__file__).resolve().parent.parent / "instance")
    app = Flask(__name__, instance_path=instance)
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
        if app.config.get("AUTO_SEED_DEMO"):
            _seed_if_empty(app)

    from .routes.admin_routes import bp as admin_bp
    from .routes.api_routes import bp as api_bp
    from .routes.cron_routes import bp as cron_bp
    from .routes.web_routes import bp as web_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(cron_bp)
    app.register_blueprint(web_bp)
    app.register_blueprint(admin_bp)

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    _register_cli(app)
    # O agendador NÃO sobe aqui: seed, testes e `flask jobs` também chamam create_app.
    # Quem serve a aplicação (run.py / wsgi.py) chama init_scheduler explicitamente.
    return app


def _seed_if_empty(app: Flask) -> None:
    """Primeiro deploy: popula dados de demonstração se não houver praças.

    Duas instâncias frias simultâneas podem tentar ao mesmo tempo; a restrição
    única de `pracas.code` faz uma delas falhar e desfazer tudo, sem duplicar.
    """
    from .models import Praca
    if db.session.query(Praca.id).first():
        return
    try:
        import sys
        root = str(Path(__file__).resolve().parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        import seed
        seed.populate(date.today(), 60, app.config)
        log.info("Banco vazio: dados de demonstração carregados.")
    except Exception as exc:  # outra instância venceu a corrida, ou falha de rede
        db.session.rollback()
        log.warning("Seed automático não executado: %s", exc)


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
