"""
Campos Orkavyn — Painel Analítico de Fisiologia e Conforto de Rebanho
=====================================================================
Projeto de extensão — Anatomia e Fisiologia Animal (Agronomia) — Vilhena-RO.

Cruza o clima (ITU) com a observação clínica real (frequência respiratória e
escore de locomoção) para separar ESTRESSE TÉRMICO de PROBLEMA SANITÁRIO.

Como rodar:  streamlit run app.py
"""

from __future__ import annotations

import html
import math
import os
import random
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# 1. CONSTANTES (limiares e identidade visual — fáceis de ajustar)
# =============================================================================

APP_NOME = "Campos Orkavyn"
APP_TITULO = "Painel de Conforto do Rebanho"

# Vilhena-RO fica em UTC-4 (Rondônia não adota horário de verão).
FUSO = timezone(timedelta(hours=-4))

DB_PATH = os.environ.get(
    "ORKAVYN_DB", str(Path(__file__).resolve().with_name("campos_orkavyn.db"))
)
OBSERVADOR_EXEMPLO = "Dados de exemplo"

# --- Limites de validação dos formulários (valores aceitos no campo) ---------
T_MIN, T_MAX = -5.0, 50.0        # temperatura do ar (°C)
UR_MIN, UR_MAX = 0.0, 100.0      # umidade relativa (%)
FR_MIN, FR_MAX = 5, 200          # frequência respiratória (mov/min)
LOC_MIN, LOC_MAX = 1, 5          # escore de locomoção
N_ANIMAIS_MAX = 5000

# --- Faixas do ITU para bovinos de corte -------------------------------------
# Fonte das faixas: Livestock Conservation Institute (LCI, 1970), "Patterns of
# transit losses", Omaha. Usadas amplamente em bovinos; ver também Hahn (1999).
#   ITU <= 74  -> conforto | 75-78 -> alerta | 79-83 -> perigo | >= 84 -> emergência
# Como o ITU é arredondado em 1 casa decimal, usamos "menor que o início da
# próxima faixa" (ex.: 74,6 ainda é conforto; 75,0 já é alerta).
ITU_ALERTA_MIN = 75.0
ITU_PERIGO_MIN = 79.0
ITU_EMERGENCIA_MIN = 84.0

# --- Frequência respiratória (mov/min) ---------------------------------------
# Faixas adaptadas de Hahn (1999) e Silanikove (2000): até ~40 mov/min é
# resposta normal/leve; de 40 a 60 há resposta térmica de baixa intensidade;
# acima de 60 há estresse moderado a severo. Ajuste conforme o orientador.
FR_NORMAL_MAX = 40       # <= 40  -> normal
FR_ELEVADA_MAX = 60      # 41-60  -> elevada | > 60 -> alta

# --- Escore de locomoção (1 a 5) ---------------------------------------------
# Escala de 5 pontos de Sprecher, Hostetler & Kaneene (1997), adaptada para
# corte: 1 normal ... 5 muito claudicante. Acima de 3 = claudicação evidente.
LOC_ALERTA_ACIMA_DE = 3
LOC_GRAVE_MIN = 5

# --- Identidade visual: Campos Orkavyn ---------------------------------------
# >>> SUBSTITUIR PELOS TOKENS HEX OFICIAIS DO CAMPOS ORKAVYN <<<
COR_MARCA = "#2F6B45"        # verde da marca (único verde "de marca")
COR_MARCA_ESCURA = "#245336"
COR_FUNDO = "#FAFAF7"        # off-white
COR_CARTAO = "#FFFFFF"
COR_TEXTO = "#1D1D1F"        # grafite
COR_TEXTO_SUAVE = "#6E6E73"
COR_LINHA = "#E8E8E3"
# Cores de status (só para status)
COR_OK = "#34A853"
COR_ATENCAO = "#E8A317"      # âmbar
COR_CRITICO = "#D93025"
COR_SANITARIO = "#5B6B8C"    # azul-acinzentado: problema NÃO térmico
FUNDO_CRITICO = "#FDECEA"    # vermelho suave (linhas críticas)
FUNDO_ATENCAO = "#FFF4DC"    # âmbar suave

# --- Classificações ----------------------------------------------------------
CLASS_CONFORTO = "Conforto"
CLASS_SANITARIO = "Possível problema sanitário"
CLASS_ESTRESSE = "Estresse térmico"
CLASS_RISCO = "Risco ambiental"
ALERTA_LOCOMOTOR = "Alerta locomotor"

