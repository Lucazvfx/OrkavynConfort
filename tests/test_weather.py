import pytest

from app.models import Praca, WeatherSnapshot
from app.services.weather_service import (
    WeatherServiceError, evaluate_supply_impact, update_weather,
)
from tests.conftest import FakeHTTP, FakeResponse


def test_rules():
    assert evaluate_supply_impact(10).code == "dry"
    assert evaluate_supply_impact(10).price_bias == "baixa"
    assert evaluate_supply_impact(80).code == "wet"
    assert evaluate_supply_impact(80).price_bias == "alta"
    assert evaluate_supply_impact(30).code == "neutral"
    assert "dias acima" in evaluate_supply_impact(5, hot_days=6).message


def _payload(precip):
    n = len(precip)
    return {"daily": {"time": [f"2026-11-{i + 1:02d}" for i in range(n)],
                      "precipitation_sum": precip, "temperature_2m_max": [36.0] * n,
                      "temperature_2m_min": [22.0] * n}}


def _pracas(session):
    a = Praca(code="A", name="A", uf="RO", latitude=-12, longitude=-60)
    b = Praca(code="B", name="B", uf="MT", latitude=-15, longitude=-56)
    session.add_all([a, b]); session.commit()
    return [a, b]


def test_update_weather_batch(session):
    pracas = _pracas(session)
    http = FakeHTTP({"open-meteo": FakeResponse([_payload([0.5] * 15), _payload([6.0] * 15)])})
    snaps = update_weather(session, {"WEATHER_FORECAST_DAYS": 15}, pracas, http=http)
    assert [s.alert_code for s in snaps] == ["dry", "wet"]
    assert snaps[0].hot_days == 15
    params = http.calls[0][1]["params"]
    assert params["latitude"].count(",") == 1  # uma chamada para todas as praças
    assert session.query(WeatherSnapshot).count() == 2


def test_update_weather_failure_keeps_previous(session):
    pracas = _pracas(session)
    http = FakeHTTP({"open-meteo": ConnectionError("offline")})
    with pytest.raises(WeatherServiceError):
        update_weather(session, {}, pracas, http=http)
    assert session.query(WeatherSnapshot).count() == 0
