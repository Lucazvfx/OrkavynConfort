"""Painel /admin — entrada manual de cotações e disparo de jobs.

Segurança:
- Senha única via ADMIN_PASSWORD (sem senha configurada => admin desabilitado, 503).
- Sessão Flask assinada com SECRET_KEY; comparação de senha em tempo constante.
- CSRF: todo POST autenticado exige o token da sessão (header X-CSRF-Token ou campo csrf_token).
- Limite de 5 tentativas de login por IP a cada 5 minutos (memória do processo).

As telas HTML entram na Etapa 3; aqui ficam os endpoints JSON que elas consomem.
"""
from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import date
from functools import wraps

from flask import Blueprint, current_app, jsonify, render_template, request, session
from jinja2 import TemplateNotFound
from sqlalchemy import func, select

from ..data.b3 import MONTH_CODES
from ..data.pracas import STATES
from ..extensions import db
from ..models import (
    CattleCategory, CattleQuote, FemaleSlaughterStat, FuturesQuote, InputItem, InputQuote, JobRun,
    Praca, SlaughterSchedule, SupplyLevel,
)
from ..scheduler import next_runs
from ..services.calculations import contracts_for_admin
from ..services.jobs import JOBS, run_job
from ..utils import business_days_between

bp = Blueprint("admin", __name__, url_prefix="/admin")

MANUAL = "manual"
LOGIN_WINDOW_S, LOGIN_MAX_ATTEMPTS = 300, 5
_login_attempts: dict[str, deque] = defaultdict(deque)

# Faixas de sanidade: bloqueiam erros de digitação (ex.: 3100 no campo da arroba)
BOUNDS = {
    "boi_gordo": (100, 700), "vaca_gorda": (100, 700), "boi_china": (100, 700),
    "bezerro": (500, 10000), "milho": (10, 300), "farelo_soja": (500, 6000),
    "days_ahead": (0, 30), "settlement": (100, 700), "bezerro_peso_kg": (100, 400),
}
_MONTH_FROM_CODE = {v: k for k, v in MONTH_CODES.items()}
FIELD_LABELS = {
    "boi_gordo": "Boi gordo", "vaca_gorda": "Vaca gorda", "boi_china": "Boi China",
    "bezerro": "Bezerro", "milho": "Milho", "farelo_soja": "Farelo de soja",
    "days_ahead": "Dias de escala", "settlement": "Ajuste B3", "bezerro_peso_kg": "Peso do bezerro",
}


class AdminError(Exception):
    def __init__(self, message, status=400, details=None):
        super().__init__(message)
        self.message, self.status, self.details = message, status, details


@bp.errorhandler(AdminError)
def _admin_error(err: AdminError):
    body = {"error": err.message}
    if err.details:
        body["details"] = err.details
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------
def _admin_enabled() -> bool:
    return bool(current_app.config.get("ADMIN_PASSWORD"))


def _csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not _admin_enabled():
            raise AdminError("Admin desabilitado: defina ADMIN_PASSWORD no .env", 503)
        if not session.get("is_admin"):
            raise AdminError("Não autenticado", 401)
        if request.method == "POST":
            sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or \
                (request.get_json(silent=True) or {}).get("csrf_token")
            if not sent or not hmac.compare_digest(str(sent), session.get("csrf_token", "")):
                raise AdminError("Token CSRF inválido ou ausente", 403)
        return view(*args, **kwargs)
    return wrapper


def _rate_limited(ip: str) -> bool:
    now, attempts = time.monotonic(), _login_attempts[ip]
    while attempts and now - attempts[0] > LOGIN_WINDOW_S:
        attempts.popleft()
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