# Quais classificações exigem intervenção e quais só pedem monitoramento.
CLASSES_INTERVENCAO = {CLASS_ESTRESSE, CLASS_SANITARIO}
CLASSES_MONITORAR = {CLASS_RISCO}

COR_CLASSE = {
    CLASS_CONFORTO: COR_OK,
    CLASS_RISCO: COR_ATENCAO,
    CLASS_ESTRESSE: COR_CRITICO,
    CLASS_SANITARIO: COR_SANITARIO,
}
# Ordem de gravidade (usada para desempate e ordenação)
GRAVIDADE_CLASSE = {CLASS_CONFORTO: 0, CLASS_RISCO: 1, CLASS_SANITARIO: 2, CLASS_ESTRESSE: 3}

ROTULO_FAIXA_ITU = {
    "conforto": "Conforto",
    "alerta": "Alerta",
    "perigo": "Perigo",
    "emergencia": "Emergência",
}
ROTULO_FAIXA_FR = {"normal": "Normal", "elevada": "Elevada", "alta": "Alta"}

ROTULO_LOCOMOCAO = {
    1: "1 – Anda normalmente",
    2: "2 – Levemente alterado",
    3: "3 – Passo curto, cuidadoso",
    4: "4 – Mancando, claro",
    5: "5 – Muito mancando / relutante",
}

# Streamlit novo (>= 1.50) usa width="stretch"; o antigo usa use_container_width.
_VERSAO = tuple(int(p) for p in re.findall(r"\d+", st.__version__)[:2])
LARGURA_TOTAL = {"width": "stretch"} if _VERSAO >= (1, 50) else {"use_container_width": True}

# =============================================================================
# 2. BANCO DE DADOS (SQLite)
# =============================================================================

COLUNAS_BANCO = [
    "id", "data_hora", "observador", "lote", "pasto", "n_animais",
    "temperatura", "umidade", "fr", "locomocao", "observacoes",
]


def conectar() -> sqlite3.Connection:
    """Abre uma conexão com o banco SQLite do projeto."""
    return sqlite3.connect(DB_PATH)


def criar_tabelas() -> None:
    """Cria a tabela na primeira execução (não faz nada se já existir)."""
    with closing(conectar()) as con, con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS observacoes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                data_hora   TEXT    NOT NULL,
                observador  TEXT,
                lote        TEXT    NOT NULL,
                pasto       TEXT    NOT NULL,
                n_animais   INTEGER NOT NULL CHECK (n_animais >= 1),
                temperatura REAL    NOT NULL CHECK (temperatura BETWEEN -5 AND 50),
                umidade     REAL    NOT NULL CHECK (umidade BETWEEN 0 AND 100),
                fr          INTEGER NOT NULL CHECK (fr BETWEEN 5 AND 200),
                locomocao   INTEGER NOT NULL CHECK (locomocao BETWEEN 1 AND 5),
                observacoes TEXT
            )
            """
        )


def inserir_observacao(d: dict) -> None:
    """Grava uma observação (consulta parametrizada)."""
    with closing(conectar()) as con, con:
        con.execute(
            """
            INSERT INTO observacoes
                (data_hora, observador, lote, pasto, n_animais,
                 temperatura, umidade, fr, locomocao, observacoes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                d["data_hora"], d["observador"], d["lote"], d["pasto"],
                d["n_animais"], d["temperatura"], d["umidade"], d["fr"],
                d["locomocao"], d["observacoes"],
            ),
        )


def inserir_varias(linhas: list[dict]) -> None:
    """Grava várias observações de uma vez (usado nos dados de exemplo)."""
    with closing(conectar()) as con, con:
        con.executemany(
            """
            INSERT INTO observacoes
                (data_hora, observador, lote, pasto, n_animais,
                 temperatura, umidade, fr, locomocao, observacoes)
            VALUES (:data_hora, :observador, :lote, :pasto, :n_animais,
                    :temperatura, :umidade, :fr, :locomocao, :observacoes)
            """,
            linhas,
        )


def carregar_observacoes() -> pd.DataFrame:
    """Lê todas as observações do banco como DataFrame (sem cálculos)."""
    with closing(conectar()) as con:
        df = pd.read_sql_query(
            "SELECT id, data_hora, observador, lote, pasto, n_animais, "
            "temperatura, umidade, fr, locomocao, observacoes "
            "FROM observacoes ORDER BY data_hora DESC, id DESC",
            con,
        )
    df["data_hora"] = pd.to_datetime(df["data_hora"])
    return df


