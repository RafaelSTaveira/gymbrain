"""Explicabilidade: por que o GymBrain respondeu o que respondeu, rastreado aos dados e regras."""

from src.ai.orchestrator import RespostaGymBrain
from src.ai.rag_layer import ResultadoBusca
from src.ai.sql_layer import ConsultaResultado


def explicar(resposta: RespostaGymBrain) -> str:
    """Gera uma explicacao rastreavel da resposta: quais dados e regras a embasaram.

    A recomendacao nunca deve ser uma caixa-preta: esta funcao aponta, em
    texto simples, exatamente quais consultas (historico) e quais princípios
    (corpus de conhecimento) contribuiram para a resposta final.
    """
    linhas = [f'Pergunta: "{resposta.pergunta}" — classificada como "{resposta.intencao}".']

    grupos_descansados = resposta.dados_brutos.get("grupos_descansados")
    if grupos_descansados:
        linhas.append(
            "Grupos musculares sem treino recente no historico (considerados descansados): "
            + ", ".join(grupos_descansados)
            + "."
        )

    ultimo_treino = resposta.dados_brutos.get("ultimo_treino_por_grupo")
    if isinstance(ultimo_treino, ConsultaResultado) and not ultimo_treino.dados.empty:
        for _, linha in ultimo_treino.dados.iterrows():
            linhas.append(f"- {linha['grupo_muscular']}: último treino registrado em {linha['ultimo_treino']}.")
        if ultimo_treino.treinos_sem_data_ignorados:
            linhas.append(
                f"({ultimo_treino.treinos_sem_data_ignorados} treino(s) sem data na ficha original foram "
                "ignorados nessa analise temporal.)"
            )

    chunks: list[ResultadoBusca] = resposta.dados_brutos.get("chunks") or []
    if chunks:
        fontes_unicas = sorted({chunk.fonte for chunk in chunks})
        linhas.append("Princípios de treino consultados em: " + ", ".join(fontes_unicas) + ".")

    if resposta.fontes:
        linhas.append(
            "Resposta combinando o conhecimento geral do modelo (Gemini) com: "
            + "; ".join(resposta.fontes)
            + "."
        )
    else:
        linhas.append(
            "Resposta baseada no conhecimento geral do modelo (Gemini); nenhuma fonte de dados "
            "local do usuário foi relevante para esta pergunta."
        )

    return "\n".join(linhas)