@bp.post("/login")
def login():
    if not _admin_enabled():
        raise AdminError("Admin desabilitado: defina ADMIN_PASSWORD no .env", 503)
    ip = request.remote_addr or "?"
    if _rate_limited(ip):
        raise AdminError("Muitas tentativas. Aguarde alguns minutos.", 429)
    password = (request.get_json(silent=True) or {}).get("password") or request.form.get("password") or ""
    if not hmac.compare_digest(password.encode(), current_app.config["ADMIN_PASSWORD"].encode()):
        _login_attempts[ip].append(time.monotonic())
        raise AdminError("Senha incorreta", 401)
    _login_attempts.pop(ip, None)
    session.clear()
    session["is_admin"] = True
    session.permanent = True
    return jsonify(ok=True, csrf_token=_csrf_token())


@bp.post("/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get("/session")
def session_info():
    return jsonify(enabled=_admin_enabled(), authenticated=bool(session.get("is_admin")),
                   csrf_token=_csrf_token() if session.get("is_admin") else None)


@bp.get("/")
def index():
    """Tela do admin (template na Etapa 3)."""
    try:
        return render_template("admin/index.html")
    except TemplateNotFound:
        return jsonify(message="Tela do admin disponível na Etapa 3. Use os endpoints /admin/api/*."), 200


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------
def _payload() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict()
    return data or {}


def _get_praca(code) -> Praca:
    praca = db.session.scalars(select(Praca).where(Praca.code == str(code or "").upper())).first()
    if not praca:
        raise AdminError(f"Praça '{code}' não encontrada", 404)
    return praca


def _parse_date(value) -> date:
    if not value:
        return date.today()
    try:
        d = date.fromisoformat(str(value))
    except ValueError as exc:
        raise AdminError(f"Data inválida '{value}' (use AAAA-MM-DD)") from exc
    if d > date.today():
        raise AdminError("Data no futuro não é permitida")
    return d


def _number(data: dict, key: str, errors: list, required: bool = False) -> float | None:
    raw = data.get(key)
    label = FIELD_LABELS.get(key, key)
    if raw is None or raw == "":
        if required:
            errors.append(f"{label}: campo obrigatório")
        return None
    try:
        value = float(str(raw).replace(",", "."))
    except ValueError:
        errors.append(f"{label}: use apenas números (ex.: 301,50)")
        return None
    lo, hi = BOUNDS.get(key, (float("-inf"), float("inf")))
    if not lo <= value <= hi:
        errors.append(f"{label}: {value:g} está fora da faixa plausível ({lo:g} a {hi:g}). Confira a digitação.")
        return None
    return value


def _upsert(model, keys: dict, values: dict):
    row = db.session.scalars(select(model).filter_by(**keys)).first()
    created = row is None
    row = row or model(**keys)
    for k, v in values.items():
        setattr(row, k, v)
    db.session.add(row)
    return row, created


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
@bp.get("/api/status")
@admin_required
def status():
    pracas = db.session.scalars(select(Praca).order_by(Praca.uf, Praca.name)).all()
    freshness = []
    for p in pracas:
        last_q = db.session.scalar(select(func.max(CattleQuote.quote_date)).where(CattleQuote.praca_id == p.id))
        last_s = db.session.scalar(select(func.max(SlaughterSchedule.ref_date))
                                   .where(SlaughterSchedule.praca_id == p.id))
        last_i = db.session.scalar(select(func.max(InputQuote.quote_date)).where(InputQuote.praca_id == p.id))
        freshness.append({"praca": p.code, "name": p.name, "uf": p.uf, "active": p.active,
                          "last_cattle_quote": last_q.isoformat() if last_q else None,
                          "last_schedule": last_s.isoformat() if last_s else None,
                          "last_inputs": last_i.isoformat() if last_i else None})
    last_fut = db.session.scalar(select(func.max(FuturesQuote.quote_date)))
    runs = db.session.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(20)).all()
    return jsonify(pracas=freshness, futures_last_date=last_fut.isoformat() if last_fut else None,
                   contracts_to_fill=contracts_for_admin(), jobs=list(JOBS),
                   scheduler=next_runs(), recent_runs=[r.to_dict() for r in runs])


