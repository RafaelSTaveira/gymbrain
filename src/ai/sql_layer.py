"""Consultas estruturadas sobre o historico de treinos (SQL/Pandas, sem LLM)."""

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.config import get_session
from src.models.db_models import Exercicio, Registro, Treino

NAO_MAPEADO = "Não Mapeado"


@dataclass
class ConsultaResultado:
    """Resultado de uma consulta, com metadados sobre dados ignorados.

    Muitos treinos tem `data_treino` nulo (a ficha original nao trazia
    data). Consultas baseadas em janela de tempo ignoram esses treinos -
    nao ha como posiciona-los no tempo - e reportam quantos foram
    ignorados em `treinos_sem_data_ignorados`, para que o chamador (e a
    explicacao gerada para o usuario) saiba que a analise e parcial.
    """

    dados: pd.DataFrame
    treinos_sem_data_ignorados: int = 0


def _resolve_session(session: Session | None) -> tuple[Session, bool]:
    owns_session = session is None
    return session or get_session(), owns_session


def _contar_treinos_sem_data(session: Session) -> int:
    return session.query(Treino).filter(Treino.data_treino.is_(None)).count()


def volume_por_grupo(dias: int = 30, session: Session | None = None) -> ConsultaResultado:
    """Total de series por grupo muscular nos ultimos `dias` dias.

    Considera apenas treinos com `data_treino` preenchida; os demais sao
    contados em `treinos_sem_data_ignorados`. Exercicios "Nao Mapeado" (sem
    grupo muscular conhecido) sao excluidos: nao tem como agregar por grupo
    algo cujo grupo e desconhecido.
    """
    session, owns_session = _resolve_session(session)
    try:
        cutoff = date.today() - timedelta(days=dias)
        rows = (
            session.query(Exercicio.grupo_muscular, func.sum(Registro.series))
            .join(Registro, Registro.exercicio_id == Exercicio.id)
            .join(Treino, Treino.id == Registro.treino_id)
            .filter(
                Treino.data_treino.is_not(None),
                Treino.data_treino >= cutoff,
                Exercicio.grupo_muscular.is_not(None),
            )
            .group_by(Exercicio.grupo_muscular)
            .all()
        )
        dados = pd.DataFrame(rows, columns=["grupo_muscular", "total_series"])
        if not dados.empty:
            dados["total_series"] = dados["total_series"].fillna(0).astype(int)
        return ConsultaResultado(dados=dados, treinos_sem_data_ignorados=_contar_treinos_sem_data(session))
    finally:
        if owns_session:
            session.close()


def frequencia_por_grupo(dias: int = 30, session: Session | None = None) -> ConsultaResultado:
    """Quantos treinos distintos tocaram cada grupo muscular nos ultimos `dias` dias.

    Exercicios "Nao Mapeado" (sem grupo muscular conhecido) sao excluidos.
    """
    session, owns_session = _resolve_session(session)
    try:
        cutoff = date.today() - timedelta(days=dias)
        rows = (
            session.query(Exercicio.grupo_muscular, func.count(func.distinct(Registro.treino_id)))
            .join(Registro, Registro.exercicio_id == Exercicio.id)
            .join(Treino, Treino.id == Registro.treino_id)
            .filter(
                Treino.data_treino.is_not(None),
                Treino.data_treino >= cutoff,
                Exercicio.grupo_muscular.is_not(None),
            )
            .group_by(Exercicio.grupo_muscular)
            .all()
        )
        dados = pd.DataFrame(rows, columns=["grupo_muscular", "total_treinos"])
        return ConsultaResultado(dados=dados, treinos_sem_data_ignorados=_contar_treinos_sem_data(session))
    finally:
        if owns_session:
            session.close()


def ultimo_treino_por_grupo(session: Session | None = None) -> ConsultaResultado:
    """Data do treino mais recente (com data conhecida) de cada grupo muscular.

    Um grupo muscular cujos registros estejam todos em treinos sem data
    simplesmente nao aparece no resultado - nao ha como saber quando foi o
    "ultimo" treino sem nenhuma data de referencia. Exercicios "Nao Mapeado"
    (sem grupo muscular conhecido) tambem sao excluidos.
    """
    session, owns_session = _resolve_session(session)
    try:
        rows = (
            session.query(Exercicio.grupo_muscular, func.max(Treino.data_treino))
            .join(Registro, Registro.exercicio_id == Exercicio.id)
            .join(Treino, Treino.id == Registro.treino_id)
            .filter(Treino.data_treino.is_not(None), Exercicio.grupo_muscular.is_not(None))
            .group_by(Exercicio.grupo_muscular)
            .all()
        )
        dados = pd.DataFrame(rows, columns=["grupo_muscular", "ultimo_treino"])
        return ConsultaResultado(dados=dados, treinos_sem_data_ignorados=_contar_treinos_sem_data(session))
    finally:
        if owns_session:
            session.close()


def exercicios_mais_frequentes(
    limite: int = 10, incluir_nao_mapeado: bool = False, session: Session | None = None
) -> ConsultaResultado:
    """Exercicios canonicos com mais registros no historico.

    "Nao Mapeado" agrupa exercicios distintos que o dicionario canonico nao
    reconheceu, entao por padrao e excluido do ranking - caso contrario
    apareceria como se fosse um unico "exercicio" muito frequente, quando na
    verdade representa varios exercicios diferentes e nao identificados.
    """
    session, owns_session = _resolve_session(session)
    try:
        query = session.query(Exercicio.nome_canonico, func.count(Registro.id)).join(
            Registro, Registro.exercicio_id == Exercicio.id
        )
        if not incluir_nao_mapeado:
            query = query.filter(Exercicio.nome_canonico != NAO_MAPEADO)
        rows = (
            query.group_by(Exercicio.nome_canonico)
            .order_by(func.count(Registro.id).desc())
            .limit(limite)
            .all()
        )
        dados = pd.DataFrame(rows, columns=["nome_canonico", "total_registros"])
        return ConsultaResultado(dados=dados)
    finally:
        if owns_session:
            session.close()


def dias_desde_ultimo_treino(grupo: str, session: Session | None = None) -> int | None:
    """Quantos dias se passaram desde o ultimo treino registrado de `grupo`.

    Retorna None se nao houver nenhum treino com data conhecida para esse
    grupo muscular - seja porque o grupo nunca foi treinado, seja porque so
    aparece em fichas sem data.
    """
    session, owns_session = _resolve_session(session)
    try:
        ultima_data = (
            session.query(func.max(Treino.data_treino))
            .join(Registro, Registro.treino_id == Treino.id)
            .join(Exercicio, Exercicio.id == Registro.exercicio_id)
            .filter(Exercicio.grupo_muscular == grupo, Treino.data_treino.is_not(None))
            .scalar()
        )
        if ultima_data is None:
            return None
        return (date.today() - ultima_data).days
    finally:
        if owns_session:
            session.close()
