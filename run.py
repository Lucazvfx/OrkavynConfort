"""Servidor de desenvolvimento: `python run.py` (sobe API + agendador)."""
from app import create_app
from app.scheduler import init_scheduler

app = create_app()

if __name__ == "__main__":
    app.debug = True     # precisa valer antes do init: o pai do reloader não agenda
    init_scheduler(app)
    app.run(debug=True, host="0.0.0.0", port=5000)
