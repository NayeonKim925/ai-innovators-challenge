"""AgentCore Runtime entrypoint for the manufacturing investigation explainer.

★ Bedrock Agents Classic이 신규 계정에 막혀 AgentCore로 전환한 이유 ★
`aws bedrock-agent create-agent`가 이 계정(430013477501)에서
AccessDeniedException("Bedrock Agents is in Maintenance Mode. New agent
creation is not available for accounts without prior service usage.")를
던졌다. AWS 공식 문서(agents-classic-maintenance-mode.html)에 따르면
Bedrock Agents Classic은 2026-07-30부로 신규 고객에게 닫혔고, 후속 서비스는
Amazon Bedrock AgentCore다. 이 파일은 그 AgentCore Runtime에 배포하기 위한
엔트리포인트다. 참고: https://github.com/k2hdevil/Workshop-Healthcare-AgentCore
의 022_runtime_deploy.md 패턴(Container 배포, boto3 create_agent_runtime)을
구조적으로 재사용했다 -- 다만 의료 상담 에이전트 대신, 이미 존재하는
`backend/app/llm/explainer.generate_narrative()`를 그대로 호출하는 코드로
바꿨다. 이 파일은 여전히 "LLM이 새 수치를 계산하지 않는다"는 AGENTS.md
원칙을 지킨다 -- payload로 이미 계산된 InvestigationResult를 받고, 이걸
그대로 `generate_narrative()`에 넘길 뿐이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp

# backend/app을 import 경로에 추가 (컨테이너 내부에서는 backend/가 WORKDIR/app 하위에 복사됨)
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.domain import Candidate, DatasetName, Evidence, InvestigationResult  # noqa: E402
from app.llm.explainer import generate_narrative  # noqa: E402

app = BedrockAgentCoreApp()


@app.entrypoint
def investigation_explainer(payload: dict) -> dict:
    """payload는 이미 결정론적으로 계산된 InvestigationResult의 JSON 표현을
    담은 `investigation_result` 키를 기대한다. 이 함수는 새 원인후보를
    계산하지 않고, 이미 있는 결과를 요약만 한다."""
    raw = payload.get("investigation_result")
    if not raw:
        return {"error": "payload.investigation_result is required"}

    result = InvestigationResult(
        incident_id=raw["incident_id"],
        dataset=DatasetName(raw["dataset"]),
        diagnosis_time=raw["diagnosis_time"],
        candidates=[Candidate(**c) for c in raw.get("candidates", [])],
        evidence=[Evidence(**e) for e in raw.get("evidence", [])],
        trace=[],
        warnings=raw.get("warnings", []),
        next_action=raw.get("next_action", ""),
    )
    narrative, trace_event = generate_narrative(result)
    return {
        "narrative": narrative,
        "trace_event": trace_event.model_dump(mode="json"),
    }


if __name__ == "__main__":
    # AgentCore Runtime expects the container to listen on 8080 (see
    # Dockerfile's EXPOSE 8080). 8888 was only used in the workshop's local
    # test flow where 8080 was occupied by VS Code Server; that constraint
    # does not apply here, and mismatching the port caused every real
    # invocation to fail with a 502 (see docs/decisions/ADR-0003).
    app.run(port=8080)
