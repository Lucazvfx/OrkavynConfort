# AgroRadar

Hub de inteligência pecuária por estado/praça (RO, MT, MS, GO, SP, PA, TO).

> **Status: 3 etapas concluídas** — backend, API, admin, agendador e frontend.
> Painel em `/`, administração em `/admin/`.

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
    web_routes.py        página do painel
  templates/             base.html, index.html (painel), admin/index.html
  static/
    css/app.css          tokens (eucalipto, vidro, tipografia) e componentes
    js/common.js         formatação pt-BR, fetch, criação segura de DOM
    js/dashboard.js      módulos A–H, mapa SVG clicável, gráficos Chart.js
    js/admin.js          login, cadastro do dia, B3, jobs, situação dos dados
    js/brazil-map.js     geometria das UFs (CC BY 4.0)
    vendor/, fonts/      Chart.js, Tailwind (build browser) e Schibsted Grotesk locais
seed.py                  dados de demonstração
run.py / wsgi.py         entradas dev / produção (sobem o agendador)
tests/                   testes offline
```

## Origem dos dados — leia antes de confiar em um número

| Módulo | Fonte automatizada | Realidade |
|---|---|---|
| Boi gordo SP, bezerro MS, milho Campinas | **Cepea/Esalq-USP** (`cepea_service.py`, dias úteis 18:30) | Licença CC BY-NC 4.0: citar a fonte, **uso não comercial**. Um indicador de referência por produto, não por praça. Site com Cloudflare: 1 requisição por indicador por dia. |
| Arroba nas demais praças, vaca, boi China, escalas, oferta, farelo | **nenhuma** | Sem fonte gratuita que permita reuso (Agrolink proíbe robôs e reprodução nos termos de uso; Scot/Datagro são pagos). Entrada manual no `/admin`. A API marca `freshness.stale` após 3 dias úteis sem cotação. |
| B3 (BGI) | **nenhuma** | A B3 não oferece API gratuita de ajustes; manual ou feed pago. |
| Abate de fêmeas | IBGE SIDRA (tab. 1092) | Gratuito; defasagem de ~2,5 meses. |
| Clima | Open-Meteo | Gratuito, sem chave. |
| Notícias | RSS dos portais | URLs dos feeds **não validadas** neste ambiente (rede bloqueada); ajuste via `RSS_FEEDS`. |

Tudo que o `seed.py` gera tem `source="seed"` e é **ilustrativo**, não cotação real.

## Frontend

- Sem dependência de CDN: Chart.js, Tailwind e a fonte são servidos de `static/` (funciona em rede restrita de fazenda e não quebra se um CDN cair). Licenças em `static/vendor/LICENSES.md`.
- Cores dos gráficos validadas para daltonismo (boi gordo azul, vaca laranja, China verde-água). O eucalipto `#54776c` é cor de interface: como cor de série ele fica acinzentado demais ao lado das outras.
- Mapa de escalas: vermelho (< 5 dias), âmbar (5–8) e **azul** (> 8). Azul em vez de verde evita o par vermelho/verde, indistinguível para ~8% dos homens. Cada estado tem o número escrito sobre ele e há tabela equivalente.
- Texto de RSS nunca é inserido como HTML (sem risco de XSS por feed malicioso).
- `Copiar para WhatsApp` usa a área de transferência; `Abrir no WhatsApp` abre `wa.me` com o texto pronto.

## Deploy (Vercel + Supabase)

- Entrada: `wsgi.py` (a Vercel detecta o Flask por ele); agendamentos em `vercel.json` (região `gru1`, São Paulo).
- Banco: Postgres do Supabase no schema `agroradar` (`DB_SCHEMA=agroradar`), conexão pelo pooler em modo transação.
  O app usa `NullPool` e desliga prepared statements, exigência desse modo.
- Agendamento: Vercel Cron chama `/api/cron/<job>` com `Authorization: Bearer $CRON_SECRET`.
  No plano Hobby cada cron roda no máximo 1x/dia e o horário pode variar dentro da hora:
  clima ~05:20, notícias ~05:40, boletim ~06:00 (Brasília), IBGE às segundas. Notícias de hora em hora exigem plano Pro
  ou um agendador externo chamando o mesmo endpoint.
- `AUTO_SEED_DEMO=true` popula dados de demonstração no primeiro start se o banco estiver vazio.

| Variável | Valor |
|---|---|
| `DATABASE_URL` | Supabase → Connect → Transaction pooler (porta 6543) |
| `DB_SCHEMA` | `agroradar` |
| `SECRET_KEY`, `ADMIN_PASSWORD`, `CRON_SECRET` | segredos aleatórios |
| `AUTO_SEED_DEMO` | `true` no primeiro deploy |
