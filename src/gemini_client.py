"""Cliente compartilhado para chamadas a Gemini API, com rate limit e deteccao de cota.

Usado tanto pela extracao Bronze (src/bronze/extractor.py) quanto pelo
orquestrador da camada de IA (src/ai/orchestrator.py), para nao duplicar o
tratamento de rate limit (RPM) e de cota diaria esgotada do free tier.
"""

import logging
import time

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from google.rpc.error_details_pb2 import QuotaFailure, RetryInfo

from src.config import GEMINI_API_KEY, GEMINI_MODEL_NAME

logger = logging.getLogger(__name__)

# O free tier da Gemini API limita ~20 requisicoes/minuto por modelo.
# Espacar as chamadas evita boa parte dos 429 antes mesmo de acontecerem.
MIN_SECONDS_BETWEEN_CALLS = 3.5
MAX_RETRIES_ON_RATE_LIMIT = 5

_last_call_at: float = 0.0
_configurado = False


class DailyQuotaExceededError(RuntimeError):
    """A cota diaria de requisicoes do free tier (nao a de RPM) foi esgotada.

    Diferente do 429 de RPM, esperar e tentar de novo nao resolve: a cota so
    volta no proximo reset diario da Gemini API.
    """


def build_model(model_name: str | None = None) -> genai.GenerativeModel:
    """Cria um GenerativeModel configurado com a API key do projeto."""
    global _configurado
    if not _configurado:
        genai.configure(api_key=GEMINI_API_KEY)
        _configurado = True
    return genai.GenerativeModel(model_name or GEMINI_MODEL_NAME)


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


def generate_content_with_retry(model: genai.GenerativeModel, contents: list, generation_config: dict | None = None):
    """Chama a Gemini API respeitando o rate limit, com retry e backoff em 429.

    Levanta DailyQuotaExceededError imediatamente (sem gastar tentativas) se
    o 429 for de cota diaria esgotada - nenhum retry resolve esse caso.
    """
    for attempt in range(1, MAX_RETRIES_ON_RATE_LIMIT + 1):
        _wait_for_rate_limit()
        try:
            return model.generate_content(contents, generation_config=generation_config)
        except ResourceExhausted as exc:
            violation = _daily_quota_violation(exc)
            if violation is not None:
                raise DailyQuotaExceededError(
                    f"Cota diaria do free tier esgotada para o modelo "
                    f"'{model.model_name}' (limite: {violation.quota_value} requisicoes/dia). "
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
