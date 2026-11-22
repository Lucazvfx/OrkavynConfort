"""Endpoints de agendamento para hospedagem serverless (Vercel Cron).

Na Vercel não existe processo contínuo para o APScheduler: o Vercel Cron chama
GET /api/cron/<job> no horário definido em vercel.json, enviando
"Authorization: Bearer <CRON_SECRET>". Sem CRON_SECRET configurado, os
endpoints ficam desligados (503) — nunca abertos.
"""
from __future__ import annotations

import hmac

from flask import Blueprint, current_app, jsonify, request

from ..extensions import db
from ..services.jobs import JOBS, run_job

bp = Blueprint("cron", __name__, url_prefix="/api/cron")


@bp.get("/<name>")
def run(name: str):
    secret = current_app.config.get("CRON_SECRET")
    if not secret:
        return jsonify(error="Agendamento desligado: defina CRON_SECRET"), 503
    sent = request.headers.get("Authorization", "")
    if not hmac.compare_digest(sent.encode(), f"Bearer {secret}".encode()):
        return jsonify(error="Não autorizado"), 401
    if name not in JOBS:
        return jsonify(error=f"Job desconhecido. Opções: {', '.join(JOBS)}"), 404
    try:
        result = run_job(name, db.session, current_app.config, trigger="scheduler")
    except Exception as exc:  # já registrado em job_runs
        return jsonify(ok=False, job=name, error=str(exc)[:500]), 502
    return jsonify(ok=True, job=name, result=result)
