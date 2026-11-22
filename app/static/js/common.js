/* AgroRadar — utilitários compartilhados (painel e admin). Sem dependências. */
(function () {
  "use strict";
  const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const num = (d = 1) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });

  /** Sinal só quando o valor arredondado não é zero (evita "−0,0%"). */
  function signed(v, d, suffix) {
    if (v == null) return "—";
    const r = Number(v.toFixed(d));
    return (r > 0 ? "+" : r < 0 ? "−" : "") + num(d).format(Math.abs(r)) + suffix;
  }

  const fmt = {
    brl: (v) => (v == null ? "—" : (v < 0 ? "−" : "") + brl.format(Math.abs(v))),
    num: (v, d = 1) => (v == null ? "—" : num(d).format(v)),
    pct: (v, d = 1) => signed(v, d, "%"),
    pp: (v) => signed(v, 1, " p.p."),
    date: (iso) => (iso ? new Date(iso + "T12:00:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) : "—"),
    monthYear: (iso) => new Date(iso + "T12:00:00").toLocaleDateString("pt-BR", { month: "short", year: "2-digit" }).replace(".", ""),
    // datetimes do banco são UTC sem fuso
    time: (iso) => (iso ? new Date(iso + "Z").toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "—"),
    ago(iso) {
      if (!iso) return "";
      const min = Math.round((Date.now() - new Date(iso + "Z").getTime()) / 60000);
      if (min < 1) return "agora";
      if (min < 60) return `há ${min} min`;
      const h = Math.round(min / 60);
      return h < 24 ? `há ${h} h` : `há ${Math.round(h / 24)} d`;
    },
  };

  /** Cria elemento sem innerHTML (texto de RSS é de terceiros). */
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "style") node.setAttribute("style", v);
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c != null) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    return node;
  }

  async function api(url, opts = {}) {
    const res = await fetch(url, { headers: { Accept: "application/json", ...(opts.headers || {}) }, credentials: "same-origin", ...opts });
    let body = null;
    try { body = await res.json(); } catch (_) { /* sem corpo JSON */ }
    if (!res.ok) {
      const err = new Error((body && body.error) || `Erro ${res.status}`);
      err.status = res.status; err.details = body && body.details;
      throw err;
    }
    return body;
  }

  let toastTimer;
  function toast(message) {
    const t = document.getElementById("toast");
    if (!t) return;
    t.textContent = message; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 2600);
  }

  /** Converte *negrito* do WhatsApp em <strong>, escapando o resto. */
  function whatsappLine(text) {
    const frag = document.createDocumentFragment();
    String(text).split(/(\*[^*\n]+\*)/g).forEach((part) => {
      if (/^\*[^*]+\*$/.test(part)) frag.append(el("strong", { text: part.slice(1, -1) }));
      else if (part) frag.append(document.createTextNode(part));
    });
    return frag;
  }

  window.AR = { fmt, el, api, toast, whatsappLine };
})();
