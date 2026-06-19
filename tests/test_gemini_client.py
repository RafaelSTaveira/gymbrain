"""Testes da deteccao de cota diaria esgotada em src/gemini_client.py.

Cobrem o bug original: violations sem quota_id (proto vazio ou dict JSON
vazio) causavam AttributeError em vez de DailyQuotaExceededError.
"""

from google.api_core.exceptions import ResourceExhausted
from google.rpc.error_details_pb2 import QuotaFailure

from src.gemini_client import (
    DailyQuotaExceededError,
    FREE_TIER_DAILY_LIMIT,
    _daily_quota_violation,
    _is_daily_quota_message,
    _violation_field,
    generate_content_with_retry,
)


def _resource_exhausted_with_quota_failure(violations) -> ResourceExhausted:
    detail = QuotaFailure()
    for violation in violations:
        v = detail.violations.add()
        if isinstance(violation, dict):
            for key, value in violation.items():
                setattr(v, key, value)
    return ResourceExhausted("429 quota", details=[detail])


class TestViolationField:
    def test_le_campo_de_proto_snake_case(self):
        detail = QuotaFailure()
        v = detail.violations.add()
        v.quota_id = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        assert _violation_field(v, "quota_id", "quotaId") == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"

    def test_le_campo_de_dict_camel_case(self):
        violation = {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
        assert _violation_field(violation, "quota_id", "quotaId") == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"

    def test_dict_vazio_nao_levanta_attribute_error(self):
        assert _violation_field({}, "quota_id", "quotaId") is None

    def test_proto_sem_campo_preenchido_retorna_default(self):
        detail = QuotaFailure()
        v = detail.violations.add()
        assert _violation_field(v, "quota_id", "quotaId") == ""


class TestDailyQuotaViolation:
    def test_encontra_violacao_per_day_em_proto(self):
        exc = _resource_exhausted_with_quota_failure(
            [{"quota_id": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]
        )
        violation = _daily_quota_violation(exc)
        assert violation is not None
        assert "PerDay" in violation.quota_id

    def test_violacao_sem_quota_id_nao_levanta_attribute_error(self):
        # Caso real do bug: violations vem com um item vazio ("violations": [{}]),
        # ou seja, sem o campo quota_id preenchido.
        exc = _resource_exhausted_with_quota_failure([{}])
        assert _daily_quota_violation(exc) is None


class TestIsDailyQuotaMessage:
    def test_mensagem_com_free_tier_requests_e_limite_e_detectada(self):
        exc = ResourceExhausted(
            "429 You exceeded your current quota for quota metric "
            "'generate_content_free_tier_requests', limit: 20 per day."
        )
        assert _is_daily_quota_message(exc) is True

    def test_mensagem_sem_free_tier_requests_nao_e_detectada(self):
        exc = ResourceExhausted("429 rate limit exceeded, try again later")
        assert _is_daily_quota_message(exc) is False

    def test_mensagem_com_free_tier_requests_mas_sem_o_limite_nao_e_detectada(self):
        exc = ResourceExhausted("429 free_tier_requests quota exceeded")
        assert _is_daily_quota_message(exc) is False


class TestGenerateContentWithRetry:
    def test_levanta_daily_quota_quando_violation_tem_quota_id(self):
        class _ModelFake:
            model_name = "gemini-2.5-flash"

            def generate_content(self, *_args, **_kwargs):
                raise _resource_exhausted_with_quota_failure(
                    [{"quota_id": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quota_value": 20}]
                )

        try:
            generate_content_with_retry(_ModelFake(), contents=["oi"])
            assert False, "deveria ter levantado DailyQuotaExceededError"
        except DailyQuotaExceededError as exc:
            assert "20" in str(exc)

    def test_levanta_daily_quota_via_mensagem_quando_violation_vem_vazia(self):
        class _ModelFake:
            model_name = "gemini-2.5-flash"

            def generate_content(self, *_args, **_kwargs):
                raise ResourceExhausted(
                    "429 quota metric 'generate_content_free_tier_requests', limit: 20 per day.",
                    details=[{"violations": [{}]}],
                )

        try:
            generate_content_with_retry(_ModelFake(), contents=["oi"])
            assert False, "deveria ter levantado DailyQuotaExceededError"
        except DailyQuotaExceededError as exc:
            assert str(FREE_TIER_DAILY_LIMIT) in str(exc)
