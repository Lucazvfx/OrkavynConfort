"""
Campos Orkavyn — Painel Analítico de Fisiologia e Conforto de Rebanho
Projeto de extensão — Anatomia e Fisiologia Animal (Agronomia) — Vilhena-RO.

Estrutura:
  orkavyn/config.py  constantes (limiares, limites, cores)        [backend]
  orkavyn/db.py      banco SQLite                                  [backend]
  orkavyn/motor.py   motor de análise cruzada (funções puras)      [backend]
  orkavyn/ui.py      estilo, componentes e abas do Streamlit       [frontend]

Como rodar:  streamlit run app.py
"""

import streamlit as st

from orkavyn.config import APP_NOME, APP_TITULO, ASSETS_DIR
from orkavyn.db import carregar_observacoes, criar_tabelas
from orkavyn.motor import enriquecer
from orkavyn.ui import aba_historico, aba_painel, aba_registrar, aplicar_estilo, topo_marca


def main() -> None:
    st.set_page_config(page_title=f"{APP_NOME} · {APP_TITULO}", page_icon=str(ASSETS_DIR / "logo.png"),
                       layout="centered", initial_sidebar_state="collapsed")
    aplicar_estilo()
    criar_tabelas()

    topo_marca()

    df = enriquecer(carregar_observacoes())
    aba1, aba2, aba3 = st.tabs(["Registrar", "Painel", "Histórico"])
    with aba1:
        aba_registrar()
    with aba2:
        aba_painel(df)
    with aba3:
        aba_historico(df)


main()
