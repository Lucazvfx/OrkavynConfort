"""Coletor de notícias via RSS (Canal Rural, Notícias Agrícolas, Agrolink, CompreRural).

Fluxo: baixa o XML com `requests` (timeout/retry controlados — o fetch nativo do
feedparser não tem timeout), parseia com `feedparser`, normaliza, deduplica por
hash da URL e classifica (UF/categoria/sentimento) antes de salvar.

Portais mudam feeds sem aviso: o JobRun registra qual feed falhou, e RSS_FEEDS
no .env sobrescreve a lista padrão.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
from calendar import timegm
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
from sqlalchemy import delete, select

from ..models import NewsArticle
from ..utils import utcnow
from .http import build_session, timeout
from .job_log import track_job
from .news_classifier import classify

log = logging.getLogger(__name__)

DEFAULT_FEEDS: list[dict[str, str]] = [
    # Validados ao vivo em 21/11/2026. Notícias Agrícolas e CompreRural ficaram de fora:
    # protegidos por Cloudflare contra leitores automáticos (HTTP 403 "Just a moment").
    {"name": "Canal Rural", "url": "https://www.canalrural.com.br/feed/"},
    {"name": "Agrolink", "url": "https://www.agrolink.com.br/rss/noticias.rss"},
]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}


@dataclass
class FeedResult:
    name: str
    fetched: int = 0
    inserted: int = 0
    error: str | None = None


@dataclass
class CollectResult:
    feeds: list[FeedResult] = field(default_factory=list)

    @property
    def inserted(self) -> int:
        return sum(f.inserted for f in self.feeds)

    @property
    def failed(self) -> list[FeedResult]:
        return [f for f in self.feeds if f.error]

    def summary(self) -> str:
        parts = [f"{f.name}: {'ERRO ' + f.error if f.error else f'{f.inserted}/{f.fetched} novas'}"
                 for f in self.feeds]
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------
def configured_feeds(settings: Mapping) -> list[dict[str, str]]:
    """Lê RSS_FEEDS ("Nome|URL,Nome|URL"); vazio => DEFAULT_FEEDS."""
    raw = (settings.get("RSS_FEEDS") or "").strip()
    if not raw:
        return DEFAULT_FEEDS
    feeds = []
    for chunk in raw.split(","):
        if "|" in chunk:
            name, url = chunk.split("|", 1)
            feeds.append({"name": name.strip(), "url": url.strip()})
        elif chunk.strip():
            feeds.append({"name": urlsplit(chunk.strip()).netloc, "url": chunk.strip()})
    return feeds


def clean_html(text: str | None, max_len: int = 600) -> str:
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    text = _WS_RE.sub(" ", text).strip()
    return text if len(text) <= max_len else text[: max_len - 1].rsplit(" ", 1)[0] + "…"


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _TRACKING_PARAMS]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"),
                       urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def _entry_datetime(entry) -> datetime | None:
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not struct:
        return None
    # feedparser devolve struct_time em UTC; timegm evita conversão pelo fuso local.
    return datetime.fromtimestamp(timegm(struct), tz=timezone.utc).replace(tzinfo=None)


def parse_feed(content: bytes | str, source_name: str) -> list[dict]:
    """Converte o XML do feed em dicts prontos para NewsArticle (sem tocar no banco)."""
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries:
        link = (entry.get("link") or "").strip()
        title = clean_html(entry.get("title"), max_len=500)
        if not link or not title:
            continue
        summary = clean_html(entry.get("summary") or entry.get("description"))
        c = classify(title, summary)
        items.append({
            "url": link, "url_hash": url_hash(link), "title": title, "summary": summary or None,
            "source": source_name, "published_at": _entry_datetime(entry),
            "uf": c.uf, "category": c.category, "sentiment": c.sentiment,
            "sentiment_score": c.sentiment_score,
        })
    return items


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------
def save_articles(session, items: list[dict]) -> int:
    if not items:
        return 0
    hashes = {i["url_hash"] for i in items}
    existing = set(session.scalars(select(NewsArticle.url_hash).where(NewsArticle.url_hash.in_(hashes))))
    now = utcnow()
    inserted = 0
    seen: set[str] = set()
    for item in items:
        h = item["url_hash"]
        if h in existing or h in seen:
            continue
        seen.add(h)
        session.add(NewsArticle(collected_at=now, **item))
        inserted += 1
    session.commit()
    return inserted


def prune_old_news(session, retention_days: int) -> int:
    cutoff = utcnow() - timedelta(days=retention_days)
    result = session.execute(delete(NewsArticle).where(NewsArticle.collected_at < cutoff))
    session.commit()
    return result.rowcount or 0


def collect_news(session, settings: Mapping, http=None) -> CollectResult:
    """Coleta todos os feeds. Falha de um feed não derruba os demais."""
    http = http or build_session(settings)
    result = CollectResult()
    with track_job(session, "rss") as run:
        for feed in configured_feeds(settings):
            fr = FeedResult(name=feed["name"])
            try:
                resp = http.get(feed["url"], timeout=timeout(settings))
                resp.raise_for_status()
                items = parse_feed(resp.content, feed["name"])
                fr.fetched = len(items)
                fr.inserted = save_articles(session, items)
            except Exception as exc:  # rede, XML inválido, HTTP 4xx/5xx
                session.rollback()
                fr.error = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("Feed %s falhou: %s", feed["name"], fr.error)
            result.feeds.append(fr)

        pruned = prune_old_news(session, int(settings.get("NEWS_RETENTION_DAYS", 60)))
        run.detail = result.summary() + (f" | removidas {pruned} antigas" if pruned else "")
        if result.failed:
            run.status = "error" if len(result.failed) == len(result.feeds) else "partial"
    return result
