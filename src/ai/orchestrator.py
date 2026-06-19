"""Orquestrador: classifica a intencao da pergunta, roteia para as fontes certas e sintetiza a resposta."""

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from src.ai import domain_rules, sql_layer
from src.ai.rag_layer import ResultadoBusca, buscar_conhecimento
from src.gemini_client import DailyQuotaExceededError, build_model, generate_content_with_retry

logger = logging.getLogger(__name__)

CATEGORIAS_VALIDAS = ("historico", "conhecimento", "recomendacao", "mista")

# Heuristica por palavras-chave, para nao gastar uma chamada a Gemini em
# perguntas obviamente classificaveis. So recorremos ao LLM quando nenhuma
# palavra-chave bate (pergunta ambigua) - ver `classificar_intencao`.
_PALAVRAS_HISTORICO = (
    "quantas series",
    "quanto treinei",
    "quantos treinos",
    "frequencia",
    "ultima vez",
    "ultimo treino",
    "quando treinei",
    "historico",
    "volume de",
    "quanto tempo desde",
    "exercicios mais frequentes",
)
_PALAVRAS_CONHECIMENTO = (
    "o que e",
    "o que sao",
    "por que",
    "como funciona",
    "explique",
    "explica",
    "hipertrofia",
    "periodizacao",
    "overtraining",
    "deload",
    "mesociclo",
    "faixa de repeticao",
    "faixas de repeticao",
)
_PALAVRAS_RECOMENDACAO = (
    "recomende",
    "recomenda",
    "sugira",
    "sugere",
    "monte",
    "monta",
    "qual treino",
    "o que treinar",
    "posso treinar",
    "devo treinar",
    "treino para hoje",
    "o que fazer hoje",
    "nao tenho",
    "sem equipamento",
)

_PROMPT_CLASSIFICACAO = """\
Classifique a pergunta do usuario sobre treino de musculacao em EXATAMENTE \
uma categoria, respondendo so com a palavra da categoria, sem explicacao \
e sem pontuacao:

- historico: perguntas sobre o que o usuario JA treinou (volume, frequencia, \
ultima vez que treinou um grupo, exercicios mais frequentes).
- conhecimento: perguntas conceituais sobre treino (hipertrofia, \
periodizacao, faixas de repeticao, descanso, principios gerais).
- recomendacao: pedidos de sugestao do que treinar agora/hoje, adaptacao de \
exercicio por falta de equipamento, ou validacao de um treino proposto.
- mista: a pergunta combina claramente mais de uma das categorias acima.

Pergunta: {pergunta}

Categoria:"""

_PROMPT_SINTESE = """\
Voce e o assistente do GymBrain, um app de acompanhamento de treino de \
musculacao. Responda a pergunta do usuario em portugues, de forma direta e \
natural, usando APENAS os dados fornecidos abaixo como base factual. Se os \
dados nao forem suficientes para responder com certeza, diga isso \
explicitamente em vez de inventar numeros ou fatos.

Pergunta: {pergunta}

Dados disponiveis:
{contexto}

Resposta:"""


@dataclass
class RespostaGymBrain:
    """Resposta estruturada do orquestrador, com tudo necessario para explicabilidade."""

    pergunta: str
    intencao: str
    resposta: str
    fontes: list[str] = field(default_factory=list)
    dados_brutos: dict[str, object] = field(default_factory=dict)


def _classificar_por_heuristica(pergunta: str) -> str | None:
    """Tenta classificar por palavras-chave; retorna None se a pergunta for ambigua."""
    normalizado = pergunta.lower()
    pontos = {
        "historico": sum(1 for p in _PALAVRAS_HISTORICO if p in normalizado),
        "conhecimento": sum(1 for p in _PALAVRAS_CONHECIMENTO if p in normalizado),
        "recomendacao": sum(1 for p in _PALAVRAS_RECOMENDACAO if p in normalizado),
    }
    maximo = max(pontos.values())
    if maximo == 0:
        return None
    vencedoras = [categoria for categoria, pontuacao in pontos.items() if pontuacao == maximo]
    return vencedoras[0] if len(vencedoras) == 1 else "mista"


def _classificar_via_gemini(pergunta: str) -> str:
    model = build_model()
    try:
        response = generate_content_with_retry(model, [_PROMPT_CLASSIFICACAO.format(pergunta=pergunta)])
    except DailyQuotaExceededError as exc:
        logger.warning("%s Usando 'mista' como fallback seguro para a classificacao.", exc)
        return "mista"
    categoria = response.text.strip().lower()
    if categoria not in CATEGORIAS_VALIDAS:
        logger.warning("Gemini retornou categoria inesperada (%r); usando 'mista' como fallback.", categoria)
        return "mista"
    return categoria