# ---------------------------------------------------------------------------
# Entrada manual
# ---------------------------------------------------------------------------
@bp.post("/api/quotes/cattle")
@admin_required
def save_cattle_quotes():
    """{praca, date?, boi_gordo?, vaca_gorda?, boi_china?} — ao menos um preço."""
    data = _payload()
    praca, d, errors = _get_praca(data.get("praca")), _parse_date(data.get("date")), []
    prices = {cat: _number(data, cat, errors) for cat in CattleCategory.ALL}
    if errors:
        raise AdminError("Dados inválidos", 422, errors)
    if all(v is None for v in prices.values()):
        raise AdminError("Informe ao menos um preço (boi_gordo, vaca_gorda, boi_china)", 422)
    saved = []
    for cat, price in prices.items():
        if price is not None:
            _upsert(CattleQuote, {"praca_id": praca.id, "quote_date": d, "category": cat},
                    {"price": price, "source": MANUAL})
            saved.append(cat)
    db.session.commit()
    return jsonify(ok=True, praca=praca.code, date=d.isoformat(), saved=saved)


@bp.post("/api/quotes/inputs")
@admin_required
def save_input_quotes():
    """{praca, date?, bezerro?, bezerro_peso_kg?, milho?, farelo_soja?}"""
    data = _payload()
    praca, d, errors = _get_praca(data.get("praca")), _parse_date(data.get("date")), []
    prices = {item: _number(data, item, errors) for item in InputItem.ALL}
    calf_weight = _number(data, "bezerro_peso_kg", errors)
    if errors:
        raise AdminError("Dados inválidos", 422, errors)
    if all(v is None for v in prices.values()):
        raise AdminError("Informe ao menos um insumo (bezerro, milho, farelo_soja)", 422)
    saved = []
    for item, price in prices.items():
        if price is None:
            continue
        values = {"price": price, "unit": InputItem.UNITS[item], "source": MANUAL}
        if item == InputItem.BEZERRO:
            values["reference_weight_kg"] = calf_weight or 210
        _upsert(InputQuote, {"praca_id": praca.id, "quote_date": d, "item": item}, values)
        saved.append(item)
    db.session.commit()
    return jsonify(ok=True, praca=praca.code, date=d.isoformat(), saved=saved)


@bp.post("/api/schedules")
@admin_required
def save_schedule():
    """{praca, date?, days_ahead | abate_date, supply_level?, plants_surveyed?, notes?}

    Em vez dos dias úteis, aceita a data do abate que o frigorífico informou
    (abate_date) e conta os dias úteis a partir da data de referência.
    """
    data = _payload()
    praca, d, errors = _get_praca(data.get("praca")), _parse_date(data.get("date")), []
    days = _number(data, "days_ahead", errors)
    if days is None and not errors:
        raw = data.get("abate_date")
        if not raw:
            errors.append("Informe os dias úteis de escala ou a data do abate agendado")
        else:
            try:
                abate = date.fromisoformat(str(raw))
            except ValueError:
                abate = None
                errors.append("Data do abate inválida (use AAAA-MM-DD)")
            if abate is not None:
                if abate <= d:
                    errors.append("A data do abate precisa ser depois da data da cotação")
                else:
                    days = float(business_days_between(d, abate))
                    if days > BOUNDS["days_ahead"][1]:
                        errors.append(f"Abate em {days:g} dias úteis: fora da faixa plausível (até 30)")
    supply = data.get("supply_level") or None
    if supply and supply not in SupplyLevel.ALL:
        errors.append(f"supply_level deve ser um de {SupplyLevel.ALL}")
    plants = data.get("plants_surveyed")
    if plants not in (None, ""):
        try:
            plants = int(plants)
        except ValueError:
            errors.append("plants_surveyed deve ser inteiro")
    else:
        plants = None
    if errors:
        raise AdminError("Dados inválidos", 422, errors)
    if supply is None:  # deriva da escala se não informado
        supply = SupplyLevel.RESTRITA if days < 5 else (SupplyLevel.AMPLA if days > 8 else SupplyLevel.EQUILIBRADA)
    _upsert(SlaughterSchedule, {"praca_id": praca.id, "ref_date": d},
            {"days_ahead": days, "supply_level": supply, "plants_surveyed": plants,
             "notes": (data.get("notes") or None), "source": MANUAL})
    db.session.commit()
    return jsonify(ok=True, praca=praca.code, date=d.isoformat(), days_ahead=days, supply_level=supply)


