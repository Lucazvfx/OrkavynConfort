"""Frontend — estilo (CSS), componentes e abas do Streamlit."""

from __future__ import annotations

import base64
import html
import math
import re
from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .config import *  # noqa: F401,F403
from .db import (apagar_exemplos, excluir_observacao,
                 inserir_observacao, inserir_varias)
from .motor import (Diagnostico, classificar_itu, diagnosticar, filtrar,
                    gerar_exemplos, lotes_para_agir, resumo_por_pasto,
                    validar_observacao)


# Streamlit novo (>= 1.50) usa width="stretch"; o antigo usa use_container_width.
_VERSAO = tuple(int(p) for p in re.findall(r"\d+", st.__version__)[:2])
LARGURA_TOTAL = {"width": "stretch"} if _VERSAO >= (1, 50) else {"use_container_width": True}


CSS = f"""
<style>
:root {{ color-scheme: light; }}
#MainMenu, footer, header, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"] {{ display: none !important; visibility: hidden; }}

html, body, .stApp, .stApp * {{
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", Inter, "Segoe UI", Roboto, sans-serif;
}}
.stApp {{ background: radial-gradient(circle at 8% 0%, {COR_VERDE_SUAVE}b8, transparent 34%), {COR_FUNDO}; color: {COR_TEXTO}; }}
.block-container {{ max-width: 920px; padding: 1.2rem 1rem 4rem 1rem; }}
h1, h2, h3, h4, p, label, span, li {{ color: {COR_TEXTO}; }}
[data-testid="stWidgetLabel"] p {{ font-size: .98rem; font-weight: 600; color: #51584F; }}
[data-testid="stCaptionContainer"], small {{ color: {COR_TEXTO_SUAVE}; }}

/* Vidro: cartões translúcidos como no Orkavyn Fields */
.ok-vidro, .ok-cartao, [data-testid="stForm"] {{
  background: rgba(255,254,250,.78); border: 1px solid rgba(255,255,255,.8); border-radius: 18px;
  box-shadow: 0 18px 42px rgba(44,57,43,.09), 0 2px 8px rgba(62,44,28,.05);
  backdrop-filter: blur(20px) saturate(125%); -webkit-backdrop-filter: blur(20px) saturate(125%);
}}
[data-testid="stForm"] {{ padding: 1.3rem 1.2rem; }}
.ok-cartao {{ padding: 1.1rem 1.2rem; }}

/* Topo da marca */
.ok-topo {{ display: flex; align-items: center; gap: 12px; padding: .2rem 0 1rem 0; }}
.ok-topo img {{ width: 46px; height: 46px; border-radius: 12px; object-fit: cover; box-shadow: 0 4px 14px rgba(27,48,34,.18); }}
.ok-topo strong {{ display: block; font-size: 15px; letter-spacing: -.01em; }}
.ok-topo small {{ display: block; margin-top: 2px; color: {COR_TERRA}; font-size: 9.5px; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; }}
.ok-eyebrow {{ margin: 0 0 8px 0; color: {COR_TEXTO_SUAVE}; font-size: 10.5px; font-weight: 700; letter-spacing: .13em; text-transform: uppercase; }}
.ok-secao {{ font-size: 1.45rem; font-weight: 700; letter-spacing: -.035em; line-height: 1.1; margin: 1.8rem 0 .5rem 0; }}

/* Hero (faixa verde com foto da fazenda) */
.ok-hero {{ display: grid; grid-template-columns: 1.15fr .85fr; overflow: hidden; border-radius: 16px; background: {COR_MARCA}; color: {COR_FUNDO}; box-shadow: 0 14px 34px rgba(62,44,28,.12); margin-bottom: 14px; min-height: 210px; }}
.ok-hero-txt {{ padding: 1.7rem 1.6rem; display: flex; flex-direction: column; justify-content: center; }}
.ok-hero-txt .ok-eyebrow {{ color: {COR_PALHA}; }}
.ok-hero h1, .ok-hero h1 span {{ color: {COR_FUNDO}; font-size: clamp(1.7rem, 4vw, 2.5rem); font-weight: 700; letter-spacing: -.035em; line-height: 1.06; margin: 0 0 .6rem 0; padding: 0; }}
.ok-hero p {{ color: {COR_VERDE_SUAVE}; margin: 0; max-width: 34ch; line-height: 1.45; }}
.ok-hero-img {{ background-size: cover; background-position: center; min-height: 190px; }}
.ok-pill {{ display: inline-block; margin-top: 1rem; padding: .35rem .8rem; border-radius: 999px; font-size: .8rem; font-weight: 700; background: rgba(255,254,250,.16); color: {COR_FUNDO}; border: 1px solid rgba(255,255,255,.28); align-self: flex-start; }}

/* Abas: pílula verde escura no item ativo */
.stTabs [role="tablist"] {{ gap: 6px; background: rgba(255,254,250,.7); padding: 5px; border-radius: 14px; border: 1px solid rgba(255,255,255,.8); box-shadow: 0 8px 24px rgba(44,57,43,.06); }}
.stTabs [role="tab"] {{ flex: 1; justify-content: center; height: 46px; border-radius: 10px; font-size: 1rem; font-weight: 600; color: #51584F; background: transparent; }}
.stTabs [role="tab"] p {{ font-weight: 600; font-size: 1rem; color: inherit; }}
.stTabs [role="tab"][aria-selected="true"] {{ background: rgba(27,48,34,.94); color: {COR_FUNDO}; box-shadow: 0 6px 18px rgba(27,48,34,.18); }}
.stTabs [role="tab"][aria-selected="true"] p {{ color: {COR_FUNDO}; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"], .stTabs .react-aria-SelectionIndicator {{ display: none !important; }}

/* Indicadores */
.ok-grade {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: .4rem 0 .6rem 0; }}
.ok-kpi-rotulo {{ font-size: .82rem; color: {COR_TEXTO_SUAVE}; font-weight: 600; }}
.ok-kpi-valor {{ font-size: 2.1rem; font-weight: 700; letter-spacing: -.04em; line-height: 1.15; margin-top: .2rem; font-variant-numeric: tabular-nums; }}
.ok-kpi-sub {{ font-size: .8rem; color: {COR_TEXTO_SUAVE}; margin-top: .25rem; }}
.ok-kpi-destaque {{ background: rgba(220,233,221,.78); }}
.ok-chip {{ display: inline-block; padding: .22rem .7rem; border-radius: 999px; font-size: .78rem; font-weight: 700; letter-spacing: .02em; color: #fff; }}
.ok-itu {{ font-size: 2.8rem; font-weight: 700; letter-spacing: -.04em; line-height: 1; font-variant-numeric: tabular-nums; }}
.ok-acao {{ margin-top: .7rem; font-size: 1rem; line-height: 1.45; }}
.ok-vazio {{ text-align: center; padding: 2.2rem 1rem; }}
.ok-vazio h3 {{ margin: 0 0 .4rem 0; font-size: 1.3rem; }}

/* Cartões "O que fazer hoje" */
.ok-aviso {{ display: flex; gap: 14px; align-items: flex-start; padding: 15px 18px; margin-bottom: 10px; border-radius: 14px; background: rgba(255,254,250,.8); border: 1px solid rgba(255,255,255,.8); box-shadow: 0 10px 26px rgba(44,57,43,.07); border-left: 4px solid {COR_VERDE_SUAVE}; }}
.ok-aviso.atencao {{ border-left-color: {COR_ATENCAO}; }}
.ok-aviso.critico {{ border-left-color: {COR_CRITICO}; }}
.ok-aviso strong {{ display: block; font-size: 1rem; }}
.ok-aviso .ok-quando {{ margin-left: auto; white-space: nowrap; color: {COR_TEXTO_SUAVE}; font-size: .78rem; font-weight: 600; }}
.ok-aviso p {{ margin: 4px 0 0 0; color: #51584F; font-size: .92rem; line-height: 1.42; }}
.ok-aviso .ok-chip {{ margin-top: 6px; }}

/* Campos grandes, alto contraste, fáceis de tocar */
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {{
  min-height: 3.2rem; border-radius: 12px !important; background: rgba(245,243,238,.85) !important;
  border: 1px solid rgba(128,85,51,.22) !important;
}}
.stTextInput input, .stNumberInput input, .stDateInput input, .stTimeInput input, .stTextArea textarea,
[data-baseweb="select"] {{ font-size: 1.1rem !important; color: {COR_TEXTO} !important; background: transparent !important; }}
[data-baseweb="base-input"] input, [data-baseweb="input"] input, [data-baseweb="select"] div {{ font-size: 1.1rem !important; }}
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within {{ border-color: {COR_MARCA} !important; box-shadow: 0 0 0 3px rgba(27,48,34,.14) !important; }}
.stTextArea textarea {{ min-height: 5.5rem; }}
.stNumberInput button {{ min-height: 3.2rem; background: transparent; }}

/* Botões */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {{
  min-height: 3.5rem; width: 100%; border-radius: 12px; font-size: 1.05rem; font-weight: 700; letter-spacing: .01em;
  border: 1px solid rgba(255,255,255,.8); background: rgba(255,254,250,.7); color: {COR_MARCA};
  box-shadow: 0 5px 16px rgba(44,57,43,.07);
}}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"],
.stDownloadButton > button[kind="primary"] {{
  background: {COR_MARCA}; border-color: {COR_MARCA}; color: {COR_FUNDO}; box-shadow: 0 8px 20px rgba(27,48,34,.18);
}}
.stButton > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"]:hover {{ background: {COR_MARCA_ESCURA}; border-color: {COR_MARCA_ESCURA}; color: #fff; }}
.stButton > button[kind="primary"] p, [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"] p {{ color: {COR_FUNDO}; }}
.stButton > button p, [data-testid="stFormSubmitButton"] > button p {{ color: inherit; }}
[data-testid="stForm"] [data-testid="stElementContainer"], div:has(> [data-testid="stFormSubmitButton"]),
[data-testid="stFormSubmitButton"], [data-testid="stFormSubmitButton"] > button {{ width: 100% !important; }}

[data-testid="stAlert"] {{ border-radius: 14px; }}
[data-testid="stDataFrame"] {{ border-radius: 14px; overflow: hidden; }}
[data-testid="stExpander"] {{ border-radius: 14px; border-color: rgba(128,85,51,.16); background: rgba(255,254,250,.6); }}

@media (max-width: 640px) {{
  [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
  [data-testid="stColumn"] {{ min-width: 100% !important; }}
  .ok-hero {{ grid-template-columns: 1fr; }}
  .ok-hero-img {{ order: -1; min-height: 130px; }}
  .ok-hero-txt {{ padding: 1.3rem 1.2rem; }}
  .ok-kpi-valor {{ font-size: 1.8rem; }}
  .ok-aviso {{ flex-wrap: wrap; }}
  .ok-aviso .ok-quando {{ margin-left: 0; }}
}}
</style>
"""