def excluir_observacao(obs_id: int) -> None:
    with closing(conectar()) as con, con:
        con.execute("DELETE FROM observacoes WHERE id = ?", (int(obs_id),))


def apagar_exemplos() -> int:
    """Remove só os registros fictícios de exemplo. Devolve quantos foram."""
    with closing(conectar()) as con, con:
        cur = con.execute(
            "DELETE FROM observacoes WHERE observador = ?", (OBSERVADOR_EXEMPLO,)
        )
        return cur.rowcount


# =============================================================================
# 3. MOTOR DE ANÁLISE CRUZADA (funções puras, sem Streamlit)
# =============================================================================

def calcular_itu(temperatura: float, umidade: float) -> float:
    """
    Índice de Temperatura e Umidade (Thom, 1959):

        ITU = 0,8·T + (UR/100)·(T − 14,4) + 46,4

    T em °C e UR em %. O termo 0,8·T pesa o calor sensível; o termo com UR
    corrige pelo efeito da umidade, que reduz a perda de calor por evaporação.
    Resultado arredondado em 1 casa para que o valor mostrado e a faixa
    classificada sejam sempre coerentes.
    Ref.: Thom, E. C. (1959). The discomfort index. Weatherwise, 12(2), 57–61.
    """
    return round(0.8 * temperatura + (umidade / 100.0) * (temperatura - 14.4) + 46.4, 1)


def classificar_itu(itu: float) -> str:
    """Faixa do ITU para bovinos de corte (LCI, 1970): ver constantes no topo."""
    if itu >= ITU_EMERGENCIA_MIN:
        return "emergencia"
    if itu >= ITU_PERIGO_MIN:
        return "perigo"
    if itu >= ITU_ALERTA_MIN:
        return "alerta"
    return "conforto"


def classificar_fr(fr: float) -> str:
    """Faixa da frequência respiratória (Hahn, 1999; Silanikove, 2000)."""
    if fr > FR_ELEVADA_MAX:
        return "alta"
    if fr > FR_NORMAL_MAX:
        return "elevada"
    return "normal"


# Ações recomendadas, por classificação e faixa de ITU (linguagem simples).
_ACAO_ESTRESSE = {
    "alerta": "Oferecer sombra e água fresca à vontade e evitar mexer no lote nas horas mais quentes.",
    "perigo": "Garantir sombra e água fresca, levar o manejo para antes das 8h ou depois das 17h e vigiar o lote de perto.",
    "emergencia": "Suspender qualquer manejo. Sombra, água fresca e, se possível, aspersão. Acompanhar o lote o dia todo e chamar o veterinário se piorar.",
}
_ACAO_RISCO = {
    "alerta": "Animais se ajustando ao calor. Conferir sombra e água e medir de novo em algumas horas.",
    "perigo": "Calor forte, mas os animais ainda compensam. Conferir sombra e água, adiar o manejo para o fim da tarde e medir de novo em 1–2 horas.",
    "emergencia": "Calor extremo. Os animais ainda compensam, mas podem piorar rápido: garantir sombra e água agora, suspender manejo e medir de novo em 1 hora.",
}
_ACAO_SANITARIO = (
    "O clima está confortável, mas a respiração está acelerada: pode ser doença, não calor. "
    "Separar os animais com sinal de problema, medir a temperatura do corpo e chamar o veterinário."
)
_ACAO_CONFORTO = "Tudo certo. Seguir o manejo normal."
_ACAO_CONFORTO_FR_ELEVADA = "Clima confortável, mas a respiração está um pouco acima do normal. Medir de novo mais tarde."
_ACAO_LOCOMOCAO = {
    "atencao": "Locomoção alterada: olhar cascos e piso do local, separar o animal que manca e avisar o veterinário.",
    "critico": "Locomoção muito ruim: chamar o veterinário ainda hoje e evitar fazer o animal andar.",
}


