# 문제 정의와 접근 방법

> 배점 대응: 목적 부합성(문제 접근·해결 과정) 10점

## 문제 (Problem)

반도체·제조 현장에서 설비 이상이 발생하면, 원인 규명은 지금도 대부분 사람의 경험에 의존합니다. 운영자, 공정 엔지니어, 데이터 분석가가 각자 다른 대시보드·로그 파일을 따로 열어보고, 서로 다른 결론을 구두로 맞춰보는 방식이 흔합니다. 이 과정에는 산업 현장에서 반복적으로 지적되는 세 가지 구조적 문제가 있습니다.

1. **경험 의존성**: 숙련 엔지니어가 없으면 원인 후보를 좁히는 속도가 크게 떨어집니다. 특정 인력의 암묵지에 조사 품질이 좌우됩니다.
2. **근거 추적의 어려움**: "왜 이 변수를 원인으로 지목했는가"에 대한 근거가 사람의 기억이나 구두 설명에만 남고, 사후에 재현·검증하기 어렵습니다.
3. **AI 도입 시의 신뢰성 문제**: 최근 LLM 기반 이상 분석 도구가 늘고 있지만, 근거 없이 그럴듯한 답을 만들어내는(hallucination) 위험 때문에 실제 제조 현장에서는 도입을 주저하는 경우가 많습니다. (이 항목은 업계에서 흔히 논의되는 통념 수준의 서술이며, 특정 통계 인용은 하지 않습니다.)

이 프로젝트는 세 번째 문제, 즉 **"AI가 제조 현장에서 신뢰받으려면 무엇을 지켜야 하는가"**를 핵심 축으로 설계했습니다.

## 접근 (Approach) — 왜 "결정론적 통계 분석 + Agentic LLM 검토"인가

이 프로젝트는 LLM이 이상탐지 수치나 원인 순위를 직접 계산하지 않습니다. 대신 다음 원칙을 코드 레벨에서 강제합니다 (`AGENTS.md`).

> "LLM은 도구의 결과를 정리할 수 있지만, 수치 기반 이상 점수와 후보 순위는 입력·버전이 기록된 결정론적 분석 도구가 계산합니다."

이 원칙을 선택한 이유는 두 가지입니다.

- **검증 가능성**: PCA 재구성 오차(SPE contribution) 같은 결정론적 통계 기법은 같은 입력에 항상 같은 출력을 내고, 왜 그 변수가 1위인지 수식으로 설명할 수 있습니다. `backend/app/analytics/causrca.py`와 `backend/app/analytics/metal_etch_pca.py`가 정확히 동일한 함수 시그니처(`rank_*(incident, diagnosis_time, limit) -> (candidates, evidence, warnings)`)로 이 원칙을 구현합니다.
- **LLM의 역할을 "정리자"로 한정**: LLM은 이 결정론적 결과를 사람이 읽기 좋은 문장으로 요약하는 역할만 맡습니다. 숫자를 지어내거나 순위를 바꾸지 않습니다. 이렇게 역할을 나누면, LLM이 실수해도 "설명이 어색하다"는 수준에 그치고 "틀린 원인을 확신 있게 말한다"는 최악의 시나리오를 원천적으로 차단합니다.

또한 `docs/DATA_CONTRACT.md`의 근거 계약 — "근거 없는 후보는 유력 원인으로 순위화하지 않고 `inconclusive`로 처리" — 은 "모를 때는 모른다고 말하는" 신뢰성 설계의 핵심이며, 이 원칙은 문서 선언에 그치지 않고 `evidence_check` 워크플로우 노드로 실제 코드에 구현됩니다.

## 해결 과정 (Process) — 설계부터 통합까지의 흐름

```text
1. 데이터 계약 설계
   → domain.py에 Incident/Observation/Candidate/Evidence/TraceEvent 정의
   → "무엇이 runtime에 들어올 수 있는가"를 스키마로 먼저 확정

2. 데이터 격리 규칙 확정
   → runtime_repository.py의 FORBIDDEN_RUNTIME_KEYS
   → "정답 라벨은 서비스가 절대 볼 수 없다"는 규칙을 테스트로 강제
     (test_runtime_contract.py)

3. 주 benchmark(causRCA) 파이프라인 구축
   → scripts/prepare_causrca.py로 runtime/evaluation 분리
   → evals/run_causrca_benchmark.py로 Hit@1/Hit@3/MRR/MAP@3 측정

4. 이중 데이터셋 검증 (ADR-0001, ADR-0002)
   → causRCA(정답 있음, 100건 HIL) 하나만으로는 "정답이 없는 실제 현장에서도
     동작하는가"를 증명할 수 없다는 문제를 발견
   → Metal Etch(실제 LAM 9600 반도체 장비 데이터)를 같은 Incident 계약으로
     편입해, 정답이 불확실한 상황에서도 동일한 아키텍처가 작동함을 검증
     (ADR-0002)

5. LLM 계층 연결
   → agent.py/agent_tools.py(AWS Bedrock Claude 호출)의 프로토타입을
     evidence_check 게이트 뒤에 배치해 정식 워크플로우로 편입
   → LLM은 결정론적 분석 결과를 정리만 하고, InvestigationResult.mode로
     "결정론적 단독" 모드와 "LLM 내러티브 포함" 모드를 명확히 구분

6. AWS Bedrock 에이전트 계층 실제 배포
   → Amazon Bedrock Agents(Classic)가 2026-07-30부로 신규 계정에 닫혔음을
     실제 API 호출로 확인 (AccessDeniedException, "Maintenance Mode")
   → 계획을 폐기하지 않고 Amazon Bedrock AgentCore(Runtime+Gateway)로
     전환해 실제 배포 완료: Runtime이 explainer.generate_narrative()를
     실행하고 실제 Claude Sonnet 4.6을 호출, Gateway가 get_root_cause_ranking/
     get_fault_reference를 실제 MCP tool로 노출
   → 판단 근거와 실제 배포 증거(Agent ARN, Gateway URL, 호출 로그)는
     docs/decisions/ADR-0003-bedrock-agentcore-migration.md에 기록

7. 백엔드·프론트엔드 실제 AWS 배포
   → 백엔드: Lambda(컨테이너 이미지) + API Gateway HTTP API로 실제 배포,
     실제 인터넷 엔드포인트로 조사→검토→보고서 전체 흐름 왕복 확인
   → 프론트엔드: 계획한 AWS App Runner도 신규 계정에 닫혀 있음을 실제
     API 호출(SubscriptionRequiredException)로 확인 — Bedrock Agents
     Classic에 이어 이번 대회 기간 중 두 번째로 발견한 "AWS가 신규 계정에
     닫아둔 서비스" 사례
   → Amazon ECS Express Mode(App Runner의 공식 후속 서비스)로 전환해
     실제 배포 완료. 백엔드 Lambda 엔드포인트를 BACKEND_URL로 지정해
     프론트엔드·백엔드 모두 로컬이 아닌 실제 AWS 인프라에서 통신
   → 상세 근거는 docs/decisions/ADR-0003-bedrock-agentcore-migration.md
     (App Runner→ECS Express Mode 전환 절 추가)에 기록
```

이 흐름은 "먼저 안전장치(데이터 계약·격리)를 만들고, 그 위에 성능(통계 분석)을 올리고, 마지막에 신뢰 가능한 방식으로 LLM을 얹는다"는 순서를 따릅니다. LLM을 먼저 붙이고 나중에 안전장치를 끼워 넣는 흔한 순서를 뒤집은 것이 이 프로젝트의 설계 의도입니다.