@lru_cache(maxsize=None)
def imagem_uri(nome: str, mime: str) -> str:
    """Imagem da pasta assets/ embutida na página (data URI), com cache."""
    try:
        dados = (ASSETS_DIR / nome).read_bytes()
    except OSError:
        return ""
    return f"data:{mime};base64,{base64.b64encode(dados).decode()}"


def topo_marca() -> None:
    st.markdown(
        f'<div class="ok-topo"><img src="{imagem_uri("logo.png", "image/png")}" alt="">'
        f'<div><strong>{APP_NOME}</strong><small>Conforto do rebanho · Vilhena-RO</small></div></div>',
        unsafe_allow_html=True,
    )


def tempo_atras(quando: datetime) -> str:
    seg = (datetime.now(FUSO).replace(tzinfo=None) - quando.to_pydatetime()).total_seconds()
    if seg < 3600:
        return "agora há pouco"
    if seg < 86400:
        return f"há {int(seg // 3600)} h"
    return f"há {int(seg // 86400)} dia(s)"


def hero_painel(df: pd.DataFrame) -> None:
    """Faixa verde do topo do painel: pergunta central + retrato de agora."""
    if df.empty:
        pilula = "Sem registros ainda"
    else:
        n = len(lotes_para_agir(df))
        pilula = (f"{n} lote(s) pedem atenção agora" if n else "Nenhum lote em alerta agora")
    foto = imagem_uri("hero.jpg", "image/jpeg")
    st.markdown(
        f"""<div class="ok-hero">
          <div class="ok-hero-txt">
            <p class="ok-eyebrow">Fisiologia e conforto</p>
            <h1>Calor ou doença?</h1>
            <p>Cruzamos o clima com o que os trabalhadores veem no pasto para saber o que fazer primeiro.</p>
            <span class="ok-pill">{html.escape(pilula)}</span>
          </div>
          <div class="ok-hero-img" style="background-image:url({foto})"></div>
        </div>""",
        unsafe_allow_html=True,
    )


