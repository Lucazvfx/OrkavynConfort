"""Sessão HTTP com retry/backoff compartilhada pelos coletores."""
from __future__ import annotations

from collections.abc import Mapping

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def build_session(settings: Mapping | None = None, retries: int = 2) -> requests.Session:
    settings = settings or {}
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = settings.get("HTTP_USER_AGENT", "AgroRadar/0.1")
    return session


def timeout(settings: Mapping | None) -> int:
    return int((settings or {}).get("HTTP_TIMEOUT_SECONDS", 20))
