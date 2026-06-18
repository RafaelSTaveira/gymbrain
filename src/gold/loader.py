"""Carga dos dados validados (Silver) no PostgreSQL (Gold)."""

import logging

from sqlalchemy.orm import Session

from src.config import get_session
from src.models.db_models import Exercicio, Registro, Treino
from src.models.schemas import TreinoSilver

logger = logging.getLogger(__name__)


def _get_or_create_exercicio(session: Session, nome_canonico: str, grupo_muscular: str | None) -> Exercicio:
    exercicio = session.query(Exercicio).filter_by(nome_canonico=nome_canonico).one_or_none()
    if exercicio is None:
        exercicio = Exercicio(nome_canonico=nome_canonico, grupo_muscular=grupo_muscular)
        session.add(exercicio)
        session.flush()
    return exercicio


def load_treino(treino: TreinoSilver, session: Session | None = None) -> Treino | None:
    """Insere um treino validado no banco, evitando duplicatas.

    Se um treino com a mesma origem ja existir, a ficha ja foi carregada
    anteriormente: a funcao apenas registra um log e retorna None, sem
    duplicar dados. Exercicios sao reaproveitados pelo nome_canonico para
    manter a integridade referencial sem repetir cadastros.
    """
    owns_session = session is None
    session = session or get_session()

    try:
        existing = session.query(Treino).filter_by(origem=treino.origem).one_or_none()
        if existing is not None:
            logger.info("Treino com origem '%s' ja existe (id=%s), pulando carga.", treino.origem, existing.id)
            return None

        treino_row = Treino(data_treino=treino.data_treino, origem=treino.origem)
        session.add(treino_row)
        session.flush()

        for exercicio_silver in treino.exercicios:
            exercicio_row = _get_or_create_exercicio(
                session, exercicio_silver.nome_canonico, exercicio_silver.grupo_muscular
            )
            registro = Registro(
                treino_id=treino_row.id,
                exercicio_id=exercicio_row.id,
                nome_original=exercicio_silver.nome_original,
                series=exercicio_silver.series,
                repeticoes=exercicio_silver.repeticoes,
                carga_kg=exercicio_silver.carga_kg,
            )
            session.add(registro)

        session.commit()
        logger.info("Treino '%s' carregado com %d registros.", treino.origem, len(treino.exercicios))
        return treino_row
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def load_all(treinos: list[TreinoSilver]) -> list[Treino]:
    """Carrega varios treinos validados, reutilizando a mesma sessao/conexao."""
    session = get_session()
    loaded: list[Treino] = []
    try:
        for treino in treinos:
            result = load_treino(treino, session=session)
            if result is not None:
                loaded.append(result)
    finally:
        session.close()
    return loaded
