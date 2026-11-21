from app.services.news_classifier import classify, detect_uf


def test_ms_is_not_counted_as_mt():
    assert detect_uf("Arroba sobe em Mato Grosso do Sul") == "MS"
    assert detect_uf("IMEA: arroba sobe em Mato Grosso") == "MT"


def test_para_preposition_is_not_state():
    assert detect_uf("Exportação para a China cresce") == "BR"
    assert detect_uf("Abate cresce no Pará") == "PA"


def test_city_detection():
    assert detect_uf("Escalas curtas em Vilhena") == "RO"
    assert detect_uf("Boi firme em Araguaína") == "TO"


def test_sentiment_bigram_overrides_unigram():
    # "alta oferta" é negativo para preço, apesar de conter "alta"
    c = classify("Alta oferta de boiadas pressiona frigoríficos")
    assert c.sentiment == "negativo"
    assert classify("Arroba sobe com escalas curtas").sentiment == "positivo"
    assert classify("Reunião técnica marcada para terça").sentiment == "neutro"


def test_category():
    assert classify("Preço do milho recua com colheita").category == "graos"
    assert classify("Surto de aftosa em país vizinho").category == "sanidade"
    assert classify("Boi gordo sobe no frigorífico").category == "pecuaria_corte"
