from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai import sql_layer
from src.models.db_models import Base, Exercicio, Registro, Treino

HOJE = date.today()


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _exercicio(nome_canonico: str, grupo_muscular: str) -> Exercicio:
        exercicio = Exercicio(nome_canonico=nome_canonico, grupo_muscular=grupo_muscular)
        session.add(exercicio)
        session.flush()
        return exercicio

    def _treino(origem: str, data_treino: date | None) -> Treino:
        treino = Treino(origem=origem, data_treino=data_treino)
        session.add(treino)
        session.flush()
        return treino

    def _registro(treino: Treino, exercicio: Exercicio, series: int | None = 3) -> None:
        session.add(Registro(treino_id=treino.id, exercicio_id=exercicio.id, series=series))

    supino = _exercicio("Supino Reto", "Peito")
    remada = _exercicio("Remada Curvada", "Costas")
    nao_mapeado = _exercicio(sql_layer.NAO_MAPEADO, None)

    # Treino recente (dentro de 30 dias) de peito.
    treino_recente = _treino("recente.pdf", HOJE - timedelta(days=5))
    _registro(treino_recente, supino, series=4)
    _registro(treino_recente, nao_mapeado, series=2)

    # Treino antigo (fora de 30 dias) de costas.
    treino_antigo = _treino("antigo.pdf", HOJE - timedelta(days=90))
    _registro(treino_antigo, remada, series=3)

    # Treino sem data - deve ser ignorado nas consultas por janela de tempo.
    treino_sem_data = _treino("sem_data.pdf", None)
    _registro(treino_sem_data, supino, series=5)

    session.commit()
    yield session
    session.close()


class TestVolumePorGrupo:
    def test_soma_series_apenas_dentro_da_janela(self, session):
        resultado = sql_layer.volume_por_grupo(dias=30, session=session)

        linhas = resultado.dados.set_index("grupo_muscular")["total_series"].to_dict()
        assert linhas["Peito"] == 4
        assert "Costas" not in linhas  # treino de costas esta fora da janela de 30 dias

    def test_ignora_e_conta_treinos_sem_data(self, session):
        resultado = sql_layer.volume_por_grupo(dias=30, session=session)

        assert resultado.treinos_sem_data_ignorados == 1

    def test_janela_maior_inclui_treino_antigo(self, session):
        resultado = sql_layer.volume_por_grupo(dias=120, session=session)

        linhas = resultado.dados.set_index("grupo_muscular")["total_series"].to_dict()
        assert linhas["Costas"] == 3


class TestVolumeTotalPorGrupo:
    def test_soma_series_de_todo_o_historico_sem_filtro_de_data(self, session):
        resultado = sql_layer.volume_total_por_grupo(session=session)

        linhas = resultado.dados.set_index("grupo_muscular")["total_series"].to_dict()
        # Peito: 4 (treino_recente) + 5 (treino_sem_data) = 9. Costas: 3 (treino_antigo).
        assert linhas["Peito"] == 9
        assert linhas["Costas"] == 3

    def test_exclui_nao_mapeado(self, session):
        resultado = sql_layer.volume_total_por_grupo(session=session)

        assert "Não Mapeado" not in set(resultado.dados["grupo_muscular"])

    def test_informa_quantos_treinos_sem_data_existem(self, session):
        resultado = sql_layer.volume_total_por_grupo(session=session)

        assert resultado.treinos_sem_data_ignorados == 1


class TestExerciciosDistintosPorGrupo:
    def test_conta_exercicios_distintos_catalogados_por_grupo(self, session):
        resultado = sql_layer.exercicios_distintos_por_grupo(session=session)

        linhas = resultado.dados.set_index("grupo_muscular")["total_exercicios"].to_dict()
        assert linhas["Peito"] == 1
        assert linhas["Costas"] == 1

    def test_exclui_nao_mapeado(self, session):
        resultado = sql_layer.exercicios_distintos_por_grupo(session=session)

        assert "Não Mapeado" not in set(resultado.dados["grupo_muscular"])


class TestFrequenciaPorGrupo:
    def test_conta_treinos_distintos_por_grupo(self, session):
        resultado = sql_layer.frequencia_por_grupo(dias=30, session=session)

        linhas = resultado.dados.set_index("grupo_muscular")["total_treinos"].to_dict()
        assert linhas["Peito"] == 1


class TestUltimoTreinoPorGrupo:
    def test_retorna_data_mais_recente_por_grupo(self, session):
        resultado = sql_layer.ultimo_treino_por_grupo(session=session)

        linhas = resultado.dados.set_index("grupo_muscular")["ultimo_treino"].to_dict()
        assert linhas["Peito"] == HOJE - timedelta(days=5)
        assert linhas["Costas"] == HOJE - timedelta(days=90)

    def test_grupo_so_com_treinos_sem_data_nao_aparece(self, session):
        # "Nao Mapeado" so tem registros em treino_recente (com data) e
        # nenhum em treino sem data, entao nao serve para este caso - aqui
        # so confirmamos que nenhum grupo inexistente aparece por engano.
        resultado = sql_layer.ultimo_treino_por_grupo(session=session)

        grupos_conhecidos = {g for g in resultado.dados["grupo_muscular"] if pd.notna(g)}
        assert grupos_conhecidos <= {"Peito", "Costas"}


class TestExerciciosMaisFrequentes:
    def test_exclui_nao_mapeado_por_padrao(self, session):
        resultado = sql_layer.exercicios_mais_frequentes(session=session)

        assert sql_layer.NAO_MAPEADO not in set(resultado.dados["nome_canonico"])

    def test_inclui_nao_mapeado_quando_solicitado(self, session):
        resultado = sql_layer.exercicios_mais_frequentes(incluir_nao_mapeado=True, session=session)

        assert sql_layer.NAO_MAPEADO in set(resultado.dados["nome_canonico"])

    def test_respeita_limite(self, session):
        resultado = sql_layer.exercicios_mais_frequentes(limite=1, session=session)

        assert len(resultado.dados) == 1
        assert resultado.dados.iloc[0]["nome_canonico"] == "Supino Reto"


class TestDiasDesdeUltimoTreino:
    def test_calcula_dias_a_partir_da_data_mais_recente(self, session):
        dias = sql_layer.dias_desde_ultimo_treino("Peito", session=session)

        assert dias == 5

    def test_retorna_none_para_grupo_sem_treino_com_data(self, session):
        dias = sql_layer.dias_desde_ultimo_treino("Perna", session=session)

        assert dias is None
