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


class _RespostaGeminiFake:
    def __init__(self, text: str):
        self.text = text


class TestResponderUsaConhecimentoGeralAlemDoCorpus:
    """O orquestrador nao deve mais se recusar a responder por falta de chunk no RAG.

    Ver prompt_claude_code_gymbrain_ajuste_chat.md: o conhecimento geral do
    Gemini passa a ser a base da resposta, com o contexto local (SQL/RAG)
    apenas enriquecendo - nao limitando.
    """

    def _preparar_mocks(self, monkeypatch, texto_sintese: str):
        def _generate_fake(model, contents, generation_config=None):
            prompt_enviado = contents[0]
            if "Categoria:" in prompt_enviado:
                return _RespostaGeminiFake("mista")
            return _RespostaGeminiFake(texto_sintese)

        monkeypatch.setattr(orchestrator, "build_model", lambda: object())
        monkeypatch.setattr(orchestrator, "generate_content_with_retry", _generate_fake)
        monkeypatch.setattr(orchestrator, "buscar_conhecimento", lambda pergunta, k=3: [])
        monkeypatch.setattr(orchestrator, "_coletar_historico", lambda session=None: {})
        monkeypatch.setattr(orchestrator.domain_rules, "grupos_descansados", lambda session=None: [])

    def test_pergunta_fora_do_corpus_produz_resposta_substantiva(self, monkeypatch):
        texto_esperado = (
            "Va com calma na volta: fortaleca tornozelo e panturrilha antes de "
            "voltar a carga total na perna, e respeite a dor."
        )
        self._preparar_mocks(monkeypatch, texto_esperado)

        resposta = orchestrator.responder("Quebrei o pé há um mês, como volto a treinar perna?")

        assert resposta.resposta == texto_esperado
        assert "não tenho dados" not in resposta.resposta.lower()
        assert "não foi possível" not in resposta.resposta.lower()

    def test_conhecimento_tambem_coleta_historico_para_personalizar(self, monkeypatch):
        chamadas = []
        monkeypatch.setattr(orchestrator, "build_model", lambda: object())
        monkeypatch.setattr(
            orchestrator,
            "generate_content_with_retry",
            lambda model, contents, generation_config=None: _RespostaGeminiFake("Resposta qualquer."),
        )
        monkeypatch.setattr(orchestrator, "buscar_conhecimento", lambda pergunta, k=3: [])
        monkeypatch.setattr(
            orchestrator,
            "_coletar_historico",
            lambda session=None: chamadas.append("historico") or {"volume_por_grupo": "dummy"},
        )
        monkeypatch.setattr(orchestrator.domain_rules, "grupos_descansados", lambda session=None: [])

        resposta = orchestrator.responder("O que e hipertrofia muscular?")

        assert resposta.intencao == "conhecimento"
        assert chamadas == ["historico"]
        assert "volume_por_grupo" in resposta.dados_brutos


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
