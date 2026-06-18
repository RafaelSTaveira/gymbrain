"""Padronizacao de nomes de exercicios da camada Bronze para a Silver."""

import re
import unicodedata

from src.models.schemas import ExercicioBronze, TreinoBronze
from src.silver.exercise_dictionary import EXERCISE_DICTIONARY

NAO_MAPEADO = "Não Mapeado"

# Abreviacoes comuns nas fichas reais (ex: "ELEVAÇÃO PÉLVICA C/ BARRA",
# "TRÍCEPS COICE S/I") que precisam ser expandidas antes de remover o
# restante da pontuacao, ou a busca no dicionario falha.
_ABBREVIATIONS = (
    (re.compile(r"\bc/\s*"), "com "),
    (re.compile(r"\bs/\s*"), "sem "),
    (re.compile(r"\bp/\s*"), "para "),
)


def normalize_exercise_name(name: str) -> str:
    """Normaliza um nome de exercicio para busca no dicionario canonico.

    Passos: lowercase, remove acentos, expande abreviacoes (c/, s/, p/) e
    converte qualquer simbolo remanescente (/, -, (), ., ,, °) em espaco.
    """
    text = name.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    for pattern, replacement in _ABBREVIATIONS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def standardize_exercicio(exercicio: ExercicioBronze) -> dict:
    """Atribui nome_canonico e grupo_muscular a um exercicio bruto.

    Quando o exercicio nao e encontrado no dicionario canonico, marca como
    "Não Mapeado" em vez de descartar, para revisao manual posterior.
    """
    normalized = normalize_exercise_name(exercicio.nome_original)
    match = EXERCISE_DICTIONARY.get(normalized)
    if match is None:
        nome_canonico = NAO_MAPEADO
        grupo_muscular = exercicio.grupo_muscular_informado
    else:
        nome_canonico = match["nome_canonico"]
        grupo_muscular = match["grupo_muscular"]

    return {
        "nome_original": exercicio.nome_original,
        "nome_canonico": nome_canonico,
        "grupo_muscular": grupo_muscular,
        "series": exercicio.series,
        "repeticoes": exercicio.repeticoes,
        "carga_kg": exercicio.carga_kg,
    }


def standardize_treino(treino: TreinoBronze) -> list[dict]:
    """Padroniza todos os exercicios de um treino bronze.

    O resultado ainda nao foi validado pelas regras de negocio (isso e
    responsabilidade do validator.py); aqui so atribuimos nome_canonico e
    grupo_muscular.
    """
    return [standardize_exercicio(exercicio) for exercicio in treino.exercicios]
