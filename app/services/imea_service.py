"""Indicadores do IMEA (Instituto Mato-grossense de Economia Agropecuária) para MT.

STATUS: DESLIGADO por padrão (IMEA_ENABLED=false). O IMEA não publica licença de uso
dos dados; a autorização foi solicitada ao instituto. Só ligue IMEA_ENABLED=true depois
de receber a autorização por escrito, e mantenha a citação da fonte no painel.

Fonte: a mesma API que a página pública https://www.imea.com.br/imea-site/indicador-boi
consome (cadeia 2 = boi). Formato inferido do código da página (campos IndicadorFinalId,
Localidade, Valor, Variacao, DataPublicacao); NÃO validado contra resposta real — conferir
a primeira execução após a autorização.

Mapeamento: região IMEA -> praça AgroRadar
- Centro-Sul -> MT_CUIABA
- Oeste      -> MT_PONTES_LACERDA (Pontes e Lacerda, Cáceres, Vale do Guaporé)
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select

from ..models import CattleCategory, CattleQuote, Praca, SlaughterSchedule, SupplyLevel
from ..utils import normalize_text
from .http import build_session, timeout
from .job_log import track_job

log = logging.getLogger(__name__)

API_URL = "https://api1.imea.com.br/api/v2/mobile/cadeias/2/cotacoes"
REFERER = "https://www.imea.com.br/imea-site/indicador-boi"
SOURCE = "imea"
ATTRIBUTION = "IMEA (Instituto Mato-grossense de Economia Agropecuária)"

# IDs publicados no código da página do indicador do boi
INDICATORS = {
    "708192508809576456": ("cattle", CattleCategory.BOI_GORDO),   # BOI GORDO À VISTA (R$/@, sem prêmio China)
    "708192508809576457": ("cattle", CattleCategory.VACA_GORDA),  # VACA GORDA À VISTA (R$/@)
    "708192508809576449": ("schedule", None),                     # ESCALA DE ABATE (dias)
}

# região do IMEA (normalizada) -> código da praça
REGION_TO_PRACA = {
    "centro-sul": "MT_CUIABA",
    "centro sul": "MT_CUIABA",
    "oeste": "MT_PONTES_LACERDA",
}


@dataclass
class ImeaRow:
    indicator_id: str
    region: str
    value: float
    ref_date: date


@dataclass
class ImeaResult:
    enabled: bool = True
    rows: int = 0
    saved: int = 0
    skipped_manual: int = 0
    unmapped_regions: set[str] = field(default_factory=set)

    def summary(self) -> str:
        if not self.enabled:
            return "IMEA desligado (IMEA_ENABLED=false): aguardando autorização do instituto"
        extra = f"; regiões sem praça: {sorted(self.unmapped_regions)}" if self.unmapped_regions else ""
        return f"{self.saved} gravados de {self.rows} linhas, {self.skipped_manual} manuais preservados{extra}"


def is_enabled(settings: Mapping) -> bool:
    return str(settings.get("IMEA_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "sim"}


def _parse_number(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    text = str(v).strip()
    if "," in text:  # formato brasileiro 1.234,56
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(v) -> date | None:
    if not v:
        return None
    text = str(v).strip()
    for fmt, size in (("%Y-%m-%d", 10), ("%d/%m/%Y", 10)):
        try:
            return datetime.strptime(text[:size], fmt).date()
        except ValueError:
            continue
    return None


def parse_rows(payload) -> list[ImeaRow]:
    """Aceita lista direta ou {"data": [...]}; ignora indicadores fora do mapa."""
    items = payload.get("data") if isinstance(payload, dict) else payload
    rows = []
    for item in items or []:
        ind = str(item.get("IndicadorFinalId", ""))
        if ind not in INDICATORS:
            continue
        value = _parse_number(item.get("Valor"))
        ref = _parse_date(item.get("DataPublicacao"))
        region = (item.get("Localidade") or "").strip()
        if value is None or ref is None or not region:
            continue
        rows.append(ImeaRow(ind, region, value, ref))
    return rows


def _supply_from_days(days: float) -> str:
    return SupplyLevel.RESTRITA if days < 5 else (SupplyLevel.AMPLA if days > 8 else SupplyLevel.EQUILIBRADA)


def save_rows(session, rows: list[ImeaRow]) -> ImeaResult:
    res = ImeaResult(rows=len(rows))
    pracas = {p.code: p for p in session.scalars(select(Praca).where(Praca.uf == "MT"))}
    for r in rows:
        code = REGION_TO_PRACA.get(normalize_text(r.region))
        praca = pracas.get(code) if code else None
        if praca is None:
            res.unmapped_regions.add(r.region)
            continue
        kind, category = INDICATORS[r.indicator_id]
        if kind == "cattle":
            row = session.scalars(select(CattleQuote).filter_by(
                praca_id=praca.id, quote_date=r.ref_date, category=category)).first()
            if row is not None and row.source == "manual":
                res.skipped_manual += 1
                continue
            row = row or CattleQuote(praca_id=praca.id, quote_date=r.ref_date, category=category)
            row.price, row.source = r.value, SOURCE
        else:
            row = session.scalars(select(SlaughterSchedule).filter_by(
                praca_id=praca.id, ref_date=r.ref_date)).first()
            if row is not None and row.source == "manual":
                res.skipped_manual += 1
                continue
            row = row or SlaughterSchedule(praca_id=praca.id, ref_date=r.ref_date)
            row.days_ahead, row.supply_level, row.source = r.value, _supply_from_days(r.value), SOURCE
        session.add(row)
        res.saved += 1
    session.commit()
    return res


def sync_imea(session, settings: Mapping, http=None) -> ImeaResult:
    with track_job(session, "imea") as run:
        if not is_enabled(settings):
            res = ImeaResult(enabled=False)
            run.detail, run.status = res.summary(), "success"
            return res
        http = http or build_session(settings, retries=1)
        resp = http.get(API_URL, headers={"Referer": REFERER, "Accept": "application/json"},
                        timeout=timeout(settings))
        resp.raise_for_status()
        res = save_rows(session, parse_rows(resp.json()))
        run.detail = res.summary()
        if res.unmapped_regions and not res.saved:
            run.status = "partial"
    return res
