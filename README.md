# AgroRadar

Hub de inteligência pecuária por estado/praça (RO, MT, MS, GO, SP, PA, TO).

> **Status: Etapa 2 de 3** — backend completo (API, admin, cálculos, agendador).
> Etapa 3: frontend (Tailwind, mapa de calor, Chart.js, telas do `/admin`).

## Rodando

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # ajuste ADMIN_PASSWORD e, opcionalmente, chaves de IA
python seed.py --reset        # dados de demonstração para todos os módulos
python seed.py --reset --live # idem + tenta Open-Meteo, IBGE SIDRA e RSS reais
python -m pytest -q           # testes offline (APIs externas simuladas)
python run.py                 # dev: API + agendador em http://localhost:5000
gunicorn -w 2 wsgi:app        # produção (lock garante 1 agendador entre workers)
flask --app run jobs run rss  # roda um job na mão (rss | weather | ibge | briefing)
```

## API (`/api`, somente leitura)

| Rota | Módulo |
|---|---|
| `GET /api/pracas` | praças agrupadas por UF |
| `GET /api/dashboard?praca=RO_VILHENA` | tudo abaixo em uma chamada |
| `GET /api/kpis?praca=` | A — arroba boi/vaca/China (dia/semana), escala + semáforo, oferta, tendência, frescor do dado |
| `GET /api/trade?praca=` | B — bezerro (@/bezerro, bezerros/boi 18@), milho e farelo (sacas 60 kg/@) vs. média histórica |
| `GET /api/cycle?uf=MT` | C — % fêmeas no abate, fase do ciclo, variação anual |
| `GET /api/briefing?uf=` · `/api/briefings` | D — Boletim das 6h |
| `GET /api/weather?praca=` | E — chuva 15 dias e alerta de oferta |
| `GET /api/heatmap` | F — escala média por UF com cores |
| `GET /api/futures?praca=` | G — curva BGI, basis R$/% e basis vs. média de 60 dias |
| `POST /api/simulator` | H — segurar vs. vender (sem preço de venda, projeta B3 do mês + basis) |
| `GET /api/news?uf=&category=&sentiment=&q=&page=` | H — feed filtrável |
| `GET /api/history?praca=&days=90` | séries para gráficos |

## Admin (`/admin`, JSON)

`POST /admin/login {password}` devolve `csrf_token`; todo POST seguinte exige o header `X-CSRF-Token`.

`/admin/api/quotes/cattle`, `/quotes/inputs`, `/schedules`, `/futures`, `/female-slaughter`,
`/pracas/<code>/toggle`, `/jobs/<nome>/run`, `GET /admin/api/status` (frescor por praça, últimas execuções, próximos jobs).
Valores fora de faixas plausíveis (ex.: arroba 3100) são rejeitados com 422.

## Agenda (America/Sao_Paulo)

RSS de hora em hora 05h–22h · clima 05:20 · RSS 05:40 · **boletim 06:00** · IBGE segunda 07:00.
06h de Brasília = 05h em RO — ajuste `BRIEFING_HOUR` se o público principal for RO.

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
    calculations.py      KPIs, relação de troca, basis, ciclo, mapa, simulador
    jobs.py              registro único de jobs (agendador, admin, CLI)
  routes/
    api_routes.py        API pública
    admin_routes.py      login, CSRF, entrada manual, disparo de jobs
  scheduler.py           APScheduler + lock de processo único
  templates/, static/    (Etapa 3)
seed.py                  dados de demonstração
run.py / wsgi.py         entradas dev / produção (sobem o agendador)
tests/                   testes offline
```

## Origem dos dados — leia antes de confiar em um número

| Módulo | Fonte automatizada | Realidade |
|---|---|---|
| Arroba (boi/vaca/China), escalas, oferta | **nenhuma** | Não há API pública gratuita (Scot, IMEA, Datagro, Agrifatto são pagos ou sem API). Entrada manual no `/admin`. A API marca `freshness.stale` após 3 dias úteis sem cotação. |
| Bezerro, milho, farelo | **nenhuma** | Idem — manual. |
| B3 (BGI) | **nenhuma** | A B3 não oferece API gratuita de ajustes; manual ou feed pago. |
| Abate de fêmeas | IBGE SIDRA (tab. 1092) | Gratuito; defasagem de ~2,5 meses. |
| Clima | Open-Meteo | Gratuito, sem chave. |
| Notícias | RSS dos portais | URLs dos feeds **não validadas** neste ambiente (rede bloqueada); ajuste via `RSS_FEEDS`. |

Tudo que o `seed.py` gera tem `source="seed"` e é **ilustrativo**, não cotação real.
