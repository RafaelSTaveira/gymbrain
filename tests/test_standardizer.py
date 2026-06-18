from src.models.schemas import ExercicioBronze, TreinoBronze
from src.silver.standardizer import (
    NAO_MAPEADO,
    normalize_exercise_name,
    standardize_exercicio,
    standardize_treino,
)


class TestNormalizeExerciseName:
    def test_lowercases_and_strips_accents(self):
        assert normalize_exercise_name("TRÍCEPS TESTA") == "triceps testa"

    def test_strips_leading_and_trailing_whitespace(self):
        assert normalize_exercise_name("  Cadeira Extensora  ") == "cadeira extensora"

    def test_expands_c_barra_abbreviation(self):
        assert normalize_exercise_name("ELEVAÇÃO PÉLVICA C/ BARRA") == "elevacao pelvica com barra"

    def test_expands_c_abbreviation_without_space(self):
        assert normalize_exercise_name("CRUCIFIXO INCLINADO C/HALTER") == "crucifixo inclinado com halter"

    def test_expands_s_abbreviation(self):
        assert normalize_exercise_name("TRÍCEPS COICE S/I") == "triceps coice sem i"

    def test_expands_p_abbreviation(self):
        assert normalize_exercise_name("SUPINO P/ CIMA") == "supino para cima"

    def test_converts_hyphen_to_space(self):
        assert normalize_exercise_name("LEG PRESS - PÉS PARALELOS") == "leg press pes paralelos"

    def test_strips_parentheses_period_and_degree_sign(self):
        assert normalize_exercise_name("ROSCA SPIDER BANCO 45° (SIMULTÂNEO)") == "rosca spider banco 45 simultaneo"

    def test_collapses_multiple_spaces(self):
        assert normalize_exercise_name("SUPINO   RETO") == "supino reto"


class TestStandardizeExercicio:
    def test_maps_known_exercise_to_canonical_name_and_group(self):
        exercicio = ExercicioBronze(nome_original="CADEIRA EXTENSORA", series=4, repeticoes="15", carga_kg=25)
        result = standardize_exercicio(exercicio)

        assert result["nome_canonico"] == "Cadeira Extensora"
        assert result["grupo_muscular"] == "Perna"
        assert result["nome_original"] == "CADEIRA EXTENSORA"
        assert result["series"] == 4
        assert result["carga_kg"] == 25

    def test_maps_exercise_with_abbreviation_in_raw_text(self):
        exercicio = ExercicioBronze(nome_original="ELEVAÇÃO PÉLVICA C/ BARRA", series=4, repeticoes="15")
        result = standardize_exercicio(exercicio)

        assert result["nome_canonico"] == "Elevação Pélvica com Barra"
        assert result["grupo_muscular"] == "Glúteo"

    def test_unknown_exercise_is_marked_as_nao_mapeado_not_discarded(self):
        exercicio = ExercicioBronze(
            nome_original="Exercicio Bizarro Que Nao Existe",
            series=3,
            repeticoes="12",
            grupo_muscular_informado="Peito",
        )
        result = standardize_exercicio(exercicio)

        assert result["nome_canonico"] == NAO_MAPEADO
        # mantem o grupo muscular informado na ficha, quando disponivel
        assert result["grupo_muscular"] == "Peito"
        assert result["nome_original"] == "Exercicio Bizarro Que Nao Existe"

    def test_unknown_exercise_without_informed_group_has_none_group(self):
        exercicio = ExercicioBronze(nome_original="Exercicio Bizarro", series=3, repeticoes="12")
        result = standardize_exercicio(exercicio)

        assert result["nome_canonico"] == NAO_MAPEADO
        assert result["grupo_muscular"] is None


class TestStandardizeTreino:
    def test_standardizes_every_exercise_preserving_order_and_count(self):
        treino = TreinoBronze(
            origem="ficha.pdf",
            exercicios=[
                ExercicioBronze(nome_original="SUPINO RETO NO SMITH", series=4, repeticoes="12"),
                ExercicioBronze(nome_original="AGACHAMENTO LIVRE", series=3, repeticoes="10"),
                ExercicioBronze(nome_original="Exercicio Desconhecido", series=2, repeticoes="8"),
            ],
        )

        result = standardize_treino(treino)

        assert len(result) == 3
        assert result[0]["nome_canonico"] == "Supino Reto no Smith"
        assert result[1]["nome_canonico"] == "Agachamento Livre"
        assert result[2]["nome_canonico"] == NAO_MAPEADO

    def test_empty_treino_returns_empty_list(self):
        treino = TreinoBronze(origem="ficha_vazia.pdf", exercicios=[])
        assert standardize_treino(treino) == []
