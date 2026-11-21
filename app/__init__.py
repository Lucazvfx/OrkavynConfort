"""Application factory do AgroRadar.

Etapa 1: banco + healthcheck. Blueprints (API/admin) e agendador entram na Etapa 2.
"""
from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify

from .config import Config
from .extensions import db


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__, instance_path=str(Path(__file__).resolve().parent.parent / "instance"))
    app.config.from_object(config_class)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    with app.app_context():
        from . import models  # noqa: F401  (registra as tabelas no metadata)

        # Sem Alembic por enquanto: create_all é idempotente (não altera colunas existentes).
        db.create_all()

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    return app
