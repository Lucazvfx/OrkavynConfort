"""API REST pública (somente leitura, exceto o simulador que não grava nada).

Todas as rotas por praça aceitam `?praca=RO_VILHENA`; sem o parâmetro usa a
primeira praça de referência ativa.
"""
from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func, or_, select
from werkzeug.exceptions import HTTPException

from ..data.pracas import STATES
from ..extensions import db
from ..models import DailyBriefing, NewsArticle, Praca
from ..services import calculations as calc

bp = Blueprint("api", __name__, url_prefix="/api")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, details=None):
        super().__init__(message)
        self.message, self.status, self.details = message, status, details


@bp.errorhandler(ApiError)
def _api_error(err: ApiError):
    body = {"error": err.message}
    if err.details:
        body["details"] = err.details
    return jsonify(body), err.status


@bp.errorhandler(HTTPException)
def _http_error(err: HTTPException):
    return jsonify(error=err.description), err.code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def resolve_praca(code: str | None = None) -> Praca:
    code = (code or request.args.get("praca") or "").strip().upper()
    stmt = select(Praca).where(Praca.active.is_(True))
    if code:
        praca = db.session.scalars(stmt.where(Praca.code == code)).first()
        if not praca:
            raise ApiError(f"Praça '{code}' não encontrada", 404)
        return praca
    praca = db.session.scalars(stmt.order_by(Praca.is_state_reference.desc(), Praca.id)).first()
    if not praca:
        raise ApiError("Nenhuma praça cadastrada. Rode `python seed.py`.", 404)
    return praca


def resolve_uf(default: str | None = None) -> str:
    uf = (request.args.get("uf") or default or "").strip().upper()
    if uf not in STATES and uf != "BR":
        raise ApiError(f"UF '{uf}' não monitorada. Opções: {', '.join(STATES)}, BR", 404)
    return uf


def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(request.args.get(name, default))
    except ValueError as exc:
        raise ApiError(f"Parâmetro '{name}' deve ser inteiro") from exc
    return max(lo, min(hi, value))


def latest_briefing(uf: str) -> dict | None:
    row = db.session.scalars(select(DailyBriefing).where(DailyBriefing.uf == uf)
                             .order_by(DailyBriefing.briefing_date.desc()).limit(1)).first()
    return row.to_dict() if row else None


def query_news(uf: str | None, category: str | None = None, sentiment: str | None = None,
               q: str | None = None, page: int = 1, per_page: int = 20) -> dict:
    stmt = select(NewsArticle)
    if uf:
        stmt = stmt.where(NewsArticle.uf.in_([uf, "BR"]) if uf != "BR" else NewsArticle.uf == "BR")
    if category:
        stmt = stmt.where(NewsArticle.category == category)
    if sentiment:
        stmt = stmt.where(NewsArticle.sentiment == sentiment)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(NewsArticle.title.ilike(like), NewsArticle.summary.ilike(like)))
    total = db.session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.session.scalars(stmt.order_by(NewsArticle.published_at.desc().nulls_last(),
                                            NewsArticle.id.desc())
                              .offset((page - 1) * per_page).limit(per_page)).all()
    return {"items": [r.to_dict() for r in rows], "page": page, "per_page": per_page, "total": total}


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
@bp.get("/pracas")
def pracas():
    rows = db.session.scalars(select(Praca).where(Praca.active.is_(True)).order_by(Praca.uf, Praca.name)).all()
    states = []
    for uf, meta in STATES.items():
        items = [p.to_dict() for p in rows if p.uf == uf]
        if items:
            states.append({"uf": uf, "name": meta["name"], "pracas": items})
    return jsonify(states=states)


@bp.get("/dashboard")
def dashboard():
    """Payload agregado: tudo que o painel precisa em uma chamada."""
    praca = resolve_praca()
    s = db.session
    return jsonify(
        praca=praca.to_dict(),
        state={"uf": praca.uf, "name": STATES.get(praca.uf, {}).get("name", praca.uf)},
        kpis=calc.build_kpis(s, praca),
        trade=calc.build_trade_ratios(s, praca),
        cycle=calc.build_cycle(s, praca.uf),
        weather=calc.build_weather(s, praca),
        futures=calc.build_basis(s, praca),
        briefing=latest_briefing(praca.uf),
        news=query_news(praca.uf, per_page=10)["items"],
        generated_at=date.today().isoformat(),
    )


