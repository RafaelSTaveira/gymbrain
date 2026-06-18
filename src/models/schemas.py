from datetime import date

from pydantic import BaseModel, Field, field_validator


class ExercicioBronze(BaseModel):
    """Exercício como extraído pelo Gemini Vision, antes de qualquer padronização."""

    nome_original: str
    series: int | None = None
    repeticoes: str | None = None
    carga_kg: float | None = None
    grupo_muscular_informado: str | None = None


class TreinoBronze(BaseModel):
    """Ficha de treino bruta, uma entrada por arquivo processado na camada Bronze."""

    data_treino: date | None = None
    origem: str
    exercicios: list[ExercicioBronze] = Field(default_factory=list)


class ExercicioSilver(BaseModel):
    """Exercício padronizado e validado, pronto para a camada Gold."""

    nome_original: str
    nome_canonico: str
    grupo_muscular: str | None = None
    series: int | None = None
    repeticoes: str | None = None
    carga_kg: float | None = None

    @field_validator("series")
    @classmethod
    def series_deve_ser_positiva(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("series deve ser um inteiro positivo")
        return v

    @field_validator("carga_kg")
    @classmethod
    def carga_nao_pode_ser_negativa(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("carga_kg nao pode ser negativa")
        return v

    @field_validator("nome_canonico")
    @classmethod
    def nome_canonico_obrigatorio(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("nome_canonico e obrigatorio apos a padronizacao")
        return v


class TreinoSilver(BaseModel):
    """Ficha de treino padronizada e validada, pronta para a camada Gold."""

    data_treino: date | None = None
    origem: str
    exercicios: list[ExercicioSilver] = Field(default_factory=list)


class RegistroRejeitado(BaseModel):
    """Registro que falhou na validação da camada Silver, para revisão manual."""

    origem: str
    nome_original: str
    motivo: str