def avisos_hoje(f: pd.DataFrame) -> None:
    """Cartões "O que fazer hoje": um por lote, a partir da observação mais recente."""
    st.markdown('<p class="ok-eyebrow" style="margin-top:1.6rem">Prioridades</p>'
                '<div class="ok-secao" style="margin-top:0">O que fazer hoje</div>', unsafe_allow_html=True)
    ag = lotes_para_agir(f)
    if ag.empty:
        st.markdown('<div class="ok-aviso"><div><strong>Tudo tranquilo</strong>'
                    '<p>Nenhum lote com alerta na observação mais recente. Siga o manejo normal.</p></div></div>',
                    unsafe_allow_html=True)
        return
    partes = []
    for r in ag.head(6).itertuples():
        cor = COR_CRITICO if r.nivel == "critico" else COR_ATENCAO
        partes.append(
            f'<div class="ok-aviso {r.nivel}"><div>'
            f'<strong>{html.escape(r.lote)} · {html.escape(r.pasto)}</strong>'
            f'{chip(r.situacao, cor)}'
            f'<p>{html.escape(r.acao)}</p></div>'
            f'<span class="ok-quando">{tempo_atras(r.data_hora)}</span></div>'
        )
    st.markdown("".join(partes), unsafe_allow_html=True)