@bp.get("/kpis")
def kpis():
    praca = resolve_praca()
    return jsonify(praca=praca.code, **calc.build_kpis(db.session, praca))


@bp.get("/trade")
def trade():
    praca = resolve_praca()
    return jsonify(praca=praca.code, **calc.build_trade_ratios(db.session, praca))


@bp.get("/cycle")
def cycle():
    uf = resolve_uf(default="BR")
    return jsonify(calc.build_cycle(db.session, uf, quarters=_int_arg("quarters", 12, 4, 40)))


@bp.get("/weather")
def weather():
    praca = resolve_praca()
    return jsonify(praca=praca.code, weather=calc.build_weather(db.session, praca))


@bp.get("/futures")
def futures():
    praca = resolve_praca()
    return jsonify(praca=praca.code, **calc.build_basis(db.session, praca))


@bp.get("/heatmap")
def heatmap():
    return jsonify(calc.build_heatmap(db.session))


@bp.get("/history")
def history():
    praca = resolve_praca()
    return jsonify(praca=praca.code, **calc.build_history(db.session, praca, _int_arg("days", 90, 7, 730)))


@bp.get("/briefing")
def briefing():
    uf = resolve_uf(default=None if request.args.get("uf") else resolve_praca().uf)
    return jsonify(briefing=latest_briefing(uf))


@bp.get("/briefings")
def briefings_today():
    """Último boletim de cada UF (para a visão nacional)."""
    return jsonify(briefings=[b for uf in STATES if (b := latest_briefing(uf))])


@bp.get("/news")
def news():
    uf = request.args.get("uf")
    if uf:
        uf = resolve_uf()
    return jsonify(query_news(
        uf, category=request.args.get("category") or None, sentiment=request.args.get("sentiment") or None,
        q=request.args.get("q") or None, page=_int_arg("page", 1, 1, 1000),
        per_page=_int_arg("per_page", 20, 1, 100)))


@bp.post("/simulator")
def simulator():
    """Simulador Segurar vs. Vender. Aceita `peso_atual_arroba` no lugar de kg.

    Sem `preco_arroba_venda`, projeta pelo B3 do mês de venda + basis atual da praça.
    """
    data = request.get_json(silent=True) or {}
    praca = resolve_praca(data.get("praca"))

    def num(key, default=None):
        v = data.get(key, default)
        if v is None or v == "":
            return default
        try:
            return float(v)
        except (TypeError, ValueError) as exc:
            raise ApiError(f"'{key}' deve ser numérico") from exc

    rend_atual = num("rendimento_atual", 0.52)
    if rend_atual and rend_atual > 1:  # aceita 52 ou 0.52
        rend_atual /= 100
    rend_final = num("rendimento_final", 0.54)
    if rend_final and rend_final > 1:
        rend_final /= 100

    peso_kg = num("peso_atual_kg")
    if peso_kg is None and num("peso_atual_arroba") is not None:
        peso_kg = num("peso_atual_arroba") * 15 / rend_atual
    if peso_kg is None:
        raise ApiError("Informe 'peso_atual_kg' ou 'peso_atual_arroba'")

    dias = int(num("dias", 0))
    preco_hoje = num("preco_arroba_hoje")
    if preco_hoje is None:
        q = calc.mq.latest_quote(db.session, praca.id, "boi_gordo")
        if not q:
            raise ApiError("Sem cotação para a praça; informe 'preco_arroba_hoje'")
        preco_hoje = q.price

    preco_venda = num("preco_arroba_venda")
    projection = None
    if preco_venda is None:
        projection = calc.projected_sale_price(db.session, praca, date.today() + timedelta(days=dias))
        preco_venda = projection["price"] if projection else None

    inp = calc.FatteningInput(
        peso_atual_kg=peso_kg, gmd_kg=num("gmd_kg", 0) or 0, dias=dias,
        custo_diario=num("custo_diario", 0) or 0, preco_arroba_hoje=preco_hoje,
        preco_arroba_venda=preco_venda, rendimento_atual=rend_atual, rendimento_final=rend_final,
        juros_mensal_pct=num("juros_mensal_pct", 0) or 0)
    errors = inp.validate()
    if errors:
        raise ApiError("Parâmetros inválidos", 422, errors)
    return jsonify(praca=praca.code, result=calc.simulate_fattening(inp), price_projection=projection)