@dataclass(frozen=True)
class Diagnostico:
    itu: float
    faixa_itu: str            # conforto | alerta | perigo | emergencia
    faixa_fr: str             # normal | elevada | alta
    categoria: str            # classificação da matriz ITU × FR
    alerta_locomotor: bool    # escore de locomoção > 3
    nivel: str                # ok | atencao | critico (já considera a locomoção)
    exige_atencao: bool       # entra na tabela "Lotes em Alerta"?
    acao: str                 # ação recomendada (térmica + locomotora)

    @property
    def situacao(self) -> str:
        """Classificação completa, somando o alerta locomotor quando houver."""
        return f"{self.categoria} + {ALERTA_LOCOMOTOR}" if self.alerta_locomotor else self.categoria


def diagnosticar(temperatura: float, umidade: float, fr: float, locomocao: int) -> Diagnostico:
    """
    Matriz de diagnóstico ITU × FR.

        ITU conforto  + FR normal  -> Conforto
        ITU conforto  + FR alta    -> Possível problema sanitário (NÃO térmico):
                                      o ambiente não explica a respiração acelerada.
        ITU ≥ alerta  + FR alta    -> Estresse térmico (intervir no manejo)
        ITU ≥ alerta  + FR normal  -> Risco ambiental (animais compensando)

    Decisão de projeto: a faixa "elevada" (41–60 mov/min) não aparece na
    matriz do enunciado. Aqui ela segue o lado "normal" (só > 60 conta como
    "alta", o mesmo limiar da linha de referência do gráfico). Em ITU de
    conforto, FR elevada continua "Conforto", mas a ação pede nova medida.

    A locomoção é regra independente (escore > 3 => Alerta locomotor) e se soma.
    """
    itu = calcular_itu(temperatura, umidade)
    faixa_itu = classificar_itu(itu)
    faixa_fr = classificar_fr(fr)
    fr_alta = faixa_fr == "alta"
    itu_conforto = faixa_itu == "conforto"

    if itu_conforto and not fr_alta:
        categoria, nivel = CLASS_CONFORTO, "ok"
        acao = _ACAO_CONFORTO_FR_ELEVADA if faixa_fr == "elevada" else _ACAO_CONFORTO
    elif itu_conforto and fr_alta:
        categoria, nivel, acao = CLASS_SANITARIO, "critico", _ACAO_SANITARIO
    elif fr_alta:
        categoria, nivel, acao = CLASS_ESTRESSE, "critico", _ACAO_ESTRESSE[faixa_itu]
    else:
        categoria, nivel, acao = CLASS_RISCO, "atencao", _ACAO_RISCO[faixa_itu]

    alerta_loc = locomocao > LOC_ALERTA_ACIMA_DE
    if alerta_loc:
        nivel_loc = "critico" if locomocao >= LOC_GRAVE_MIN else "atencao"
        acao = f"{acao} {_ACAO_LOCOMOCAO[nivel_loc]}" if categoria != CLASS_CONFORTO else _ACAO_LOCOMOCAO[nivel_loc]
        ordem = {"ok": 0, "atencao": 1, "critico": 2}
        if ordem[nivel_loc] > ordem[nivel]:
            nivel = nivel_loc

    exige_atencao = alerta_loc or categoria in CLASSES_INTERVENCAO
    return Diagnostico(itu, faixa_itu, faixa_fr, categoria, alerta_loc, nivel, exige_atencao, acao)


def validar_observacao(d: dict) -> list[str]:
    """Valida o formulário. Devolve lista de mensagens simples (vazia = ok)."""
    erros: list[str] = []
    if not (d.get("lote") or "").strip():
        erros.append("Informe o lote.")
    if not (d.get("pasto") or "").strip():
        erros.append("Informe o pasto.")

    n = d.get("n_animais")
    if n is None or n < 1:
        erros.append("Informe quantos animais foram observados (pelo menos 1).")
    elif n > N_ANIMAIS_MAX:
        erros.append(f"O número de animais parece alto demais (máximo {N_ANIMAIS_MAX}). Confira o valor.")

    t, ur, fr = d.get("temperatura"), d.get("umidade"), d.get("fr")
    if t is None:
        erros.append("Informe a temperatura do ar.")
    elif not (T_MIN <= t <= T_MAX):
        erros.append(f"A temperatura precisa estar entre {T_MIN:.0f} e {T_MAX:.0f} °C. Confira o termômetro.")
    if ur is None:
        erros.append("Informe a umidade do ar.")
    elif not (UR_MIN <= ur <= UR_MAX):
        erros.append(f"A umidade precisa estar entre {UR_MIN:.0f} e {UR_MAX:.0f} %. Confira o aparelho.")
    if fr is None:
        erros.append("Informe a frequência respiratória (movimentos por minuto).")
    elif not (FR_MIN <= fr <= FR_MAX):
        erros.append(f"A respiração precisa estar entre {FR_MIN} e {FR_MAX} movimentos por minuto. Confira a contagem.")
    return erros


