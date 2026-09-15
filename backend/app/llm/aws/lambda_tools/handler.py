"""Lambda handler exposed to the AgentCore Gateway as two MCP tools.

★ 계약이 action_group_schema.json과 다른 이유 (실행 로그로 정직하게 기록) ★
원래 `action_group_schema.json`의 `get_root_cause_ranking`은 `incident_id` +
`diagnosis_time`을 받아 "이미 저장된 조사 결과를 조회"하는 걸로 설계됐다.
그 조회 대상(저장된 InvestigationResult)은 지금 FastAPI 프로세스의 in-memory
저장소(`backend/app/repositories/investigations.py`)에만 있고, 이 저장소는
아직 인터넷에 노출된 배포가 없다 (태스크 #17, 아직 미완료). Lambda가 그
저장소를 직접 조회할 방법이 없으므로, 이 두 함수는 대신
`backend/app/llm/aws/agentcore_main.py`와 같은 계약(이미 계산된
`investigation_result` payload를 그대로 받아 재요약)을 쓴다. 이건
"LLM/도구가 수치를 새로 계산하지 않는다"는 AGENTS.md 원칙을 그대로
지키면서, 태스크 #17이 아직 없는 상태에서 실제로 동작 가능한 유일한
정직한 구현이다. 태스크 #17에서 백엔드가 실제 URL로 배포되면, 이 Lambda를
그 URL을 호출하는 방식으로 교체할 수 있다.
"""

from __future__ import annotations

import json


FAULT_REFERENCE: dict[str, dict[str, str]] = {
    "TCP": {
        "title": "TCP (Transformer Coupled Plasma) family",
        "role": "Generates the plasma itself via RF power on the chamber's top coil.",
        "common_causes": "RF generator output drift, impedance matching network mistuning, coil wear.",
        "symptoms": "Etch rate changes, wafer surface non-uniformity.",
    },
    "RF": {
        "title": "RF (wafer chuck bias) family",
        "role": "Controls ion bombardment energy at the wafer chuck. A separate power system from TCP.",
        "common_causes": "Bias RF generator fault, chuck-wafer contact issue.",
        "symptoms": "Etch selectivity/profile changes; wafer damage risk if excessive.",
    },
    "CL2": {
        "title": "Cl2 Flow (reactive gas)",
        "role": "Primary reactive gas for metal etch.",
        "common_causes": "MFC drift, gas line blockage/leak.",
        "symptoms": "Etch rate/selectivity changes.",
    },
    "BCL3": {
        "title": "BCl3 Flow (reactive gas)",
        "role": "Usually paired with Cl2 to remove native oxide.",
        "common_causes": "MFC drift, gas line blockage/leak.",
        "symptoms": "Etch rate/selectivity changes.",
    },
    "PR": {
        "title": "Pressure (chamber pressure)",
        "role": "Affects plasma density and ion mean free path.",
        "common_causes": "Throttle valve fault, pump degradation.",
        "symptoms": "Etch profile (vertical/tapered) changes.",
    },
    "HE": {
        "title": "He Press (chuck backside cooling pressure)",
        "role": "Helps heat transfer between wafer and electrostatic chuck.",
        "common_causes": "Chuck seal leak, He supply line fault.",
        "symptoms": "Wafer temperature non-uniformity.",
    },
}
FAULT_REFERENCE_DISCLAIMER = (
    "AI-curated general process knowledge, not a verified equipment manual. "
    "For reference only; a process engineer must confirm before use."
)
_KEYWORD_PREFIXES: dict[str, str] = {
    "TCP": "TCP", "RF": "RF", "CL2": "CL2", "BCL3": "BCL3", "PR": "PRESSURE", "HE": "HE",
}


def _get_fault_reference(variable_name: str) -> dict:
    name = variable_name.strip().upper()
    for keyword, prefix in _KEYWORD_PREFIXES.items():
        if name.startswith(prefix):
            entry = FAULT_REFERENCE[keyword]
            return {"found": True, "variable": variable_name, **entry, "disclaimer": FAULT_REFERENCE_DISCLAIMER}
    return {"found": False, "reason": f"Could not resolve a subsystem for '{variable_name}'."}


def _get_root_cause_ranking(investigation_result: dict, limit: int = 3) -> dict:
    """Repackages an ALREADY-COMPUTED investigation_result. Never recomputes
    candidates/scores -- see module docstring for why this differs from the
    original incident_id-based lookup contract."""
    evidence_by_id = {item["id"]: item for item in investigation_result.get("evidence", [])}
    top = [c for c in investigation_result.get("candidates", []) if c.get("status") == "candidate"][:limit]
    return {
        "found": bool(top),
        "candidates": [
            {
                "rank": c["rank"],
                "signal": c["signal"],
                "status": c["status"],
                "reason": c["reason"],
                "evidence": [
                    {
                        "title": evidence_by_id[eid]["title"],
                        "detail": evidence_by_id[eid]["detail"],
                        "source": evidence_by_id[eid]["source"],
                    }
                    for eid in c.get("evidence_ids", [])
                    if eid in evidence_by_id
                ],
            }
            for c in top
        ],
    }


def handler(event, context):  # noqa: ANN001
    """AgentCore Gateway Lambda targets invoke with `event` containing only
    the tool's declared input fields. The tool identity (which of this
    Lambda's tools was called) is delivered separately via
    `context.client_context.custom["bedrockAgentCoreToolName"]`, formatted as
    "<target-name>___<tool-name>" (AgentCore's gateway naming convention --
    the target name prefix must be stripped by the Lambda per AWS docs:
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/
    gateway-add-target-lambda.html)."""
    custom = {}
    client_context = getattr(context, "client_context", None)
    if client_context is not None:
        custom = getattr(client_context, "custom", None) or {}
    tool_name = custom.get("bedrockAgentCoreToolName", "")
    # Strip the "<target>___" prefix if present.
    short_name = tool_name.rsplit("___", 1)[-1] if tool_name else ""

    if short_name == "get_fault_reference":
        result = _get_fault_reference(event.get("variable_name", ""))
    elif short_name == "get_root_cause_ranking":
        result = _get_root_cause_ranking(
            event.get("investigation_result", {}), event.get("top_k", 3)
        )
    else:
        result = {
            "error": f"Unknown tool: {tool_name!r}",
            "event_keys": list(event.keys()),
            "has_client_context": client_context is not None,
        }
    return result


if __name__ == "__main__":
    print(json.dumps(_get_fault_reference("RF Load"), indent=2))
    print(
        json.dumps(
            _get_root_cause_ranking(
                {
                    "candidates": [
                        {"rank": 1, "signal": "RF Load", "status": "candidate", "reason": "r", "evidence_ids": ["E1"]}
                    ],
                    "evidence": [{"id": "E1", "title": "t", "detail": "d", "source": "s"}],
                }
            ),
            indent=2,
        )
    )
