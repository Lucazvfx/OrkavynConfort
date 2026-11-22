"""Ciclo pecuário — IBGE SIDRA, Pesquisa Trimestral do Abate de Animais (tabela 1092).

Busca cabeças abatidas por tipo de rebanho (Bois, Vacas, Novilhos, Novilhas) para
Brasil + UFs monitoradas e calcula a % de fêmeas (vacas + novilhas) no abate.

Robustez: o parser localiza as dimensões pelo RÓTULO do cabeçalho do SIDRA
(não pela posição D1/D2/...), e descarta linhas que não sejam "Total" em
classificações auxiliares (Referência temporal / Tipo de inspeção), caso a API
as devolva desagregadas. Códigos da tabela ficam em constantes para ajuste fácil.

Defasagem: o IBGE publica o trimestre ~2,5 meses após o fechamento. Um "termômetro"
baseado nele mostra a fase do ciclo, não o mês corrente.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select

from ..data.pracas import IBGE_CODE_TO_UF, STATES
from ..models import FemaleSlaughterStat
from ..utils import normalize_text
from .http import build_session, timeout
from .job_log import track_job

log = logging.getLogger(__name__)

SIDRA_BASE = "https://apis.sidra.ibge.gov.br/values"
TABLE_ID = 1092                 # Abate de animais — bovinos, trimestral
VARIABLE_ANIMALS = 284          # Animais abatidos (cabeças)
CLASS_HERD_TYPE = 18            # Tipo de rebanho bovino

# Limiares do termômetro (% de fêmeas no abate total)
LIQUIDATION_THRESHOLD = 45.0
RETENTION_THRESHOLD = 40.0

_HERD_MAP = {"total": "total_head", "bois": "bulls_head", "novilhos": "steers_head",
             "vacas": "cows_head", "novilhas": "heifers_head"}


class IBGEServiceError(RuntimeError):
    pass


@dataclass
class QuarterRecord:
    uf: str
    year: int
    quarter: int
    total_head: int | None = None
    bulls_head: int | None = None
    steers_head: int | None = None
    cows_head: int | None = None
    heifers_head: int | None = None

    @property
    def female_share(self) -> float | None:
        if self.cows_head is None and self.heifers_head is None:
            return None
        total = self.total_head
        if not total:
            parts = [self.bulls_head, self.steers_head, self.cows_head, self.heifers_head]
            total = sum(p or 0 for p in parts)
        if not total:
            return None
        return round(((self.cows_head or 0) + (self.heifers_head or 0)) / total * 100, 2)


# ---------------------------------------------------------------------------
# Interpretação (Módulo C)
# ---------------------------------------------------------------------------
def classify_cycle(female_share: float | None) -> dict:
    if female_share is None:
        return {"phase": "indefinido", "label": "Sem dados", "color": "gray",
                "message": "Dados de abate de fêmeas indisponíveis para o período."}
    if female_share > LIQUIDATION_THRESHOLD:
        return {"phase": "liquidacao", "label": "Liquidação de matrizes", "color": "red",
                "message": "Descarte elevado de fêmeas: mais oferta e pressão de baixa no curto prazo; "
                           "tende a gerar escassez de bezerro em 18–24 meses."}
    if female_share >= RETENTION_THRESHOLD:
        return {"phase": "equilibrio", "label": "Equilíbrio / transição", "color": "yellow",
                "message": "Participação de fêmeas em zona de transição de ciclo. Acompanhar a direção "
                           "dos próximos trimestres."}
    return {"phase": "retencao", "label": "Retenção de fêmeas", "color": "green",
            "message": "Matrizes retidas para cria: oferta de boi tende a encolher — viés estrutural de alta."}


# ---------------------------------------------------------------------------
# Requisição e parsing
# ---------------------------------------------------------------------------
def build_url(periods: str = "last 8", ufs: list[str] | None = None) -> str:
    ufs = ufs or list(STATES.keys())
    uf_codes = ",".join(STATES[uf]["ibge_code"] for uf in ufs if uf in STATES)
    period = periods.replace(" ", "%20")
    return (f"{SIDRA_BASE}/t/{TABLE_ID}/n1/all/n3/{uf_codes}/v/{VARIABLE_ANIMALS}"
            f"/p/{period}/c{CLASS_HERD_TYPE}/all")


def _parse_int(value) -> int | None:
    """SIDRA usa '-', 'X' (sigilo), '..', '...' para ausência."""
    if value is None:
        return None
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    try:
        return int(float(text))
    except ValueError:
        return None


def _find_dim(header: dict, *needles: str) -> str | None:
    """Retorna o prefixo 'Dn' cujo rótulo contém algum dos termos."""
    for key, label in header.items():
        if not (key.startswith("D") and key.endswith("N")):
            continue
        norm = normalize_text(label)
        if any(n in norm for n in needles):
            return key[:-1]  # "D3N" -> "D3"
    return None


def parse_sidra(rows: list[dict]) -> list[QuarterRecord]:
    if not rows or len(rows) < 2:
        return []
    header, data = rows[0], rows[1:]
    terr = _find_dim(header, "unidade da federacao", "brasil")
    period = _find_dim(header, "trimestre")
    herd = _find_dim(header, "tipo de rebanho")
    if not (terr and period and herd):
        raise IBGEServiceError(f"Cabeçalho SIDRA inesperado: {header}")
    aux_dims = [d for d in (_find_dim(header, "referencia temporal"), _find_dim(header, "tipo de inspecao")) if d]

    records: dict[tuple, QuarterRecord] = {}
    for row in data:
        if any(not normalize_text(row.get(f"{d}N", "")).startswith("total") for d in aux_dims):
            continue
        uf = IBGE_CODE_TO_UF.get(str(row.get(f"{terr}C")))
        code = str(row.get(f"{period}C", ""))
        field = _HERD_MAP.get(normalize_text(row.get(f"{herd}N", "")).strip())
        if not uf or len(code) != 6 or not field:
            continue
        year, quarter = int(code[:4]), int(code[4:])
        rec = records.setdefault((uf, year, quarter), QuarterRecord(uf, year, quarter))
        setattr(rec, field, _parse_int(row.get("V")))
    return sorted(records.values(), key=lambda r: (r.uf, r.year, r.quarter))


def fetch_female_slaughter(settings: Mapping, periods: str = "last 8", http=None) -> list[QuarterRecord]:
    http = http or build_session(settings)
    url = build_url(periods)
    try:
        resp = http.get(url, timeout=max(timeout(settings), 40))  # SIDRA é lento
        resp.raise_for_status()
        return parse_sidra(resp.json())
    except IBGEServiceError:
        raise
    except Exception as exc:
        raise IBGEServiceError(f"SIDRA indisponível ({url}): {exc}") from exc


def upsert_records(session, records: list[QuarterRecord], source: str = "ibge_sidra") -> int:
    count = 0
    existing = {(s.uf, s.year, s.quarter): s for s in session.scalars(select(FemaleSlaughterStat))}
    for rec in records:
        if rec.female_share is None:
            continue
        stat = existing.get((rec.uf, rec.year, rec.quarter)) or FemaleSlaughterStat(
            uf=rec.uf, year=rec.year, quarter=rec.quarter)
        stat.total_head = rec.total_head
        stat.bulls_head, stat.steers_head = rec.bulls_head, rec.steers_head
        stat.cows_head, stat.heifers_head = rec.cows_head, rec.heifers_head
        stat.female_share = rec.female_share
        stat.source = source
        session.add(stat)
        count += 1
    session.commit()
    return count


def sync_female_slaughter(session, settings: Mapping, periods: str = "last 8", http=None) -> int:
    """Atualiza a tabela female_slaughter_stats a partir do SIDRA. Dados de seed são sobrescritos."""
    with track_job(session, "ibge") as run:
        records = fetch_female_slaughter(settings, periods, http=http)
        if not records:
            raise IBGEServiceError("SIDRA retornou zero registros válidos")
        count = upsert_records(session, records)
        by_uf = defaultdict(int)
        for r in records:
            by_uf[r.uf] += 1
        run.detail = f"{count} trimestres atualizados ({dict(by_uf)})"
    return count
