"""Gateway tools read verified investigation results from durable storage.

The tool intentionally accepts an opaque ``investigation_id`` rather than a
caller-supplied candidate/evidence payload. This keeps the AgentCore path
inside the same evidence boundary as the FastAPI service.
"""

from __future__ import annotations

import json
import os

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


def _load_investigation(investigation_id: str) -> dict | None:
    table_name = os.getenv("INVESTIGATION_DDB_TABLE")
    if not table_name:
        return None
    import boto3

    response = boto3.resource(
        "dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1")
    ).Table(table_name).get_item(Key={"investigation_id": investigation_id})
    item = response.get("Item")
    if not item:
        return None
    return json.loads(item["result_json"])


def _get_root_cause_ranking(investigation_id: str, limit: int = 3) -> dict:
    """Read and repackage an investigation stored by the API."""
    if not investigation_id:
        return {"found": False, "error": "investigation_id is required."}
    investigation_result = _load_investigation(investigation_id)
    if investigation_result is None:
        return {"found": False, "error": "Investigation was not found in durable storage."}
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
            event.get("investigation_id", ""), event.get("top_k", 3)
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
            {"error": "Set INVESTIGATION_DDB_TABLE to run this tool locally."},
            indent=2,
        )
    )
