"""Cliente compartilhado para chamadas a Gemini API, com rate limit e deteccao de cota.

Usado tanto pela extracao Bronze (src/bronze/extractor.py) quanto pelo
orquestrador da camada de IA (src/ai/orchestrator.py), para nao duplicar o
tratamento de rate limit (RPM) e de cota diaria esgotada do free tier.
"""

import logging
import re
import time
from collections.abc import Mapping

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from google.rpc.error_details_pb2 import QuotaFailure, RetryInfo

from src.config import GEMINI_API_KEY, GEMINI_MODEL_NAME

logger = logging.getLogger(__name__)

# O free tier da Gemini API limita ~20 requisicoes/minuto por modelo.
# Espacar as chamadas evita boa parte dos 429 antes mesmo de acontecerem.
MIN_SECONDS_BETWEEN_CALLS = 3.5
MAX_RETRIES_ON_RATE_LIMIT = 5

# Limite diario do free tier (requisicoes/dia). Usado como fallback quando o
# 429 nao informa quota_value (ex: violation sem esse campo).
FREE_TIER_DAILY_LIMIT = 20

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


def _violation_field(violation, name: str, json_name: str):
    """Le um campo de uma violacao de cota, que pode vir como proto ou dict.

    O transporte REST da API entrega os details do 429 como dicts JSON
    (chaves camelCase, ex: "quotaId"), enquanto o transporte grpc entrega
    mensagens protobuf (atributos snake_case, ex: quota_id). Alem disso,
    nem toda violacao traz o campo preenchido (ex: "violations": [{}]).
    Usar getattr/.get direto sem isso e o que causava o AttributeError.
    """
    if isinstance(violation, Mapping):
        return violation.get(json_name) or violation.get(name)
    return getattr(violation, name, None)


def _daily_quota_violation(exc: ResourceExhausted):
    """Procura uma violacao de cota *diaria* (quota_id contendo "PerDay") no 429.

    Essa cota e separada da de RPM: nenhum retry/backoff a resolve antes do
    proximo reset diario da API.
    """
    for detail in getattr(exc, "details", None) or []:
        if isinstance(detail, QuotaFailure):
            for violation in detail.violations:
                quota_id = _violation_field(violation, "quota_id", "quotaId") or ""
                if "PerDay" in quota_id:
                    return violation
    return None


def _is_daily_quota_message(exc: ResourceExhausted) -> bool:
    """Sinal alternativo de cota diaria esgotada quando o 429 nao traz quota_id.

    O free tier expoe a cota diaria pela metrica
    "...generate_content_free_tier_requests" com limite de 20/dia: quando a
    violacao vem sem quota_id (ex: "violations": [{}]), usamos a mensagem de
    erro do 429 como sinal alternativo.
    """
    message = str(exc).lower()
    if "free_tier_requests" not in message:
        return False
    return bool(re.search(rf"\b{FREE_TIER_DAILY_LIMIT}\b", message))


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
            if violation is not None or _is_daily_quota_message(exc):
                quota_value = _violation_field(violation, "quota_value", "quotaValue") if violation is not None else None
                limite = quota_value or FREE_TIER_DAILY_LIMIT
                raise DailyQuotaExceededError(
                    f"Cota diaria do free tier esgotada para o modelo "
                    f"'{model.model_name}' (limite: {limite} requisicoes/dia). "
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
