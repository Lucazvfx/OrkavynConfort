"""Context manager que registra execuções de jobs na tabela job_runs."""
from __future__ import annotations

import logging
from contextlib import contextmanager

from ..models import JobRun
from ..utils import utcnow

log = logging.getLogger(__name__)


@contextmanager
def track_job(session, job_name: str):
    """Uso:
        with track_job(db.session, "rss") as run:
            ...
            run.detail = "12 novas"
            run.status = "partial"   # opcional; padrão = success
    Exceções são registradas como `error` e re-levantadas.
    """
    run = JobRun(job_name=job_name, status="running")
    session.add(run)
    session.commit()
    try:
        yield run
    except Exception as exc:
        session.rollback()
        run.status = "error"
        run.detail = f"{type(exc).__name__}: {exc}"[:2000]
        run.finished_at = utcnow()
        session.add(run)
        session.commit()
        log.error("Job %s falhou: %s", job_name, run.detail, exc_info=log.isEnabledFor(logging.DEBUG))
        raise
    else:
        if run.status == "running":
            run.status = "success"
        run.finished_at = utcnow()
        session.commit()
