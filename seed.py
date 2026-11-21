"""Popula o banco com dados de DEMONSTRAÇÃO para todos os módulos funcionarem no 1º start.

    python seed.py            # cria tudo (recusa se já houver dados)
    python seed.py --reset    # apaga e recria todas as tabelas
    python seed.py --live     # após o seed, tenta Open-Meteo, IBGE SIDRA e RSS reais

IMPORTANTE: preços, escalas, B3, notícias e abate de fêmeas gerados aqui são
ILUSTRATIVOS (ordem de grandeza plausível, não cotações reais). Toda linha recebe
source="seed" para o dashboard poder sinalizar "dado de demonstração".
Substitua pelo /admin (manual) ou pelos coletores reais.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import date, timedelta

from app import create_app
from app.data.b3 import next_contracts
from app.data.pracas import PRACAS, STATES
from app.extensions import db
from app.models import (
    CattleCategory, CattleQuote, FemaleSlaughterStat, FuturesQuote, InputItem, InputQuote,
    NewsArticle, Praca, SlaughterSchedule, SupplyLevel,
)
from app.services import briefing_service
from app.services.news_classifier import classify
from app.services.rss_collector import url_hash
from app.services.weather_service import build_snapshot
from app.utils import business_days_back, utcnow

SEED = "seed"
RNG = random.Random(42)  # determinístico: o mesmo seed gera sempre os mesmos dados

# ---------------------------------------------------------------------------
# Parâmetros por praça (valores de referência ILUSTRATIVOS, ordem de grandeza 2025/26)
# boi = R$/@ à vista | bezerro = R$/cab | milho = R$/sc60 | farelo = R$/t | escala = dias úteis
# chuva15 = mm previstos (novembro = início/meio da estação chuvosa no Brasil Central)
# ---------------------------------------------------------------------------
PROFILE = {
    "RO_VILHENA":        dict(boi=296, bezerro=2950, milho=52, farelo=1900, escala=6.0, chuva15=95),
    "RO_PORTO_VELHO":    dict(boi=290, bezerro=2850, milho=55, farelo=1980, escala=7.5, chuva15=120),
    "MT_PONTES_LACERDA": dict(boi=298, bezerro=3000, milho=50, farelo=1750, escala=6.5, chuva15=85),
    "MT_CUIABA":         dict(boi=302, bezerro=3100, milho=48, farelo=1700, escala=6.0, chuva15=78),
    "MS_CAMPO_GRANDE":   dict(boi=312, bezerro=3250, milho=56, farelo=1800, escala=5.0, chuva15=62),
    "GO_GOIANIA":        dict(boi=308, bezerro=3200, milho=58, farelo=1820, escala=5.5, chuva15=88),
    "SP_ARACATUBA":      dict(boi=322, bezerro=3400, milho=68, farelo=1950, escala=4.5, chuva15=55),
    "PA_MARABA":         dict(boi=294, bezerro=2800, milho=62, farelo=2100, escala=8.5, chuva15=42),
    "PA_REDENCAO":       dict(boi=296, bezerro=2880, milho=60, farelo=2050, escala=8.0, chuva15=70),
    "TO_ARAGUAINA":      dict(boi=300, bezerro=2950, milho=58, farelo=2000, escala=7.0, chuva15=38),
}

# % fêmeas no abate — trajetória ilustrativa do ciclo (retenção 2021 → liquidação 2024 → transição)
FEMALE_SHARE_BY_YEAR = {2021: 35.5, 2022: 39.0, 2023: 42.0, 2024: 46.5, 2025: 44.5, 2026: 41.8}
QUARTER_SEASONALITY = {1: -1.0, 2: 0.4, 3: 1.0, 4: -0.4}
STATE_SHARE_OFFSET = {"BR": 0.0, "RO": 1.5, "PA": 1.0, "TO": 2.0, "MT": 0.0, "MS": -1.0, "GO": 0.5, "SP": -2.0}
BR_HEADS_PER_QUARTER = {2021: 6.9e6, 2022: 7.5e6, 2023: 8.5e6, 2024: 9.9e6, 2025: 10.1e6, 2026: 9.6e6}
STATE_SLAUGHTER_WEIGHT = {"BR": 1.0, "MT": 0.17, "SP": 0.10, "GO": 0.10, "MS": 0.10, "PA": 0.08, "RO": 0.07, "TO": 0.035}

# Manchetes FICTÍCIAS de demonstração (o classificador define UF/categoria/sentimento).
DEMO_NEWS = [
    ("Arroba do boi gordo sobe em Rondônia com escalas curtas em Vilhena", "Frigoríficos do Cone Sul de RO operam com escalas apertadas e oferta restrita de boiadas terminadas."),
    ("Frigoríficos de Porto Velho alongam escalas e pressionam preço do boi", "Indústria em Rondônia trabalha com escala de mais de uma semana e oferta maior."),
    ("Idaron reforça calendário de vacinação e rastreabilidade em Rondônia", "Agência de defesa sanitária destaca avanços no status sanitário do rebanho."),
    ("IMEA: boi gordo em Mato Grosso acumula alta na semana", "Indicador do IMEA mostra valorização da arroba em Cuiabá e no Vale do Guaporé."),
    ("Pontes e Lacerda tem demanda firme por boi China", "Plantas habilitadas para exportação buscam animais jovens no Oeste de Mato Grosso."),
    ("Acrimat alerta para custo de reposição elevado em Mato Grosso", "Preço do bezerro segue firme e aperta margem de recria."),
    ("Milho recua em Mato Grosso com avanço da colheita da safrinha", "Oferta elevada de grão derruba preço da saca nas principais praças."),
    ("Mato Grosso do Sul: Famasul aponta retenção de fêmeas no rebanho", "Retenção de matrizes sinaliza menor oferta de boi nos próximos ciclos em Campo Grande."),
    ("Escalas em Campo Grande seguem curtas e arroba firme", "Frigoríficos de Mato Grosso do Sul compram para poucos dias."),
    ("Goiás: chuvas regulares melhoram pastagens e pecuarista segura boiada", "Retorno das águas em Goiânia e Rio Verde reduz oferta de animais para abate."),
    ("Faeg discute crédito rural e juros altos com bancos em Goiás", "Selic elevada encarece custeio da pecuária goiana."),
    ("Boi gordo em São Paulo renova recorde nominal em Araçatuba", "Indicador paulista avança com demanda forte do varejo e exportação aquecida."),
    ("Confinamentos paulistas reduzem giro com farelo de soja caro", "Custo de dieta pressiona margem em Presidente Prudente e Araçatuba."),
    ("Pará: Marabá registra queda na arroba com escalas alongadas", "Frigoríficos paraenses operam com escalas longas e oferta elevada de vacas."),
    ("Redenção e Xinguara ampliam abate de fêmeas no Pará", "Descarte de matrizes segue elevado no Sul do Pará."),
    ("Adepará intensifica fiscalização sanitária em São Félix do Xingu", "Defesa agropecuária amplia barreiras volantes no Pará."),
    ("Tocantins: Araguaína tem oferta curta e preço firme do boi", "Pecuaristas tocantinenses seguram animais à espera das chuvas."),
    ("Veranico preocupa produtores em Gurupi e no sul do Tocantins", "Estiagem fora de época atrasa recuperação das pastagens no Tocantins."),
    ("Exportações de carne bovina batem recorde em novembro, aponta Secex", "Embarques para a China seguem aquecidos e sustentam a arroba no Brasil."),
    ("China habilita novas plantas frigoríficas brasileiras", "Abertura de mercado amplia demanda por boi China em diversos estados."),
    ("Estados Unidos mantêm tarifa sobre carne bovina brasileira", "Barreira comercial limita embarques e preocupa exportadores."),
    ("B3: contratos futuros de boi gordo recuam com realização de lucros", "Vencimentos do primeiro trimestre registram queda após sequência de alta."),
    ("Ciclo pecuário: abate de fêmeas recua e indica virada para retenção", "Análise do IBGE mostra menor participação de vacas no abate nacional."),
    ("La Niña fraca deve trazer chuva irregular ao Brasil Central", "Previsão climática indica risco de veranico em parte do Centro-Oeste."),
    ("Dólar firme favorece exportação de carne bovina", "Câmbio valorizado melhora competitividade da proteína brasileira."),
    ("Preço do bezerro segue em alta e relação de troca piora para recriador", "Reposição cara reduz poder de compra do boi gordo."),
    ("Farelo de soja recua no mercado interno com safra cheia", "Oferta maior de farelo alivia custo do confinamento."),
    ("Febre aftosa: Brasil consolida status de livre sem vacinação", "Reconhecimento internacional abre portas para novos mercados."),
]


def _supply_from_days(days: float) -> str:
    if days < 5:
        return SupplyLevel.RESTRITA
    if days > 8:
        return SupplyLevel.AMPLA
    return SupplyLevel.EQUILIBRADA


def _shared_market_path(n: int) -> list[float]:
    """Fator de mercado comum (as praças se movem juntas), terminando em 1.0."""
    level, path = 1.0, []
    for _ in range(n):
        level *= 1 + RNG.gauss(0.0007, 0.0055)
        path.append(level)
    last = path[-1]
    return [p / last for p in path]


def seed_pracas() -> dict[str, Praca]:
    pracas = {}
    for data in PRACAS:
        p = Praca(**data)
        db.session.add(p)
        pracas[p.code] = p
    db.session.flush()
    return pracas


def seed_market_series(pracas: dict[str, Praca], days: list[date]) -> None:
    market = _shared_market_path(len(days))
    input_market = _shared_market_path(len(days))
    for code, praca in pracas.items():
        prof = PROFILE[code]
        idio = 0.0
        sched = prof["escala"]
        for i, d in enumerate(days):
            idio = 0.85 * idio + RNG.gauss(0, 0.002)  # ruído local autocorrelacionado
            boi = round(prof["boi"] * market[i] * (1 + idio), 2)
            vaca = round(boi * (0.925 + RNG.gauss(0, 0.003)), 2)
            china = round(boi + 7 + RNG.gauss(0, 1.2), 2)
            for cat, price in ((CattleCategory.BOI_GORDO, boi), (CattleCategory.VACA_GORDA, vaca),
                               (CattleCategory.BOI_CHINA, china)):
                db.session.add(CattleQuote(praca_id=praca.id, quote_date=d, category=cat,
                                           price=price, source=SEED))

            # Insumos: cotação semanal (segundas) + último dia, como numa pesquisa de mercado real
            if d.weekday() == 0 or i == len(days) - 1:
                f = input_market[i]
                db.session.add_all([
                    InputQuote(praca_id=praca.id, quote_date=d, item=InputItem.BEZERRO,
                               unit=InputItem.UNITS[InputItem.BEZERRO], reference_weight_kg=210,
                               price=round(prof["bezerro"] * f * (1 + RNG.gauss(0, 0.006)), 2), source=SEED),
                    InputQuote(praca_id=praca.id, quote_date=d, item=InputItem.MILHO,
                               unit=InputItem.UNITS[InputItem.MILHO],
                               price=round(prof["milho"] * (1 + RNG.gauss(0, 0.02)), 2), source=SEED),
                    InputQuote(praca_id=praca.id, quote_date=d, item=InputItem.FARELO_SOJA,
                               unit=InputItem.UNITS[InputItem.FARELO_SOJA],
                               price=round(prof["farelo"] * (1 + RNG.gauss(0, 0.015)), 2), source=SEED),
                ])

            # Escala: reversão à média em torno do perfil da praça
            sched = max(2.0, sched + 0.35 * (prof["escala"] - sched) + RNG.gauss(0, 0.45))
            days_ahead = round(sched * 2) / 2  # pesquisas reportam em meio dia
            db.session.add(SlaughterSchedule(praca_id=praca.id, ref_date=d, days_ahead=days_ahead,
                                             supply_level=_supply_from_days(days_ahead),
                                             plants_surveyed=RNG.randint(3, 9), source=SEED))


def seed_futures(days: list[date], sp_praca: Praca) -> None:
    """Curva BGI ancorada no físico de SP (referência do contrato), com leve backwardation."""
    sp_prices = {q.quote_date: q.price for q in db.session.query(CattleQuote).filter_by(
        praca_id=sp_praca.id, category=CattleCategory.BOI_GORDO)}
    spreads = [0.004, -0.008, -0.018, -0.024]  # vencimento corrente ≈ físico; 1º tri (safra) abaixo
    for d in days[-60:]:
        for idx, (code, maturity) in enumerate(next_contracts(d, 4)):
            price = sp_prices[d] * (1 + spreads[idx] + RNG.gauss(0, 0.003))
            db.session.add(FuturesQuote(quote_date=d, contract_code=code, maturity_month=maturity,
                                        settlement_price=round(price, 2),
                                        open_interest=RNG.randint(2000, 18000) // (idx + 1), source=SEED))


def _latest_published_quarter(ref: date, lag_days: int = 75) -> tuple[int, int]:
    """Último trimestre já divulgado pelo IBGE (~75 dias após o fechamento)."""
    year, q = ref.year, (ref.month - 1) // 3 + 1
    while True:
        end_month = q * 3
        next_first = date(year + (end_month == 12), end_month % 12 + 1, 1)
        if next_first - timedelta(days=1) + timedelta(days=lag_days) <= ref:
            return year, q
        year, q = (year - 1, 4) if q == 1 else (year, q - 1)


def seed_female_slaughter(ref: date) -> None:
    last_year, last_q = _latest_published_quarter(ref)
    for uf in ["BR", *STATES.keys()]:
        for year in range(2021, last_year + 1):
            for q in range(1, 5):
                if (year, q) > (last_year, last_q):
                    break
                share = (FEMALE_SHARE_BY_YEAR[year] + QUARTER_SEASONALITY[q]
                         + STATE_SHARE_OFFSET[uf] + RNG.gauss(0, 0.6))
                total = int(BR_HEADS_PER_QUARTER[year] * STATE_SLAUGHTER_WEIGHT[uf] * (1 + RNG.gauss(0, 0.03)))
                females = int(total * share / 100)
                males = total - females
                stat = FemaleSlaughterStat(
                    uf=uf, year=year, quarter=q, total_head=total,
                    cows_head=int(females * 0.84), heifers_head=females - int(females * 0.84),
                    bulls_head=int(males * 0.86), steers_head=males - int(males * 0.86), source=SEED)
                stat.recompute_share()
                db.session.add(stat)


def seed_weather(pracas: dict[str, Praca], start: date) -> None:
    for code, praca in pracas.items():
        target = PROFILE[code]["chuva15"]
        weights = [RNG.random() ** 2 for _ in range(15)]  # chuva concentrada em poucos dias
        total_w = sum(weights)
        daily = []
        for i, w in enumerate(weights):
            d = start + timedelta(days=i)
            tmax = round(32 + 2.2 * math.sin(i / 3) + RNG.gauss(0, 1.0) - (1.5 if w > 0.5 else 0), 1)
            daily.append({"date": d.isoformat(), "precip_mm": round(target * w / total_w, 1),
                          "tmax": tmax, "tmin": round(tmax - 10 + RNG.gauss(0, 1), 1)})
        db.session.add(build_snapshot(praca, daily, source=SEED))


def seed_news() -> None:
    now = utcnow()
    for i, (title, summary) in enumerate(DEMO_NEWS):
        c = classify(title, summary)
        url = f"https://agroradar.local/demo/{i + 1}"
        ts = now - timedelta(minutes=35 * i + 10)  # todas dentro das últimas 24h
        db.session.add(NewsArticle(
            url=url, url_hash=url_hash(url), title=title, summary=summary,
            source="AgroRadar Demo", published_at=ts, collected_at=ts,
            uf=c.uf, category=c.category, sentiment=c.sentiment, sentiment_score=c.sentiment_score))


def run_live_collectors(app) -> None:
    """Opcional (--live): substitui clima/IBGE/notícias de seed por dados reais, se a rede permitir."""
    from app.services.ibge_service import sync_female_slaughter
    from app.services.rss_collector import collect_news
    from app.services.weather_service import update_weather

    for label, fn in (("Open-Meteo", lambda: update_weather(db.session, app.config)),
                      ("IBGE SIDRA", lambda: sync_female_slaughter(db.session, app.config)),
                      ("RSS", lambda: collect_news(db.session, app.config))):
        try:
            result = fn()
            failed = getattr(result, "failed", None)
            if failed and len(failed) == len(result.feeds):
                print(f"  ✗ {label}: todos os feeds falharam (mantidas notícias de seed)")
            elif failed:
                print(f"  ~ {label}: parcial — {result.summary()}")
            else:
                print(f"  ✓ {label}: ok")
        except Exception as exc:  # o seed já garante dados; a falha aqui não é fatal
            print(f"  ✗ {label}: {exc} (mantidos dados de seed)")


def populate(today: date, n_days: int = 120, settings=None) -> list:
    """Gera todos os dados de demonstração (usado pelo CLI e pelos testes)."""
    days = business_days_back(today, n_days)
    pracas = seed_pracas()
    seed_market_series(pracas, days)
    db.session.flush()
    seed_futures(days, pracas["SP_ARACATUBA"])
    seed_female_slaughter(today)
    seed_weather(pracas, today)
    seed_news()
    db.session.commit()
    # Boletins pelo motor de regras: o seed nunca chama APIs pagas.
    return briefing_service.generate_all(db.session, {**(settings or {}), "AI_PROVIDER": "rules"},
                                         trigger="seed", ref_date=today)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed do AgroRadar")
    parser.add_argument("--reset", action="store_true", help="apaga e recria todas as tabelas")
    parser.add_argument("--live", action="store_true", help="tenta coletores reais após o seed")
    parser.add_argument("--days", type=int, default=120, help="dias úteis de histórico (padrão 120)")
    args = parser.parse_args(argv)

    app = create_app()
    with app.app_context():
        if args.reset:
            db.drop_all()
            db.create_all()
        elif db.session.query(Praca).count():
            print("Banco já populado. Use --reset para recriar.")
            return 1

        today = date.today()
        print(f"Gerando {args.days} dias úteis até {today} para {len(PRACAS)} praças...")
        briefings = populate(today, args.days, app.config)
        print(f"✓ Seed concluído: {len(briefings)} boletins, "
              f"{db.session.query(CattleQuote).count()} cotações, "
              f"{db.session.query(FemaleSlaughterStat).count()} trimestres IBGE (ilustrativos).")

        if args.live:
            print("Tentando coletores reais...")
            run_live_collectors(app)
    return 0


if __name__ == "__main__":
    sys.exit(main())
