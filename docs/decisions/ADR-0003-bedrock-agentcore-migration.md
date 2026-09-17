# ADR-0003: Bedrock Agents Classic 대신 AgentCore로 LLM 도구 연동, App Runner 대신 ECS Express Mode로 프론트엔드 배포

## 상태

승인됨. 실제 AWS 리소스로 배포 완료 (2026-09-14 ~ 2026-09-15).

## 추가 기록 (2026-09-15): 두 번째 AWS 플랫폼 전환 사례 — App Runner도 신규 계정에 닫혀 있었다

태스크 #28(Streamlit 프론트엔드를 AWS에 배포)에서 원래 계획은 AWS App Runner였다. 실제로 시도한 결과, 모든 API 호출(`list-services`, `list-connections`)이 리전(us-east-1/us-west-2/us-east-2 전부)과 무관하게 다음 오류로 실패했다.

```
SubscriptionRequiredException: The AWS Access Key Id needs a subscription for the service
```

`AWSAppRunnerFullAccess` 관리형 정책을 IAM 사용자에 추가한 뒤에도 동일하게 실패해, IAM 권한 문제가 아님을 확인했다. AWS 공식 문서(<https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html>)를 확인한 결과, App Runner도 신규 고객에게 닫혀 있고 계정 레벨 제한이라 콘솔 방문이나 IAM 정책 추가로 풀리지 않는다는 것을 확인했다. Bedrock Agents Classic(태스크 #13) 이후 이번이 **두 번째로 발견된 "AWS가 이 대회 진행 시점에 이미 단계적으로 폐쇄한 서비스"** 사례다.

사용자가 지정한 대체 서비스는 Amazon ECS Express Mode(re:Invent 2025에서 발표된 App Runner의 공식 후속 서비스)였다. 진행 순서:

1. `ecsTaskExecutionRole`(trust: `ecs-tasks.amazonaws.com`, 정책: `AmazonECSTaskExecutionRolePolicy`)와 `ecsInfrastructureRoleForExpressServices`(trust: `ecs.amazonaws.com`, 정책: `AmazonECSInfrastructureRoleforExpressGatewayServices`) 두 IAM 역할 생성.
2. IAM 사용자에 `AmazonECS_FullAccess` 추가.
3. `aws ecs create-express-gateway-service`로 서비스 생성. 첫 시도는 `--primary-container`에 `port` 파라미터를 썼다가 `Unknown parameter ... must be one of: image, containerPort, ...`로 실패 → `containerPort`로 수정해서 해결. 두 번째 시도는 `Unable to assume the service linked role`로 실패 → ECS 서비스 연결 역할(`AWSServiceRoleForECS`)이 막 생성돼 전파 중이었던 것으로, 30초 대기 후 재시도해서 해결.
4. 서비스가 실제로 `CANARY` 배포 전략(5% canary, 3분 bake time)으로 태스크를 하나씩 늘려가며 배포됨을 실측 확인 (`rolloutState`: `IN_PROGRESS` → `COMPLETED`, `runningCount`: 0 → 1).

## 실제 배포 증거 — ECS Express Mode 프론트엔드

- 서비스 ARN: `arn:aws:ecs:us-east-1:430013477501:service/default/mfg-investigation-frontend`
- 엔드포인트: `https://mf-402d7cdcc2334f2c849cfe7485511d5c.ecs.us-east-1.on.aws`
- `curl`/`Invoke-WebRequest`로 실제 확인: 루트 경로가 실제 Streamlit HTML 셸을 200으로 반환, `/_stcore/health`가 `ok`를 200으로 반환.
- `BACKEND_URL` 환경변수를 태스크 #26에서 배포한 실제 Lambda+API Gateway 엔드포인트(`https://dwn13wrel9.execute-api.us-east-1.amazonaws.com`)로 지정 — 프론트엔드와 백엔드 모두 로컬이 아닌 실제 AWS 인프라에서 서로 통신하는 구성.
- 사용한 컨테이너 이미지는 이전에 준비해 둔 `mfg-investigation-frontend:latest`(ECR에 이미 push됨, `frontend/Dockerfile`)를 그대로 재사용 — App Runner용으로 만든 이미지가 ECS Express Mode에도 그대로 쓰인다는 것을 확인(이미지 자체는 플랫폼에 종속적이지 않음).

## 결정 (추가)

App Runner를 이 프로젝트의 배포 대상에서 제외하고, ECS Express Mode를 프론트엔드 배포의 정식 경로로 채택한다. `frontend/deploy_apprunner.py`는 삭제하지 않고 참고 자료로 남긴다 — App Runner가 막혀 있었다는 사실 자체와, IAM 역할/이미지 준비까지는 App Runner든 ECS Express Mode든 동일했다는 것을 보여주는 근거가 된다. 대신 `frontend/deploy_ecs_express.py`(신규)가 실제 배포 경로가 된다.

## 이유 (추가)

- Bedrock Agents Classic과 App Runner 두 사례 모두 "AWS 서비스가 신규 계정에 닫혀 있다"는 동일한 패턴이다. 이건 우연이 아니라, 이 대회 진행 시점(2026년 하반기)에 AWS가 여러 "Classic"/1세대 관리형 서비스를 신규 고객에게 순차적으로 닫고 후속 서비스(AgentCore, ECS Express Mode)로 유도하고 있다는 것을 시사한다.
- 두 경우 모두 증거(AccessDeniedException/SubscriptionRequiredException 실제 오류 메시지 + AWS 공식 문서)를 먼저 확인한 뒤에만 전환을 결정했다 — "이 서비스가 안 되니까 대충 다른 걸 쓴다"가 아니라, 계정 레벨 제한임을 문서로 확인하고 나서만 대체재로 전환하는 원칙을 두 번 다 지켰다.

## 배경

ADR-0002는 `backend/app/llm/`을 만들면서, LLM narrative 생성뿐 아니라 "Bedrock Agent 생성 + Action Group 등록 + Guardrails 등록"까지 태스크로 잡았다. 이 태스크는 `backend/app/llm/action_group_schema.json`(OpenAPI 3.0, `get_root_cause_ranking`/`get_fault_reference` 두 오퍼레이션)까지 준비된 상태에서 실행 단계로 넘어갔다.

IAM 사용자(`ai-innovation-challenge`, AmazonBedrockFullAccess 포함) 자격증명으로 `aws bedrock-agent create-agent`를 호출(boto3 `create_agent`)한 결과, 다음 오류가 발생했다.

```
botocore.errorfactory.AccessDeniedException: An error occurred (AccessDeniedException)
when calling the CreateAgent operation: Bedrock Agents is in Maintenance Mode.
New agent creation is not available for accounts without prior service usage.
```

AWS 공식 문서(<https://docs.aws.amazon.com/bedrock/latest/userguide/agents-classic-maintenance-mode.html>)를 확인한 결과, "Amazon Bedrock Agents"(2023년 11월 출시)는 이제 "Amazon Bedrock Agents **Classic**"으로 명명이 바뀌었고, **2026년 7월 30일부로 신규 고객에게 닫혔다.** 이 AWS 계정(430013477501)은 Bedrock Agents Classic을 이전에 써본 적이 없어서, IAM 권한이 충분해도 `CreateAgent` API 자체가 서비스 정책 레벨에서 거부된다. 이는 코드나 권한 설정의 결함이 아니라, 대회 진행 시점(2026-09)에 AWS가 이미 이 서비스를 단계적으로 폐쇄하고 있었기 때문이다.

AWS는 대안으로 Amazon Bedrock AgentCore를 제시한다. AgentCore는 Agents Classic과 API 형태가 다르며(Harness/Runtime/Gateway/Memory로 구성된 모듈형 플랫폼), 단일 `create_agent` 호출로 되지 않고 다음이 필요하다:

- Runtime: 컨테이너 이미지를 빌드해 ECR에 올리고, `create_agent_runtime`으로 배포
- Gateway: Lambda/OpenAPI/Smithy를 MCP 호환 tool로 노출하는 `create_gateway` + `create_gateway_target`
- Guardrails: 기존 Bedrock Guardrails API(`create_guardrail`)는 AgentCore와 무관하게 그대로 사용 가능 — 이 서비스는 Maintenance Mode 제약을 받지 않았다

## 결정

1. `aws bedrock-agent create-agent`(Bedrock Agents Classic)로 진행하려던 계획을 폐기하고, **Amazon Bedrock AgentCore Runtime + Gateway**로 대체한다.
2. 재사용 가능한 실전 코드 패턴은 사용자가 제공한 강의 저장소([k2hdevil/Workshop-Healthcare-AgentCore](https://github.com/k2hdevil/Workshop-Healthcare-AgentCore), `022_runtime_deploy.md`)의 Container 배포 절차(IAM 역할 생성 → ECR 리포지토리 → docker build/push → `create_agent_runtime`)를 구조적으로 재사용했다. 의료 상담 에이전트 로직 대신, 이미 존재하는 `backend/app/llm/explainer.generate_narrative()`를 그대로 호출하는 엔트리포인트로 교체했다 — AgentCore로 옮겨도 "LLM이 새 수치를 계산하지 않는다"는 AGENTS.md 원칙은 그대로 유지된다.
3. `get_root_cause_ranking`/`get_fault_reference`는 AgentCore Gateway의 Lambda target으로 등록했다. 원래 `action_group_schema.json`이 설계한 계약(`incident_id`로 저장된 조사 결과를 조회)은 실제 배포된 조사 API(태스크 #17)가 아직 없어서 그대로 쓸 수 없었다 — 대신 이미 계산된 `investigation_result` payload를 그대로 받아 재요약하는 계약으로 축소했다. 이건 임시 타협이 아니라, "도구가 수치를 재계산하지 않는다"는 원칙을 지키면서 현재 시점에 정직하게 구현 가능한 유일한 형태다. 태스크 #17이 완료되어 조사 API가 실제 URL로 배포되면, 이 Lambda를 그 URL을 호출하는 방식으로 교체할 수 있다.
4. Guardrails는 별도 서비스라 Maintenance Mode의 영향을 받지 않았고, 계획대로 `create_guardrail`로 생성했다.

## 실제 배포 증거 (지어낸 값 아님, 실행 로그 기준)

- Guardrail: `guardrailId=a4a1x56g3vrv`, version 1. `apply_guardrail`로 실제 검증: "This is the confirmed root cause. Replace the RF generator now."라는 문장이 topic policy(`EquipmentControlInstructions`)와 word policy(`confirmed root cause`) 둘 다에 걸려 `action=GUARDRAIL_INTERVENED`로 차단됨. 안전한 문장("RF Load is a candidate signal... An engineer should review it")은 `action=NONE`으로 통과.
- AgentCore Runtime: `arn:aws:bedrock-agentcore:us-east-1:430013477501:runtime/mfg_investigation_explainer-6hhXzrBcNk`, status=READY. 실제 causRCA 조사 결과(incident `case_00e964450b22e69e0d42089c`)를 payload로 `invoke_agent_runtime` 호출 → Bedrock Claude Sonnet 4.6이 실제로 응답(latency_ms=8724.1, token_usage=1068), "status가 candidate일 뿐 확정 원인이 아님"과 "배경지식은 AI가 정리한 것이며 검증된 매뉴얼이 아님"을 명시한 한국어 요약을 생성함.
- AgentCore Gateway: `gatewayId=mfg-investigation-gateway-iddfv7fzea`, URL `https://mfg-investigation-gateway-iddfv7fzea.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp`. `tools/list`로 `investigation-tools___get_fault_reference`/`investigation-tools___get_root_cause_ranking` 두 tool이 실제로 노출됨을 확인. `tools/call`로 둘 다 실제 호출해 정상 JSON 응답을 받음(SigV4 서명된 HTTPS 요청, `backend/app/llm/aws/invoke_gateway.py`).
- 관련 파일: `backend/app/llm/aws/`(trust/invoke policy JSON, `provision_agent.py`, `deploy_agentcore.py`, `agentcore_main.py`, `Dockerfile`, `deploy_gateway.py`, `lambda_tools/handler.py`, `gateway_tool_schema.json`, `invoke_agentcore.py`, `invoke_gateway.py`, `test_guardrail.py`).

## 이유

- AWS 서비스 자체의 정책 변경(신규 계정 차단)은 이 프로젝트가 통제할 수 없는 외부 제약이다. 이걸 "구현 실패"로 남기지 않고, 실제로 동작하는 대체 경로(AgentCore)로 완주한 것이 기술적 우월성 평가 기준(배점표 1단계)에 더 부합한다.
- Gateway tool 계약을 `incident_id` 조회 대신 `investigation_result` payload 전달로 바꾼 것은, 아직 존재하지 않는 배포(태스크 #17)에 의존하는 척 하지 않고 지금 실제로 검증 가능한 것만 만들겠다는 이 프로젝트의 원칙("숫자를 지어내지 않는다", "실행이 실패하면 실패 로그를 그대로 보고한다")을 도구 계약 설계에도 동일하게 적용한 것이다.

## 결과

- `backend/app/llm/action_group_schema.json`(Bedrock Agents Classic용 OpenAPI 스키마)은 삭제하지 않고 참고 자료로 남긴다 — Agents Classic이 신규 계정에 닫혔다는 사실 자체가 기록할 가치가 있는 히스토리이기 때문이다.
- `backend/app/llm/bedrock_client.py`/`explainer.py`(Anthropic Messages API를 직접 호출하는 기존 경로)는 변경하지 않는다. AgentCore Runtime은 이 경로를 컨테이너 안에서 그대로 실행하는 것이지, 대체하는 것이 아니다. FastAPI 서비스(`backend/app/main.py`)는 여전히 Bedrock을 직접 호출하며 AgentCore Runtime/Gateway를 호출하지 않는다 — 이 AgentCore 배포는 "AWS AI 서비스를 실제로 다뤘다"는 대회 제출용 증거이며, 프로덕션 요청 경로의 일부가 아니다.
- 이후 누군가 이 프로젝트를 이어받아 Gateway tool 계약을 `incident_id` 기반으로 다시 좁히고 싶다면, 태스크 #17(백엔드 실제 URL 배포) 완료 후 `lambda_tools/handler.py`가 그 URL을 호출하도록 교체하면 된다.
