from app.services.ai_service import (
    BriefingContext, GeminiProvider, OpenAIProvider, generate_briefing, resolve_provider,
)
from tests.conftest import FakeHTTP, FakeResponse

CTX = BriefingContext(uf="RO", state_name="Rondônia", praca_name="Vilhena", ref_date="2026-11-20",
                      boi_price=300.0, boi_change_day_pct=0.5, boi_change_week_pct=1.5,
                      schedule_days=4.0, supply_level="restrita", weather_title="Melhora de pastagem",
                      weather_precip_mm=80, weather_bias="alta",
                      headlines=[{"title": "Arroba sobe", "sentiment": "positivo", "uf": "RO"}])

LLM_TEXT = "🐂 linha 1\n🏭 linha 2\n🌦️ linha 3\n📰 linha 4\n🎯 linha 5\nlinha 6 extra"


def test_rules_when_no_key():
    res = generate_briefing(CTX, {"AI_PROVIDER": "auto"})
    assert res.provider == "rules" and res.fallback_reason is None
    assert "R$ 300,00" in res.content and "Viés de alta" in res.content
    assert 4 <= len(res.content.splitlines()) <= 5


def test_auto_prefers_gemini_then_openai():
    assert isinstance(resolve_provider({"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o"}), GeminiProvider)
    assert isinstance(resolve_provider({"OPENAI_API_KEY": "o"}), OpenAIProvider)
    assert resolve_provider({"AI_PROVIDER": "gemini"}) is None  # sem chave


def test_gemini_success_is_trimmed_to_five_lines():
    http = FakeHTTP({"generativelanguage": FakeResponse(
        {"candidates": [{"content": {"parts": [{"text": LLM_TEXT}]}}]})})
    res = generate_briefing(CTX, {"GEMINI_API_KEY": "k"}, http=http)
    assert res.provider == "gemini" and len(res.content.splitlines()) == 5
    assert http.calls[0][1]["headers"]["x-goog-api-key"] == "k"


def test_openai_error_falls_back_to_rules():
    http = FakeHTTP({"chat/completions": FakeResponse({"error": "quota"}, status=429)})
    res = generate_briefing(CTX, {"OPENAI_API_KEY": "k"}, http=http)
    assert res.provider == "rules" and "429" in res.fallback_reason


def test_ollama_response_parsing():
    http = FakeHTTP({"/api/chat": FakeResponse({"message": {"content": LLM_TEXT}})})
    res = generate_briefing(CTX, {"AI_PROVIDER": "ollama", "OLLAMA_BASE_URL": "http://x:11434"}, http=http)
    assert res.provider == "ollama"
