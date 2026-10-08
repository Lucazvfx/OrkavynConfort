"""Backend — motor de análise cruzada (funções puras, sem Streamlit nem banco)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from .config import *  # noqa: F401,F403 — constantes e limiares


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


def ultimos_por_lote(df: pd.DataFrame) -> pd.DataFrame:
    """Só a observação mais recente de cada lote (o retrato "de agora")."""
    if df.empty:
        return df
    return df.sort_values("data_hora").groupby("lote", as_index=False).tail(1)


def lotes_para_agir(df: pd.DataFrame) -> pd.DataFrame:
    """Lotes cuja observação mais recente exige atenção, do mais grave ao menos."""
    ult = ultimos_por_lote(df)
    if ult.empty:
        return ult
    ult = ult[ult["exige_atencao"]].copy()
    ult["_peso"] = ult["nivel"].map({"critico": 2, "atencao": 1, "ok": 0})
    return ult.sort_values(["_peso", "data_hora"], ascending=[False, False]).drop(columns="_peso")


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