def enriquecer(df: pd.DataFrame) -> pd.DataFrame:
    """
    Acrescenta ao DataFrame as colunas calculadas (ITU, faixas, classificação,
    alerta locomotor, ação). Calcula na leitura, então mudar um limiar no topo
    do arquivo vale também para os registros antigos.
    """
    df = df.copy()
    colunas = ["itu", "faixa_itu", "faixa_fr", "classificacao", "alerta_locomotor",
               "nivel", "exige_atencao", "situacao", "acao"]
    if df.empty:
        for c in colunas:
            df[c] = pd.Series(dtype="object")
        return df
    diag = [diagnosticar(r.temperatura, r.umidade, r.fr, int(r.locomocao)) for r in df.itertuples()]
    df["itu"] = [x.itu for x in diag]
    df["faixa_itu"] = [x.faixa_itu for x in diag]
    df["faixa_fr"] = [x.faixa_fr for x in diag]
    df["classificacao"] = [x.categoria for x in diag]
    df["alerta_locomotor"] = [x.alerta_locomotor for x in diag]
    df["nivel"] = [x.nivel for x in diag]
    df["exige_atencao"] = [x.exige_atencao for x in diag]
    df["situacao"] = [x.situacao for x in diag]
    df["acao"] = [x.acao for x in diag]
    return df


def filtrar(df: pd.DataFrame, inicio: date | None, fim: date | None,
            pastos: list[str], lotes: list[str]) -> pd.DataFrame:
    """Aplica período, pasto e lote (listas vazias = sem filtro)."""
    if df.empty:
        return df
    m = pd.Series(True, index=df.index)
    if inicio is not None:
        m &= df["data_hora"].dt.date >= inicio
    if fim is not None:
        m &= df["data_hora"].dt.date <= fim
    if pastos:
        m &= df["pasto"].isin(pastos)
    if lotes:
        m &= df["lote"].isin(lotes)
    return df[m]


def classificacao_predominante(g: pd.DataFrame) -> str:
    """Classificação mais frequente do grupo; empate resolvido pela mais grave."""
    contagem = g["classificacao"].value_counts()
    return max(contagem.index, key=lambda c: (contagem[c], GRAVIDADE_CLASSE[c]))


