"""Entrada de produção: `gunicorn -w 2 wsgi:app`.

O lock de arquivo em init_scheduler garante um único agendador entre os workers.
"""
from app import create_app
from app.scheduler import init_scheduler

app = create_app()
init_scheduler(app)
