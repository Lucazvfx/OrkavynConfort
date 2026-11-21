/* AgroRadar — painel do administrador. Fala com /admin/api/* usando sessão + token CSRF. */
(function () {
  "use strict";
  const { fmt, el, api, toast } = window.AR;
  const $ = (id) => document.getElementById(id);
  let csrf = null;

  const JOB_LABELS = { rss: "Notícias", weather: "Clima", ibge: "IBGE", cepea: "Cepea", briefing: "Boletim", rss_pre_briefing: "Notícias (antes do boletim)" };
  const STATUS = { success: ["chip-up", "✓", "Concluída"], partial: ["chip-warn", "!", "Parcial"], error: ["chip-down", "✕", "Falhou"], running: ["", "…", "Rodando"] };

  const today = () => new Date().toLocaleDateString("sv-SE"); // AAAA-MM-DD no fuso local

  function show(view) {
    ["view-disabled", "view-login", "view-panel"].forEach((id) => ($(id).hidden = id !== view));
    $("logout").hidden = view !== "view-panel";
  }

  const post = (url, payload) => api(url, {
    method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload || {}),
  });

  // ------------------------------------------------------------------ sessão
  async function boot() {
    const s = await api("/admin/session");
    if (!s.enabled) return show("view-disabled");
    if (!s.authenticated) { show("view-login"); $("password").focus(); return; }
    csrf = s.csrf_token;
    show("view-panel");
    await loadPanel();
  }

  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("login-error").textContent = "";
    try {
      const r = await api("/admin/login", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: $("password").value }) });
      csrf = r.csrf_token;
      $("password").value = "";
      show("view-panel");
      await loadPanel();
    } catch (err) {
      $("login-error").textContent = err.status === 429 ? "Muitas tentativas. Aguarde alguns minutos e tente de novo." : "Senha incorreta.";
    }
  });

  $("logout").addEventListener("click", async () => {
    await api("/admin/logout", { method: "POST" });
    csrf = null;
    show("view-login");
  });

  // ------------------------------------------------------------------ painel
  async function loadPanel() {
    const [status, pracas] = await Promise.all([api("/admin/api/status"), api("/api/pracas")]);
    const sel = $("adm-praca");
    if (!sel.options.length) {
      pracas.states.forEach((s) => {
        const g = el("optgroup", { label: s.name });
        s.pracas.forEach((p) => g.append(el("option", { value: p.code, text: `${p.name} (${p.uf})` })));
        sel.append(g);
      });
      const ref = pracas.states[0].pracas.find((p) => p.is_state_reference) || pracas.states[0].pracas[0];
      sel.value = localStorage.getItem("ar.admin.praca") || ref.code;
      sel.addEventListener("change", () => { localStorage.setItem("ar.admin.praca", sel.value); loadPlaceholders(); });
      $("adm-date").value = today();
      $("adm-date").max = today();
    }
    renderFutures(status);
    renderFreshness(status);
    renderRuns(status);
    loadPlaceholders();
  }

  /** Mostra o último valor cadastrado como placeholder (referência contra erro de digitação). */
  async function loadPlaceholders() {
    const code = $("adm-praca").value;
    try {
      const [k, t] = await Promise.all([api(`/api/kpis?praca=${code}`), api(`/api/trade?praca=${code}`)]);
      const ph = (id, v, d = 2) => { $(id).placeholder = v == null ? "" : `último: ${fmt.num(v, d)}`; };
      ph("f-boi", k.prices.boi_gordo.price); ph("f-vaca", k.prices.vaca_gorda.price); ph("f-china", k.prices.boi_china.price);
      ph("f-dias", k.schedule.days_ahead, 1);
      ph("f-bezerro", t.items.bezerro && t.items.bezerro.price);
      ph("f-milho", t.items.milho && t.items.milho.price);
      ph("f-farelo", t.items.farelo_soja && t.items.farelo_soja.price);
    } catch (_) { /* praça sem dados: sem placeholder */ }
  }

  // ------------------------------------------------------------------ formulários por praça
  document.querySelectorAll("form[data-endpoint]").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = form.querySelector("[data-error]");
      err.textContent = "";
      const payload = { praca: $("adm-praca").value, date: $("adm-date").value };
      new FormData(form).forEach((v, k) => { if (String(v).trim() !== "") payload[k] = String(v).trim(); });
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        await post(form.dataset.endpoint, payload);
        toast(`${form.dataset.done}: ${$("adm-praca").selectedOptions[0].text}`);
        form.reset();
        await loadPanel();
      } catch (ex) {
        err.textContent = ex.details ? ex.details.join("; ") : ex.message;
      } finally { btn.disabled = false; }
    });
  });

  // ------------------------------------------------------------------ B3
  function renderFutures(status) {
    const rows = $("futures-rows");
    if (rows.children.length) return;
    rows.replaceChildren(...status.contracts_to_fill.map((c, i) => el("tr", {},
      el("td", {}, el("input", { class: "field", name: `contract_${i}`, value: c.contract, "aria-label": `Código do contrato ${i + 1}`, maxlength: "6" })),
      el("td", {}, el("input", { class: "field", name: `settlement_${i}`, inputmode: "decimal", "aria-label": `Ajuste do ${c.contract}` })),
      el("td", {}, el("input", { class: "field", name: `oi_${i}`, inputmode: "numeric", "aria-label": `Contratos em aberto do ${c.contract}` })))));
  }

  $("form-futures").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target, err = form.querySelector("[data-error]");
    err.textContent = "";
    const contracts = [];
    for (let i = 0; i < 4; i++) {
      const code = form.elements[`contract_${i}`].value.trim();
      const settlement = form.elements[`settlement_${i}`].value.trim().replace(",", ".");
      const oi = form.elements[`oi_${i}`].value.trim();
      if (code && settlement) contracts.push({ contract: code, settlement, open_interest: oi || null });
    }
    if (!contracts.length) { err.textContent = "Preencha o ajuste de ao menos um contrato."; return; }
    try {
      const r = await post("/admin/api/futures", { date: $("adm-date").value, contracts });
      toast(`Ajustes salvos: ${r.saved.join(", ")}`);
      form.querySelectorAll("input[name^=settlement_], input[name^=oi_]").forEach((i) => (i.value = ""));
      await loadPanel();
    } catch (ex) {
      err.textContent = ex.details ? ex.details.join("; ") : ex.message;
    }
  });

  // ------------------------------------------------------------------ jobs
  document.querySelectorAll("[data-job]").forEach((btn) => btn.addEventListener("click", async () => {
    const job = btn.dataset.job, out = $("job-result");
    document.querySelectorAll("[data-job]").forEach((b) => (b.disabled = true));
    out.textContent = `${JOB_LABELS[job]}: rodando…`;
    try {
      const r = await post(`/admin/api/jobs/${job}/run`);
      out.textContent = `${JOB_LABELS[job]}: concluído. ${describe(job, r.result)}`;
      toast(`${JOB_LABELS[job]} concluído`);
    } catch (ex) {
      out.textContent = `${JOB_LABELS[job]}: falhou. ${ex.message}`;
    } finally {
      document.querySelectorAll("[data-job]").forEach((b) => (b.disabled = false));
      loadPanel();
    }
  }));

  function describe(job, r) {
    if (!r) return "";
    if (job === "rss") return `${r.inserted} notícias novas${r.failed_feeds.length ? `; feeds com erro: ${r.failed_feeds.join(", ")}` : ""}.`;
    if (job === "weather") return `${r.snapshots} praças atualizadas.`;
    if (job === "ibge") return `${r.quarters_upserted} trimestres atualizados.`;
    if (job === "cepea") return `${r.saved} cotações gravadas${r.failed.length ? `; com erro: ${r.failed.join(", ")}` : ""}.`;
    if (job === "briefing") return `${r.briefings} boletins gerados (${r.providers.join(", ")}).`;
    return "";
  }

  // ------------------------------------------------------------------ situação
  function businessDaysSince(iso) {
    if (!iso) return Infinity;
    let d = new Date(iso + "T12:00:00"), n = 0;
    const end = new Date(today() + "T12:00:00");
    while (d < end) { d.setDate(d.getDate() + 1); if (d.getDay() % 6 !== 0) n++; }
    return n;
  }

  function freshCell(iso) {
    const stale = businessDaysSince(iso) > 3;
    return el("td", {}, el("span", { class: `chip ${stale ? "chip-down" : ""}` },
      stale ? el("span", { "aria-hidden": "true", text: "!" }) : null, iso ? fmt.date(iso) : "nunca"));
  }

  function renderFreshness(status) {
    $("fresh-rows").replaceChildren(...status.pracas.map((p) => el("tr", {},
      el("td", { class: "font-semibold", text: `${p.name} (${p.uf})` }),
      freshCell(p.last_cattle_quote), freshCell(p.last_schedule), freshCell(p.last_inputs),
      el("td", {}, el("button", { type: "button", class: "btn btn-ghost !py-1 !px-3 small", text: p.active ? "Visível" : "Oculta",
        "aria-label": `${p.active ? "Ocultar" : "Mostrar"} ${p.name} no painel`,
        onclick: async () => { await post(`/admin/api/pracas/${p.praca}/toggle`); toast(p.active ? `${p.name} oculta do painel` : `${p.name} visível no painel`); loadPanel(); } })))));
  }

  function renderRuns(status) {
    $("run-rows").replaceChildren(...(status.recent_runs.length ? status.recent_runs.map((r) => {
      const [cls, icon, label] = STATUS[r.status] || ["", "·", r.status];
      return el("tr", {},
        el("td", { text: JOB_LABELS[r.job] || r.job }),
        el("td", {}, el("span", { class: `chip ${cls}` }, el("span", { "aria-hidden": "true", text: icon }), label)),
        el("td", { class: "whitespace-nowrap", text: new Date(r.started_at + "Z").toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) }),
        el("td", { class: "small text-[var(--ink-2)] max-w-[52ch]", text: r.detail || "" }));
    }) : [el("tr", {}, el("td", { colspan: "4", class: "muted", text: "Nenhuma execução registrada ainda." }))]));
    $("next-runs").replaceChildren(...(status.scheduler.length
      ? status.scheduler.map((j) => el("li", { text: `${JOB_LABELS[j.id] || j.id}: ${new Date(j.next_run).toLocaleString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}` }))
      : [el("li", { class: "muted", text: "Agendador desligado neste processo (rode com python run.py ou wsgi.py)." })]));
  }

  boot().catch((err) => toast(`Erro ao abrir o admin: ${err.message}`));
})();
