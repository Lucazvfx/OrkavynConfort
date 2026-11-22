"""APScheduler: rotinas agendadas do AgroRadar.

Agenda (fuso SCHEDULER_TIMEZONE, padrão America/Sao_Paulo):
  rss       de hora em hora, 05h–22h (min 10) + 05:40 garantido antes do boletim
  weather   05:20 diário (Open-Meteo atualiza os modelos de madrugada)
  briefing  BRIEFING_HOUR:00 diário (padrão 06:00)
  ibge      segunda 07:00 (o IBGE publica trimestral; checar semanalmente basta)
  cepea     dias úteis 18:30 (indicadores do dia saem no fim da tarde)

Atenção: 06:00 de Brasília = 05:00 em RO. Ajuste BRIEFING_HOUR se o público for RO/AM.

Processo único: o agendador roda dentro do processo web. Com vários workers
(gunicorn -w 4) cada worker subiria o seu — evitamos isso com um lock de arquivo
em instance/scheduler.lock (POSIX). Em Windows o lock é ignorado: use 1 worker.
"""
from __future__ import annotations

import atexit
import logging
import os
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask

from .extensions import db
from .services.jobs import run_job

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_lock_handle = None


def _acquire_lock(instance_path: str) -> bool:
    global _lock_handle
    try:
        import fcntl
    except ImportError:  # Windows
        return True
    handle = open(Path(instance_path) / "scheduler.lock", "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _lock_handle = handle  # mantém o descritor aberto enquanto o processo viver
    return True


def _job_wrapper(app: Flask, name: str):
    def _run():
        with app.app_context():
            try:
                result = run_job(name, db.session, app.config, trigger="scheduler")
                log.info("Job %s ok: %s", name, result)
            except Exception as exc:  # já registrado em job_runs pelo track_job
                log.error("Job %s falhou: %s", name, exc)
            finally:
                db.session.remove()
    _run.__name__ = f"job_{name}"
    return _run


def build_schedule(app: Flask) -> list[tuple[str, CronTrigger]]:
    tz = app.config.get("SCHEDULER_TIMEZONE", "America/Sao_Paulo")
    hour = int(app.config.get("BRIEFING_HOUR", 6))
    pre = (hour - 1) % 24
    return [
        ("rss", CronTrigger(hour="5-22", minute=10, timezone=tz)),
        ("rss_pre_briefing", CronTrigger(hour=pre, minute=40, timezone=tz)),
        ("weather", CronTrigger(hour=pre, minute=20, timezone=tz)),
        ("briefing", CronTrigger(hour=hour, minute=0, timezone=tz)),
        ("ibge", CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=tz)),
        ("cepea", CronTrigger(day_of_week="mon-fri", hour=18, minute=30, timezone=tz)),
        ("imea", CronTrigger(day_of_week="mon-fri", hour=18, minute=0, timezone=tz)),
    ]


def init_scheduler(app: Flask) -> BackgroundScheduler | None:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if not app.config.get("SCHEDULER_ENABLED", True) or app.config.get("TESTING"):
        return None
    if app.config.get("ON_VERCEL"):  # serverless: quem agenda é o Vercel Cron (vercel.json)
        return None
    # Reloader do Flask em debug cria um processo pai que não deve agendar nada.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return None
    if not _acquire_lock(app.instance_path):
        log.info("Agendador já ativo em outro processo; este worker não agenda jobs.")
        return None

    sched = BackgroundScheduler(timezone=app.config.get("SCHEDULER_TIMEZONE", "America/Sao_Paulo"),
                                job_defaults={"coalesce": True, "max_instances": 1,
                                              "misfire_grace_time": 15 * 60})
    for job_id, trigger in build_schedule(app):
        name = "rss" if job_id.startswith("rss") else job_id
        sched.add_job(_job_wrapper(app, name), trigger, id=job_id, replace_existing=True)
    sched.start()
    atexit.register(lambda: sched.running and sched.shutdown(wait=False))
    _scheduler = sched
    log.info("Agendador iniciado: %s", [j.id for j in sched.get_jobs()])
    return sched


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def next_runs() -> list[dict]:
    if not _scheduler:
        return []
    return [{"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
            for j in _scheduler.get_jobs()]