def grafico_itu_diario(f: pd.DataFrame) -> go.Figure | None:
    """ITU médio por dia, com as faixas de alerta/perigo/emergência ao fundo."""
    dia = f.assign(dia=f["data_hora"].dt.normalize()).groupby("dia")["itu"].mean().reset_index()
    if len(dia) < 2:
        return None
    topo = max(float(dia["itu"].max()) + 2, ITU_EMERGENCIA_MIN + 3)
    base = min(float(dia["itu"].min()) - 3, ITU_ALERTA_MIN - 4)
    fig = go.Figure()
    for y0, y1, cor, nome in ((ITU_ALERTA_MIN, ITU_PERIGO_MIN, COR_ATENCAO, "Alerta"),
                              (ITU_PERIGO_MIN, ITU_EMERGENCIA_MIN, COR_CRITICO, "Perigo"),
                              (ITU_EMERGENCIA_MIN, topo, COR_CRITICO, "Emergência")):
        fig.add_hrect(y0=y0, y1=y1, fillcolor=cor, opacity=0.16 if nome == "Emergência" else 0.10, line_width=0,
                      annotation_text=nome, annotation_position="top right",
                      annotation_font=dict(size=11, color=COR_TEXTO_SUAVE))
    fig.add_trace(go.Scatter(
        x=dia["dia"], y=dia["itu"].round(1), mode="lines+markers", name="ITU médio",
        line=dict(color=COR_MARCA, width=2), marker=dict(size=8, color=COR_MARCA, line=dict(width=2, color="#FFFEFA")),
        hovertemplate="%{x|%d/%m}<br>ITU médio: %{y:.1f}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=300, showlegend=False,
        margin=dict(l=8, r=8, t=16, b=8),
        font=dict(family='-apple-system, "SF Pro Text", Inter, sans-serif', color=COR_TEXTO, size=13),
        xaxis=dict(showgrid=False, zeroline=False, showline=True, linecolor=COR_LINHA, tickformat="%d/%m"),
        yaxis=dict(title="ITU médio", gridcolor=COR_LINHA, gridwidth=0.5, zeroline=False, range=[base, topo]),
    )
    return fig


def aplicar_estilo() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def chip(texto: str, cor: str) -> str:
    txt = COR_TEXTO if cor == COR_ATENCAO else "#fff"  # texto escuro sobre o âmbar, para contraste
    return f'<span class="ok-chip" style="background:{cor};color:{txt}">{html.escape(texto)}</span>'


def cor_do_nivel(nivel: str) -> str:
    return {"ok": COR_OK, "atencao": COR_ATENCAO, "critico": COR_CRITICO}[nivel]


def cartao_kpi(rotulo: str, valor: str, sub: str = "") -> str:
    sub_html = f'<div class="ok-kpi-sub">{sub}</div>' if sub else ""
    return (
        f'<div class="ok-cartao"><div class="ok-kpi-rotulo">{html.escape(rotulo)}</div>'
        f'<div class="ok-kpi-valor">{valor}</div>{sub_html}</div>'
    )


def mostrar_resultado_itu(diag: Diagnostico, titulo: str = "Resultado da observação") -> None:
    """Cartão com ITU, classificação e ação recomendada."""
    cor_itu = {"conforto": COR_OK, "alerta": COR_ATENCAO, "perigo": COR_CRITICO, "emergencia": COR_CRITICO}[diag.faixa_itu]
    cor_class = COR_CLASSE[diag.categoria]
    chips = chip(diag.categoria, cor_class)
    if diag.alerta_locomotor:
        chips += " " + chip(ALERTA_LOCOMOTOR, COR_CRITICO if diag.nivel == "critico" else COR_ATENCAO)
    st.markdown(
        f"""
        <div class="ok-cartao" style="margin:.8rem 0">
          <div class="ok-kpi-rotulo">{html.escape(titulo)}</div>
          <div style="display:flex;align-items:center;gap:.9rem;margin:.4rem 0 .6rem 0;flex-wrap:wrap">
            <div class="ok-itu" style="color:{cor_itu}">{diag.itu:.1f}</div>
            <div>
              <div class="ok-kpi-rotulo">ITU · {ROTULO_FAIXA_ITU[diag.faixa_itu]} · respiração {ROTULO_FAIXA_FR[diag.faixa_fr].lower()}</div>
              <div style="margin-top:.3rem">{chips}</div>
            </div>
          </div>
          <div class="ok-acao"><b>O que fazer:</b> {html.escape(diag.acao)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def botao_exemplos(chave: str) -> None:
    if st.button("Carregar dados de exemplo", key=chave, type="primary"):
        inserir_varias(gerar_exemplos())
        st.rerun()


def estado_vazio(chave: str) -> None:
    st.markdown(
        """
        <div class="ok-cartao ok-vazio">
          <h3>Ainda não há registros</h3>
          <p style="color:#6E6E73;margin:0">Faça a primeira observação na aba <b>Registrar</b>
          ou veja como o painel funciona com dados fictícios.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    botao_exemplos(chave)


# --- Aba: Registrar ----------------------------------------------------------

CAMPOS_A_LIMPAR = ["f_t", "f_ur", "f_fr", "f_loc", "f_texto", "f_data", "f_hora"]


def aba_registrar() -> None:
    st.markdown('<div class="ok-secao" style="margin-top:.8rem">Nova observação de campo</div>', unsafe_allow_html=True)

    if st.session_state.pop("_limpar_form", False):
        for k in CAMPOS_A_LIMPAR:
            st.session_state.pop(k, None)
    salvo = st.session_state.pop("_salvo", None)
    if salvo:
        st.success("Observação salva. Obrigado!")
        mostrar_resultado_itu(salvo, "Resultado da observação salva")

    agora = datetime.now(FUSO)
    with st.form("form_observacao", border=False):
        c1, c2 = st.columns(2)
        data_obs = c1.date_input("Data", value=agora.date(), key="f_data", format="DD/MM/YYYY")
        hora_obs = c2.time_input("Hora", value=agora.time().replace(second=0, microsecond=0), key="f_hora", step=60)
        observador = st.text_input("Quem está observando", key="f_observador", placeholder="Seu nome")
        c3, c4 = st.columns(2)
        lote = c3.text_input("Lote *", key="f_lote", placeholder="Ex.: Lote A")
        pasto = c4.text_input("Pasto *", key="f_pasto", placeholder="Ex.: Pasto Boa Vista")
        n_animais = st.number_input("Quantos animais você observou", min_value=None, value=None, step=1,
                                    key="f_n", placeholder="Ex.: 20")

        st.markdown("**Clima agora**")
        c5, c6 = st.columns(2)
        temperatura = c5.number_input("Temperatura do ar (°C)", value=None, step=0.5, format="%.1f",
                                      key="f_t", placeholder="Ex.: 32.0")
        umidade = c6.number_input("Umidade do ar (%)", value=None, step=1.0, format="%.0f",
                                  key="f_ur", placeholder="Ex.: 55")

        st.markdown("**Como estão os animais**")
        fr = st.number_input(
            "Respiração (movimentos por minuto)", value=None, step=1, key="f_fr", placeholder="Ex.: 48",
            help="Conte as subidas e descidas do flanco (lado da barriga) em 30 segundos e multiplique por 2.",
        )
        locomocao = st.selectbox("Como os animais andam", options=list(ROTULO_LOCOMOCAO), key="f_loc",
                                 format_func=lambda k: ROTULO_LOCOMOCAO[k])
        texto = st.text_area("Observações (se quiser)", key="f_texto",
                             placeholder="Ex.: animais parados na sombra, bebedouro seco…")

        b1, b2 = st.columns(2)
        so_ver = b1.form_submit_button("Ver ITU antes de salvar")
        salvar = b2.form_submit_button("Salvar observação", type="primary")

    if not (so_ver or salvar):
        return

    dados = {
        "data_hora": datetime.combine(data_obs, hora_obs).strftime("%Y-%m-%d %H:%M"),
        "observador": (observador or "").strip(),
        "lote": (lote or "").strip(),
        "pasto": (pasto or "").strip(),
        "n_animais": int(n_animais) if n_animais is not None else None,
        "temperatura": temperatura,
        "umidade": umidade,
        "fr": int(fr) if fr is not None else None,
        "locomocao": int(locomocao),
        "observacoes": (texto or "").strip(),
    }
    erros = validar_observacao(dados)
    if erros:
        for e in erros:
            st.error(e)
        return

    diag = diagnosticar(dados["temperatura"], dados["umidade"], dados["fr"], dados["locomocao"])
    if salvar:
        inserir_observacao(dados)
        st.session_state["_salvo"] = diag
        st.session_state["_limpar_form"] = True
        st.rerun()
    else:
        mostrar_resultado_itu(diag, "Prévia (ainda não salvo)")
        st.caption("Se estiver certo, toque em “Salvar observação”.")


# --- Aba: Painel -------------------------------------------------------------

def filtros_dashboard(df: pd.DataFrame) -> pd.DataFrame:
    hoje = datetime.now(FUSO).date()
    c1, c2, c3 = st.columns(3)
    periodo = c1.selectbox("Período", ["Últimos 7 dias", "Últimos 30 dias", "Tudo", "Escolher datas"], index=1, key="p_periodo")
    inicio, fim = None, None
    if periodo == "Últimos 7 dias":
        inicio = hoje - timedelta(days=6)
    elif periodo == "Últimos 30 dias":
        inicio = hoje - timedelta(days=29)
    elif periodo == "Escolher datas":
        faixa = st.date_input("De / até", value=(hoje - timedelta(days=29), hoje), key="p_datas", format="DD/MM/YYYY")
        if isinstance(faixa, (tuple, list)):
            if len(faixa) == 2:
                inicio, fim = faixa
            elif len(faixa) == 1:
                inicio = faixa[0]
        else:
            inicio = faixa
    pastos = c2.multiselect("Pasto", sorted(df["pasto"].unique()), key="p_pasto", placeholder="Todos")
    lotes = c3.multiselect("Lote", sorted(df["lote"].unique()), key="p_lote", placeholder="Todos")
    return filtrar(df, inicio, fim, pastos, lotes)


def grafico_dispersao(resumo: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    ordem = resumo.sort_values("temperatura")["pasto"].tolist()
    pos_rotulo = {p: ("top center" if i % 2 == 0 else "bottom center") for i, p in enumerate(ordem)}
    for classe in COR_CLASSE:
        sub = resumo[resumo["classificacao"] == classe]
        if sub.empty:
            continue
        # Rótulos alternando acima/abaixo (por temperatura) para não se sobreporem.
        posicoes = [pos_rotulo[p] for p in sub["pasto"]]
        fig.add_trace(go.Scatter(
            x=sub["temperatura"], y=sub["fr"], mode="markers+text", name=classe,
            text=sub["pasto"], textposition=posicoes, textfont=dict(size=12, color=COR_TEXTO),
            marker=dict(size=[min(14 + 7 * math.sqrt(n), 64) for n in sub["registros"]],
                        color=COR_CLASSE[classe], opacity=0.85, line=dict(width=2, color="#FFFFFF")),
            customdata=sub[["registros"]],
            hovertemplate="<b>%{text}</b><br>Temperatura média: %{x:.1f} °C<br>"
                          "Respiração média: %{y:.0f} mov/min<br>Registros: %{customdata[0]}<extra></extra>",
        ))
    fig.add_hline(y=FR_ELEVADA_MAX, line_dash="dash", line_color=COR_CRITICO, line_width=1.5,
                  annotation_text=f"Respiração alta (> {FR_ELEVADA_MAX})", annotation_position="top left",
                  annotation_font=dict(color=COR_CRITICO, size=12))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=430,
        margin=dict(l=8, r=8, t=24, b=8),
        font=dict(family='-apple-system, "SF Pro Text", Inter, sans-serif', color=COR_TEXTO, size=13),
        legend=dict(orientation="h", yanchor="top", y=-0.22, x=0, title_text=""),
        xaxis=dict(title="Temperatura média (°C)", showgrid=False, zeroline=False, showline=True, linecolor=COR_LINHA),
        yaxis=dict(title="Respiração média (mov/min)", gridcolor=COR_LINHA, gridwidth=0.5, zeroline=False),
        hoverlabel=dict(font_size=13),
    )
    # Margem em Y para a linha de referência e os pontos ficarem sempre visíveis.
    ymax = max(float(resumo["fr"].max()), FR_ELEVADA_MAX) + 15
    ymin = min(float(resumo["fr"].min()), FR_NORMAL_MAX) - 10
    fig.update_yaxes(range=[max(ymin, 0), ymax])
    fig.update_xaxes(range=[resumo["temperatura"].min() - 2, resumo["temperatura"].max() + 2])
    return fig


def estilo_linhas(row: pd.Series) -> list[str]:
    fundo = {"critico": f"background-color: {FUNDO_CRITICO}; color: #7A1F17",
             "atencao": f"background-color: {FUNDO_ATENCAO}; color: #6B4A00"}.get(row["_nivel"], "")
    return [fundo] * len(row)


def tabela_alertas(df: pd.DataFrame) -> None:
    alertas = df[df["exige_atencao"]].sort_values("data_hora", ascending=False)
    if alertas.empty:
        st.success("Nenhum lote em alerta neste filtro. 🎉")
        return
    t = pd.DataFrame({
        "Quando": alertas["data_hora"].dt.strftime("%d/%m %H:%M"),
        "Lote": alertas["lote"], "Pasto": alertas["pasto"],
        "Temp. (°C)": alertas["temperatura"], "Umid. (%)": alertas["umidade"],
        "ITU": alertas["itu"], "Resp. (mov/min)": alertas["fr"],
        "Locomoção": alertas["locomocao"], "Situação": alertas["situacao"],
        "Ação recomendada": alertas["acao"], "_nivel": alertas["nivel"],
    })
    estilizada = (t.style.apply(estilo_linhas, axis=1)
                  .format({"Temp. (°C)": "{:.1f}", "Umid. (%)": "{:.0f}", "ITU": "{:.1f}"}))
    st.dataframe(estilizada, hide_index=True, **LARGURA_TOTAL,
                 column_config={"_nivel": None, "Ação recomendada": st.column_config.TextColumn(width="large")})
    st.caption("Vermelho suave = precisa de ação agora. Âmbar = atenção.")


def csv_para_download(df: pd.DataFrame) -> bytes:
    """CSV pensado para abrir direto no Excel em português (; e vírgula decimal)."""
    out = pd.DataFrame({
        "data_hora": df["data_hora"].dt.strftime("%Y-%m-%d %H:%M"),
        "observador": df["observador"], "lote": df["lote"], "pasto": df["pasto"],
        "n_animais": df["n_animais"], "temperatura_c": df["temperatura"], "umidade_pct": df["umidade"],
        "itu": df["itu"], "faixa_itu": df["faixa_itu"].map(ROTULO_FAIXA_ITU),
        "fr_mov_min": df["fr"], "faixa_fr": df["faixa_fr"].map(ROTULO_FAIXA_FR),
        "escore_locomocao": df["locomocao"], "classificacao": df["classificacao"],
        "alerta_locomotor": df["alerta_locomotor"].map({True: "sim", False: "não"}),
        "acao_recomendada": df["acao"], "observacoes": df["observacoes"],
    })
    return out.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


def aba_painel(df: pd.DataFrame) -> None:
    hero_painel(df)
    if df.empty:
        estado_vazio("exemplos_painel")
        return

    f = filtros_dashboard(df)
    if f.empty:
        st.info("Nenhum registro nesse filtro. Tente outro período, pasto ou lote.")
        return

    itu_medio = f["itu"].mean()
    faixa_medio = classificar_itu(round(itu_medio, 1))
    cor_faixa = {"conforto": COR_OK, "alerta": COR_ATENCAO, "perigo": COR_CRITICO, "emergencia": COR_CRITICO}[faixa_medio]
    lotes_alerta = f.loc[f["exige_atencao"], "lote"].nunique()
    st.markdown(
        '<div class="ok-grade">'
        + cartao_kpi("Registros", f"{len(f)}", "no período filtrado")
        + cartao_kpi("ITU médio", f"{itu_medio:.1f}", chip(ROTULO_FAIXA_ITU[faixa_medio], cor_faixa))
        + cartao_kpi("Respiração média", f"{f['fr'].mean():.0f}", "movimentos por minuto")
        + cartao_kpi("Lotes em alerta", f"{lotes_alerta}",
                     "com ao menos um registro de alerta" if lotes_alerta else "nenhum no período")
        + "</div>",
        unsafe_allow_html=True,
    )

    avisos_hoje(f)

    st.markdown('<p class="ok-eyebrow" style="margin-top:1.6rem">Por pasto</p>'
                '<div class="ok-secao" style="margin-top:0">Comparar os pastos</div>', unsafe_allow_html=True)
    st.caption("Cada bolha é um pasto. Quanto maior, mais registros. Acima da linha vermelha, a respiração está alta.")
    st.plotly_chart(grafico_dispersao(resumo_por_pasto(f)), **LARGURA_TOTAL,
                    config={"displayModeBar": False})

    fig_itu = grafico_itu_diario(f)
    if fig_itu is not None:
        st.markdown('<p class="ok-eyebrow" style="margin-top:1.6rem">Ao longo do tempo</p>'
                    '<div class="ok-secao" style="margin-top:0">ITU médio por dia</div>', unsafe_allow_html=True)
        st.caption("Quanto mais alto, mais calor sentido pelos animais. As faixas coloridas marcam alerta, perigo e emergência.")
        st.plotly_chart(fig_itu, **LARGURA_TOTAL, config={"displayModeBar": False})

    st.markdown('<p class="ok-eyebrow" style="margin-top:1.6rem">Histórico de alertas</p>'
                '<div class="ok-secao" style="margin-top:0">Lotes em alerta</div>', unsafe_allow_html=True)
    tabela_alertas(f)

    st.write("")
    st.download_button("Baixar dados filtrados (CSV)", data=csv_para_download(f.sort_values("data_hora", ascending=False)),
                       file_name=f"campos_orkavyn_{datetime.now(FUSO):%Y%m%d}.csv", mime="text/csv",
                       key="baixar_csv")


# --- Aba: Histórico ----------------------------------------------------------

def aba_historico(df: pd.DataFrame) -> None:
    if df.empty:
        estado_vazio("exemplos_historico")
        return

    st.markdown('<div class="ok-secao" style="margin-top:.8rem">Todos os registros</div>', unsafe_allow_html=True)
    st.caption(f"{len(df)} registros, do mais recente para o mais antigo.")
    h = df.sort_values(["data_hora", "id"], ascending=False)
    tabela = pd.DataFrame({
        "Nº": h["id"], "Quando": h["data_hora"].dt.strftime("%d/%m/%Y %H:%M"),
        "Observador": h["observador"], "Lote": h["lote"], "Pasto": h["pasto"],
        "Animais": h["n_animais"], "Temp. (°C)": h["temperatura"], "Umid. (%)": h["umidade"],
        "ITU": h["itu"], "Resp. (mov/min)": h["fr"], "Locomoção": h["locomocao"],
        "Situação": h["situacao"], "Observações": h["observacoes"],
    })
    st.dataframe(
        tabela.style.format({"Temp. (°C)": "{:.1f}", "Umid. (%)": "{:.0f}", "ITU": "{:.1f}"}),
        hide_index=True, **LARGURA_TOTAL,
    )

    with st.expander("Excluir um registro"):
        rotulos = {int(r.id): f"Nº {r.id} · {r.data_hora:%d/%m %H:%M} · {r.lote} · {r.pasto}" for r in h.itertuples()}
        escolhido = st.selectbox("Qual registro", list(rotulos), format_func=lambda k: rotulos[k], key="h_excluir")
        confirmar = st.checkbox("Tenho certeza de que quero excluir este registro", key="h_confirma")
        if st.button("Excluir registro", key="h_btn_excluir", disabled=not confirmar):
            excluir_observacao(escolhido)
            st.session_state.pop("h_confirma", None)
            st.rerun()

    if (df["observador"] == OBSERVADOR_EXEMPLO).any():
        with st.expander("Dados de exemplo"):
            st.caption("Remove apenas os registros fictícios; as observações reais continuam.")
            if st.button("Apagar dados de exemplo", key="h_apagar_exemplos"):
                apagar_exemplos()
                st.rerun()
