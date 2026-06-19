"""Extracao de fichas de treino (imagem ou PDF) via Gemini Vision."""

import json
import logging
from pathlib import Path

from src.config import BRONZE_DIR
from src.gemini_client import DailyQuotaExceededError, build_model, generate_content_with_retry
from src.models.schemas import TreinoBronze

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

PROMPT = """\
Você é um assistente especializado em extrair dados de fichas de treino de \
musculação a partir de imagens ou PDFs.

Analise o documento fornecido e retorne ESTRITAMENTE um JSON (sem markdown, \
sem texto adicional, sem comentários) no formato:

{
  "data_treino": "YYYY-MM-DD ou null se a ficha nao tiver data",
  "origem": "nome do arquivo original",
  "exercicios": [
    {
      "nome_original": "texto exato do exercicio como aparece na ficha",
      "series": numero inteiro de series ou null,
      "repeticoes": "texto como '10-12' ou '12', ou null",
      "carga_kg": numero (pode ter decimais) ou null,
      "grupo_muscular_informado": "grupo muscular se a ficha indicar, senao null"
    }
  ]
}

Regras:
- Extraia TODOS os exercicios visiveis no documento, mesmo que a ficha tenha \
multiplas paginas ou dias de treino diferentes.
- Use o nome exatamente como esta escrito na ficha em "nome_original", sem \
corrigir, traduzir ou abreviar.
- Se nao houver informacao para um campo, use null.
- Nao invente dados que nao estejam na ficha.
"""


def _mime_type(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Tipo de arquivo nao suportado: {file_path.name}")
    return SUPPORTED_SUFFIXES[suffix]


def extract_treino(file_path: Path) -> TreinoBronze:
    """Envia uma ficha (imagem ou PDF) para a Gemini API e retorna o TreinoBronze extraido."""
    if not file_path.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {file_path}")

    mime_type = _mime_type(file_path)

    try:
        file_bytes = file_path.read_bytes()
    except OSError as exc:
        logger.error("Falha ao ler o arquivo %s: %s", file_path, exc)
        raise

    model = build_model()
    try:
        response = generate_content_with_retry(
            model,
            [PROMPT, {"mime_type": mime_type, "data": file_bytes}],
            {"response_mime_type": "application/json"},
        )
    except Exception as exc:
        logger.error("Falha na chamada a API Gemini para %s: %s", file_path, exc)
        raise

    try:
        raw_data = json.loads(response.text)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Resposta da Gemini API nao e um JSON valido para %s: %s", file_path, exc)
        raise

    # A origem e sempre o nome real do arquivo, independente do que o modelo retornar.
    raw_data["origem"] = file_path.name
    return TreinoBronze.model_validate(raw_data)


def save_bronze(treino: TreinoBronze, file_path: Path) -> Path:
    """Salva o JSON bruto extraido em data/bronze/."""
    BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    output_path = BRONZE_DIR / f"{file_path.stem}.json"
    output_path.write_text(treino.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def extract_and_save(file_path: Path) -> Path:
    """Extrai uma ficha e salva o resultado bruto em data/bronze/."""
    treino = extract_treino(file_path)
    return save_bronze(treino, file_path)


def extract_all(raw_dir: Path) -> list[Path]:
    """Processa todos os arquivos suportados em raw_dir.

    Arquivos com erro de extracao (API ou arquivo corrompido) sao
    registrados no log e pulados, sem interromper o processamento dos
    demais. Ja o esgotamento da cota *diaria* interrompe o processamento
    imediatamente, pois todos os arquivos restantes falhariam do mesmo jeito.
    """
    saved_paths: list[Path] = []
    for file_path in sorted(raw_dir.iterdir()):
        if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        try:
            saved_paths.append(extract_and_save(file_path))
        except DailyQuotaExceededError as exc:
            logger.error("%s Interrompendo o processamento dos arquivos restantes.", exc)
            break
        except Exception:
            logger.exception("Falha ao processar %s, pulando para o proximo arquivo", file_path)
    return saved_paths
