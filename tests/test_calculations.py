import pytest

from app.services.calculations import (
    FatteningInput, compute_trend, ratio_signal, schedule_signal, simulate_fattening,
)


def test_schedule_signal_thresholds():
    assert schedule_signal(4.5)["color"] == "red"
    assert schedule_signal(5)["color"] == "yellow"
    assert schedule_signal(8)["color"] == "yellow"
    assert schedule_signal(8.5)["color"] == "green"
    assert schedule_signal(None)["level"] == "sem_dado"


def test_trend_combines_drivers():
    up = compute_trend(1.2, 4.0, "alta", 5, 1)
    assert up["direction"] == "alta" and up["score"] == 4
    down = compute_trend(-1.0, 9.0, None)
    assert down["direction"] == "baixa"
    assert compute_trend(None, 6, None)["direction"] == "lateral"


def test_ratio_signal():
    assert ratio_signal(2.1, 2.0, True, "fav", "ruim")["status"] == "favoravel"   # +5%
    assert ratio_signal(1.9, 2.0, True, "fav", "ruim")["status"] == "apertada"    # -5%
    assert ratio_signal(2.02, 2.0, True, "fav", "ruim")["status"] == "neutra"
    assert ratio_signal(None, 2.0, True, "fav", "ruim")["status"] == "sem_dado"


def test_simulator_math():
    r = simulate_fattening(FatteningInput(
        peso_atual_kg=450, gmd_kg=1.0, dias=60, custo_diario=15, preco_arroba_hoje=300,
        preco_arroba_venda=300, rendimento_atual=0.52, rendimento_final=0.52))
    # 450*0.52/15 = 15,6@ ; 510*0.52/15 = 17,68@ ; ganho 2,08@
    assert r["arrobas_hoje"] == 15.6 and r["arrobas_final"] == 17.68
    assert r["receita_vender_hoje"] == 4680.0 and r["custo_total"] == 900.0
    assert r["lucro_incremental"] == pytest.approx(17.68 * 300 - 4680 - 900, abs=0.01)  # -276
    assert r["custo_por_arroba_produzida"] == pytest.approx(900 / 2.08, abs=0.01)
    # equilíbrio: preço que zera o lucro incremental
    assert r["preco_equilibrio_arroba"] == pytest.approx((4680 + 900) / 17.68, abs=0.01)
    # custo da @ produzida (R$ 432) > preço da @ (R$ 300) => vender
    assert r["decisao"] == "vender_agora"


def test_simulator_opportunity_cost_can_flip_decision():
    base = dict(peso_atual_kg=450, gmd_kg=1.2, dias=60, custo_diario=10, preco_arroba_hoje=300,
                preco_arroba_venda=300, rendimento_atual=0.52, rendimento_final=0.52)
    assert simulate_fattening(FatteningInput(**base))["decisao"] == "segurar"
    assert simulate_fattening(FatteningInput(**base, juros_mensal_pct=2.0))["decisao"] == "vender_agora"


def test_simulator_validation():
    with pytest.raises(ValueError, match="gmd_kg"):
        simulate_fattening(FatteningInput(450, 5.0, 60, 15, 300))
