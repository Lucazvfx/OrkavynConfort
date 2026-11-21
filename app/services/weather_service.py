"""Clima vs. Oferta de Boi — Open-Meteo (gratuita, sem chave).

Uma única requisição traz todas as praças (a API aceita listas de lat/lon).
O motor de regra traduz chuva acumulada em viés de oferta/preço da arroba.

Ressalva de domínio: a regra é sazonal. Pouca chuva em julho (seca normal no
Brasil Central) já está no preço; o sinal forte é chuva ABAIXO DO ESPERADO na
transição seca→águas (set–nov) ou veranico em plena estação chuvosa. Uma evolução
natural é comparar com a climatologia da praça em vez de limiares fixos.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..models import Praca, WeatherSnapshot
from .http import build_session, timeout
from .job_log import track_job

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
DRY_THRESHOLD_MM = 15.0    # < 15 mm em 15 dias: pasto seco
WET_THRESHOLD_MM = 50.0    # > 50 mm em 15 dias: águas regulares
HEAT_THRESHOLD_C = 35.0    # Tmax a partir da qual conta como dia de estresse térmico
HEAT_DAYS_ALERT = 5


class WeatherServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SupplyImpact:
    code: str        # dry | neutral | wet
    title: str
    message: str
    price_bias: str  # baixa | neutro | alta


def evaluate_supply_impact(precip_total_mm: float, hot_days: int = 0, horizon_days: int = 15) -> SupplyImpact:
    """Regra do Módulo E. Faixa 15–50 mm (não especificada) = transição/neutro."""
    if precip_total_mm < DRY_THRESHOLD_MM:
        heat = (f" {hot_days} dias acima de {HEAT_THRESHOLD_C:.0f}°C agravam o quadro."
                if hot_days >= HEAT_DAYS_ALERT else "")
        return SupplyImpact(
            "dry", "Alerta de pasto seco",
            f"Apenas {precip_total_mm:.0f} mm previstos em {horizon_days} dias: maior pressão de "
            f"entrega de boiadas (viés de baixa na @).{heat}",
            "baixa",
        )
    if precip_total_mm > WET_THRESHOLD_MM:
        return SupplyImpact(
            "wet", "Melhora de pastagem",
            f"{precip_total_mm:.0f} mm previstos em {horizon_days} dias: pecuarista tende a reter o "
            "boi no pasto (viés de alta na @).",
            "alta",
        )
    return SupplyImpact(
        "neutral", "Chuva irregular / transição",
        f"{precip_total_mm:.0f} mm previstos em {horizon_days} dias: sem sinal claro sobre a oferta.",
        "neutro",
    )


def build_params(pracas: list[Praca], days: int) -> dict[str, str]:
    return {
        "latitude": ",".join(f"{p.latitude:.4f}" for p in pracas),
        "longitude": ",".join(f"{p.longitude:.4f}" for p in pracas),
        "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min",
        "forecast_days": str(days),
        "timezone": "America/Sao_Paulo",
    }


def parse_daily(payload: dict) -> list[dict]:
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    precip = daily.get("precipitation_sum") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "date": d,
            "precip_mm": float(precip[i]) if i < len(precip) and precip[i] is not None else 0.0,
            "tmax": float(tmax[i]) if i < len(tmax) and tmax[i] is not None else None,
            "tmin": float(tmin[i]) if i < len(tmin) and tmin[i] is not None else None,
        })
    return rows


def build_snapshot(praca: Praca, daily: list[dict], source: str = "open-meteo") -> WeatherSnapshot:
    precip_total = round(sum(r["precip_mm"] for r in daily), 1)
    tmaxes = [r["tmax"] for r in daily if r["tmax"] is not None]
    hot_days = sum(1 for t in tmaxes if t >= HEAT_THRESHOLD_C)
    impact = evaluate_supply_impact(precip_total, hot_days, len(daily))
    return WeatherSnapshot(
        praca_id=praca.id, horizon_days=len(daily), precip_total_mm=precip_total,
        tmax_avg=round(sum(tmaxes) / len(tmaxes), 1) if tmaxes else None,
        tmax_peak=max(tmaxes) if tmaxes else None, hot_days=hot_days,
        alert_code=impact.code, alert_title=impact.title, alert_message=impact.message,
        price_bias=impact.price_bias, daily=daily, source=source,
    )


def fetch_forecasts(pracas: list[Praca], settings: Mapping, http=None) -> dict[int, list[dict]]:
    """Retorna {praca_id: daily_rows}. Levanta WeatherServiceError em falha total."""
    if not pracas:
        return {}
    http = http or build_session(settings)
    days = int(settings.get("WEATHER_FORECAST_DAYS", 15))
    try:
        resp = http.get(OPEN_METEO_URL, params=build_params(pracas, days), timeout=timeout(settings))
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise WeatherServiceError(f"Open-Meteo indisponível: {exc}") from exc
    # Uma coordenada => objeto; várias => lista na mesma ordem enviada.
    payloads = data if isinstance(data, list) else [data]
    if len(payloads) != len(pracas):
        raise WeatherServiceError(f"Esperava {len(pracas)} séries, recebi {len(payloads)}")
    return {p.id: parse_daily(payload) for p, payload in zip(pracas, payloads)}


def update_weather(session, settings: Mapping, pracas: Iterable[Praca] | None = None, http=None) -> list[WeatherSnapshot]:
    """Busca previsão e grava um snapshot por praça. Em falha, o último snapshot continua válido."""
    with track_job(session, "weather") as run:
        if pracas is None:
            pracas = session.query(Praca).filter_by(active=True).order_by(Praca.id).all()
        pracas = list(pracas)
        forecasts = fetch_forecasts(pracas, settings, http=http)
        snapshots: list[WeatherSnapshot] = []
        labels: list[str] = []
        for praca in pracas:
            daily = forecasts.get(praca.id) or []
            if not daily:
                continue
            snap = build_snapshot(praca, daily)
            session.add(snap)
            snapshots.append(snap)
            labels.append(f"{praca.code}={snap.precip_total_mm}mm/{snap.alert_code}")
        session.commit()
        run.detail = ", ".join(labels)
    return snapshots
