"""Pagina de chat: conversa com o GymBrain reaproveitando o orquestrador da Fase 2."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from src.ai.explainer import explicar
from src.ai.orchestrator import responder
from src.gemini_client import DailyQuotaExceededError

st.set_page_config(page_title="GymBrain - Chat", page_icon="💬", layout="wide")

st.title("💬 Chat com o GymBrain")
st.caption(
    "Pergunte sobre seu histórico de treino, tire dúvidas conceituais ou peça uma recomendação. "
    "Cada resposta vem com uma explicação rastreável aos dados e regras que a geraram."
)

PERGUNTAS_SUGERIDAS = [
    "Quais grupos musculares não treino há mais tempo?",
    "Qual a melhor faixa de repetições para hipertrofia?",
    "Monta um treino pra hoje",
]

if "mensagens" not in st.session_state:
    st.session_state.mensagens = []


def _renderizar_mensagem(mensagem: dict) -> None:
    with st.chat_message(mensagem["role"]):
        st.markdown(mensagem["content"])
        if mensagem.get("explicacao"):
            with st.expander("Por que essa resposta?"):
                st.markdown(mensagem["explicacao"])


def _processar_pergunta(pergunta: str) -> None:
    st.session_state.mensagens.append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)

    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            try:
                resposta = responder(pergunta)
                explicacao = explicar(resposta)
            except DailyQuotaExceededError:
                aviso = (
                    "⚠️ O limite diário gratuito de requisições à Gemini API foi atingido. "
                    "Tente de novo depois do reset diário da API, ou explore o **Dashboard** "
                    "enquanto isso — ele não depende dessa cota."
                )
                st.warning(aviso)
                st.session_state.mensagens.append({"role": "assistant", "content": aviso})
                return
        st.markdown(resposta.resposta)
        with st.expander("Por que essa resposta?"):
            st.markdown(explicacao)
    st.session_state.mensagens.append(
        {"role": "assistant", "content": resposta.resposta, "explicacao": explicacao}
    )


for mensagem in st.session_state.mensagens:
    _renderizar_mensagem(mensagem)

if not st.session_state.mensagens:
    st.markdown("**Experimente perguntar:**")
    colunas = st.columns(len(PERGUNTAS_SUGERIDAS))
    for coluna, pergunta_sugerida in zip(colunas, PERGUNTAS_SUGERIDAS):
        if coluna.button(pergunta_sugerida, width='stretch'):
            st.session_state.pergunta_pendente = pergunta_sugerida
            st.rerun()

pergunta = st.chat_input("Pergunte algo sobre seu treino...")
if not pergunta and "pergunta_pendente" in st.session_state:
    pergunta = st.session_state.pop("pergunta_pendente")

if pergunta:
    _processar_pergunta(pergunta)
