"""Constantes do projeto: limiares fisiológicos, limites de validação e identidade visual."""

import os
from datetime import timedelta, timezone
from pathlib import Path

# =============================================================================
# 1. CONSTANTES (limiares e identidade visual — fáceis de ajustar)
# =============================================================================

APP_NOME = "Campos Orkavyn"
APP_TITULO = "Painel de Conforto do Rebanho"

# Vilhena-RO fica em UTC-4 (Rondônia não adota horário de verão).
FUSO = timezone(timedelta(hours=-4))

DB_PATH = os.environ.get(
    "ORKAVYN_DB", str(Path(__file__).resolve().parent.parent / "campos_orkavyn.db")
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
COR_MARCA = "#1B3022"        # verde profundo da marca (mesmo do Orkavyn Fields)
COR_MARCA_ESCURA = "#284832"
COR_FUNDO = "#FBF9F4"        # canvas off-white
COR_CARTAO = "#FFFEFA"       # papel
COR_TEXTO = "#1B1C19"        # grafite
COR_TEXTO_SUAVE = "#737973"
COR_LINHA = "#C3C8C1"
COR_TERRA = "#805533"        # marrom terra (detalhes e links)
COR_PALHA = "#D4A373"        # couro/palha
COR_VERDE_SUAVE = "#DCE9DD"  # fundo verde claro
# Cores de status (só para status). Validadas com o validador de paletas
# (separação para daltônicos e contraste): ver README do projeto.
COR_OK = "#2F7D4E"
COR_ATENCAO = "#D4A017"      # âmbar
COR_CRITICO = "#B3382B"
COR_SANITARIO = "#3B6FC0"    # azul: problema NÃO térmico
FUNDO_CRITICO = "#FFEBE7"    # vermelho suave (linhas críticas)
FUNDO_ATENCAO = "#FFF4DC"    # âmbar suave
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

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
