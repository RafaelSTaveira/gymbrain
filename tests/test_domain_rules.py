from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai import domain_rules as dr
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

    def _registro(treino: Treino, exercicio: Exercicio, series: int = 3) -> None:
        session.add(Registro(treino_id=treino.id, exercicio_id=exercicio.id, series=series))

    peito = _exercicio("Supino Reto", "Peito")
    costas = _exercicio("Remada Curvada Pronada", "Costas")

    treino_recente = _treino("recente.pdf", HOJE - timedelta(days=1))
    _registro(treino_recente, peito, series=4)

    treino_antigo = _treino("antigo.pdf", HOJE - timedelta(days=10))
    _registro(treino_antigo, costas, series=4)

    session.commit()
    yield session
    session.close()


class TestEquipamentoNecessario:
    def test_override_curado_tem_prioridade(self):
        # "Levantamento Terra" nao tem palavra-chave de equipamento no nome,
        # mas convencionalmente exige barra - por isso entra no override.
        assert dr.equipamento_necessario("Levantamento Terra") == "Barra"

    def test_palavra_chave_no_nome_e_reconhecida(self):
        assert dr.equipamento_necessario("Supino Reto com Halter") == "Halter"
        assert dr.equipamento_necessario("Cadeira Extensora") == "Máquina"

    def test_exercicio_sem_equipamento_e_peso_do_corpo(self):
        assert dr.equipamento_necessario("Flexão de Braço no Solo") == dr.PESO_DO_CORPO
        assert dr.equipamento_necessario("Prancha Abdominal") == dr.PESO_DO_CORPO


class TestAdaptarExercicio:
    def test_equipamento_disponivel_nao_precisa_adaptar(self):
        resultado = dr.adaptar_exercicio("Supino Reto com Barra", ["Barra"])

        assert resultado.precisa_adaptar is False
        assert resultado.alternativa is None

    def test_equipamento_indisponivel_sugere_alternativa_do_mesmo_grupo(self):
        resultado = dr.adaptar_exercicio("Supino Reto com Barra", ["Máquina"])

        assert resultado.precisa_adaptar is True
        assert resultado.alternativa is not None
        assert resultado.alternativa != "Supino Reto com Barra"
        info_alternativa = dr._info_exercicio(resultado.alternativa)
        assert info_alternativa["grupo_muscular"] == "Peito"

    def test_nenhuma_alternativa_disponivel_no_grupo(self):
        resultado = dr.adaptar_exercicio("Tríceps Coice", [])

        assert resultado.precisa_adaptar is True
        assert resultado.alternativa is None
        assert "nenhuma alternativa" in resultado.motivo.lower()

    def test_exercicio_nao_reconhecido(self):
        resultado = dr.adaptar_exercicio("Exercicio Bizarro Que Nao Existe", ["Barra"])

        assert resultado.precisa_adaptar is False
        assert resultado.equipamento_necessario is None
        assert "nao reconhecido" in resultado.motivo.lower()


class TestGruposDescansados:
    def test_grupo_treinado_ontem_nao_esta_descansado(self, session):
        descansados = dr.grupos_descansados(dias_minimo=2, session=session)

        assert "Peito" not in descansados

    def test_grupo_treinado_ha_10_dias_esta_descansado(self, session):
        descansados = dr.grupos_descansados(dias_minimo=2, session=session)

        assert "Costas" in descansados

    def test_grupo_nunca_treinado_e_considerado_descansado(self, session):
        descansados = dr.grupos_descansados(dias_minimo=2, session=session)

        assert "Ombro" in descansados


class TestValidarTreino:
    def test_treino_curto_cabe_no_tempo(self, session):
        resultado = dr.validar_treino(
            [dr.ItemTreino(nome="Remada Curvada Pronada", series=3)],
            tempo_disponivel_min=60,
            session=session,
        )

        assert resultado.cabe_no_tempo is True
        assert resultado.grupos_sobrecarregados == []

    def test_treino_longo_nao_cabe_no_tempo(self, session):
        exercicios = [dr.ItemTreino(nome="Remada Curvada Pronada", series=5) for _ in range(10)]

        resultado = dr.validar_treino(exercicios, tempo_disponivel_min=20, session=session)

        assert resultado.cabe_no_tempo is False
        assert resultado.motivos  # explica o motivo

    def test_grupo_treinado_recentemente_e_sinalizado_como_sobrecarregado(self, session):
        resultado = dr.validar_treino(
            [dr.ItemTreino(nome="Supino Reto", series=3)],
            tempo_disponivel_min=120,
            dias_minimo_descanso=2,
            session=session,
        )

        assert "Peito" in resultado.grupos_sobrecarregados
        assert resultado.motivos
