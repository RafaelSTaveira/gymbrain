"""Extracao de fichas de treino (imagem ou PDF) via Gemini Vision."""

import json
import logging
import time
from pathlib import Path

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from google.rpc.error_details_pb2 import QuotaFailure, RetryInfo

from src.config import BRONZE_DIR, GEMINI_API_KEY, GEMINI_MODEL_NAME
from src.models.schemas import TreinoBronze

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

# O free tier da Gemini API limita ~20 requisicoes/minuto por modelo.
# Espacar as chamadas evita boa parte dos 429 antes mesmo de acontecerem.
MIN_SECONDS_BETWEEN_CALLS = 3.5
MAX_RETRIES_ON_RATE_LIMIT = 5

_last_call_at: float = 0.0


class DailyQuotaExceededError(RuntimeError):
    """A cota diaria de requisicoes do free tier (nao a de RPM) foi esgotada.

    Diferente do 429 de RPM, esperar e tentar de novo nao resolve: a cota so
    volta no proximo reset diario da Gemini API.
    """


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


def _build_model() -> genai.GenerativeModel:
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(GEMINI_MODEL_NAME)


def _wait_for_rate_limit() -> None:
    """Garante um intervalo minimo entre chamadas para respeitar o limite de RPM."""
    global _last_call_at
    remaining = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call_at)
    if remaining > 0:
        time.sleep(remaining)
    _last_call_at = time.monotonic()


def _retry_delay_seconds(exc: ResourceExhausted) -> float | None:
    """Extrai o tempo de espera sugerido pela API (google.rpc.RetryInfo), se houver."""
    for detail in getattr(exc, "details", None) or []:
        if isinstance(detail, RetryInfo):
            return detail.retry_delay.seconds + detail.retry_delay.nanos / 1e9
    return None


def _daily_quota_violation(exc: ResourceExhausted) -> QuotaFailure.Violation | None:
    """Procura uma violacao de cota *diaria* (quota_id contendo "PerDay") no 429.

    Essa cota e separada da de RPM: nenhum retry/backoff a resolve antes do
    proximo reset diario da API.
    """
    for detail in getattr(exc, "details", None) or []:
        if isinstance(detail, QuotaFailure):
            for violation in detail.violations:
                if "PerDay" in violation.quota_id:
                    return violation
    return None


def _generate_content_with_retry(model: genai.GenerativeModel, contents: list, generation_config: dict):
    """Chama a Gemini API respeitando o rate limit, com retry e backoff em 429."""
    for attempt in range(1, MAX_RETRIES_ON_RATE_LIMIT + 1):
        _wait_for_rate_limit()
        try:
            return model.generate_content(contents, generation_config=generation_config)
        except ResourceExhausted as exc:
            violation = _daily_quota_violation(exc)
            if violation is not None:
                raise DailyQuotaExceededError(
                    f"Cota diaria do free tier esgotada para o modelo "
                    f"'{GEMINI_MODEL_NAME}' (limite: {violation.quota_value} requisicoes/dia). "
                    "Aguarde o reset diario da Gemini API ou habilite billing/troque de modelo."
                ) from exc
            if attempt == MAX_RETRIES_ON_RATE_LIMIT:
                raise
            wait_seconds = _retry_delay_seconds(exc)
            if wait_seconds is None:
                wait_seconds = 2**attempt  # backoff exponencial caso a API nao informe o retry_delay
            logger.warning(
                "Rate limit da Gemini API (tentativa %d/%d), aguardando %.1fs antes de tentar novamente.",
                attempt,
                MAX_RETRIES_ON_RATE_LIMIT,
                wait_seconds,
            )
            time.sleep(wait_seconds)


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

    model = _build_model()
    try:
        response = _generate_content_with_retry(
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
