"""Dashboard de estatisticas do historico de treinos, reaproveitando src/ai/sql_layer.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import plotly.express as px
import streamlit as st

from src.ai import sql_layer
from src.ai.sql_layer import NAO_MAPEADO
from src.config import get_session
from src.models.db_models import Exercicio, Registro, Treino

st.set_page_config(page_title="GymBrain - Dashboard", page_icon="📊", layout="wide")

st.title("📊 Dashboard do histórico de treinos")
st.caption(
    "Estatísticas calculadas direto sobre o histórico real (PostgreSQL), via "
    "`src/ai/sql_layer.py` — a mesma camada usada pelo chat."
)

session = get_session()
try:
    total_treinos = session.query(Treino).count()
    total_exercicios = session.query(Exercicio).count()
    total_registros = session.query(Registro).count()
    total_nao_mapeados = session.query(Exercicio).filter(Exercicio.nome_canonico == NAO_MAPEADO).count()
finally:
    session.close()

taxa_nao_mapeado = (total_nao_mapeados / total_exercicios) if total_exercicios else 0.0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Treinos", total_treinos)
col2.metric("Exercícios distintos", total_exercicios)
col3.metric("Registros (séries)", total_registros)
col4.metric(
    "Taxa \"Não Mapeado\"",
    f"{taxa_nao_mapeado:.0%}",
    help="Proporção de exercícios catalogados sem grupo muscular reconhecido pelo dicionário canônico — indicador de qualidade dos dados.",
)

st.divider()

col_esq, col_dir = st.columns(2)

with col_esq:
    st.subheader("Volume por grupo muscular")
    volume = sql_layer.volume_total_por_grupo()
    if volume.dados.empty:
        st.info("Sem dados de volume disponíveis.")
    else:
        fig = px.bar(
            volume.dados.sort_values("total_series", ascending=False),
            x="grupo_muscular",
            y="total_series",
            labels={"grupo_muscular": "Grupo muscular", "total_series": "Total de séries"},
        )
        st.plotly_chart(fig, width='stretch')
    st.caption("Considera todo o histórico, com ou sem data registrada.")

with col_dir:
    st.subheader("Exercícios mais frequentes (top 10)")
    frequentes = sql_layer.exercicios_mais_frequentes(limite=10)
    if frequentes.dados.empty:
        st.info("Sem dados de frequência disponíveis.")
    else:
        fig = px.bar(
            frequentes.dados.sort_values("total_registros"),
            x="total_registros",
            y="nome_canonico",
            orientation="h",
            labels={"nome_canonico": "Exercício", "total_registros": "Registros no histórico"},
        )
        st.plotly_chart(fig, width='stretch')
    st.caption('Exclui exercícios "Não Mapeado" — eles não representam um único exercício real.')

st.divider()

col_esq2, col_dir2 = st.columns(2)

with col_esq2:
    st.subheader("Exercícios catalogados por grupo muscular")
    distintos = sql_layer.exercicios_distintos_por_grupo()
    if distintos.dados.empty:
        st.info("Sem exercícios catalogados com grupo muscular conhecido.")
    else:
        fig = px.pie(distintos.dados, names="grupo_muscular", values="total_exercicios")
        st.plotly_chart(fig, width='stretch')
    st.caption("Mede a cobertura do dicionário canônico, não o volume de treino.")

with col_dir2:
    st.subheader("Último treino por grupo muscular")
    ultimo = sql_layer.ultimo_treino_por_grupo()
    st.dataframe(ultimo.dados, width='stretch', hide_index=True)
    if ultimo.treinos_sem_data_ignorados:
        st.caption(
            f"⚠️ {ultimo.treinos_sem_data_ignorados} treino(s) sem data registrada foram "
            "ignorados nesta análise — não há como saber quando ocorreram."
        )
