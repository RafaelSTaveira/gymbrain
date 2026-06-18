import json

from src.models.schemas import ExercicioBronze, RegistroRejeitado, TreinoBronze, TreinoSilver
from src.silver import validator
from src.silver.standardizer import NAO_MAPEADO


def _treino(*exercicios: ExercicioBronze, origem: str = "ficha.pdf") -> TreinoBronze:
    return TreinoBronze(origem=origem, exercicios=list(exercicios))


class TestValidateTreino:
    def test_valid_exercise_goes_to_silver_and_nothing_is_rejected(self):
        treino = _treino(ExercicioBronze(nome_original="SUPINO RETO NO SMITH", series=4, repeticoes="12", carga_kg=40))

        silver, rejeitados = validator.validate_treino(treino)

        assert len(silver.exercicios) == 1
        assert silver.exercicios[0].nome_canonico == "Supino Reto no Smith"
        assert rejeitados == []

    def test_negative_series_is_rejected_with_clear_reason(self):
        treino = _treino(ExercicioBronze(nome_original="ROSCA DIRETA C/ BARRA W", series=-2, repeticoes="12"))

        silver, rejeitados = validator.validate_treino(treino)

        assert silver.exercicios == []
        assert len(rejeitados) == 1
        assert isinstance(rejeitados[0], RegistroRejeitado)
        assert rejeitados[0].origem == "ficha.pdf"
        assert rejeitados[0].nome_original == "ROSCA DIRETA C/ BARRA W"
        assert "series" in rejeitados[0].motivo

    def test_negative_carga_kg_is_rejected(self):
        treino = _treino(ExercicioBronze(nome_original="AGACHAMENTO LIVRE", series=3, repeticoes="10", carga_kg=-5))

        silver, rejeitados = validator.validate_treino(treino)

        assert silver.exercicios == []
        assert len(rejeitados) == 1
        assert "carga_kg" in rejeitados[0].motivo

    def test_unmapped_exercise_is_not_rejected_just_marked(self):
        treino = _treino(ExercicioBronze(nome_original="Exercicio Bizarro", series=3, repeticoes="10"))

        silver, rejeitados = validator.validate_treino(treino)

        assert rejeitados == []
        assert len(silver.exercicios) == 1
        assert silver.exercicios[0].nome_canonico == NAO_MAPEADO

    def test_valid_and_invalid_records_are_separated_independently(self):
        treino = _treino(
            ExercicioBronze(nome_original="SUPINO RETO NO SMITH", series=4, repeticoes="12", carga_kg=40),
            ExercicioBronze(nome_original="ROSCA DIRETA C/ BARRA W", series=-2, repeticoes="12"),
            ExercicioBronze(nome_original="AGACHAMENTO LIVRE", series=3, repeticoes="10", carga_kg=-5),
        )

        silver, rejeitados = validator.validate_treino(treino)

        assert len(silver.exercicios) == 1
        assert len(rejeitados) == 2

    def test_treino_metadata_is_preserved_in_silver_output(self):
        treino = TreinoBronze(
            data_treino="2026-06-10",
            origem="treino_dia1.pdf",
            exercicios=[ExercicioBronze(nome_original="SUPINO RETO NO SMITH", series=4, repeticoes="12")],
        )

        silver, _ = validator.validate_treino(treino)

        assert silver.origem == "treino_dia1.pdf"
        assert str(silver.data_treino) == "2026-06-10"


class TestSaveSilver:
    def test_writes_validated_json_named_after_origem(self, tmp_path, monkeypatch):
        monkeypatch.setattr(validator, "SILVER_DIR", tmp_path)

        silver = TreinoSilver(origem="treino_dia1.pdf", exercicios=[])
        output_path = validator.save_silver(silver)

        assert output_path == tmp_path / "treino_dia1.json"
        assert output_path.exists()
        saved = json.loads(output_path.read_text(encoding="utf-8"))
        assert saved["origem"] == "treino_dia1.pdf"


class TestSaveRejeitados:
    def test_appends_one_json_per_line(self, tmp_path, monkeypatch):
        monkeypatch.setattr(validator, "SILVER_DIR", tmp_path)
        log_path = tmp_path / "rejeitados.jsonl"
        monkeypatch.setattr(validator, "REJEITADOS_LOG", log_path)

        rejeitados = [
            RegistroRejeitado(origem="ficha.pdf", nome_original="X", motivo="motivo 1"),
            RegistroRejeitado(origem="ficha.pdf", nome_original="Y", motivo="motivo 2"),
        ]
        validator.save_rejeitados(rejeitados)

        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["nome_original"] == "X"
        assert json.loads(lines[1])["nome_original"] == "Y"

    def test_does_nothing_when_no_rejected_records(self, tmp_path, monkeypatch):
        monkeypatch.setattr(validator, "SILVER_DIR", tmp_path)
        log_path = tmp_path / "rejeitados.jsonl"
        monkeypatch.setattr(validator, "REJEITADOS_LOG", log_path)

        validator.save_rejeitados([])

        assert not log_path.exists()


class TestValidateAndSave:
    def test_saves_silver_and_rejeitados_in_one_call(self, tmp_path, monkeypatch):
        monkeypatch.setattr(validator, "SILVER_DIR", tmp_path)
        monkeypatch.setattr(validator, "REJEITADOS_LOG", tmp_path / "rejeitados.jsonl")

        treino = _treino(
            ExercicioBronze(nome_original="SUPINO RETO NO SMITH", series=4, repeticoes="12", carga_kg=40),
            ExercicioBronze(nome_original="ROSCA DIRETA C/ BARRA W", series=-2, repeticoes="12"),
            origem="treino_misto.pdf",
        )

        output_path = validator.validate_and_save(treino)

        assert output_path.exists()
        saved = json.loads(output_path.read_text(encoding="utf-8"))
        assert len(saved["exercicios"]) == 1
        assert (tmp_path / "rejeitados.jsonl").exists()
