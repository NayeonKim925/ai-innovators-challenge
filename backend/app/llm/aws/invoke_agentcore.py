"""Invokes the deployed AgentCore Runtime with a real, previously-computed
InvestigationResult (from the causRCA runtime data) to prove the deployed
container actually runs `generate_narrative()` end to end.

Run: python backend/app/llm/aws/invoke_agentcore.py
"""

from __future__ import annotations

import json
import time
import uuid

import boto3

REGION = "us-east-1"
AGENT_NAME = "mfg_investigation_explainer"

control = boto3.client("bedrock-agentcore-control", region_name=REGION)
runtimes = control.list_agent_runtimes()
agent_arn = next(
    rt["agentRuntimeArn"]
    for rt in runtimes["agentRuntimes"]
    if rt["agentRuntimeName"] == AGENT_NAME
)
print(f"agent_arn={agent_arn}")

payload = {
    "investigation_result": {
        "incident_id": "case_00e964450b22e69e0d42089c",
        "dataset": "causrca",
        "diagnosis_time": 212.103,
        "candidates": [
            {
                "rank": 1,
                "signal": "Spd_ActSpeed_Z",
                "reason": (
                    "CausTR ranked this observable signal using the runtime "
                    "expert graph and pre-cutoff observations. It remains an "
                    "investigation candidate, not a confirmed cause."
                ),
                "evidence_ids": ["E1"],
                "status": "candidate",
            }
        ],
        "evidence": [
            {
                "id": "E1",
                "title": "CausTR candidate signal: Spd_ActSpeed_Z",
                "detail": "At t=211.948s, Spd_ActSpeed_Z reported '5000.0' before the diagnosis cutoff.",
                "source": "Pinned causRCA CausalPrioTimeRecencyRCA (d932ab7ad91a) with runtime expert graph",
            }
        ],
        "warnings": ["This is a research investigation aid. Candidates require explicit expert review."],
        "next_action": "Compare each candidate with process documentation and the observed signal history.",
    }
}

client = boto3.client("bedrock-agentcore", region_name=REGION)
session_id = str(uuid.uuid4())
started = time.monotonic()
response = client.invoke_agent_runtime(
    agentRuntimeArn=agent_arn,
    runtimeSessionId=session_id,
    payload=json.dumps(payload).encode(),
    qualifier="DEFAULT",
)

raw = b""
for chunk in response.get("response", []):
    raw += chunk
latency_ms = (time.monotonic() - started) * 1000

print(f"session_id={session_id}")
print(f"latency_ms={latency_ms:.1f}")
print("raw_response=" + raw.decode("utf-8"))
