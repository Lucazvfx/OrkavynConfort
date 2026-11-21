"""Indicadores do Cepea/Esalq-USP (fonte pública de referência).

Licença dos dados: CEPEA, CC BY-NC 4.0. Isso significa:
- citar a fonte onde o número aparece (o painel mostra "Cepea/Esalq-USP");
- uso NÃO comercial. Se o AgroRadar passar a ser vendido/monetizado, é preciso
  licenciar os dados com o Cepea.

Cobertura (um indicador de referência por produto, não por praça):
- Boi gordo CEPEA/ESALQ — estado de SP (R$/@ à vista, sem Funrural)
- Bezerro CEPEA/ESALQ — MS (R$/cabeça)
- Milho ESALQ/B3 — Campinas-SP (R$/saca 60 kg)

Cuidados operacionais: o site usa Cloudflare e bloqueia acesso automatizado
agressivo. Por isso: uma requisição por indicador por dia, pausa entre elas, e
falha de um indicador nunca apaga dado existente. Lançamento manual do admin
tem prioridade e nunca é sobrescrito.
"""
from __future__ import annotations

import html
import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select

from ..models import CattleCategory, CattleQuote, InputItem, InputQuote, Praca
from .http import build_session, timeout
from .job_log import track_job

log = logging.getLogger(__name__)

BASE_URL = "https://www.cepea.org.br/br/indicador/"
ATTRIBUTION = "Cepea/Esalq-USP (CC BY-NC 4.0)"
SOURCE = "cepea"
PAUSE_SECONDS = 4.0

INDICATORS: dict[str, dict] = {
    "boi_gordo_sp": {"page": "boi-gordo.aspx", "kind": "cattle", "category": CattleCategory.BOI_GORDO,
                     "praca": "SP_ARACATUBA", "label": "Indicador do Boi Gordo CEPEA/ESALQ (SP)"},
    "bezerro_ms": {"page": "bezerro.aspx", "kind": "input", "item": InputItem.BEZERRO,
                   "praca": "MS_CAMPO_GRANDE", "label": "Indicador do Bezerro CEPEA/ESALQ (MS)"},
    "milho": {"page": "milho.aspx", "kind": "input", "item": InputItem.MILHO,
              "praca": "SP_ARACATUBA", "label": "Indicador do Milho ESALQ/B3 (Campinas-SP)"},
}

_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


class CepeaError(RuntimeError):
    pass


@dataclass
class IndicatorResult:
    key: str
    rows: int = 0
    saved: int = 0
    skipped_manual: int = 0
    latest: tuple[str, float] | None = None
    error: str | None = None


@dataclass
class SyncResult:
    indicators: list[IndicatorResult] = field(default_factory=list)

    @property
    def failed(self) -> list[IndicatorResult]:
        return [i for i in self.indicators if i.error]

    def summary(self) -> str:
        parts = []
        for i in self.indicators:
            if i.error:
                parts.append(f"{i.key}: ERRO {i.error}")
            else:
                last = f" (último {i.latest[0]} = {i.latest[1]:.2f})" if i.latest else ""
                parts.append(f"{i.key}: {i.saved} gravados, {i.skipped_manual} manuais preservados{last}")
        return " | ".join(parts)


