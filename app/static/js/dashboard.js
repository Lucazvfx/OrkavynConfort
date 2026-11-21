/* AgroRadar — painel. Lê /api/* e desenha os módulos A–H. */
(function () {
  "use strict";
  const { fmt, el, api, toast, whatsappLine } = window.AR;
  const $ = (id) => document.getElementById(id);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  const state = { praca: null, uf: null, days: 90, newsPage: 1, heatmap: null, briefingText: "", charts: {} };

  const CATEGORY_LABELS = {
    pecuaria_corte: "Pecuária de corte", mercado_externo: "Mercado externo", graos: "Grãos e insumos",
    clima: "Clima", sanidade: "Sanidade", politica_economia: "Política e economia", geral: "Geral",
  };
  const PROVIDERS = { rules: "motor de regras", gemini: "Gemini", openai: "OpenAI", ollama: "Ollama" };
  const SOURCE_LABELS = { cepea: "Cepea/Esalq-USP", manual: "cadastro manual", seed: "demonstração" };
  const sourceLabel = (src) => SOURCE_LABELS[src] || src || "";
  const SCHED_COLOR = { red: "--esc-curta", yellow: "--esc-conf", green: "--esc-longa" };

  // ------------------------------------------------------------------ Chart.js
  Chart.defaults.font.family = css("--font");
  Chart.defaults.font.size = 12;
  Chart.defaults.color = css("--ink-3");
  Chart.defaults.borderColor = "rgba(29,43,39,.07)";
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.animation.duration = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 400;
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: "rgba(255,255,255,.96)", titleColor: css("--ink"), bodyColor: css("--ink-2"),
    borderColor: "rgba(29,43,39,.12)", borderWidth: 1, padding: 10, cornerRadius: 10,
    titleFont: { weight: "700" }, boxPadding: 4, usePointStyle: true,
  });

  /** Rótulo direto no fim de cada linha (identidade nunca só por cor). */
  const endLabels = {
    id: "endLabels",
    afterDatasetsDraw(chart, _a, opts) {
      if (!opts || !opts.enabled) return;
      const { ctx } = chart;
      ctx.save();
      ctx.font = `600 12px ${css("--font")}`;
      ctx.fillStyle = css("--ink-2");
      ctx.textBaseline = "middle";
      const placed = [];
      chart.data.datasets.forEach((ds, i) => {
        const meta = chart.getDatasetMeta(i);
        if (meta.hidden || !meta.data.length) return;
        const pt = [...meta.data].reverse().find((p) => !p.skip);
        if (!pt) return;
        let y = pt.y;
        for (const py of placed) if (Math.abs(py - y) < 14) y = py + (y >= py ? 14 : -14);
        placed.push(y);
        ctx.fillText(ds.label, pt.x + 8, y);
      });
      ctx.restore();
    },
  };

  /** Linhas/faixas de referência horizontais. */
  const refLines = {
    id: "refLines",
    beforeDatasetsDraw(chart, _a, opts) {
      const { ctx, chartArea: a, scales: { y } } = chart;
      if (!opts || !y) return;
      ctx.save();
      (opts.bands || []).forEach((b) => {
        const top = y.getPixelForValue(Math.min(b.to, y.max)), bot = y.getPixelForValue(Math.max(b.from, y.min));
        ctx.fillStyle = b.color; ctx.fillRect(a.left, top, a.right - a.left, bot - top);
        ctx.fillStyle = css("--ink-3"); ctx.font = `600 11px ${css("--font")}`; ctx.textAlign = "right";
        ctx.fillText(b.label, a.right - 6, top + 13);
      });
      (opts.lines || []).forEach((l) => {
        const py = y.getPixelForValue(l.y);
        ctx.strokeStyle = l.color || css("--ink-3"); ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(a.left, py); ctx.lineTo(a.right, py); ctx.stroke(); ctx.setLineDash([]);
        if (l.label) {
          ctx.fillStyle = css("--ink-2"); ctx.font = `600 11px ${css("--font")}`; ctx.textAlign = "left";
          ctx.fillText(l.label, a.left + 6, py - 6);
        }
      });
      ctx.restore();
    },
  };
  Chart.register(endLabels, refLines);

  function upsertChart(key, canvasId, config) {
    if (state.charts[key]) state.charts[key].destroy();
    state.charts[key] = new Chart($(canvasId), config);
    return state.charts[key];
  }

  const lineDs = (label, data, color, extra = {}) => ({
    label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0,
    pointHoverRadius: 5, pointHoverBorderWidth: 2, pointHoverBorderColor: "#fff", tension: 0.25, spanGaps: true, ...extra,
  });

  // ------------------------------------------------------------------ boot
  async function boot() {
    const [{ states }, heat] = await Promise.all([api("/api/pracas"), api("/api/heatmap")]);
    state.heatmap = heat;
    const select = $("praca-select");
    states.forEach((s) => {
      const group = el("optgroup", { label: s.name });
      s.pracas.forEach((p) => group.append(el("option", { value: p.code, text: `${p.name} (${p.uf})` })));
      select.append(group);
    });
    const fromUrl = new URLSearchParams(location.search).get("praca");
    const all = states.flatMap((s) => s.pracas.map((p) => p.code));
    const saved = localStorage.getItem("ar.praca");
    const reference = (states[0].pracas.find((p) => p.is_state_reference) || states[0].pracas[0]).code;
    state.praca = all.includes(fromUrl) ? fromUrl : all.includes(saved) ? saved : reference;
    select.value = state.praca;
    select.addEventListener("change", () => selectPraca(select.value));
    renderMap();
    wireStatic();
    await loadDashboard();
  }

  function selectPraca(code) {
    if (!code || code === state.praca) return;
    state.praca = code;
    $("praca-select").value = code;
    localStorage.setItem("ar.praca", code);
    history.replaceState(null, "", `?praca=${encodeURIComponent(code)}`);
    loadDashboard();
  }

  async function loadDashboard() {
    try {
      const d = await api(`/api/dashboard?praca=${encodeURIComponent(state.praca)}`);
      state.uf = d.praca.uf;
      renderHero(d); renderNotices(d); renderBriefing(d); renderKpis(d);
      renderTrade(d.trade); renderCycle(d.cycle); renderWeather(d.weather); renderB3(d.futures);
      markMapSelection();
      $("app").classList.remove("loading");
      await Promise.all([loadHistory(), loadNews(true)]);
    } catch (err) {
      $("notices").replaceChildren(el("div", { class: "notice", role: "alert" },
        `Não foi possível carregar o painel: ${err.message}. Verifique se o servidor está rodando e se o seed foi executado.`));
    }
  }

  // ------------------------------------------------------------------ A: hero + KPIs
  function changeChip(v, suffix) {
    if (v == null) return el("span", { class: "chip", text: `sem dado ${suffix}` });
    const up = v > 0, down = v < 0;
    return el("span", { class: `chip ${up ? "chip-up" : down ? "chip-down" : ""}` },
      el("span", { "aria-hidden": "true", text: up ? "▲" : down ? "▼" : "■" }), `${fmt.pct(v)} ${suffix}`);
  }

  function renderHero(d) {
    const { praca, state: st, kpis } = d;
    $("hero-place").textContent = `${praca.name}, ${st.name}`;
    $("hero-region").textContent = praca.region || "";
    const boi = kpis.prices.boi_gordo;
    $("hero-price").textContent = boi.price == null ? "Sem cotação" : fmt.brl(boi.price);
    $("hero-changes").replaceChildren(changeChip(boi.change_day_pct, "hoje"), changeChip(boi.change_week_pct, "na semana"),
      el("span", { class: "small muted", text: boi.date ? `cotação de ${fmt.date(boi.date)}, fonte: ${sourceLabel(boi.source)}` : "" }));
    const t = kpis.trend;
    const word = { alta: "Tendência de alta", baixa: "Tendência de baixa", lateral: "Mercado de lado" }[t.direction];
    $("hero-trend").textContent = `${word} nos próximos dias: ${t.drivers.join(", ")}.`;

    const other = (cat) => {
      const p = kpis.prices[cat];
      return el("div", {}, el("dt", { class: "small muted", text: p.label }),
        el("dd", { class: "figure text-2xl mt-0.5" }, fmt.brl(p.price),
          el("span", { class: "small muted font-normal ml-2", text: p.change_week_pct == null ? "" : `${fmt.pct(p.change_week_pct)} na semana` })));
    };
    $("hero-others").replaceChildren(other("vaca_gorda"), other("boi_china"));
  }

  function renderNotices(d) {
    const box = $("notices");
    box.replaceChildren();
    const k = d.kpis;
    if (k.is_demo) box.append(el("div", { class: "notice" }, el("span", { "aria-hidden": "true", text: "ⓘ" }),
      el("span", {}, "Você está vendo dados de demonstração. Cadastre cotações reais no ", el("a", { href: "/admin/", class: "underline font-semibold", text: "Admin" }), ".")));
    if (k.freshness.stale) box.append(el("div", { class: "notice", role: "alert" }, el("span", { "aria-hidden": "true", text: "!" }),
      el("span", { text: k.freshness.last_date
        ? `A última cotação de ${d.praca.name} é de ${fmt.date(k.freshness.last_date)} (${k.freshness.business_days_old} dias úteis). Atualize no Admin.`
        : `${d.praca.name} ainda não tem cotação cadastrada. Cadastre no Admin.` })));
  }

  function renderKpis(d) {
    const s = d.kpis.schedule;
    $("kpi-escala").textContent = fmt.num(s.days_ahead);
    $("kpi-pin").style.left = `${Math.min(Math.max((s.days_ahead || 0) / 12, 0), 1) * 100}%`;
    $("kpi-escala-label").replaceChildren(el("span", { class: "dot", style: `background:var(${SCHED_COLOR[s.color] || "--ink-3"})` }), ` ${s.label}`,
      s.plants_surveyed ? el("span", { class: "muted", text: ` (${s.plants_surveyed} frigoríficos consultados)` }) : null);
    $("kpi-escala-label").className = "small mt-2 flex items-center gap-1.5 flex-wrap";

    const supply = d.kpis.supply.level;
    $("kpi-oferta").textContent = supply || "sem dado";
    $("kpi-oferta-note").textContent = {
      restrita: "Pouco boi terminado ofertado: indústria disputa lotes.",
      equilibrada: "Oferta e demanda dos frigoríficos em equilíbrio.",
      ampla: "Muito boi ofertado: comprador com poder de barganha.",
    }[supply] || "";

    const t = d.kpis.trend;
    $("kpi-trend").replaceChildren(el("span", { "aria-hidden": "true", text: { alta: "▲ ", baixa: "▼ ", lateral: "▶ " }[t.direction] }),
      { alta: "Alta", baixa: "Baixa", lateral: "Lateral" }[t.direction]);
    $("kpi-drivers").replaceChildren(...t.drivers.map((x) => el("li", { text: x })));
  }

  // ------------------------------------------------------------------ D: boletim
  function renderBriefing(d) {
    const b = d.briefing, body = $("briefing-body");
    const copy = $("copy-briefing"), share = $("share-briefing");
    if (!b) {
      body.replaceChildren(el("p", { class: "muted", text: "Ainda não há boletim para este estado. Ele é gerado todo dia às 6h ou pelo Admin." }));
      $("briefing-meta").textContent = "";
      copy.disabled = true; share.setAttribute("aria-disabled", "true"); share.removeAttribute("href");
      state.briefingText = "";
      return;
    }
    body.replaceChildren(...b.content.split("\n").filter(Boolean).map((line) => el("p", { class: "briefing-line" }, whatsappLine(line))));
    const when = new Date(b.generated_at + "Z");
    $("briefing-meta").textContent = `Gerado às ${fmt.time(b.generated_at)} de ${when.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} pelo ${PROVIDERS[b.provider] || b.provider}`;
    state.briefingText = `*Boletim das 6h AgroRadar: ${d.state.name}, ${fmt.date(b.date)}*\n\n${b.content}`;
    copy.disabled = false; share.removeAttribute("aria-disabled");
    share.href = `https://wa.me/?text=${encodeURIComponent(state.briefingText)}`;
  }

  async function copyBriefing() {
    if (!state.briefingText) return;
    try {
      await navigator.clipboard.writeText(state.briefingText);
    } catch (_) { // contexto sem clipboard API (http fora de localhost)
      const ta = el("textarea", { style: "position:fixed;opacity:0" }); ta.value = state.briefingText;
      document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
    }
    toast("Boletim copiado. Cole no WhatsApp.");
  }

  // ------------------------------------------------------------------ F: mapa
  function renderMap() {
    const svg = $("map"), data = window.BRAZIL_MAP;
    svg.setAttribute("viewBox", data.viewBox);
    const NS = "http://www.w3.org/2000/svg";
    const byUf = Object.fromEntries(state.heatmap.states.map((s) => [s.uf, s]));
    const labels = [];
    data.locations.forEach((loc) => {
      const info = byUf[loc.id];
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", loc.path);
      path.dataset.uf = loc.id;
      if (info && info.avg_days != null) {
        path.classList.add("active");
        path.style.fill = `var(${SCHED_COLOR[info.color] || "--ink-3"})`;
        path.setAttribute("tabindex", "0");
        path.setAttribute("role", "button");
        path.setAttribute("aria-label", `${info.name}: escala média de ${fmt.num(info.avg_days)} dias úteis, ${info.label}. Abrir ${info.default_praca}.`);
        const open = () => selectPraca(info.default_praca);
        path.addEventListener("click", open);
        path.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
        path.addEventListener("mousemove", (e) => showTip(e, info));
        path.addEventListener("mouseleave", hideTip);
        path.addEventListener("focus", (e) => showTip(e, info));
        path.addEventListener("blur", hideTip);
        labels.push([path, info]);
      } else {
        path.classList.add("inactive");
        const t = document.createElementNS(NS, "title"); t.textContent = `${loc.name}: não monitorado`; path.append(t);
      }
      svg.append(path);
    });
    labels.forEach(([path, info]) => {
      const bb = path.getBBox();
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", bb.x + bb.width / 2); t.setAttribute("y", bb.y + bb.height / 2);
      t.setAttribute("text-anchor", "middle"); t.setAttribute("dominant-baseline", "middle");
      t.textContent = `${info.uf} ${fmt.num(info.avg_days)}d`;
      svg.append(t);
    });
    $("map-legend").replaceChildren(...state.heatmap.legend.map((l) =>
      el("li", { class: "flex items-center gap-1.5" }, el("span", { class: "dot", style: `background:var(${SCHED_COLOR[l.color]})` }), l.label)));
    $("map-table").replaceChildren(...state.heatmap.states.map((s) => el("tr", {},
      el("td", {}, el("button", { class: "underline decoration-dotted", text: s.name, onclick: () => selectPraca(s.default_praca) })),
      el("td", { class: "num", text: fmt.num(s.avg_days) }), el("td", { text: s.label }))));
  }

  function showTip(e, info) {
    const tip = $("map-tip"), wrap = $("map-wrap").getBoundingClientRect();
    tip.replaceChildren(el("p", { class: "font-bold text-[var(--ink)]", text: `${info.name}: ${fmt.num(info.avg_days)} dias úteis` }),
      el("p", { class: "muted", text: info.label }),
      el("ul", { class: "mt-1" }, ...info.pracas.map((p) => el("li", { text: `${p.name}: ${fmt.num(p.days_ahead)} dias` }))));
    tip.hidden = false;
    const r = e.clientX ? { x: e.clientX, y: e.clientY } : (() => { const b = e.target.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; })();
    const x = Math.min(r.x - wrap.left + 14, wrap.width - tip.offsetWidth - 4);
    tip.style.left = `${Math.max(4, x)}px`; tip.style.top = `${r.y - wrap.top + 14}px`;
  }
  function hideTip() { $("map-tip").hidden = true; }
  function markMapSelection() {
    document.querySelectorAll("#map path").forEach((p) => p.classList.toggle("selected", p.dataset.uf === state.uf));
  }

  // ------------------------------------------------------------------ histórico de preços
  async function loadHistory() {
    const h = await api(`/api/history?praca=${encodeURIComponent(state.praca)}&days=${state.days}`);
    const dates = h.prices.boi_gordo.map((p) => p.date);
    const align = (rows) => { const m = Object.fromEntries(rows.map((r) => [r.date, r.price])); return dates.map((d) => m[d] ?? null); };
    upsertChart("history", "chart-history", {
      type: "line",
      data: {
        labels: dates.map(fmt.date),
        datasets: [
          lineDs("Boi China", align(h.prices.boi_china), css("--s-china")),
          lineDs("Boi gordo", align(h.prices.boi_gordo), css("--s-boi"), { borderWidth: 2.5 }),
          lineDs("Vaca gorda", align(h.prices.vaca_gorda), css("--s-vaca")),
        ],
      },
      options: {
        interaction: { mode: "index", intersect: false },
        layout: { padding: { right: 78 } },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 7, maxRotation: 0 } },
          y: { ticks: { callback: (v) => fmt.brl(v).replace(",00", "") }, grace: "5%" },
        },
        plugins: {
          legend: { position: "top", align: "start", labels: { usePointStyle: true, pointStyle: "line", boxWidth: 18, color: css("--ink-2") } },
          tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${fmt.brl(c.parsed.y)}` } },
          endLabels: { enabled: true },
        },
      },
    });
  }

  // ------------------------------------------------------------------ B: relação de troca
  function signalChip(sig) {
    const cls = { favoravel: "chip-up", apertada: "chip-down" }[sig.status] || "";
    const icon = { favoravel: "✓", apertada: "!", neutra: "=" }[sig.status] || "·";
    return el("span", { class: `chip ${cls}` }, el("span", { "aria-hidden": "true", text: icon }), sig.label);
  }

  function sparkline(canvas, series, avg) {
    return new Chart(canvas, {
      type: "line",
      data: { labels: series.map((p) => fmt.date(p.date)), datasets: [lineDs("Valor", series.map((p) => p.value), css("--eucalipto"), { borderWidth: 2 })] },
      options: {
        interaction: { mode: "index", intersect: false },
        scales: { x: { display: false }, y: { display: false, grace: "15%" } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${fmt.num(c.parsed.y, 2)}` } },
          refLines: { lines: avg != null ? [{ y: avg, label: "média" }] : [] } },
      },
    });
  }

  function renderTrade(t) {
    (state.charts.spark || []).forEach((c) => c.destroy());
    state.charts.spark = [];
    const grid = $("trade-grid");
    const cards = [];
    const it = t.items;
    const card = (headline, sub, item) => {
      const canvas = el("canvas", { "aria-label": "Evolução da relação de troca" });
      const avg = item.history.average;
      const node = el("article", { class: "glass p-5 flex flex-col" },
        el("p", { class: "text-lg leading-snug" }, ...headline),
        el("p", { class: "small muted mt-1", text: `${sub} Fonte: ${sourceLabel(item.source)}.` }),
        el("div", { class: "mt-3" }, signalChip(item.signal)),
        el("div", { class: "mt-3 h-16" }, canvas),
        el("p", { class: "small muted mt-2", text: avg == null ? "" :
          `Média do histórico: ${fmt.num(avg, 2)} (${item.history.observations} cotações). Hoje: ${fmt.pct(item.signal.deviation_pct)} vs. média.` }));
      cards.push([canvas, item.series, avg]);
      return node;
    };
    const nodes = [];
    if (it.bezerro) nodes.push(card(["1 boi de 18@ compra ", el("strong", { class: "figure text-3xl", text: fmt.num(it.bezerro.calves_per_boi_18, 2) }), " bezerros"],
      `Bezerro a ${fmt.brl(it.bezerro.price)} por cabeça, ou ${fmt.num(it.bezerro.arrobas_per_calf)}@ de boi gordo.`, it.bezerro));
    if (it.milho) nodes.push(card(["1 arroba paga ", el("strong", { class: "figure text-3xl", text: fmt.num(it.milho.sacks60_per_arroba) }), " sacas de milho"],
      `Saca de 60 kg a ${fmt.brl(it.milho.price)}.`, it.milho));
    if (it.farelo_soja) nodes.push(card(["1 arroba paga ", el("strong", { class: "figure text-3xl", text: `${fmt.num(it.farelo_soja.kg_per_arroba, 0)} kg` }), " de farelo de soja"],
      `Tonelada a ${fmt.brl(it.farelo_soja.price)} (${fmt.num(it.farelo_soja.sacks60_per_arroba)} sacas de 60 kg por @).`, it.farelo_soja));
    grid.replaceChildren(...(nodes.length ? nodes : [el("p", { class: "muted", text: "Sem cotações de bezerro, milho ou farelo para esta praça. Cadastre no Admin." })]));
    cards.forEach(([c, s, a]) => state.charts.spark.push(sparkline(c, s, a)));
  }

  // ------------------------------------------------------------------ C: ciclo
  function renderCycle(c) {
    const latest = c.latest;
    $("cycle-share").textContent = latest ? `${fmt.num(latest.female_share)}%` : "—";
    const phase = c.interpretation;
    const phaseCls = { liquidacao: "chip-down", retencao: "chip-up", equilibrio: "chip-warn" }[phase.phase] || "";
    $("cycle-phase").className = `chip ${phaseCls}`;
    $("cycle-phase").textContent = phase.label;
    $("cycle-yoy").textContent = latest ? `${latest.label}, ${fmt.pp(c.yoy_change_pp)} vs. um ano antes` : "";
    $("cycle-msg").textContent = phase.message;
    $("cycle-sub").textContent = c.fallback_to_br
      ? "Sem dados do estado: mostrando Brasil (IBGE, trimestral)."
      : "Participação de fêmeas no abate total (IBGE, trimestral). O dado sai cerca de 75 dias após o trimestre.";

    const base = c.series.length ? c.series : c.brazil_series;
    const labels = base.map((r) => r.label);
    const br = Object.fromEntries(c.brazil_series.map((r) => [r.label, r.female_share]));
    const datasets = [lineDs(c.fallback_to_br ? "Brasil" : c.uf, base.map((r) => r.female_share), css("--s-boi"), { pointRadius: 3, borderWidth: 2.5 })];
    if (!c.fallback_to_br) datasets.push(lineDs("Brasil", labels.map((l) => br[l] ?? null), css("--ink-3"), { borderDash: [5, 4], borderWidth: 2 }));
    upsertChart("cycle", "chart-cycle", {
      type: "line",
      data: { labels, datasets },
      options: {
        interaction: { mode: "index", intersect: false },
        layout: { padding: { right: 48 } },
        scales: { x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
          y: { suggestedMin: 34, suggestedMax: 50, ticks: { callback: (v) => `${v}%` } } },
        plugins: {
          legend: { display: datasets.length > 1, position: "top", align: "start", labels: { usePointStyle: true, pointStyle: "line", boxWidth: 18, color: css("--ink-2") } },
          tooltip: { callbacks: { label: (x) => ` ${x.dataset.label}: ${fmt.num(x.parsed.y)}% de fêmeas` } },
          endLabels: { enabled: datasets.length > 1 },
          refLines: { bands: [
            { from: 45, to: 100, color: "rgba(214,69,61,.08)", label: "Liquidação de matrizes (> 45%)" },
            { from: 0, to: 40, color: "rgba(27,175,122,.10)", label: "Retenção de fêmeas (< 40%)" },
          ] },
        },
      },
    });
  }

  // ------------------------------------------------------------------ E: clima
  function renderWeather(w) {
    if (!w) {
      $("weather-mm").textContent = "—"; $("weather-chip").textContent = "Sem previsão";
      $("weather-msg").textContent = "A previsão é atualizada todo dia às 5h20 ou pelo Admin.";
      if (state.charts.weather) state.charts.weather.destroy();
      return;
    }
    $("weather-mm").textContent = `${fmt.num(w.precip_total_mm, 0)} mm`;
    const a = w.alert;
    $("weather-chip").className = `chip ${{ wet: "chip-up", dry: "chip-down" }[a.code] || ""}`;
    $("weather-chip").replaceChildren(el("span", { "aria-hidden": "true", text: { wet: "☔", dry: "☀", neutral: "⛅" }[a.code] || "" }), a.title);
    $("weather-msg").textContent = `${a.message}${w.tmax_peak != null ? ` Máxima prevista de ${fmt.num(w.tmax_peak)} °C.` : ""}`;
    upsertChart("weather", "chart-weather", {
      type: "bar",
      data: { labels: w.daily.map((d) => fmt.date(d.date)),
        datasets: [{ label: "Chuva (mm)", data: w.daily.map((d) => d.precip_mm), backgroundColor: css("--s-boi"),
          borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "bottom", barPercentage: 0.7, categoryPercentage: 0.9 }] },
      options: {
        scales: { x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
          y: { beginAtZero: true, ticks: { callback: (v) => `${v} mm` } } },
        plugins: { legend: { display: false },
          tooltip: { callbacks: { label: (c) => {
            const d = w.daily[c.dataIndex];
            return [` Chuva: ${fmt.num(d.precip_mm)} mm`, ` Máxima: ${d.tmax == null ? "—" : fmt.num(d.tmax) + " °C"}`];
          } } } },
      },
    });
  }

  // ------------------------------------------------------------------ G: B3 / basis
  function renderB3(f) {
    const tbody = $("b3-table");
    if (!f.contracts.length) {
      tbody.replaceChildren(el("tr", {}, el("td", { colspan: "5", class: "muted", text: "Sem ajustes da B3 cadastrados. Informe no Admin." })));
      $("b3-reading").textContent = ""; $("b3-note").textContent = "";
      if (state.charts.basis) state.charts.basis.destroy();
      return;
    }
    tbody.replaceChildren(...f.contracts.map((c) => el("tr", {},
      el("td", { class: "font-semibold", text: c.contract }),
      el("td", { text: fmt.monthYear(c.maturity) }),
      el("td", { class: "num", text: fmt.brl(c.settlement) }),
      el("td", { class: "num font-semibold", text: fmt.brl(c.basis_rs) }),
      el("td", { class: "num", text: fmt.pct(c.basis_pct) }))));
    $("b3-sub").textContent = `Físico ${fmt.brl(f.physical)}/@ em ${fmt.date(f.physical_date)}; ajustes da B3 de ${fmt.date(f.futures_date)}.`;
    const h = f.history;
    $("b3-reading").textContent = h && h.reading
      ? `${h.reading}: média de 60 dias ${fmt.brl(h.average_rs)}, hoje ${h.deviation_rs >= 0 ? "+" : "−"}${fmt.brl(Math.abs(h.deviation_rs))} vs. média.` : "";
    $("b3-note").textContent = f.note || "";
    if (!h || !h.series.length) return;
    upsertChart("basis", "chart-basis", {
      type: "line",
      data: { labels: h.series.map((p) => fmt.date(p.date)),
        datasets: [lineDs("Basis", h.series.map((p) => p.basis_rs), css("--eucalipto"), { borderWidth: 2.5 })] },
      options: {
        interaction: { mode: "index", intersect: false },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 6, maxRotation: 0 } },
          y: { grace: "10%", ticks: { callback: (v) => fmt.brl(v).replace(",00", "") } } },
        plugins: { legend: { display: false },
          tooltip: { callbacks: { label: (c) => ` ${h.series[c.dataIndex].contract}: ${fmt.brl(c.parsed.y)}/@` } },
          refLines: { lines: [{ y: h.average_rs, label: `média ${fmt.brl(h.average_rs)}` }] } },
      },
    });
  }

  // ------------------------------------------------------------------ H: simulador
  async function simulate(e) {
    e.preventDefault();
    const form = e.target, btn = $("sim-submit");
    const payload = { praca: state.praca };
    new FormData(form).forEach((v, k) => { if (v !== "") payload[k] = Number(v); });
    btn.disabled = true; $("sim-error").textContent = "";
    try {
      const { result: r, price_projection: proj } = await api("/api/simulator", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const hold = r.decisao === "segurar";
      const row = (k, v) => el("div", { class: "flex justify-between gap-4 py-2 border-t border-[var(--hairline)]" },
        el("dt", { class: "text-[var(--ink-2)]", text: k }), el("dd", { class: "figure text-right", text: v }));
      $("sim-result").replaceChildren(
        el("h3", { class: "h3", text: "Resultado" }),
        el("p", { class: "mt-3 figure text-4xl", style: `color:${hold ? css("--eucalipto-escuro") : css("--queda")}`, text: hold ? "Segurar compensa" : "Vender agora" }),
        el("p", { class: "mt-1 text-lg", text: `${r.lucro_incremental >= 0 ? "+" : "−"}${fmt.brl(Math.abs(r.lucro_incremental))} por cabeça vs. vender hoje` }),
        el("dl", { class: "mt-5 small" },
          row("Peso na venda", `${fmt.num(r.peso_final_kg, 0)} kg`),
          row("Arrobas hoje e na venda", `${fmt.num(r.arrobas_hoje, 2)}@ → ${fmt.num(r.arrobas_final, 2)}@`),
          row("Custo da @ produzida", fmt.brl(r.custo_por_arroba_produzida)),
          row("Preço de equilíbrio da @ na venda", fmt.brl(r.preco_equilibrio_arroba)),
          row("Preço da @ usado na venda", fmt.brl(r.preco_arroba_venda)),
          row("Receita vendendo hoje", fmt.brl(r.receita_vender_hoje)),
          row("Receita segurando", fmt.brl(r.receita_segurar)),
          row("Custo de engorda", fmt.brl(r.custo_total)),
          row("Custo de oportunidade (juros)", fmt.brl(r.custo_oportunidade))),
        proj ? el("p", { class: "small muted mt-3", text: `Preço de venda projetado: ajuste ${proj.contract} de ${fmt.brl(proj.settlement)} somado ao basis atual de ${fmt.brl(proj.basis_rs)}.` }) : null);
    } catch (err) {
      $("sim-error").textContent = err.details ? err.details.join("; ") : err.message;
    } finally {
      btn.disabled = false;
    }
  }

  // ------------------------------------------------------------------ H: notícias
  let newsTimer;
  async function loadNews(reset) {
    if (reset) state.newsPage = 1;
    const params = new URLSearchParams({ page: state.newsPage, per_page: 8 });
    if ($("news-scope").value === "uf" && state.uf) params.set("uf", state.uf);
    if ($("news-cat").value) params.set("category", $("news-cat").value);
    if ($("news-sent").value) params.set("sentiment", $("news-sent").value);
    if ($("news-q").value.trim()) params.set("q", $("news-q").value.trim());
    const res = await api(`/api/news?${params}`);
    const list = $("news-list");
    if (reset) list.replaceChildren();
    if (!res.items.length && reset) list.append(el("li", { class: "muted py-4", text: "Nenhuma notícia com esses filtros. Tente outra busca ou amplie para todos os estados." }));
    res.items.forEach((n) => list.append(newsItem(n)));
    $("news-count").textContent = `${res.total} ${res.total === 1 ? "notícia" : "notícias"}`;
    $("news-more").hidden = state.newsPage * res.per_page >= res.total;
  }

  function newsItem(n) {
    const demo = n.source === "AgroRadar Demo";
    const safeUrl = /^https?:\/\//i.test(n.url) && !demo ? n.url : null;
    const title = safeUrl ? el("a", { href: safeUrl, target: "_blank", rel: "noopener noreferrer", text: n.title }) : el("span", { class: "font-semibold", text: n.title });
    const sent = { positivo: ["chip-up", "▲"], negativo: ["chip-down", "▼"], neutro: ["", "●"] }[n.sentiment] || ["", "●"];
    return el("li", { class: "news-item" }, title,
      n.summary ? el("p", { class: "small text-[var(--ink-2)] mt-1 max-w-[75ch]", text: n.summary }) : null,
      el("div", { class: "mt-2 flex flex-wrap items-center gap-2 small muted" },
        el("span", { text: demo ? `${n.source} (demonstração)` : n.source }),
        el("span", { text: fmt.ago(n.published_at || n.collected_at) }),
        el("span", { class: "chip", text: n.uf === "BR" ? "Brasil" : n.uf }),
        el("span", { class: "chip", text: CATEGORY_LABELS[n.category] || n.category }),
        el("span", { class: `chip ${sent[0]}` }, el("span", { "aria-hidden": "true", text: sent[1] }), n.sentiment)));
  }

  // ------------------------------------------------------------------ eventos fixos
  function wireStatic() {
    $("copy-briefing").addEventListener("click", copyBriefing);
    document.querySelectorAll("[data-days]").forEach((b) => b.addEventListener("click", () => {
      state.days = Number(b.dataset.days);
      document.querySelectorAll("[data-days]").forEach((x) => {
        const on = x === b; x.classList.toggle("chip-up", on); x.setAttribute("aria-pressed", String(on));
      });
      loadHistory();
    }));
    $("sim-form").addEventListener("submit", simulate);
    ["news-cat", "news-sent", "news-scope"].forEach((id) => $(id).addEventListener("change", () => loadNews(true)));
    $("news-q").addEventListener("input", () => { clearTimeout(newsTimer); newsTimer = setTimeout(() => loadNews(true), 300); });
    $("news-filters").addEventListener("submit", (e) => { e.preventDefault(); loadNews(true); });
    $("news-more").addEventListener("click", () => { state.newsPage += 1; loadNews(false); });
  }

  boot().catch((err) => {
    $("notices").replaceChildren(el("div", { class: "notice", role: "alert" }, `Não foi possível iniciar o painel: ${err.message}`));
  });
})();
