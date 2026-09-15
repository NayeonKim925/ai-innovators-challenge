"""One-off provisioning script for the Bedrock Agent (task #13, ADR-0002).

★ 왜 별도 스크립트인가 ★
`aws bedrock-agent create-agent` CLI가 이 Windows/PowerShell 환경에서 한글이
포함된 `--instruction` 파라미터 파일을 읽을 때 UTF-8 디코딩에 실패하는
문제가 있었다 (`Unable to load paramfile ... text contents could not be
decoded`). `chcp 65001`, `$env:PYTHONUTF8` 등으로도 해결되지 않아, boto3로
직접 API를 호출하는 이 스크립트로 대체한다. 이 스크립트는 일회성
프로비저닝 도구이며 `backend/app`의 런타임 코드가 이 파일을 import하지
않는다 -- 서비스 자체는 여전히 `backend/app/llm/bedrock_client.py`의
`AnthropicBedrock` 클라이언트만 쓴다(Agent가 아니라 모델을 직접 호출).
이 Bedrock Agent는 대회 심사용으로 "AWS AI 서비스를 실제로 다뤘다"는 증거를
남기기 위해 생성하는 것이며, `main.py`의 조사 흐름이 이 Agent를 호출하지는
않는다 (services/investigations.py가 이미 Anthropic Messages API로 직접
narrative를 만든다).

사용법:
    python backend/app/llm/aws/provision_agent.py create
    python backend/app/llm/aws/provision_agent.py add-action-group <agent_id>
    python backend/app/llm/aws/provision_agent.py prepare <agent_id>
    python backend/app/llm/aws/provision_agent.py create-guardrail
    python backend/app/llm/aws/provision_agent.py invoke <agent_id> <agent_alias_id>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import boto3

REGION = "us-east-1"
ROLE_ARN = "arn:aws:iam::430013477501:role/AmazonBedrockExecutionRoleForAgents_MfgInvestigation"
FOUNDATION_MODEL = "us.anthropic.claude-sonnet-4-6"
AGENT_NAME = "mfg-investigation-explainer"
HERE = Path(__file__).parent


def _instruction_text() -> str:
    return (HERE / "agent_instruction.txt").read_text(encoding="utf-8")


def cmd_create() -> None:
    client = boto3.client("bedrock-agent", region_name=REGION)
    response = client.create_agent(
        agentName=AGENT_NAME,
        agentResourceRoleArn=ROLE_ARN,
        foundationModel=FOUNDATION_MODEL,
        instruction=_instruction_text(),
        description=(
            "ADR-0002: summarizes already-computed root-cause candidates. "
            "Never controls equipment, never invents numbers."
        ),
        idleSessionTTLInSeconds=600,
    )
    print(json.dumps(response["agent"], indent=2, default=str))


def cmd_add_action_group(agent_id: str) -> None:
    client = boto3.client("bedrock-agent", region_name=REGION)
    schema = (HERE.parent / "action_group_schema.json").read_text(encoding="utf-8")
    response = client.create_agent_action_group(
        agentId=agent_id,
        agentVersion="DRAFT",
        actionGroupName="investigation-tools",
        description="Read-only lookups over an already-computed investigation result.",
        apiSchema={"payload": schema},
        actionGroupExecutor={"customControl": "RETURN_CONTROL"},
    )
    print(json.dumps(response["agentActionGroup"], indent=2, default=str))


def cmd_prepare(agent_id: str) -> None:
    client = boto3.client("bedrock-agent", region_name=REGION)
    response = client.prepare_agent(agentId=agent_id)
    print(json.dumps(response, indent=2, default=str))
    print("Waiting for agent to become PREPARED...")
    for _ in range(30):
        status = client.get_agent(agentId=agent_id)["agent"]["agentStatus"]
        print(f"  status={status}")
        if status == "PREPARED":
            return
        if status in ("FAILED", "NOT_PREPARED"):
            raise SystemExit(f"Agent preparation failed with status={status}")
        time.sleep(5)
    raise SystemExit("Timed out waiting for agent to become PREPARED")


def cmd_create_alias(agent_id: str) -> None:
    client = boto3.client("bedrock-agent", region_name=REGION)
    response = client.create_agent_alias(
        agentId=agent_id,
        agentAliasName="demo",
        description="Demo alias used for the AWS AI Innovators Challenge submission.",
    )
    print(json.dumps(response["agentAlias"], indent=2, default=str))


def cmd_create_guardrail() -> None:
    client = boto3.client("bedrock", region_name=REGION)
    response = client.create_guardrail(
        name="mfg-investigation-evidence-guardrail",
        description=(
            "ADR-0002 / AGENTS.md guardrail: blocks language that presents an "
            "investigation candidate as a confirmed physical root cause, and "
            "blocks any equipment-control / repair-instruction language."
        ),
        topicPolicyConfig={
            "topicsConfig": [
                {
                    "name": "EquipmentControlInstructions",
                    "definition": (
                        "Instructions that tell a person or system to physically "
                        "operate, repair, replace, or adjust manufacturing "
                        "equipment (e.g. valves, RF generators, pumps)."
                    ),
                    "examples": [
                        "Replace the RF generator now.",
                        "Open the throttle valve to fix the pressure.",
                        "Shut down the pump immediately.",
                    ],
                    "type": "DENY",
                }
            ]
        },
        wordPolicyConfig={
            "wordsConfig": [
                {"text": "confirmed root cause"},
                {"text": "definitely caused by"},
                {"text": "guaranteed to be the cause"},
            ]
        },
        blockedInputMessaging=(
            "이 요청은 근거 없는 원인 확정 표현이나 설비 제어 지시를 포함할 수 있어 처리할 수 없습니다."
        ),
        blockedOutputsMessaging=(
            "생성된 응답이 근거 없는 원인 확정 표현이나 설비 제어 지시를 포함해 차단되었습니다. "
            "후보는 항상 전문가 검토가 필요한 조사 대상으로만 표현해야 합니다."
        ),
    )
    print(json.dumps(response, indent=2, default=str))


def cmd_invoke(agent_id: str, agent_alias_id: str) -> None:
    client = boto3.client("bedrock-agent-runtime", region_name=REGION)
    session_id = f"demo-session-{int(time.time())}"
    started = time.monotonic()
    response = client.invoke_agent(
        agentId=agent_id,
        agentAliasId=agent_alias_id,
        sessionId=session_id,
        inputText=(
            "간단히 자기소개하고, 당신이 원인을 '확정'하지 않고 '후보'로만 "
            "표현한다는 걸 한 문장으로 설명해줘."
        ),
    )
    chunks: list[str] = []
    for event in response["completion"]:
        if "chunk" in event:
            chunks.append(event["chunk"]["bytes"].decode("utf-8"))
    latency_ms = (time.monotonic() - started) * 1000
    print(f"session_id={session_id}")
    print(f"latency_ms={latency_ms:.1f}")
    print("response_text=" + "".join(chunks))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "create":
        cmd_create()
    elif command == "add-action-group":
        cmd_add_action_group(sys.argv[2])
    elif command == "prepare":
        cmd_prepare(sys.argv[2])
    elif command == "create-alias":
        cmd_create_alias(sys.argv[2])
    elif command == "create-guardrail":
        cmd_create_guardrail()
    elif command == "invoke":
        cmd_invoke(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        raise SystemExit(1)
