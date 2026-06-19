from datetime import date

import pandas as pd

from src.ai.explainer import explicar
from src.ai.orchestrator import RespostaGymBrain
from src.ai.rag_layer import ResultadoBusca
from src.ai.sql_layer import ConsultaResultado


class TestExplicar:
    def test_explica_grupos_descansados(self):
        resposta = RespostaGymBrain(
            pergunta="O que treinar hoje?",
            intencao="recomendacao",
            resposta="Treine Peito hoje.",
            fontes=["Histórico de treinos (PostgreSQL)"],
            dados_brutos={"grupos_descansados": ["Peito", "Ombro"]},
        )

        explicacao = explicar(resposta)

        assert "Peito" in explicacao
        assert "Ombro" in explicacao
        assert "descansad" in explicacao.lower()

    def test_explica_ultimo_treino_por_grupo(self):
        dados = pd.DataFrame([{"grupo_muscular": "Peito", "ultimo_treino": date(2026, 6, 10)}])
        resposta = RespostaGymBrain(
            pergunta="Quando treinei peito?",
            intencao="historico",
            resposta="Você treinou peito em 2026-06-10.",
            fontes=["Histórico de treinos (PostgreSQL)"],
            dados_brutos={"ultimo_treino_por_grupo": ConsultaResultado(dados=dados)},
        )

        explicacao = explicar(resposta)

        assert "Peito" in explicacao
        assert "2026-06-10" in explicacao

    def test_explica_fontes_de_conhecimento_consultadas(self):
        resposta = RespostaGymBrain(
            pergunta="O que e deload?",
            intencao="conhecimento",
            resposta="Deload e uma reducao deliberada de volume.",
            fontes=["Corpus de conhecimento: periodizacao.md"],
            dados_brutos={
                "chunks": [ResultadoBusca(texto="...", fonte="periodizacao.md", secao="Deload", distancia=0.1)]
            },
        )

        explicacao = explicar(resposta)

        assert "periodizacao.md" in explicacao

    def test_sem_fontes_e_explicito(self):
        resposta = RespostaGymBrain(pergunta="Oi", intencao="mista", resposta="Oi!", fontes=[], dados_brutos={})

        explicacao = explicar(resposta)

        assert "nenhuma fonte" in explicacao.lower()
