"""Registro das praças pecuárias e metadados dos estados.

É a fonte usada pelo seed. Em runtime, a verdade é a tabela `pracas`
(o admin pode ativar/desativar praças sem mexer em código).
"""
from __future__ import annotations

# UF -> (nome, código IBGE)
STATES: dict[str, dict] = {
    "RO": {"name": "Rondônia", "ibge_code": "11"},
    "PA": {"name": "Pará", "ibge_code": "15"},
    "TO": {"name": "Tocantins", "ibge_code": "17"},
    "SP": {"name": "São Paulo", "ibge_code": "35"},
    "MS": {"name": "Mato Grosso do Sul", "ibge_code": "50"},
    "MT": {"name": "Mato Grosso", "ibge_code": "51"},
    "GO": {"name": "Goiás", "ibge_code": "52"},
}

IBGE_CODE_TO_UF: dict[str, str] = {meta["ibge_code"]: uf for uf, meta in STATES.items()}
IBGE_CODE_TO_UF["1"] = "BR"  # nível territorial n1 (Brasil)

# `is_state_reference`: praça que representa o estado no mapa de calor e no boletim.
PRACAS: list[dict] = [
    {"code": "RO_VILHENA", "name": "Vilhena", "uf": "RO", "region": "Cone Sul / Sudeste de RO",
     "latitude": -12.7406, "longitude": -60.1458, "is_state_reference": True},
    {"code": "RO_PORTO_VELHO", "name": "Porto Velho", "uf": "RO", "region": "Norte de RO",
     "latitude": -8.7612, "longitude": -63.9004, "is_state_reference": False},
    {"code": "MT_PONTES_LACERDA", "name": "Pontes e Lacerda", "uf": "MT", "region": "Oeste de MT",
     "latitude": -15.2219, "longitude": -59.3353, "is_state_reference": False},
    {"code": "MT_CUIABA", "name": "Cuiabá", "uf": "MT", "region": "Centro-Sul de MT",
     "latitude": -15.6014, "longitude": -56.0979, "is_state_reference": True},
    {"code": "MS_CAMPO_GRANDE", "name": "Campo Grande", "uf": "MS", "region": "Centro de MS",
     "latitude": -20.4697, "longitude": -54.6201, "is_state_reference": True},
    {"code": "GO_GOIANIA", "name": "Goiânia", "uf": "GO", "region": "Centro de GO",
     "latitude": -16.6869, "longitude": -49.2648, "is_state_reference": True},
    {"code": "SP_ARACATUBA", "name": "Araçatuba", "uf": "SP", "region": "Noroeste de SP",
     "latitude": -21.2089, "longitude": -50.4328, "is_state_reference": True},
    {"code": "PA_MARABA", "name": "Marabá", "uf": "PA", "region": "Sudeste do PA",
     "latitude": -5.3686, "longitude": -49.1178, "is_state_reference": True},
    {"code": "PA_REDENCAO", "name": "Redenção", "uf": "PA", "region": "Sul do PA",
     "latitude": -8.0281, "longitude": -50.0317, "is_state_reference": False},
    {"code": "TO_ARAGUAINA", "name": "Araguaína", "uf": "TO", "region": "Norte do TO",
     "latitude": -7.1911, "longitude": -48.2072, "is_state_reference": True},
]
