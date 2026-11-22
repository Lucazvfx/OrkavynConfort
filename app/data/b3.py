"""Convenções do contrato futuro de Boi Gordo da B3 (código BGI)."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from ..utils import last_business_day

# Letras de vencimento padrão B3/CME
MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
               7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}


def contract_code(year: int, month: int, root: str = "BGI") -> str:
    return f"{root}{MONTH_CODES[month]}{str(year)[-2:]}"


def last_trading_day(year: int, month: int) -> date:
    """BGI vence no último dia útil do mês (feriados ignorados)."""
    return last_business_day(date(year, month, calendar.monthrange(year, month)[1]))


def next_contracts(ref: date, count: int = 4) -> list[tuple[str, date]]:
    """Próximos `count` vencimentos ainda negociáveis em `ref`: [(código, 1º dia do mês)]."""
    year, month = ref.year, ref.month
    if ref > last_trading_day(year, month):
        month += 1
        if month == 13:
            year, month = year + 1, 1
    out = []
    for _ in range(count):
        out.append((contract_code(year, month), date(year, month, 1)))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out