def parse_brl(text: str) -> float | None:
    """'3.412,55' -> 3412.55; '-' ou vazio -> None."""
    text = (text or "").strip().replace("R$", "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def parse_indicator_table(page_html: str) -> list[tuple[date, float]]:
    """Lê a primeira tabela cujo cabeçalho tem 'Valor R$' (série diária à vista).

    Retorna [(data, valor)] do mais antigo para o mais recente. Levanta CepeaError
    se a estrutura não for encontrada (mudança de layout ou página de bloqueio).
    """
    if "Attention Required" in page_html or "Just a moment" in page_html:
        raise CepeaError("bloqueado pela proteção do site (Cloudflare)")
    for table in re.findall(r"<table.*?</table>", page_html, flags=re.S | re.I):
        header = re.search(r"<thead.*?</thead>", table, flags=re.S | re.I)
        head_text = html.unescape(re.sub(r"<[^>]+>", " ", header.group(0))) if header else ""
        if "Valor R$" not in head_text:
            continue
        rows = []
        for tr in re.findall(r"<tr.*?</tr>", table, flags=re.S | re.I):
            cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                     for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.S | re.I)]
            if len(cells) < 2:
                continue
            m = _DATE_RE.match(cells[0])
            value = parse_brl(cells[1])
            if m and value is not None:
                rows.append((date(int(m[3]), int(m[2]), int(m[1])), value))
        if rows:
            return sorted(rows)
    raise CepeaError("tabela do indicador não encontrada (layout mudou?)")


def _upsert(session, model, keys: dict, values: dict) -> str:
    row = session.scalars(select(model).filter_by(**keys)).first()
    if row is not None and row.source == "manual":
        return "manual"
    row = row or model(**keys)
    for k, v in values.items():
        setattr(row, k, v)
    session.add(row)
    return "saved"


def save_indicator(session, key: str, rows: list[tuple[date, float]]) -> IndicatorResult:
    spec = INDICATORS[key]
    res = IndicatorResult(key=key, rows=len(rows))
    praca = session.scalars(select(Praca).where(Praca.code == spec["praca"])).first()
    if praca is None:
        res.error = f"praça {spec['praca']} não cadastrada"
        return res
    # Dado real substitui a série de demonstração inteira daquela praça/produto:
    # misturar seed com valor real criaria variações falsas (ex.: +22% num dia).
    if rows:
        if spec["kind"] == "cattle":
            session.execute(delete(CattleQuote).where(
                CattleQuote.praca_id == praca.id, CattleQuote.category == spec["category"],
                CattleQuote.source == "seed"))
        else:
            session.execute(delete(InputQuote).where(
                InputQuote.praca_id == praca.id, InputQuote.item == spec["item"], InputQuote.source == "seed"))
    for d, value in rows:
        if spec["kind"] == "cattle":
            outcome = _upsert(session, CattleQuote,
                              {"praca_id": praca.id, "quote_date": d, "category": spec["category"]},
                              {"price": value, "source": SOURCE})
        else:
            outcome = _upsert(session, InputQuote,
                              {"praca_id": praca.id, "quote_date": d, "item": spec["item"]},
                              {"price": value, "unit": InputItem.UNITS[spec["item"]], "source": SOURCE,
                               **({"reference_weight_kg": None} if spec["item"] == InputItem.BEZERRO else {})})
        if outcome == "manual":
            res.skipped_manual += 1
        else:
            res.saved += 1
    if rows:
        res.latest = (rows[-1][0].isoformat(), rows[-1][1])
    session.commit()
    return res


def sync_cepea(session, settings: Mapping, http=None, keys: list[str] | None = None,
               pause: float = PAUSE_SECONDS) -> SyncResult:
    http = http or build_session(settings, retries=0)  # sem retry: insistir piora o bloqueio
    result = SyncResult()
    with track_job(session, "cepea") as run:
        for i, key in enumerate(keys or list(INDICATORS)):
            if i and pause:
                time.sleep(pause)
            url = BASE_URL + INDICATORS[key]["page"]
            try:
                resp = http.get(url, timeout=timeout(settings))
                if resp.status_code == 403:
                    raise CepeaError("HTTP 403 (bloqueado pela proteção do site)")
                resp.raise_for_status()
                rows = parse_indicator_table(resp.text)
                result.indicators.append(save_indicator(session, key, rows))
            except Exception as exc:
                session.rollback()
                log.warning("Cepea %s falhou: %s", key, exc)
                result.indicators.append(IndicatorResult(key=key, error=str(exc)[:200]))
        run.detail = result.summary()
        if result.failed:
            run.status = "error" if len(result.failed) == len(result.indicators) else "partial"
    return result

