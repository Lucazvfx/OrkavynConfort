"""Classificação de notícias por regras: Região (UF), Categoria e Sentimento.

Por que regras e não LLM: roda a custo zero em cada coleta, é determinístico e
auditável. Limitação conhecida: léxico não entende negação nem ironia
("arroba NÃO deve subir" conta como positivo). O sentimento é do ponto de vista
de PREÇO PARA O PECUARISTA (alta da @ = positivo; alta de oferta = negativo).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..utils import normalize_text

# ---------------------------------------------------------------------------
# Região: termos (já sem acento) que apontam para cada UF. Peso 2 = termo forte.
# ---------------------------------------------------------------------------
UF_TERMS: dict[str, dict[str, int]] = {
    "MS": {"mato grosso do sul": 3, "sul-mato-grossense": 3, "campo grande": 2, "dourados": 2,
           "tres lagoas": 2, "famasul": 2, "acrissul": 2, "navirai": 1},
    "MT": {"mato grosso": 3, "mato-grossense": 3, "cuiaba": 2, "pontes e lacerda": 3, "caceres": 2,
           "rondonopolis": 2, "barra do garcas": 2, "juina": 2, "sinop": 1, "agua boa": 1,
           "imea": 3, "acrimat": 3, "famato": 3, "vale do guapore": 1},
    "RO": {"rondonia": 3, "porto velho": 2, "vilhena": 3, "ji-parana": 2, "ariquemes": 2,
           "cacoal": 2, "rolim de moura": 2, "idaron": 3, "faperon": 3},
    "PA": {"para": 0, "paraense": 3, "maraba": 3, "redencao": 2, "xinguara": 2,
           "sao felix do xingu": 3, "paragominas": 2, "adepara": 3, "faepa": 3},
    "TO": {"tocantins": 3, "tocantinense": 3, "araguaina": 3, "gurupi": 2, "palmas": 1, "adapec": 3},
    "GO": {"goias": 3, "goiano": 2, "goiania": 2, "rio verde": 1, "jatai": 1, "faeg": 3, "agrodefesa": 3},
    "SP": {"sao paulo": 1, "paulista": 2, "aracatuba": 3, "presidente prudente": 2, "barretos": 2,
           "sao jose do rio preto": 2, "faesp": 3},
}
# "Pará" sem acento ("para") é preposição — só casamos a forma acentuada no texto original.
_PARA_ACCENTED = re.compile(r"\bpar[áa]\b(?!\s+(?:o|a|os|as|que)\b)", re.IGNORECASE)
_PARA_STRICT = re.compile(r"\bPará\b")

CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "pecuaria_corte": ("boi gordo", "boi", "boiada", "arroba", "@", "frigorifico", "abate", "bezerro", "reposicao",
                       "escala", "confinamento", "novilha", "vaca gorda", "boi china", "pecuaria",
                       "rebanho", "gado", "carne bovina"),
    "graos": ("milho", "soja", "farelo", "safra", "safrinha", "plantio", "colheita", "grao"),
    "clima": ("chuva", "seca", "estiagem", "la nina", "el nino", "frente fria", "geada",
              "previsao do tempo", "temperatura", "queimada", "veranico"),
    "mercado_externo": ("exportac", "embarque", "china", "chines", "tarifa", "secex",
                        "importac", "habilitac", "mercado externo", "estados unidos", "eua"),
    "sanidade": ("aftosa", "vacinac", "vaca louca", "eeb", "brucelose", "tuberculose",
                 "sanidade", "defesa agropecuaria", "raiva", "surto", "rastreabilidade"),
    "politica_economia": ("governo", "ministerio", "mapa ", "credito rural", "plano safra", "juros",
                          "selic", "imposto", "icms", "funrural", "congresso", "dolar", "cambio"),
}

# Bigramas primeiro (removidos do texto antes dos unigramas) para evitar
# que "alta oferta" conte como "alta".
SENTIMENT_PHRASES: dict[str, int] = {
    "alta oferta": -1, "oferta elevada": -1, "oferta maior": -1, "aumento da oferta": -1,
    "escalas alongadas": -1, "escala alongada": -1, "escalas longas": -1, "escalas confortaveis": -1,
    "oferta restrita": 1, "oferta curta": 1, "oferta escassa": 1, "escalas curtas": 1,
    "escalas apertadas": 1, "escala curta": 1, "retencao de femeas": 1, "retencao de matrizes": 1,
    "abate de femeas recua": 1, "abate de femeas": -1, "descarte de matrizes": -1,
    "novos mercados": 1, "abertura de mercado": 1,
    "reposicao elevado": -1, "reposicao cara": -1, "relacao de troca piora": -1,
    "relacao de troca melhora": 1,
}
POSITIVE_TERMS = ("alta", "sobe", "subiu", "valoriza", "valorizacao", "recorde", "aquecid", "firme",
                  "firmeza", "avanca", "avanco", "recupera", "otimis", "habilita", "demanda forte",
                  "reajuste", "ganho", "favoravel", "melhora")
NEGATIVE_TERMS = ("queda", "cai ", "caiu", "recua", "recuo", "baixa", "desvaloriz", "pressao",
                  "embargo", "suspend", "suspensao", "prejuizo", "crise", "surto", "foco de",
                  "pessimis", "retrai", "retracao", "perda", "desaba", "fraca", "fraco", "risco",
                  "restricao", "barreira", "preocupa", "alerta", "piora", "atrasa", "veranico",
                  "estiagem", "aperta")


@dataclass(frozen=True)
class Classification:
    uf: str
    category: str
    sentiment: str
    sentiment_score: float


def _count(text: str, term: str) -> int:
    if term == "@":
        return text.count("@")
    if term.endswith(" ") or len(term) <= 4:
        # termos curtos/terminados em espaço: exige fronteira de palavra
        return len(re.findall(rf"\b{re.escape(term.strip())}\b", text))
    return text.count(term)


def detect_uf(raw_text: str) -> str:
    text = normalize_text(raw_text)
    scores: dict[str, int] = {}
    for uf, terms in UF_TERMS.items():
        score = 0
        for term, weight in terms.items():
            if weight == 0:
                continue
            hits = len(re.findall(rf"\b{re.escape(term)}\b", text))
            score += hits * weight
        scores[uf] = score
    # "Mato Grosso do Sul" contém "mato grosso": descontamos o falso positivo de MT.
    ms_full = len(re.findall(r"\bmato grosso do sul\b", text))
    scores["MT"] -= ms_full * UF_TERMS["MT"]["mato grosso"]
    # Pará: apenas forma acentuada e com P maiúsculo no texto original.
    scores["PA"] += len(_PARA_STRICT.findall(raw_text or "")) * 3

    best_uf, best = max(scores.items(), key=lambda kv: kv[1])
    return best_uf if best >= 2 else "BR"


def detect_category(raw_text: str) -> str:
    text = normalize_text(raw_text)
    scores = {cat: sum(_count(text, t) for t in terms) for cat, terms in CATEGORY_TERMS.items()}
    best_cat, best = max(scores.items(), key=lambda kv: kv[1])
    return best_cat if best > 0 else "geral"


def detect_sentiment(raw_text: str) -> tuple[str, float]:
    text = f" {normalize_text(raw_text)} "
    pos = neg = 0
    for phrase, polarity in SENTIMENT_PHRASES.items():
        hits = text.count(phrase)
        if hits:
            if polarity > 0:
                pos += hits * 2
            else:
                neg += hits * 2
            text = text.replace(phrase, " ")
    pos += sum(_count(text, t) for t in POSITIVE_TERMS)
    neg += sum(_count(text, t) for t in NEGATIVE_TERMS)
    total = pos + neg
    if total == 0:
        return "neutro", 0.0
    score = round((pos - neg) / total, 2)
    if score >= 0.2:
        return "positivo", score
    if score <= -0.2:
        return "negativo", score
    return "neutro", score


def classify(title: str, summary: str | None = None) -> Classification:
    # Título pesa o dobro: resumos de RSS costumam trazer ruído (tags, "leia mais").
    text = f"{title}. {title}. {summary or ''}"
    sentiment, score = detect_sentiment(text)
    return Classification(uf=detect_uf(text), category=detect_category(text),
                          sentiment=sentiment, sentiment_score=score)
