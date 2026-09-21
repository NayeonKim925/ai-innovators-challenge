"""LLM provider configuration for the Continuum narrative layer.

★ 이식 근거 (ADR-0002) ★
이 모듈은 루트의 `agent.py`가 쓰던 `AnthropicBedrock` 호출부를 그대로 재사용한다.
바뀐 부분은 설정값(리전, 모델 ID)을 하드코딩 상수에서 환경변수로 뺀 것뿐이다 --
`agent.py`는 `BEDROCK_REGION = "us-east-1"`, `MODEL = "us.anthropic.claude-sonnet-4-6"`을
파일 상단에 고정해뒀는데, 이건 리전/모델을 바꾸려면 코드를 고쳐야 한다는 뜻이다.
`.env.example`이 이미 `LLM_PROVIDER`/`OPENAI_API_KEY` 같은 환경변수 패턴을 예고해
뒀으므로, 여기서도 같은 관례를 따른다.

★ 조건부 가용성 (metal_etch_pca.py/metal_etch_adapter.py와 동일 원칙) ★
`anthropic` SDK가 설치돼 있지 않거나 AWS 자격증명이 없는 환경에서도
`backend.app.main`의 import 체인이 죽으면 안 된다. 이 모듈은 클라이언트를
"필요할 때만" 지연 생성하고, 실패하면 `BedrockUnavailable`을 던져서 호출자
(`explainer.py`)가 결정론적 모드로 안전하게 폴백할 수 있게 한다.
대회 기간에는 동일한 Bedrock 계열 모델을 제공하는 OpenAI-compatible Gateway를
사용할 수 있도록 `LLM_PROVIDER=competition_gateway`를 지원한다. 직접 Bedrock
경로는 기본값으로 보존하여 기존 배포와 테스트의 동작을 깨지 않는다.
"""

from __future__ import annotations

import os

try:
    from anthropic import AnthropicBedrock

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

try:
    from openai import OpenAI

    _OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = object  # type: ignore[assignment,misc]
    _OPENAI_AVAILABLE = False


class BedrockUnavailable(RuntimeError):
    """Raised when the Bedrock client cannot be constructed or called.

    Callers must treat this as a normal, expected outcome (missing SDK, missing
    AWS credentials, model access not granted) and fall back to the
    deterministic-only response -- never crash the request.
    """


class GuardrailBlocked(RuntimeError):
    """Raised when the configured Bedrock Guardrail rejects input or output."""


def llm_timeout_s() -> float:
    """Return a bounded timeout for every remote LLM/Guardrail call.

    A bad environment value must not accidentally turn a user request into an
    unbounded connection. The upper bound also stays below the 30s Lambda
    timeout used by the deployment script.
    """
    try:
        configured = float(os.getenv("LLM_TIMEOUT_S", "8"))
    except ValueError:
        configured = 8.0
    return max(1.0, min(configured, 20.0))


def bedrock_region() -> str:
    return os.getenv("BEDROCK_REGION", "us-east-1")


def bedrock_model_id() -> str:
    """Cross-region inference profile ID (the "us." prefix is required --
    see agent.py's original comment: the bare model ID without a region
    prefix fails with "on-demand throughput isn't supported")."""
    return os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")


def llm_provider() -> str:
    """Return the configured provider while keeping direct Bedrock as default."""
    return os.getenv("LLM_PROVIDER", "direct_bedrock").strip().lower()


def llm_api_key() -> str:
    """Return the gateway key without ever logging or exposing its value."""
    return os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")


def llm_base_url() -> str:
    return os.getenv("LLM_BASE_URL", "https://52.79.201.46/v1")


def llm_model_id(task: str = "narrative") -> str:
    """Return the model alias for the active provider and task.

    Narrative output is user-facing and defaults to the stronger balanced
    model. Future high-volume structuring calls can opt into Haiku without
    changing the provider or the current narrative setting.
    """
    if llm_provider() == "competition_gateway":
        if task == "structuring":
            return os.getenv("LLM_STRUCTURING_MODEL", "bedrock-haiku")
        return os.getenv("LLM_MODEL", "bedrock-gpt-5.6-terra")
    return bedrock_model_id()


def llm_is_configured() -> bool:
    """Return whether the active provider has the minimum required settings."""
    if llm_provider() == "competition_gateway":
        return bool(llm_api_key())
    return bool(os.getenv("BEDROCK_MODEL_ID"))


def build_client() -> AnthropicBedrock | OpenAI:
    """Construct the active provider client lazily.

    The gateway uses the OpenAI-compatible SDK but is still backed by the
    competition's Bedrock model aliases. Missing optional SDKs/configuration
    become ``BedrockUnavailable`` so callers can preserve deterministic output.
    """
    provider = llm_provider()
    if provider == "competition_gateway":
        if not _OPENAI_AVAILABLE:
            raise BedrockUnavailable("The 'openai' package is not installed.")
        api_key = llm_api_key()
        if not api_key:
            raise BedrockUnavailable("LLM_API_KEY is not configured for the competition gateway.")
        try:
            return OpenAI(
                base_url=llm_base_url(),
                api_key=api_key,
                timeout=llm_timeout_s(),
                max_retries=0,
            )
        except Exception as exc:
            raise BedrockUnavailable(
                f"Failed to construct the competition gateway client: {exc}"
            ) from exc

    if provider != "direct_bedrock":
        raise BedrockUnavailable(f"Unsupported LLM_PROVIDER: {provider}")

    if not _ANTHROPIC_AVAILABLE:
        raise BedrockUnavailable("The 'anthropic' package is not installed.")
    try:
        return AnthropicBedrock(aws_region=bedrock_region(), timeout=llm_timeout_s())
    except Exception as exc:  # credentials, region misconfiguration, etc.
        raise BedrockUnavailable(f"Failed to construct Bedrock client: {exc}") from exc


def apply_guardrail(text: str, source: str) -> None:
    """Validate text with the configured Guardrail, if one is configured.

    The guardrail is deliberately an independent API call so the same policy
    can protect both direct Bedrock calls and future AgentCore/chat paths.
    """
    # The competition gateway does not expose our account's Bedrock
    # Guardrail API. Keep the safe deterministic/prompt constraints active,
    # but do not accidentally issue a separate AWS call for gateway traffic.
    if llm_provider() == "competition_gateway":
        if os.getenv("LLM_REQUIRE_GUARDRAIL", "false").lower() == "true":
            raise BedrockUnavailable(
                "LLM_REQUIRE_GUARDRAIL=true is unsupported for the competition gateway."
            )
        return

    guardrail_id = os.getenv("BEDROCK_GUARDRAIL_ID")
    guardrail_version = os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT")
    if not guardrail_id:
        if os.getenv("LLM_REQUIRE_GUARDRAIL", "false").lower() == "true":
            raise BedrockUnavailable("A Bedrock Guardrail is required but not configured")
        return
    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "bedrock-runtime",
            region_name=bedrock_region(),
            config=Config(
                connect_timeout=min(3.0, llm_timeout_s()),
                read_timeout=min(5.0, llm_timeout_s()),
                retries={"max_attempts": 1, "mode": "standard"},
            ),
        )
        response = client.apply_guardrail(
            guardrailIdentifier=guardrail_id,
            guardrailVersion=guardrail_version,
            source=source,
            content=[{"text": {"text": text}}],
        )
    except Exception as exc:
        raise BedrockUnavailable("Guardrail could not be evaluated") from exc
    if response.get("action") == "GUARDRAIL_INTERVENED":
        raise GuardrailBlocked("Guardrail blocked the request")
