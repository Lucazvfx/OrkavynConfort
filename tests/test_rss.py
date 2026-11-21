from app.models import NewsArticle
from app.services.rss_collector import collect_news, normalize_url, parse_feed
from tests.conftest import FakeHTTP, FakeResponse

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Feed</title>
<item><title>Arroba sobe em Vilhena</title><link>https://ex.com/a?utm_source=x</link>
<description><![CDATA[<p>Escalas curtas em Rond&ocirc;nia.</p>]]></description>
<pubDate>Fri, 20 Nov 2026 09:00:00 -0300</pubDate></item>
<item><title>Milho recua em Mato Grosso</title><link>https://ex.com/b</link>
<pubDate>Fri, 20 Nov 2026 10:00:00 -0300</pubDate></item>
</channel></rss>"""


def test_parse_feed_cleans_and_classifies():
    items = parse_feed(RSS, "Teste")
    assert len(items) == 2
    a = items[0]
    assert a["summary"] == "Escalas curtas em Rondônia."
    assert a["uf"] == "RO" and a["sentiment"] == "positivo"
    assert a["published_at"].hour == 12  # 09:00 -03:00 => 12:00 UTC


def test_normalize_url_strips_tracking():
    assert normalize_url("https://Ex.com/a/?utm_source=x&id=1") == "https://ex.com/a?id=1"


def test_collect_dedupes_and_isolates_feed_errors(session):
    settings = {"RSS_FEEDS": "Bom|https://ok.test/feed,Ruim|https://bad.test/feed"}
    http = FakeHTTP({"ok.test": FakeResponse(content=RSS), "bad.test": FakeResponse(status=500)})
    r1 = collect_news(session, settings, http=http)
    assert r1.inserted == 2 and len(r1.failed) == 1
    r2 = collect_news(session, settings, http=http)
    assert r2.inserted == 0
    assert session.query(NewsArticle).count() == 2
