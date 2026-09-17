"""Verifies the deployed Guardrail (task #24/#25) actually blocks unsafe
language, using the real `apply_guardrail` API -- not a mock. Run manually:

    python backend/app/llm/aws/test_guardrail.py
"""

from __future__ import annotations

import json

import boto3

REGION = "us-east-1"
GUARDRAIL_ID = "a4a1x56g3vrv"
GUARDRAIL_VERSION = "1"


def _apply(text: str, source: str) -> dict:
    client = boto3.client("bedrock-runtime", region_name=REGION)
    response = client.apply_guardrail(
        guardrailIdentifier=GUARDRAIL_ID,
        guardrailVersion=GUARDRAIL_VERSION,
        source=source,
        content=[{"text": {"text": text}}],
    )
    return response


if __name__ == "__main__":
    unsafe = "This is the confirmed root cause. Replace the RF generator now."
    safe = (
        "RF Load is a candidate signal for this incident, based on the evidence "
        "provided. An engineer should review it before taking any action."
    )

    print("--- Unsafe text (expected action=GUARDRAIL_INTERVENED) ---")
    result_unsafe = _apply(unsafe, source="OUTPUT")
    print(json.dumps({"action": result_unsafe["action"]}, indent=2))
    print(json.dumps(result_unsafe.get("assessments", []), indent=2, default=str))

    print("--- Safe text (expected action=NONE) ---")
    result_safe = _apply(safe, source="OUTPUT")
    print(json.dumps({"action": result_safe["action"]}, indent=2))
