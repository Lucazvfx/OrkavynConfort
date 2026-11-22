"""Páginas HTML (o conteúdo é carregado via /api pelo JavaScript)."""
from flask import Blueprint, render_template

bp = Blueprint("web", __name__)


@bp.get("/")
def index():
    return render_template("index.html")
