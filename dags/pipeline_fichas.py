"""DAG do pipeline ETL Bronze -> Silver -> Gold do GymBrain.

Disparo manual (schedule=None): e um processamento batch unico das fichas
de treino historicas em data/raw/, nao uma rotina recorrente.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pendulum
from airflow.decorators import dag, task

logger = logging.getLogger(__name__)


@dag(
    dag_id="pipeline_fichas",
    description="ETL Bronze -> Silver -> Gold das fichas de treino do GymBrain",
    schedule=None,
    start_date=pendulum.datetime(2024, 1, 1, tz="America/Sao_Paulo"),
    catchup=False,
    tags=["gymbrain", "etl"],
)
def pipeline_fichas():
    @task
    def extract_bronze() -> list[str]:
        """Le as fichas em data/raw/ e extrai o JSON bruto via Gemini Vision."""
        from src.bronze.extractor import extract_all
        from src.config import RAW_DIR

        saved_paths = extract_all(RAW_DIR)
        logger.info("Bronze: %d ficha(s) processada(s) de %s", len(saved_paths), RAW_DIR)
        return [str(path) for path in saved_paths]

    @task
    def transform_silver(bronze_paths: list[str]) -> list[str]:
        """Padroniza e valida cada JSON bronze, salvando o resultado na Silver."""
        from src.models.schemas import TreinoBronze
        from src.silver.validator import validate_and_save

        silver_paths = []
        for bronze_path in bronze_paths:
            treino_bronze = TreinoBronze.model_validate_json(Path(bronze_path).read_text(encoding="utf-8"))
            silver_path = validate_and_save(treino_bronze)
            silver_paths.append(str(silver_path))
        logger.info("Silver: %d ficha(s) validada(s)", len(silver_paths))
        return silver_paths

    @task
    def load_gold(silver_paths: list[str]) -> None:
        """Carrega os treinos validados da Silver no PostgreSQL (Gold)."""
        from src.gold.loader import load_all
        from src.models.schemas import TreinoSilver

        treinos = [
            TreinoSilver.model_validate_json(Path(silver_path).read_text(encoding="utf-8"))
            for silver_path in silver_paths
        ]
        loaded = load_all(treinos)
        logger.info("Gold: %d treino(s) carregado(s) no PostgreSQL", len(loaded))

    load_gold(transform_silver(extract_bronze()))


pipeline_fichas()
