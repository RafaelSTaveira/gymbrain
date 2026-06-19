from src.ai import orchestrator


class TestClassificarPorHeuristica:
    def test_pergunta_sobre_historico(self):
        categoria = orchestrator._classificar_por_heuristica("Quantas series eu fiz de peito no ultimo mes?")

        assert categoria == "historico"

    def test_pergunta_conceitual_e_conhecimento(self):
        categoria = orchestrator._classificar_por_heuristica("O que e hipertrofia muscular?")

        assert categoria == "conhecimento"

    def test_pedido_de_sugestao_e_recomendacao(self):
        categoria = orchestrator._classificar_por_heuristica("Monta um treino de peito para hoje")

        assert categoria == "recomendacao"

    def test_empate_entre_categorias_e_mista(self):
        categoria = orchestrator._classificar_por_heuristica("Ultimo treino de peito e deload")

        assert categoria == "mista"

    def test_pergunta_sem_palavra_chave_e_ambigua(self):
        categoria = orchestrator._classificar_por_heuristica("Quero saber sobre meu treino de academia")

        assert categoria is None


class TestClassificarIntencaoNaoChamaLLMQuandoHeuristicaResolve:
    def test_nao_chama_gemini_quando_heuristica_classifica(self, monkeypatch):
        def _falha_se_chamado(*args, **kwargs):
            raise AssertionError("classificar_intencao nao deveria chamar a Gemini API quando a heuristica resolve")

        monkeypatch.setattr(orchestrator, "_classificar_via_gemini", _falha_se_chamado)

        categoria = orchestrator.classificar_intencao("O que e periodizacao linear?")

        assert categoria == "conhecimento"


class TestFormatarContexto:
    def test_consulta_resultado_vazia_e_legivel(self):
        import pandas as pd

        resultado = orchestrator.sql_layer.ConsultaResultado(dados=pd.DataFrame(), treinos_sem_data_ignorados=2)

        texto = orchestrator._formatar_dado(resultado)

        assert "sem dados" in texto.lower()
        assert "2 treino" in texto

    def test_chunks_de_busca_incluem_fonte(self):
        from src.ai.rag_layer import ResultadoBusca

        chunks = [ResultadoBusca(texto="Texto X", fonte="hipertrofia.md", secao="Volume", distancia=0.1)]

        texto = orchestrator._formatar_dado(chunks)

        assert "hipertrofia.md" in texto
        assert "Texto X" in texto