def classificar_intencao(pergunta: str) -> str:
    """Classifica a pergunta em historico/conhecimento/recomendacao/mista.

    Tenta primeiro por heuristica de palavras-chave (custo zero de cota); so
    chama a Gemini API quando a pergunta nao bate com nenhuma palavra-chave
    conhecida.
    """
    categoria = _classificar_por_heuristica(pergunta)
    return categoria if categoria is not None else _classificar_via_gemini(pergunta)


def _coletar_historico(session: Session | None = None) -> dict[str, object]:
    return {
        "volume_por_grupo": sql_layer.volume_por_grupo(session=session),
        "frequencia_por_grupo": sql_layer.frequencia_por_grupo(session=session),
        "ultimo_treino_por_grupo": sql_layer.ultimo_treino_por_grupo(session=session),
        "exercicios_mais_frequentes": sql_layer.exercicios_mais_frequentes(session=session),
    }


def _coletar_conhecimento(pergunta: str) -> dict[str, object]:
    return {"chunks": buscar_conhecimento(pergunta, k=3)}


def _fontes_conhecimento(dados: dict[str, object]) -> list[str]:
    chunks: list[ResultadoBusca] = dados.get("chunks") or []
    return sorted({f"Corpus de conhecimento: {chunk.fonte}" for chunk in chunks})


def _formatar_dado(valor: object) -> str:
    if isinstance(valor, sql_layer.ConsultaResultado):
        texto = valor.dados.to_string(index=False) if not valor.dados.empty else "(sem dados na janela consultada)"
        if valor.treinos_sem_data_ignorados:
            texto += f"\n({valor.treinos_sem_data_ignorados} treino(s) sem data ignorado(s) nesta analise)"
        return texto
    if isinstance(valor, list) and valor and isinstance(valor[0], ResultadoBusca):
        return "\n\n".join(f"[{chunk.fonte} - {chunk.secao}]\n{chunk.texto}" for chunk in valor)
    return str(valor)


def _formatar_contexto(dados: dict[str, object]) -> str:
    return "\n\n".join(f"### {chave}\n{_formatar_dado(valor)}" for chave, valor in dados.items())


def _sintetizar(pergunta: str, contexto: str) -> str:
    model = build_model()
    try:
        response = generate_content_with_retry(model, [_PROMPT_SINTESE.format(pergunta=pergunta, contexto=contexto)])
        return response.text.strip()
    except DailyQuotaExceededError as exc:
        logger.warning("%s Retornando os dados brutos sem sintese em linguagem natural.", exc)
        return (
            "Não foi possível gerar uma resposta em linguagem natural porque a cota diária "
            "gratuita da Gemini API foi esgotada. Os dados brutos abaixo ainda são válidos:\n\n" + contexto
        )


def responder(pergunta: str, session: Session | None = None) -> RespostaGymBrain:
    """Responde a pergunta do usuario, roteando para as fontes apropriadas e sintetizando o resultado."""
    intencao = classificar_intencao(pergunta)
    fontes: list[str] = []

    if intencao == "historico":
        dados = _coletar_historico(session=session)
        fontes = ["Histórico de treinos (PostgreSQL)"]
    elif intencao == "conhecimento":
        dados = _coletar_conhecimento(pergunta)
        fontes = _fontes_conhecimento(dados)
    elif intencao == "recomendacao":
        dados = _coletar_historico(session=session)
        dados["grupos_descansados"] = domain_rules.grupos_descansados(session=session)
        dados.update(_coletar_conhecimento(pergunta))
        fontes = ["Histórico de treinos (PostgreSQL)", "Regras de domínio (descanso por grupo muscular)"]
        fontes += _fontes_conhecimento(dados)
    else:  # mista
        dados = _coletar_historico(session=session)
        dados["grupos_descansados"] = domain_rules.grupos_descansados(session=session)
        dados.update(_coletar_conhecimento(pergunta))
        fontes = ["Histórico de treinos (PostgreSQL)", "Regras de domínio (descanso por grupo muscular)"]
        fontes += _fontes_conhecimento(dados)

    contexto = _formatar_contexto(dados)
    resposta_texto = _sintetizar(pergunta, contexto)

    return RespostaGymBrain(pergunta=pergunta, intencao=intencao, resposta=resposta_texto, fontes=fontes, dados_brutos=dados)
