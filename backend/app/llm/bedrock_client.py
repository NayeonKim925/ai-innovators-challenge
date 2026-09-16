"""AWS Bedrock (Anthropic Claude) client configuration for the LLM narrative layer.

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
"""

from __future__ import annotations

import os

try:
    from anthropic import AnthropicBedrock

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


class BedrockUnavailable(RuntimeError):
    """Raised when the Bedrock client cannot be constructed or called.

    Callers must treat this as a normal, expected outcome (missing SDK, missing
    AWS credentials, model access not granted) and fall back to the
    deterministic-only response -- never crash the request.
    """


class GuardrailBlocked(RuntimeError):
    """Raised when the configured Bedrock Guardrail rejects input or output."""


def bedrock_region() -> str:
    return os.getenv("BEDROCK_REGION", "us-east-1")


def bedrock_model_id() -> str:
    """Cross-region inference profile ID (the "us." prefix is required --
    see agent.py's original comment: the bare model ID without a region
    prefix fails with "on-demand throughput isn't supported")."""
    return os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")


def build_client() -> AnthropicBedrock:
    if not _ANTHROPIC_AVAILABLE:
        raise BedrockUnavailable("The 'anthropic' package is not installed.")
    try:
        return AnthropicBedrock(aws_region=bedrock_region())
    except Exception as exc:  # credentials, region misconfiguration, etc.
        raise BedrockUnavailable(f"Failed to construct Bedrock client: {exc}") from exc


def apply_guardrail(text: str, source: str) -> None:
    """Validate text with the configured Guardrail, if one is configured.

    The guardrail is deliberately an independent API call so the same policy
    can protect both direct Bedrock calls and future AgentCore/chat paths.
    """
    guardrail_id = os.getenv("BEDROCK_GUARDRAIL_ID")
    guardrail_version = os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT")
    if not guardrail_id:
        if os.getenv("LLM_REQUIRE_GUARDRAIL", "false").lower() == "true":
            raise BedrockUnavailable("A Bedrock Guardrail is required but not configured")
        return
    try:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=bedrock_region())
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
