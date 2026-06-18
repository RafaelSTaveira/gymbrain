"""Criacao do esquema da camada Gold no PostgreSQL."""

from src.config import get_engine
from src.models.db_models import Base


def init_db() -> None:
    """Cria as tabelas de treinos/exercicios/registros se ainda nao existirem.

    Idempotente: create_all so cria o que estiver faltando, entao pode ser
    chamado em toda execucao do pipeline sem efeito sobre tabelas existentes.
    """
    Base.metadata.create_all(get_engine())


if __name__ == "__main__":
    init_db()
