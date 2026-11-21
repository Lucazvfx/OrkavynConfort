# AgroRadar

Hub de inteligência pecuária por estado/praça (RO, MT, MS, GO, SP, PA, TO).

> **Status: Etapa 1 de 3** — schema, seed e serviços de backend.
> Etapa 2: rotas Flask, cálculos (relação de troca, basis, ciclo, simulador) e APScheduler.
> Etapa 3: frontend (Tailwind, mapa de calor, Chart.js, `/admin`).

## Rodando

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # ajuste ADMIN_PASSWORD e, opcionalmente, chaves de IA
python seed.py --reset        # dados de demonstração para todos os módulos
python seed.py --reset --live # idem + tenta Open-Meteo, IBGE SIDRA e RSS reais
python -m pytest -q           # 22 testes, todos offline (APIs simuladas)
python run.py                 # http://localhost:5000/healthz
```

## Estrutura

```
app/
  __init__.py            application factory (create_app)
  config.py              configuração via .env
  extensions.py          instância do SQLAlchemy
  models.py              schema completo (11 tabelas)
  utils.py               datas UTC, dias úteis, normalização de texto
  data/
    pracas.py            praças (lat/lon) e metadados das UFs/códigos IBGE
    b3.py                códigos de vencimento BGI (F,G,H…Z) e rolagem
  services/
    rss_collector.py     coleta RSS → dedupe → classificação → news_articles
    news_classifier.py   UF / categoria / sentimento por regras
    weather_service.py   Open-Meteo (1 chamada p/ todas as praças) + regra de oferta
    ibge_service.py      SIDRA tabela 1092 → % fêmeas no abate + termômetro do ciclo
    ai_service.py        Gemini / OpenAI(-compatível) / Ollama + fallback por regras
    briefing_service.py  orquestra o Boletim das 6h → daily_briefings
    market_queries.py    consultas reutilizáveis (último preço, variações, curva B3)
    job_log.py           registra cada execução em job_runs
    http.py              sessão requests com retry/backoff
  routes/                (Etapa 2) api_routes.py, admin_routes.py
  templates/, static/    (Etapa 3)
seed.py                  dados de demonstração
tests/                   testes offline
```

## Origem dos dados — leia antes de confiar em um número

| Módulo | Fonte automatizada | Realidade |
|---|---|---|
| Arroba (boi/vaca/China), escalas, oferta | **nenhuma** | Não há API pública gratuita (Scot, IMEA, Datagro, Agrifatto são pagos ou sem API). Entrada manual no `/admin` (Etapa 2). |
| Bezerro, milho, farelo | **nenhuma** | Idem — manual. |
| B3 (BGI) | **nenhuma** | A B3 não oferece API gratuita de ajustes; manual ou feed pago. |
| Abate de fêmeas | IBGE SIDRA (tab. 1092) | Gratuito; defasagem de ~2,5 meses. |
| Clima | Open-Meteo | Gratuito, sem chave. |
| Notícias | RSS dos portais | URLs dos feeds **não validadas** neste ambiente (rede bloqueada); ajuste via `RSS_FEEDS`. |

Tudo que o `seed.py` gera tem `source="seed"` e é **ilustrativo**, não cotação real.
