"""Pagina inicial do GymBrain: visao geral do projeto e do estado dos dados."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src.config import get_session
from src.models.db_models import Exercicio, Registro, Treino

st.set_page_config(page_title="GymBrain", page_icon="🏋️", layout="wide")

st.title("🏋️ GymBrain")
st.subheader("Seu histórico de treino, padronizado e explicável.")

st.markdown(
    """
O **GymBrain** transforma fichas de treino heterogêneas — fotos, PDFs e
prints, vindos de academias e personal trainers diferentes — em uma base
relacional limpa e consultável, e responde perguntas sobre esse histórico
com recomendações **explicáveis**: nenhuma sugestão é uma caixa-preta, toda
recomendação aponta os dados e regras que a embasaram.

- **Fase 1** — pipeline ETL (Airflow + Gemini Vision) extrai, padroniza e
  carrega as fichas num PostgreSQL.
- **Fase 2** — camada de IA combina consultas SQL sobre o histórico, busca
  semântica (RAG) num corpus de conhecimento sobre musculação e regras de
  domínio determinísticas.
- **Fase 3** *(esta interface)* — chat para conversar com o GymBrain e
  dashboard de estatísticas do histórico.
"""
)

st.divider()

session = get_session()
try:
    total_treinos = session.query(Treino).count()
    total_exercicios = session.query(Exercicio).count()
    total_registros = session.query(Registro).count()
finally:
    session.close()

col1, col2, col3 = st.columns(3)
col1.metric("Treinos carregados", total_treinos)
col2.metric("Exercícios catalogados", total_exercicios)
col3.metric("Registros (séries) no histórico", total_registros)

st.divider()

st.markdown(
    """
### Navegação

Use o menu lateral para:
- **💬 Chat** — converse com o GymBrain sobre seu histórico, tire dúvidas
  conceituais sobre treino ou peça uma recomendação de treino para hoje.
- **📊 Dashboard** — visualize estatísticas do histórico: volume por grupo
  muscular, exercícios mais frequentes e a qualidade dos dados extraídos.
"""
)
