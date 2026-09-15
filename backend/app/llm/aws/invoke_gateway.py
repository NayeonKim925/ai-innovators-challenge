"""Calls the deployed AgentCore Gateway over MCP (SigV4-signed HTTPS) to
prove get_root_cause_ranking / get_fault_reference are real, callable tools
-- not just a registered schema.

Run: python backend/app/llm/aws/invoke_gateway.py
"""

from __future__ import annotations

import json

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

REGION = "us-east-1"
GATEWAY_URL = (
    "https://mfg-investigation-gateway-iddfv7fzea.gateway.bedrock-agentcore."
    "us-east-1.amazonaws.com/mcp"
)


def _signed_post(body: dict) -> requests.Response:
    session = boto3.Session()
    credentials = session.get_credentials().get_frozen_credentials()
    request = AWSRequest(
        method="POST",
        url=GATEWAY_URL,
        data=json.dumps(body),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    SigV4Auth(credentials, "bedrock-agentcore", REGION).add_auth(request)
    prepared = request.prepare()
    return requests.post(prepared.url, headers=dict(prepared.headers), data=prepared.body, timeout=30)


def _parse_mcp_response(response: requests.Response) -> dict:
    text = response.text
    if text.startswith("event:") or "data:" in text:
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:"):].strip())
    return response.json()


if __name__ == "__main__":
    print("--- tools/list ---")
    list_response = _signed_post({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    print(f"status_code={list_response.status_code}")
    list_body = _parse_mcp_response(list_response)
    print(json.dumps(list_body, indent=2))

    tool_names = [t["name"] for t in list_body.get("result", {}).get("tools", [])]
    fault_ref_tool = next((n for n in tool_names if "get_fault_reference" in n), None)
    if fault_ref_tool is None:
        raise SystemExit(f"get_fault_reference not found among tools: {tool_names}")

    print(f"\n--- tools/call {fault_ref_tool} ---")
    call_response = _signed_post(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": fault_ref_tool,
                "arguments": {"variable_name": "RF Load"},
            },
        }
    )
    print(f"status_code={call_response.status_code}")
    print(json.dumps(_parse_mcp_response(call_response), indent=2))

    ranking_tool = next((n for n in tool_names if "get_root_cause_ranking" in n), None)
    if ranking_tool is None:
        raise SystemExit(f"get_root_cause_ranking not found among tools: {tool_names}")

    print(f"\n--- tools/call {ranking_tool} ---")
    ranking_response = _signed_post(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": ranking_tool,
                "arguments": {
                    "investigation_result": {
                        "candidates": [
                            {
                                "rank": 1,
                                "signal": "Spd_ActSpeed_Z",
                                "status": "candidate",
                                "reason": "CausTR ranked this signal.",
                                "evidence_ids": ["E1"],
                            }
                        ],
                        "evidence": [
                            {
                                "id": "E1",
                                "title": "CausTR candidate signal: Spd_ActSpeed_Z",
                                "detail": "At t=211.948s, reported '5000.0'.",
                                "source": "Pinned causRCA CausalPrioTimeRecencyRCA",
                            }
                        ],
                    },
                    "top_k": 3,
                },
            },
        }
    )
    print(f"status_code={ranking_response.status_code}")
    print(json.dumps(_parse_mcp_response(ranking_response), indent=2))
