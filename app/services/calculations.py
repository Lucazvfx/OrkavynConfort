"""Cálculos de negócio (Etapa 2): KPIs, Relação de Troca, Basis B3, Ciclo, Mapa de Escalas, Simulador.

Funções puras (sem banco) ficam no topo e são testadas isoladamente; os
"builders" que leem o banco ficam abaixo e devolvem dicts prontos para JSON.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

from sqlalchemy import select

from ..data.b3 import next_contracts
from ..data.pracas import STATES
from ..models import (
    CattleCategory, CattleQuote, FemaleSlaughterStat, FuturesQuote, InputItem, InputQuote,
    NewsArticle, Praca, SlaughterSchedule,
)
from ..utils import business_days_between, format_brl, utcnow
from . import market_queries as mq
from .ibge_service import classify_cycle

STALE_BUSINESS_DAYS = 3           # cotação com mais de 3 dias úteis = desatualizada
SIGNAL_THRESHOLD_PCT = 3.0        # desvio vs média histórica para acender selo
BOI_REFERENCE_ARROBAS = 18        # "1 boi gordo de 18@"
SACK_KG = 60

# Escala de abate (Módulos A e F)
# Praça oculta (inativa) que guarda a média nacional da escala, usada como referência
# quando a praça não tem escala própria. Nunca colore o mapa nem entra na tendência.
NATIONAL_REF_CODE = "BR_MEDIA"

SCHEDULE_SHORT = 5.0
SCHEDULE_LONG = 8.0


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------
def schedule_signal(days: float | None) -> dict:
    if days is None:
        return {"level": "sem_dado", "color": "gray", "label": "Sem dado",
                "pressure": "indefinida"}
    if days < SCHEDULE_SHORT:
        return {"level": "curta", "color": "red", "label": "Escala curta — frigorífico apertado",
                "pressure": "alta"}
    if days <= SCHEDULE_LONG:
        return {"level": "confortavel", "color": "yellow", "label": "Escala confortável — estável",
                "pressure": "neutra"}
    return {"level": "longa", "color": "green", "label": "Escala longa — indústria abastecida",
            "pressure": "baixa"}


def compute_trend(change_week_pct: float | None, schedule_days: float | None,
                  weather_bias: str | None, news_positive: int = 0, news_negative: int = 0) -> dict:
    """Tendência de curto prazo por pontuação simples e explicável (-4..+4)."""
    score, drivers = 0, []
    if change_week_pct is not None:
        if change_week_pct > 0.5:
            score += 1; drivers.append(f"preço subiu {change_week_pct:.1f}% na semana".replace(".", ","))
        elif change_week_pct < -0.5:
            score -= 1; drivers.append(f"preço caiu {abs(change_week_pct):.1f}% na semana".replace(".", ","))
    if schedule_days is not None:
        if schedule_days < SCHEDULE_SHORT:
            score += 1; drivers.append("escalas curtas")
        elif schedule_days > SCHEDULE_LONG:
            score -= 1; drivers.append("escalas longas")
    if weather_bias == "alta":
        score += 1; drivers.append("chuva favorece retenção")
    elif weather_bias == "baixa":
        score -= 1; drivers.append("pasto seco força entregas")
    if news_positive - news_negative >= 2:
        score += 1; drivers.append("noticiário positivo")
    elif news_negative - news_positive >= 2:
        score -= 1; drivers.append("noticiário negativo")

    direction = "alta" if score >= 2 else ("baixa" if score <= -2 else "lateral")
    return {"direction": direction, "score": score, "drivers": drivers or ["sem sinais relevantes"]}


def ratio_signal(current: float | None, average: float | None, higher_is_better: bool,
                 favorable_label: str, tight_label: str) -> dict:
    if current is None or not average:
        return {"status": "sem_dado", "label": "Sem histórico suficiente", "deviation_pct": None}
    deviation = (current - average) / average * 100
    better = deviation if higher_is_better else -deviation
    if better >= SIGNAL_THRESHOLD_PCT:
        status, label = "favoravel", favorable_label
    elif better <= -SIGNAL_THRESHOLD_PCT:
        status, label = "apertada", tight_label
    else:
        status, label = "neutra", "Em linha com a média histórica"
    return {"status": status, "label": label, "deviation_pct": round(deviation, 2)}


# ---------------------------------------------------------------------------
# Simulador de engorda (Módulo H)
# ---------------------------------------------------------------------------
@dataclass
class FatteningInput:
    peso_atual_kg: float
    gmd_kg: float                    # ganho médio diário
    dias: int
    custo_diario: float              # R$/cabeça/dia (dieta + sanidade + mão de obra)
    preco_arroba_hoje: float
    preco_arroba_venda: float | None = None  # None => igual ao de hoje
    rendimento_atual: float = 0.52   # rendimento de carcaça hoje
    rendimento_final: float = 0.54   # boi mais acabado rende mais carcaça
    juros_mensal_pct: float = 0.0    # custo de oportunidade do dinheiro que não entrou hoje

    def validate(self) -> list[str]:
        errors = []
        checks = [
            ("peso_atual_kg", 150 <= self.peso_atual_kg <= 900, "entre 150 e 900 kg"),
            ("gmd_kg", 0 <= self.gmd_kg <= 2.5, "entre 0 e 2,5 kg/dia"),
            ("dias", 1 <= self.dias <= 365, "entre 1 e 365 dias"),
            ("custo_diario", 0 <= self.custo_diario <= 100, "entre R$ 0 e R$ 100/dia"),
            ("preco_arroba_hoje", 100 <= self.preco_arroba_hoje <= 700, "entre R$ 100 e R$ 700"),
            ("rendimento_atual", 0.40 <= self.rendimento_atual <= 0.65, "entre 40% e 65%"),
            ("rendimento_final", 0.40 <= self.rendimento_final <= 0.65, "entre 40% e 65%"),
            ("juros_mensal_pct", 0 <= self.juros_mensal_pct <= 10, "entre 0% e 10% a.m."),
        ]
        if self.preco_arroba_venda is not None:
            checks.append(("preco_arroba_venda", 100 <= self.preco_arroba_venda <= 700, "entre R$ 100 e R$ 700"))
        for name, ok, rule in checks:
            if not ok:
                errors.append(f"{name} deve estar {rule}")
        return errors


def simulate_fattening(inp: FatteningInput) -> dict:
    """Compara vender hoje vs. segurar `dias` a mais. @ = 15 kg de carcaça."""
    errors = inp.validate()
    if errors:
        raise ValueError("; ".join(errors))
    preco_venda = inp.preco_arroba_venda if inp.preco_arroba_venda is not None else inp.preco_arroba_hoje

    peso_final = inp.peso_atual_kg + inp.gmd_kg * inp.dias
    arrobas_hoje = inp.peso_atual_kg * inp.rendimento_atual / 15
    arrobas_final = peso_final * inp.rendimento_final / 15
    arrobas_ganhas = arrobas_final - arrobas_hoje

    receita_hoje = arrobas_hoje * inp.preco_arroba_hoje
    receita_futura = arrobas_final * preco_venda
    custo_total = inp.custo_diario * inp.dias
    custo_oportunidade = receita_hoje * ((1 + inp.juros_mensal_pct / 100) ** (inp.dias / 30) - 1)
    lucro_incremental = receita_futura - receita_hoje - custo_total - custo_oportunidade

    # Preço da @ na venda futura que empata com vender hoje (ponto de equilíbrio)
    breakeven = (receita_hoje + custo_total + custo_oportunidade) / arrobas_final
    custo_arroba_produzida = custo_total / arrobas_ganhas if arrobas_ganhas > 0 else None

    return {
        "peso_final_kg": round(peso_final, 1),
        "arrobas_hoje": round(arrobas_hoje, 2),
        "arrobas_final": round(arrobas_final, 2),
        "arrobas_ganhas": round(arrobas_ganhas, 2),
        "preco_arroba_venda": round(preco_venda, 2),
        "receita_vender_hoje": round(receita_hoje, 2),
        "receita_segurar": round(receita_futura, 2),
        "custo_total": round(custo_total, 2),
        "custo_oportunidade": round(custo_oportunidade, 2),
        "lucro_incremental": round(lucro_incremental, 2),
        "custo_por_arroba_produzida": round(custo_arroba_produzida, 2) if custo_arroba_produzida else None,
        "preco_equilibrio_arroba": round(breakeven, 2),
        "decisao": "segurar" if lucro_incremental > 0 else "vender_agora",
        "decisao_label": f"{'Segurar compensa' if lucro_incremental > 0 else 'Vender agora'} "
                         f"({'+' if lucro_incremental >= 0 else '−'}{format_brl(abs(lucro_incremental))}/cab)",
        "premissas": asdict(inp) | {"preco_arroba_venda": preco_venda},
    }


# ---------------------------------------------------------------------------
# Builders (leem o banco)
# ---------------------------------------------------------------------------
def _freshness(ref: date | None, today: date | None = None) -> dict:
    today = today or date.today()
    if ref is None:
        return {"last_date": None, "business_days_old": None, "stale": True}
    age = business_days_between(ref, today)
    return {"last_date": ref.isoformat(), "business_days_old": age, "stale": age > STALE_BUSINESS_DAYS}


def news_balance(session, uf: str, hours: int = 72) -> dict:
    cutoff = utcnow() - timedelta(hours=hours)
    rows = session.execute(select(NewsArticle.sentiment).where(
        NewsArticle.collected_at >= cutoff, NewsArticle.uf.in_([uf, "BR"]))).scalars().all()
    bal = {"positivo": 0, "neutro": 0, "negativo": 0}
    for s in rows:
        bal[s] = bal.get(s, 0) + 1
    return bal


def build_kpis(session, praca: Praca) -> dict:
    prices = {cat: mq.price_with_changes(session, praca.id, cat) for cat in CattleCategory.ALL}
    sched = mq.latest_schedule(session, praca.id)
    weather = mq.latest_weather(session, praca.id)
    bal = news_balance(session, praca.uf)
    boi = prices[CattleCategory.BOI_GORDO]
    trend = compute_trend(boi["change_week_pct"], sched.days_ahead if sched else None,
                          weather.price_bias if weather else None, bal["positivo"], bal["negativo"])
    sources = {p["source"] for p in prices.values() if p["source"]} | ({sched.source} if sched else set())
    reference = None
    if sched is None:
        ref_praca = session.scalars(select(Praca).where(Praca.code == NATIONAL_REF_CODE)).first()
        ref = mq.latest_schedule(session, ref_praca.id) if ref_praca else None
        if ref:
            reference = {"days_ahead": ref.days_ahead, "date": ref.ref_date.isoformat(), "source": ref.source,
                         **schedule_signal(ref.days_ahead)}
    return {
        "prices": {cat: {**p, "label": CattleCategory.LABELS[cat],
                         "date": p["date"].isoformat() if p["date"] else None}
                   for cat, p in prices.items()},
        "schedule": {
            "days_ahead": sched.days_ahead if sched else None,
            "date": sched.ref_date.isoformat() if sched else None,
            "plants_surveyed": sched.plants_surveyed if sched else None,
            "source": sched.source if sched else None,
            "national_reference": reference,
            **schedule_signal(sched.days_ahead if sched else None),
        },
        "supply": {"level": sched.supply_level if sched else None},
        "trend": trend,
        "news_balance": bal,
        "freshness": _freshness(boi["date"]),
        "is_demo": "seed" in sources,
    }


def _boi_price_index(session, praca_id: int) -> list[tuple[date, float]]:
    rows = session.execute(select(CattleQuote.quote_date, CattleQuote.price).where(
        CattleQuote.praca_id == praca_id, CattleQuote.category == CattleCategory.BOI_GORDO)
        .order_by(CattleQuote.quote_date)).all()
    return [(d, p) for d, p in rows]


def _price_on_or_before(index: list[tuple[date, float]], target: date) -> float | None:
    best = None
    for d, p in index:
        if d > target:
            break
        best = p
    return best


def build_trade_ratios(session, praca: Praca) -> dict:
    """Módulo B. A 'média histórica' é a de todo o histórico do banco para a praça."""
    boi_index = _boi_price_index(session, praca.id)
    boi_now = boi_index[-1][1] if boi_index else None

    def series(item: str) -> list[tuple[date, float, float]]:
        rows = session.execute(select(InputQuote.quote_date, InputQuote.price).where(
            InputQuote.praca_id == praca.id, InputQuote.item == item).order_by(InputQuote.quote_date)).all()
        out = []
        for d, price in rows:
            boi = _price_on_or_before(boi_index, d)
            if boi and price:
                out.append((d, price, boi))
        return out

    def summarize(values: list[float]) -> dict:
        if not values:
            return {"average": None, "min": None, "max": None, "observations": 0}
        return {"average": round(sum(values) / len(values), 3), "min": round(min(values), 3),
                "max": round(max(values), 3), "observations": len(values)}

    result: dict = {"boi_gordo_price": boi_now, "items": {}}

    def latest_source(item: str) -> str | None:
        return session.scalars(select(InputQuote.source).where(
            InputQuote.praca_id == praca.id, InputQuote.item == item)
            .order_by(InputQuote.quote_date.desc()).limit(1)).first()

    calf = series(InputItem.BEZERRO)
    if calf:
        _, calf_price, _ = calf[-1]
        calves_per_steer = [boi * BOI_REFERENCE_ARROBAS / price for _, price, boi in calf]
        stats = summarize(calves_per_steer)
        current = round(boi_now * BOI_REFERENCE_ARROBAS / calf_price, 3)
        result["items"]["bezerro"] = {
            "price": calf_price, "unit": InputItem.UNITS[InputItem.BEZERRO], "date": calf[-1][0].isoformat(),
            "source": latest_source(InputItem.BEZERRO),
            "arrobas_per_calf": round(calf_price / boi_now, 2),
            "calves_per_boi_18": current,
            "history": stats,
            "series": [{"date": d.isoformat(), "value": round(v, 3)} for (d, _, _), v in zip(calf, calves_per_steer)],
            "signal": ratio_signal(current, stats["average"], True,
                                   "Troca favorável para recria/reposição", "Reposição cara — margem apertada"),
        }

    for item, unit_kg, label in ((InputItem.MILHO, SACK_KG, "sacas de 60 kg"),
                                 (InputItem.FARELO_SOJA, 1000, "toneladas")):
        rows = series(item)
        if not rows:
            continue
        _, price, _ = rows[-1]
        # farelo cotado em R$/t => preço da saca de 60 kg equivalente
        sack_price = price if item == InputItem.MILHO else price / 1000 * SACK_KG
        values = [boi / (p if item == InputItem.MILHO else p / 1000 * SACK_KG) for _, p, boi in rows]
        stats = summarize(values)
        current = round(boi_now / sack_price, 3)
        result["items"][item] = {
            "price": price, "unit": InputItem.UNITS[item], "date": rows[-1][0].isoformat(),
            "source": latest_source(item),
            "sacks60_per_arroba": current,
            "kg_per_arroba": round(boi_now / (price / unit_kg), 1),
            "history": stats,
            "series": [{"date": d.isoformat(), "value": round(v, 3)} for (d, _, _), v in zip(rows, values)],
            "signal": ratio_signal(current, stats["average"], True,
                                   "Favorável para confinamento", "Dieta cara — margem apertada"),
        }
    return result


def build_basis(session, praca: Praca, history_days: int = 60) -> dict:
    """Módulo G. Basis = físico da praça − ajuste B3. Inclui média do basis do 1º vencimento."""
    boi = mq.latest_quote(session, praca.id, CattleCategory.BOI_GORDO)
    curve = mq.latest_futures_curve(session)
    if not boi or not curve:
        return {"physical": boi.price if boi else None, "contracts": [], "history": None}

    contracts = [{
        "contract": f.contract_code, "maturity": f.maturity_month.isoformat(),
        "settlement": f.settlement_price, "open_interest": f.open_interest,
        "basis_rs": round(boi.price - f.settlement_price, 2),
        "basis_pct": round((boi.price - f.settlement_price) / f.settlement_price * 100, 2),
    } for f in curve]

    # Histórico do basis contra o vencimento mais próximo de cada dia
    since = curve[0].quote_date - timedelta(days=history_days)
    fut_rows = session.scalars(select(FuturesQuote).where(FuturesQuote.quote_date >= since)
                               .order_by(FuturesQuote.quote_date, FuturesQuote.maturity_month)).all()
    nearest_by_day: dict[date, FuturesQuote] = {}
    for f in fut_rows:
        nearest_by_day.setdefault(f.quote_date, f)
    index = _boi_price_index(session, praca.id)
    hist = []
    for d, f in nearest_by_day.items():
        phys = _price_on_or_before(index, d)
        if phys:
            hist.append({"date": d.isoformat(), "contract": f.contract_code,
                         "basis_rs": round(phys - f.settlement_price, 2)})
    avg = round(sum(h["basis_rs"] for h in hist) / len(hist), 2) if hist else None
    current = contracts[0]["basis_rs"]
    return {
        "physical": boi.price, "physical_date": boi.quote_date.isoformat(),
        "futures_date": curve[0].quote_date.isoformat(),
        "contracts": contracts,
        "history": {
            "series": hist, "average_rs": avg,
            "deviation_rs": round(current - avg, 2) if avg is not None else None,
            # Basis mais forte (menos negativo) que a média => físico caro vs. B3
            "reading": None if avg is None else (
                "Físico forte vs. B3 (basis acima da média)" if current - avg > 2 else
                "Físico fraco vs. B3 (basis abaixo da média)" if current - avg < -2 else
                "Basis em linha com a média"),
        },
        "note": "Contrato BGI referencia SP: basis negativo em praças distantes é estrutural; "
                "compare com a média da própria praça.",
    }


def projected_sale_price(session, praca: Praca, sale_date: date) -> dict | None:
    """Preço de venda projetado = ajuste B3 do mês de venda + basis atual da praça."""
    basis = build_basis(session, praca)
    if not basis["contracts"]:
        return None
    target = date(sale_date.year, sale_date.month, 1)
    chosen = next((c for c in basis["contracts"] if c["maturity"] >= target.isoformat()), basis["contracts"][-1])
    current_basis = basis["contracts"][0]["basis_rs"]
    return {"price": round(chosen["settlement"] + current_basis, 2), "contract": chosen["contract"],
            "settlement": chosen["settlement"], "basis_rs": current_basis,
            "method": "B3 do mês de venda + basis atual"}


def build_cycle(session, uf: str, quarters: int = 12) -> dict:
    """Módulo C. Usa BR quando a UF não tem dados."""
    def series_for(code: str) -> list[FemaleSlaughterStat]:
        rows = session.scalars(select(FemaleSlaughterStat).where(FemaleSlaughterStat.uf == code)
                               .order_by(FemaleSlaughterStat.year.desc(), FemaleSlaughterStat.quarter.desc())
                               .limit(quarters)).all()
        return list(reversed(rows))

    state_rows = series_for(uf)
    br_rows = series_for("BR")
    base = state_rows or br_rows
    latest = base[-1] if base else None
    yoy = None
    if latest:
        prev = next((r for r in base if r.year == latest.year - 1 and r.quarter == latest.quarter), None)
        if prev and prev.female_share is not None and latest.female_share is not None:
            yoy = round(latest.female_share - prev.female_share, 2)
    return {
        "uf": uf if state_rows else "BR",
        "fallback_to_br": not state_rows,
        "latest": latest.to_dict() if latest else None,
        "yoy_change_pp": yoy,
        "interpretation": classify_cycle(latest.female_share if latest else None),
        "series": [r.to_dict() for r in state_rows],
        "brazil_series": [r.to_dict() for r in br_rows],
        "thresholds": {"liquidation": 45.0, "retention": 40.0},
        "is_demo": any(r.source == "seed" for r in base),
        "note": "IBGE divulga cada trimestre ~75 dias após o fechamento.",
    }


def build_heatmap(session) -> dict:
    """Módulo F. Média da escala (último registro de cada praça ativa) por UF."""
    states = []
    for uf, meta in STATES.items():
        pracas = session.scalars(select(Praca).where(Praca.uf == uf, Praca.active.is_(True))).all()
        details = []
        for p in pracas:
            s = mq.latest_schedule(session, p.id)
            if s:
                details.append({"praca": p.code, "name": p.name, "days_ahead": s.days_ahead,
                                "date": s.ref_date.isoformat()})
        avg = round(sum(d["days_ahead"] for d in details) / len(details), 1) if details else None
        ref = mq.state_reference_praca(session, uf)
        states.append({"uf": uf, "name": meta["name"], "avg_days": avg,
                       "default_praca": ref.code if ref else None,
                       **schedule_signal(avg), "pracas": details})
    return {"states": states,
            "legend": [{"color": "red", "label": f"< {SCHEDULE_SHORT:g} dias"},
                       {"color": "yellow", "label": f"{SCHEDULE_SHORT:g} a {SCHEDULE_LONG:g} dias"},
                       {"color": "green", "label": f"> {SCHEDULE_LONG:g} dias"}]}


def build_weather(session, praca: Praca) -> dict | None:
    snap = mq.latest_weather(session, praca.id)
    return snap.to_dict() if snap else None


def build_history(session, praca: Praca, days: int = 90) -> dict:
    since = date.today() - timedelta(days=days)
    quotes = session.scalars(select(CattleQuote).where(
        CattleQuote.praca_id == praca.id, CattleQuote.quote_date >= since).order_by(CattleQuote.quote_date)).all()
    series: dict[str, list] = {c: [] for c in CattleCategory.ALL}
    for q in quotes:
        series.setdefault(q.category, []).append({"date": q.quote_date.isoformat(), "price": q.price})
    scheds = session.scalars(select(SlaughterSchedule).where(
        SlaughterSchedule.praca_id == praca.id, SlaughterSchedule.ref_date >= since)
        .order_by(SlaughterSchedule.ref_date)).all()
    return {"prices": series,
            "schedule": [{"date": s.ref_date.isoformat(), "days_ahead": s.days_ahead} for s in scheds]}


def contracts_for_admin(ref: date | None = None) -> list[dict]:
    """Vencimentos que o admin deve preencher hoje."""
    return [{"contract": c, "maturity": m.isoformat()} for c, m in next_contracts(ref or date.today(), 4)]
