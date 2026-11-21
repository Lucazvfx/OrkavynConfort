"""Entrada WSGI.

- Vercel: detecta o Flask por este arquivo e roteia todas as requisições para `app`.
  O agendamento lá é do Vercel Cron (vercel.json); init_scheduler não faz nada na Vercel.
- Servidor próprio: `gunicorn -w 2 wsgi:app` (o lock de arquivo garante 1 agendador).
"""
from app import create_app
from app.scheduler import init_scheduler

app = create_app()
init_scheduler(app)