def resumo_por_pasto(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por pasto: T média, FR média, classe predominante, nº de registros."""
    linhas = [
        {
            "pasto": pasto,
            "temperatura": g["temperatura"].mean(),
            "fr": g["fr"].mean(),
            "classificacao": classificacao_predominante(g),
            "registros": len(g),
        }
        for pasto, g in df.groupby("pasto")
    ]
    return pd.DataFrame(linhas, columns=["pasto", "temperatura", "fr", "classificacao", "registros"])


def gerar_exemplos(semente: int = 42) -> list[dict]:
    """
    ~30 registros fictícios cobrindo os 4 quadrantes da matriz. Cada registro é
    sorteado dentro de faixas típicas e conferido pelo próprio motor de análise,
    garantindo que cai mesmo na classificação desejada.
    """
    rng = random.Random(semente)
    faixas = {  # (T, UR, FR) mín-máx por quadrante
        CLASS_CONFORTO: ((19, 26), (45, 75), (28, 40)),
        CLASS_SANITARIO: ((19, 25), (45, 70), (62, 82)),
        CLASS_ESTRESSE: ((29, 35), (40, 70), (62, 95)),
        CLASS_RISCO: ((28, 33), (40, 65), (36, 58)),
    }
    plano = (
        [("Pasto Boa Vista", "Lote A", CLASS_CONFORTO)] * 8
        + [("Pasto Sombra Verde", "Lote B", CLASS_CONFORTO)] * 3
        + [("Pasto Sombra Verde", "Lote B", CLASS_RISCO)] * 3
        + [("Pasto Cerrado", "Lote C", CLASS_ESTRESSE)] * 7
        + [("Pasto Cerrado", "Lote C", CLASS_RISCO)] * 1
        + [("Pasto Baixada", "Lote D", CLASS_SANITARIO)] * 5
        + [("Pasto Aroeira", "Lote E", CLASS_RISCO)] * 4
        + [("Pasto Aroeira", "Lote E", CLASS_ESTRESSE)] * 1
    )
    rng.shuffle(plano)
    agora = datetime.now(FUSO).replace(second=0, microsecond=0, tzinfo=None)
    # Alguns escores de locomoção ruins, espalhados entre os registros.
    loc_forcada = {2: 4, 9: 4, 17: 4, 25: 5}
    linhas = []
    for i, (pasto, lote, alvo) in enumerate(plano):
        (t0, t1), (u0, u1), (f0, f1) = faixas[alvo]
        for _ in range(500):
            t = round(rng.uniform(t0, t1), 1)
            ur = float(rng.randint(u0, u1))
            fr = rng.randint(f0, f1)
            if diagnosticar(t, ur, fr, 1).categoria == alvo:
                break
        loc = loc_forcada.get(i, rng.choices([1, 2, 3], weights=[55, 33, 12])[0])
        quando = agora - timedelta(days=rng.randint(0, 13), hours=rng.randint(0, 9), minutes=rng.randint(0, 59))
        linhas.append({
            "data_hora": quando.strftime("%Y-%m-%d %H:%M"),
            "observador": OBSERVADOR_EXEMPLO,
            "lote": lote, "pasto": pasto,
            "n_animais": rng.randint(8, 40),
            "temperatura": t, "umidade": ur, "fr": fr, "locomocao": loc,
            "observacoes": "Registro fictício para demonstração.",
        })
    return linhas


# =============================================================================
# 4. COMPONENTES DE UI
# =============================================================================

CSS = f"""
<style>
:root {{ color-scheme: light; }}
#MainMenu, footer, header, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"] {{ display: none !important; visibility: hidden; }}

html, body, .stApp, [class*="css"] {{
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", Inter, "Segoe UI", Roboto, sans-serif;
}}
.stApp {{ background: {COR_FUNDO}; color: {COR_TEXTO}; }}
.block-container {{ max-width: 860px; padding: 1.4rem 1rem 4rem 1rem; }}
h1, h2, h3, h4, p, label, span, li {{ color: {COR_TEXTO}; }}
[data-testid="stWidgetLabel"] p {{ font-size: 1rem; font-weight: 600; color: {COR_TEXTO}; }}
[data-testid="stCaptionContainer"], small {{ color: {COR_TEXTO_SUAVE}; }}

/* Cabeçalho da marca */
.ok-marca {{ font-size: .8rem; letter-spacing: .14em; text-transform: uppercase; font-weight: 700; color: {COR_MARCA}; margin: 0; }}
.ok-titulo {{ font-size: 1.9rem; line-height: 1.15; font-weight: 700; letter-spacing: -.02em; margin: .15rem 0 1.1rem 0; }}
.ok-secao {{ font-size: 1.25rem; font-weight: 700; letter-spacing: -.01em; margin: 1.6rem 0 .6rem 0; }}

/* Abas */
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; background: #EFEFEA; padding: 5px; border-radius: 16px; }}
.stTabs [data-baseweb="tab"] {{ flex: 1; justify-content: center; height: 48px; border-radius: 12px; font-size: 1.02rem; font-weight: 600; color: {COR_TEXTO_SUAVE}; background: transparent; }}
.stTabs [aria-selected="true"] {{ background: {COR_CARTAO}; color: {COR_TEXTO}; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display: none; }}

/* Formulário e cartões */
[data-testid="stForm"] {{ background: {COR_CARTAO}; border: none; border-radius: 20px; padding: 1.2rem 1.1rem; box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 6px 20px rgba(0,0,0,.04); }}
.ok-cartao {{ background: {COR_CARTAO}; border-radius: 18px; padding: 1.1rem 1.2rem; box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 6px 20px rgba(0,0,0,.04); }}
.ok-grade {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: .4rem 0 .6rem 0; }}
.ok-kpi-rotulo {{ font-size: .82rem; color: {COR_TEXTO_SUAVE}; font-weight: 600; }}
.ok-kpi-valor {{ font-size: 2.1rem; font-weight: 700; letter-spacing: -.02em; line-height: 1.15; margin-top: .2rem; }}
.ok-kpi-sub {{ font-size: .8rem; color: {COR_TEXTO_SUAVE}; margin-top: .15rem; }}
.ok-chip {{ display: inline-block; padding: .22rem .7rem; border-radius: 999px; font-size: .82rem; font-weight: 700; color: #fff; }}
.ok-itu {{ font-size: 2.8rem; font-weight: 700; letter-spacing: -.03em; line-height: 1; }}
.ok-acao {{ margin-top: .7rem; font-size: 1rem; line-height: 1.45; }}
.ok-vazio {{ text-align: center; padding: 2.2rem 1rem; }}
.ok-vazio h3 {{ margin: 0 0 .4rem 0; font-size: 1.3rem; }}

/* Campos grandes, alto contraste, fáceis de tocar */
.stTextInput input, .stNumberInput input, .stDateInput input, .stTimeInput input, .stTextArea textarea,
[data-baseweb="select"] > div {{
  min-height: 3.2rem; font-size: 1.1rem !important; border-radius: 14px !important;
  background: #fff !important; color: {COR_TEXTO} !important; border: 1.5px solid #CFCFC8 !important;
}}
.stTextArea textarea {{ min-height: 5.5rem; }}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {{ border-color: {COR_MARCA} !important; box-shadow: 0 0 0 3px {COR_MARCA}33 !important; }}
.stNumberInput button {{ min-height: 3.2rem; }}

/* Botões */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {{
  min-height: 3.5rem; width: 100%; border-radius: 14px; font-size: 1.08rem; font-weight: 700;
  border: 1.5px solid #CFCFC8; background: #fff; color: {COR_TEXTO};
}}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"],
.stDownloadButton > button[kind="primary"] {{
  background: {COR_MARCA}; border-color: {COR_MARCA}; color: #fff;
}}
.stButton > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"]:hover {{ background: {COR_MARCA_ESCURA}; border-color: {COR_MARCA_ESCURA}; color: #fff; }}
.stButton > button[kind="primary"] p, [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"] p {{ color: #fff; }}

[data-testid="stAlert"] {{ border-radius: 14px; }}
[data-testid="stDataFrame"] {{ border-radius: 14px; overflow: hidden; }}

@media (max-width: 640px) {{
  .ok-titulo {{ font-size: 1.55rem; }}
  .ok-kpi-valor {{ font-size: 1.8rem; }}
}}
</style>
"""


def aplicar_estilo() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def chip(texto: str, cor: str) -> str:
    return f'<span class="ok-chip" style="background:{cor}">{html.escape(texto)}</span>'


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
    for classe in COR_CLASSE:
        sub = resumo[resumo["classificacao"] == classe]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["temperatura"], y=sub["fr"], mode="markers+text", name=classe,
            text=sub["pasto"], textposition="top center", textfont=dict(size=12, color=COR_TEXTO),
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
        + cartao_kpi("Registros", f"{len(f)}")
        + cartao_kpi("ITU médio", f"{itu_medio:.1f}", chip(ROTULO_FAIXA_ITU[faixa_medio], cor_faixa))
        + cartao_kpi("Respiração média", f"{f['fr'].mean():.0f}", "movimentos por minuto")
        + cartao_kpi("Lotes em alerta", f"{lotes_alerta}",
                     "com ao menos um registro de alerta" if lotes_alerta else "nenhum no período")
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="ok-secao">Calor ou doença? Veja por pasto</div>', unsafe_allow_html=True)
    st.caption("Cada bolha é um pasto. Quanto maior, mais registros. Acima da linha vermelha, a respiração está alta.")
    st.plotly_chart(grafico_dispersao(resumo_por_pasto(f)), **LARGURA_TOTAL,
                    config={"displayModeBar": False})

    st.markdown('<div class="ok-secao">Lotes em alerta</div>', unsafe_allow_html=True)
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


# =============================================================================
# 5. MAIN
# =============================================================================

def main() -> None:
    st.set_page_config(page_title=f"{APP_NOME} · {APP_TITULO}", page_icon="🌿",
                       layout="centered", initial_sidebar_state="collapsed")
    aplicar_estilo()
    criar_tabelas()

    st.markdown(f'<p class="ok-marca">{APP_NOME}</p><h1 class="ok-titulo">{APP_TITULO}</h1>',
                unsafe_allow_html=True)

    df = enriquecer(carregar_observacoes())
    aba1, aba2, aba3 = st.tabs(["Registrar", "Painel", "Histórico"])
    with aba1:
        aba_registrar()
    with aba2:
        aba_painel(df)
    with aba3:
        aba_historico(df)


if __name__ == "__main__":
    main()
