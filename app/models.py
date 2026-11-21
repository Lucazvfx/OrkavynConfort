"""Schema do banco de dados do AgroRadar (SQLAlchemy 2.0, tipado).

Convenções:
- Datetimes em UTC *naive* (ver utils.utcnow).
- Preços em Numeric(…, asdecimal=False): exatos no PostgreSQL, devolvidos como float no Python.
- `source` em toda tabela de mercado: diferencia dado real (manual/IBGE/Open-Meteo) de dado de seed.
- `uf = "BR"` representa o agregado nacional onde fizer sentido.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db
from .utils import utcnow

Money = Numeric(12, 2, asdecimal=False)


# ---------------------------------------------------------------------------
# Domínio: constantes de categorias (strings simples = portáveis entre bancos)
# ---------------------------------------------------------------------------
class CattleCategory:
    BOI_GORDO = "boi_gordo"
    VACA_GORDA = "vaca_gorda"
    BOI_CHINA = "boi_china"
    ALL = (BOI_GORDO, VACA_GORDA, BOI_CHINA)
    LABELS = {BOI_GORDO: "Boi Gordo", VACA_GORDA: "Vaca Gorda", BOI_CHINA: "Boi China"}


class InputItem:
    BEZERRO = "bezerro"          # R$/cabeça (desmama, ~7@ / 210 kg)
    MILHO = "milho"              # R$/saca 60 kg
    FARELO_SOJA = "farelo_soja"  # R$/tonelada (unidade usual do mercado)
    ALL = (BEZERRO, MILHO, FARELO_SOJA)
    UNITS = {BEZERRO: "R$/cab", MILHO: "R$/sc60", FARELO_SOJA: "R$/t"}


class SupplyLevel:
    RESTRITA = "restrita"
    EQUILIBRADA = "equilibrada"
    AMPLA = "ampla"
    ALL = (RESTRITA, EQUILIBRADA, AMPLA)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Praças
# ---------------------------------------------------------------------------
class Praca(TimestampMixin, db.Model):
    __tablename__ = "pracas"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # ex.: RO_VILHENA
    name: Mapped[str] = mapped_column(String(80))
    uf: Mapped[str] = mapped_column(String(2), index=True)
    region: Mapped[Optional[str]] = mapped_column(String(80))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    is_state_reference: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    cattle_quotes: Mapped[list["CattleQuote"]] = relationship(back_populates="praca", cascade="all, delete-orphan")
    input_quotes: Mapped[list["InputQuote"]] = relationship(back_populates="praca", cascade="all, delete-orphan")
    schedules: Mapped[list["SlaughterSchedule"]] = relationship(back_populates="praca", cascade="all, delete-orphan")
    weather_snapshots: Mapped[list["WeatherSnapshot"]] = relationship(back_populates="praca", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "code": self.code, "name": self.name, "uf": self.uf,
            "region": self.region, "latitude": self.latitude, "longitude": self.longitude,
            "is_state_reference": self.is_state_reference, "active": self.active,
        }


# ---------------------------------------------------------------------------
# Módulo A — Cotações físicas da arroba
# ---------------------------------------------------------------------------
class CattleQuote(TimestampMixin, db.Model):
    __tablename__ = "cattle_quotes"
    __table_args__ = (
        UniqueConstraint("praca_id", "quote_date", "category", name="uq_cattle_quote"),
        Index("ix_cattle_quote_lookup", "praca_id", "category", "quote_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    praca_id: Mapped[int] = mapped_column(ForeignKey("pracas.id", ondelete="CASCADE"))
    quote_date: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(20))          # CattleCategory
    price: Mapped[float] = mapped_column(Money)                # R$/@ à vista
    payment_term: Mapped[str] = mapped_column(String(20), default="a_vista")
    source: Mapped[str] = mapped_column(String(60), default="manual")

    praca: Mapped[Praca] = relationship(back_populates="cattle_quotes")

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.quote_date.isoformat(), "category": self.category,
                "price": self.price, "payment_term": self.payment_term, "source": self.source}


# ---------------------------------------------------------------------------
# Módulo B — Insumos e reposição (bezerro, milho, farelo)
# ---------------------------------------------------------------------------
class InputQuote(TimestampMixin, db.Model):
    __tablename__ = "input_quotes"
    __table_args__ = (
        UniqueConstraint("praca_id", "quote_date", "item", name="uq_input_quote"),
        Index("ix_input_quote_lookup", "praca_id", "item", "quote_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    praca_id: Mapped[int] = mapped_column(ForeignKey("pracas.id", ondelete="CASCADE"))
    quote_date: Mapped[date] = mapped_column(Date)
    item: Mapped[str] = mapped_column(String(20))              # InputItem
    unit: Mapped[str] = mapped_column(String(12))              # InputItem.UNITS
    price: Mapped[float] = mapped_column(Money)
    reference_weight_kg: Mapped[Optional[float]] = mapped_column(Float)  # peso de referência do bezerro
    source: Mapped[str] = mapped_column(String(60), default="manual")

    praca: Mapped[Praca] = relationship(back_populates="input_quotes")

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.quote_date.isoformat(), "item": self.item, "unit": self.unit,
                "price": self.price, "reference_weight_kg": self.reference_weight_kg, "source": self.source}


# ---------------------------------------------------------------------------
# Módulos A/F — Escala de abate e oferta
# ---------------------------------------------------------------------------
class SlaughterSchedule(TimestampMixin, db.Model):
    __tablename__ = "slaughter_schedules"
    __table_args__ = (UniqueConstraint("praca_id", "ref_date", name="uq_schedule"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    praca_id: Mapped[int] = mapped_column(ForeignKey("pracas.id", ondelete="CASCADE"))
    ref_date: Mapped[date] = mapped_column(Date, index=True)
    days_ahead: Mapped[float] = mapped_column(Float)           # média de dias úteis de escala
    supply_level: Mapped[str] = mapped_column(String(15), default=SupplyLevel.EQUILIBRADA)
    plants_surveyed: Mapped[Optional[int]] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(60), default="manual")

    praca: Mapped[Praca] = relationship(back_populates="schedules")

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.ref_date.isoformat(), "days_ahead": self.days_ahead,
                "supply_level": self.supply_level, "plants_surveyed": self.plants_surveyed,
                "notes": self.notes, "source": self.source}


# ---------------------------------------------------------------------------
# Módulo C — Ciclo pecuário (IBGE / Pesquisa Trimestral do Abate)
# ---------------------------------------------------------------------------
class FemaleSlaughterStat(TimestampMixin, db.Model):
    __tablename__ = "female_slaughter_stats"
    __table_args__ = (UniqueConstraint("uf", "year", "quarter", name="uq_female_stat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    uf: Mapped[str] = mapped_column(String(2), index=True)     # "BR" = Brasil
    year: Mapped[int] = mapped_column(Integer)
    quarter: Mapped[int] = mapped_column(Integer)              # 1..4
    total_head: Mapped[Optional[int]] = mapped_column(BigInteger)
    bulls_head: Mapped[Optional[int]] = mapped_column(BigInteger)    # bois
    steers_head: Mapped[Optional[int]] = mapped_column(BigInteger)   # novilhos
    cows_head: Mapped[Optional[int]] = mapped_column(BigInteger)     # vacas
    heifers_head: Mapped[Optional[int]] = mapped_column(BigInteger)  # novilhas
    female_share: Mapped[Optional[float]] = mapped_column(Float)     # % (0-100), desnormalizado p/ consulta
    source: Mapped[str] = mapped_column(String(60), default="ibge_sidra")

    @property
    def period_label(self) -> str:
        return f"{self.quarter}T{str(self.year)[-2:]}"

    def recompute_share(self) -> None:
        females = (self.cows_head or 0) + (self.heifers_head or 0)
        total = self.total_head or 0
        self.female_share = round(females / total * 100, 2) if total > 0 else None

    def to_dict(self) -> dict[str, Any]:
        return {"uf": self.uf, "year": self.year, "quarter": self.quarter, "label": self.period_label,
                "total_head": self.total_head, "cows_head": self.cows_head,
                "heifers_head": self.heifers_head, "female_share": self.female_share, "source": self.source}


# ---------------------------------------------------------------------------
# Módulo G — Mercado futuro B3 (Boi Gordo BGI)
# ---------------------------------------------------------------------------
class FuturesQuote(TimestampMixin, db.Model):
    __tablename__ = "futures_quotes"
    __table_args__ = (UniqueConstraint("quote_date", "contract_code", name="uq_futures_quote"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_date: Mapped[date] = mapped_column(Date, index=True)
    contract_code: Mapped[str] = mapped_column(String(10))     # ex.: BGIZ26
    maturity_month: Mapped[date] = mapped_column(Date)         # 1º dia do mês de vencimento
    settlement_price: Mapped[float] = mapped_column(Money)     # ajuste, R$/@
    open_interest: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(60), default="manual")

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.quote_date.isoformat(), "contract": self.contract_code,
                "maturity": self.maturity_month.isoformat(), "settlement": self.settlement_price,
                "open_interest": self.open_interest, "source": self.source}


# ---------------------------------------------------------------------------
# Módulo E — Clima (Open-Meteo)
# ---------------------------------------------------------------------------
class WeatherSnapshot(db.Model):
    __tablename__ = "weather_snapshots"
    __table_args__ = (Index("ix_weather_praca_time", "praca_id", "fetched_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    praca_id: Mapped[int] = mapped_column(ForeignKey("pracas.id", ondelete="CASCADE"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    horizon_days: Mapped[int] = mapped_column(Integer)
    precip_total_mm: Mapped[float] = mapped_column(Float)
    tmax_avg: Mapped[Optional[float]] = mapped_column(Float)
    tmax_peak: Mapped[Optional[float]] = mapped_column(Float)
    hot_days: Mapped[int] = mapped_column(Integer, default=0)  # dias com Tmax >= limiar de calor
    alert_code: Mapped[str] = mapped_column(String(15))        # dry | neutral | wet
    alert_title: Mapped[str] = mapped_column(String(120))
    alert_message: Mapped[str] = mapped_column(Text)
    price_bias: Mapped[str] = mapped_column(String(10))        # baixa | neutro | alta
    daily: Mapped[list] = mapped_column(JSON, default=list)    # [{date, precip_mm, tmax, tmin}]
    source: Mapped[str] = mapped_column(String(60), default="open-meteo")

    praca: Mapped[Praca] = relationship(back_populates="weather_snapshots")

    def to_dict(self) -> dict[str, Any]:
        return {"fetched_at": self.fetched_at.isoformat(), "horizon_days": self.horizon_days,
                "precip_total_mm": self.precip_total_mm, "tmax_avg": self.tmax_avg,
                "tmax_peak": self.tmax_peak, "hot_days": self.hot_days,
                "alert": {"code": self.alert_code, "title": self.alert_title,
                          "message": self.alert_message, "price_bias": self.price_bias},
                "daily": self.daily, "source": self.source}


# ---------------------------------------------------------------------------
# Módulo H — Notícias
# ---------------------------------------------------------------------------
class NewsArticle(db.Model):
    __tablename__ = "news_articles"
    __table_args__ = (Index("ix_news_uf_time", "uf", "published_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 da URL normalizada
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(80), index=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    uf: Mapped[str] = mapped_column(String(2), default="BR")    # UF detectada ou BR
    category: Mapped[str] = mapped_column(String(30), default="geral")
    sentiment: Mapped[str] = mapped_column(String(10), default="neutro")  # positivo|neutro|negativo
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)    # -1..1

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "summary": self.summary, "url": self.url,
                "source": self.source,
                "published_at": self.published_at.isoformat() if self.published_at else None,
                "collected_at": self.collected_at.isoformat(), "uf": self.uf,
                "category": self.category, "sentiment": self.sentiment,
                "sentiment_score": self.sentiment_score}


# ---------------------------------------------------------------------------
# Módulo D — Boletim das 6h
# ---------------------------------------------------------------------------
class DailyBriefing(db.Model):
    __tablename__ = "daily_briefings"
    __table_args__ = (UniqueConstraint("briefing_date", "uf", name="uq_briefing"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    briefing_date: Mapped[date] = mapped_column(Date, index=True)
    uf: Mapped[str] = mapped_column(String(2))
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(20))          # gemini | openai | ollama | rules
    model: Mapped[Optional[str]] = mapped_column(String(80))
    news_count: Mapped[int] = mapped_column(Integer, default=0)
    trigger: Mapped[str] = mapped_column(String(15), default="scheduler")  # scheduler | manual | seed
    fallback_reason: Mapped[Optional[str]] = mapped_column(Text)  # erro do LLM, se caiu para regras
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.briefing_date.isoformat(), "uf": self.uf, "content": self.content,
                "provider": self.provider, "model": self.model, "news_count": self.news_count,
                "trigger": self.trigger, "generated_at": self.generated_at.isoformat()}


# ---------------------------------------------------------------------------
# Observabilidade dos jobs (coleta RSS, clima, IBGE, boletim)
# ---------------------------------------------------------------------------
class JobRun(db.Model):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="running")  # running|success|partial|error
    detail: Mapped[Optional[str]] = mapped_column(Text)

    def to_dict(self) -> dict[str, Any]:
        return {"job": self.job_name, "status": self.status, "detail": self.detail,
                "started_at": self.started_at.isoformat(),
                "finished_at": self.finished_at.isoformat() if self.finished_at else None}
