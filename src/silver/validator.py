"""Validacao Pydantic dos exercicios padronizados e log de rejeitados."""

import logging
from pathlib import Path

from pydantic import ValidationError

from src.config import SILVER_DIR
from src.models.schemas import ExercicioSilver, RegistroRejeitado, TreinoBronze, TreinoSilver
from src.silver.standardizer import standardize_treino

logger = logging.getLogger(__name__)

REJEITADOS_LOG = SILVER_DIR / "rejeitados.jsonl"


def validate_treino(treino: TreinoBronze) -> tuple[TreinoSilver, list[RegistroRejeitado]]:
    """Valida os exercicios padronizados de um treino.

    Exercicios que violam as regras de negocio (series <= 0, carga_kg < 0
    ou sem nome_canonico) sao separados como rejeitados; os demais compoem
    o TreinoSilver, incluindo os marcados como "Não Mapeado" pelo
    standardizer (esses nao sao descartados, apenas ficam para revisao).
    """
    standardized = standardize_treino(treino)
    validos: list[ExercicioSilver] = []
    rejeitados: list[RegistroRejeitado] = []

    for registro in standardized:
        try:
            validos.append(ExercicioSilver.model_validate(registro))
        except ValidationError as exc:
            motivo = "; ".join(error["msg"] for error in exc.errors())
            logger.warning(
                "Registro rejeitado em %s (%s): %s",
                treino.origem,
                registro["nome_original"],
                motivo,
            )
            rejeitados.append(
                RegistroRejeitado(
                    origem=treino.origem,
                    nome_original=registro["nome_original"],
                    motivo=motivo,
                )
            )

    treino_silver = TreinoSilver(data_treino=treino.data_treino, origem=treino.origem, exercicios=validos)
    return treino_silver, rejeitados


def save_silver(treino: TreinoSilver) -> Path:
    """Salva o JSON validado em data/silver/."""
    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    output_path = SILVER_DIR / f"{Path(treino.origem).stem}.json"
    output_path.write_text(treino.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def save_rejeitados(rejeitados: list[RegistroRejeitado]) -> None:
    """Acrescenta os registros rejeitados ao log (um JSON por linha)."""
    if not rejeitados:
        return
    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    with REJEITADOS_LOG.open("a", encoding="utf-8") as f:
        for registro in rejeitados:
            f.write(registro.model_dump_json() + "\n")


def validate_and_save(treino: TreinoBronze) -> Path:
    """Valida um treino bronze e persiste o resultado (validos + rejeitados)."""
    treino_silver, rejeitados = validate_treino(treino)
    save_rejeitados(rejeitados)
    return save_silver(treino_silver)