def _parse_contract(code: str) -> date:
    code = (code or "").strip().upper()
    if len(code) != 6 or not code.startswith("BGI") or code[3] not in _MONTH_FROM_CODE or not code[4:].isdigit():
        raise AdminError(f"Código de contrato inválido '{code}' (ex.: BGIZ26)", 422)
    return date(2000 + int(code[4:]), _MONTH_FROM_CODE[code[3]], 1)


@bp.post("/api/futures")
@admin_required
def save_futures():
    """{date?, contracts: [{contract: "BGIZ26", settlement: 318.5, open_interest?}]}"""
    data = _payload()
    d = _parse_date(data.get("date"))
    contracts = data.get("contracts") or []
    if not contracts:
        raise AdminError("Informe 'contracts'", 422)
    errors, saved = [], []
    for c in contracts:
        maturity = _parse_contract(c.get("contract"))
        price = _number({"settlement": c.get("settlement")}, "settlement", errors, required=True)
        if price is None:
            continue
        oi = c.get("open_interest")
        _upsert(FuturesQuote, {"quote_date": d, "contract_code": c["contract"].upper()},
                {"maturity_month": maturity, "settlement_price": price,
                 "open_interest": int(oi) if oi not in (None, "") else None, "source": MANUAL})
        saved.append(c["contract"].upper())
    if errors:
        db.session.rollback()
        raise AdminError("Dados inválidos", 422, errors)
    db.session.commit()
    return jsonify(ok=True, date=d.isoformat(), saved=saved)


@bp.post("/api/female-slaughter")
@admin_required
def save_female_slaughter():
    """Correção manual de um trimestre: {uf, year, quarter, total_head, cows_head, heifers_head}."""
    data = _payload()
    uf = str(data.get("uf", "")).upper()
    if uf not in STATES and uf != "BR":
        raise AdminError("UF inválida", 422)
    try:
        year, quarter = int(data["year"]), int(data["quarter"])
        total, cows, heifers = int(data["total_head"]), int(data["cows_head"]), int(data["heifers_head"])
    except (KeyError, ValueError, TypeError) as exc:
        raise AdminError("Campos obrigatórios: year, quarter, total_head, cows_head, heifers_head", 422) from exc
    if not 1 <= quarter <= 4 or not 2000 <= year <= 2100 or cows + heifers > total or total <= 0:
        raise AdminError("Valores inconsistentes (trimestre 1–4; fêmeas ≤ total)", 422)
    row, _ = _upsert(FemaleSlaughterStat, {"uf": uf, "year": year, "quarter": quarter},
                     {"total_head": total, "cows_head": cows, "heifers_head": heifers, "source": MANUAL})
    row.recompute_share()
    db.session.commit()
    return jsonify(ok=True, **row.to_dict())


@bp.post("/api/pracas/<code>/toggle")
@admin_required
def toggle_praca(code):
    praca = _get_praca(code)
    praca.active = not praca.active
    db.session.commit()
    return jsonify(ok=True, praca=praca.code, active=praca.active)


# ---------------------------------------------------------------------------
# Jobs manuais
# ---------------------------------------------------------------------------
@bp.post("/api/jobs/<name>/run")
@admin_required
def trigger_job(name):
    if name not in JOBS:
        raise AdminError(f"Job desconhecido. Opções: {', '.join(JOBS)}", 404)
    try:
        result = run_job(name, db.session, current_app.config, trigger="manual")
    except Exception as exc:  # falha já registrada em job_runs
        return jsonify(ok=False, job=name, error=str(exc)[:500]), 502
    return jsonify(ok=True, job=name, result=result)
