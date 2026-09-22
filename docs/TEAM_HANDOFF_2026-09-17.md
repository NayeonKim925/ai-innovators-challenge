# 팀 핸드오프 · 증거 폐쇄형 사건 오케스트레이션

> 기준일: 2026-09-17 · 기준 브랜치: `service-hardening`
> 목적: 다음 회의와 구현에서 팀원·개발 에이전트가 동일한 제품 경계와 완료 기준을 사용한다.

## 1. 회의에서 먼저 합의할 한 문장

**Cluephase는 제조 이상을 자동으로 진단·제어하는 시스템이 아니라, 결정론적 분석의 후보와 근거를 사람이 검토 가능한 사건으로 전환하고 증거가 닫힐 때까지 후속 확인 업무를 관리하는 연구용 AI 조사 서비스다.**

이 문장이 현재 제품의 범위다. 범용 챗봇, 다수 에이전트의 대화 연출, 설비 제어, 근거 없는 원인 확정으로 확장하지 않는다.

## 2. 현재 구현 상태

| 영역 | 상태 | 구현 근거 | 주의점 |
| --- | --- | --- | --- |
| causRCA runtime/evaluation 분리 | 완료 | `data/runtime/`, `data/evaluation/`, 누출 방지 테스트 | 서비스와 LLM은 evaluation 정답을 읽지 않는다. |
| 결정론적 조사 | 완료 | `backend/app/workflows/investigation.py` | 후보는 확정 원인이 아니다. |
| 선택적 LLM 해설 | 조건부 구현 | `backend/app/services/investigations.py` | 순위·점수·종료 판단을 바꾸지 않는다. |
| Case Orchestrator | 완료 | `backend/app/services/cases.py` | LLM 없이 분석, 근거 확인 업무, 상태 전이를 수행한다. |
| 사건 API | 완료 | `backend/app/main.py` | `POST` 요청은 인증 토큰이 설정된 배포 환경에서 보호된다. |
| Case Inbox UI | 완료 | `frontend/src/App.tsx`, `frontend/src/styles.css` | 실제 저장 이벤트만 보여 준다. 가짜 사고 과정 애니메이션은 금지한다. |
| 사건 영속성 | 구현 완료, AWS 실검증 전 | `backend/app/repositories/cases.py`, `backend/deploy_lambda_api.py` | AWS에서는 `CASE_DDB_TABLE`을 반드시 설정한다. |
| 프론트 프록시 | 완료 | `frontend/server.mjs` | 새 cases API가 allowlist에 포함됐다. |
| 공개 AWS 재배포 | 미실행 | — | 현재 공개 주소는 이 문서의 Case Inbox 변경을 포함하지 않을 수 있다. |

## 3. 이미 검증한 것

- Python backend: `51 passed`
- 변경 backend 파일 Ruff 검사: 통과
- frontend Node tests: `12 passed`
- TypeScript/Vite production build: 통과
- Playwright E2E: `후보 → 증거 확인 → 최종 검토 → 종료` 통과
- 시각 QA: Case Inbox 92/100, 기존 조사 워크스페이스와 일관된 정보 구조 확인

LangGraph/Starlette의 Python 3.14 deprecation warning 10개가 있으나 테스트 실패는 없다.

## 4. 제품 흐름과 상태 계약

```text
사건 선택
  → 진단 시점 지정
  → 결정론적 RCA + 근거 검증
  → Case Orchestrator
       ├─ 후보 있음: 공정 전문가에게 verify_candidate 업무 생성
       │    ├─ confirmed → READY_FOR_REVIEW → 전문가 승인 → CLOSED
       │    └─ refuted / unavailable → REOPENED → collect_observation 업무
       └─ 후보 없음: 운영자에게 collect_observation 업무 생성
            └─ 응답 기록 → ABSTAINED
```

절대 깨면 안 되는 불변식:

1. `CLOSED`는 필수 업무 완료와 별도의 전문가 승인 뒤에만 가능하다.
2. `confirmed`는 “근거 확인 가능”이지 실제 원인 확정이 아니다.
3. `refuted`, `unavailable`, 후보 부재는 자동 원인 추정 대신 재개 또는 판단 보류로 간다.
4. LLM은 설명·질문 정리에만 사용하며 후보 순위, 수치, 상태 전이를 변경하지 않는다.
5. 장비 제어·정비 지시·현장 사실 생성은 하지 않는다.
6. evaluation 데이터는 runtime API, Case Orchestrator, LLM에 전달하지 않는다.
7. 상태 변경은 version 조건부 저장을 사용한다. 오래된 화면의 응답·검토는 409 충돌로 거부한다.

## 5. 핵심 파일 지도

```text
backend/app/domain.py                    Case/Task/Event/Review Pydantic 계약
backend/app/services/cases.py            상태 전이와 업무 계획, LLM 미사용
backend/app/repositories/cases.py        InMemory + DynamoDB 사건 저장소
backend/app/main.py                      Case API, 인증 경계, health storage 표시
backend/deploy_lambda_api.py             case table 생성, Lambda 환경변수·IAM 권한
backend/tests/test_cases.py              종료 게이트·재개·보류·DynamoDB round-trip 회귀 테스트
frontend/src/App.tsx                     Case Inbox, Human Action Queue, Agent Run Ledger
frontend/src/api.ts                      Case API 타입과 호출 계약
frontend/src/presentation.ts             알려진 서버 상태 문구의 UI 한국어 표시만 담당
frontend/server.mjs                      브라우저에서 공개 가능한 API 프록시 allowlist
frontend/e2e/workspace.spec.ts           사건 전체 흐름 브라우저 E2E
docs/CASE_ORCHESTRATION_PLAN.md          제품 방향·상태·배포·평가의 단일 기준
```

## 6. AI 에이전트 파이프라인: 실제 구현과 경계

### 6.1 실제로 실행되는 조사 파이프라인

```text
runtime incident + 사용자가 고른 diagnosis cutoff
  → LangGraph: validate_request
  → LangGraph: deterministic analysis
       ├─ causRCA: CausTR/시간 최근순 기반 후보·근거
       └─ Metal Etch: PCA contribution 후보·근거 (후속 시연 범위)
  → LangGraph: evidence_check
       └─ 근거 ID가 해석되지 않는 후보는 inconclusive로 강등
  → LangGraph: prepare_human_review
  → InvestigationResult(candidate, evidence, warnings, trace)
  → Case Orchestrator
       └─ 역할별 증거 확인 업무와 상태 전이를 생성
```

이 경로가 제품의 핵심 **agentic workflow**다. LangGraph는 네 개의 제한된 노드를 고정 순서로 실행하며, 각 노드는 `TraceEvent`를 남긴다. 모델이 임의의 도구를 고르거나 장비를 조작하지 않는다.

`Case Orchestrator`도 LLM을 호출하지 않는다. 결정론적 결과를 저장한 뒤 후보의 근거 ID에 연결된 `verify_candidate` 또는 `collect_observation` 업무를 만들고, 전문가 응답에 따라 `AWAITING_EVIDENCE → READY_FOR_REVIEW → CLOSED` 혹은 `REOPENED/ABSTAINED`로만 전이한다.

### 6.2 선택적 LLM 파이프라인

```text
evidence_check를 통과한 InvestigationResult
  → 입력 Bedrock Guardrail
  → Claude Bedrock Messages API (SYSTEM_PROMPT + 최소 컨텍스트)
  → 출력 Bedrock Guardrail
  → evidence ID [E...] 인용 검사
  → 통과: narrative 저장 / 실패: 결정론적 결과 유지
```

- 기본값은 `include_llm_narrative=false`다.
- 후보가 없거나 `inconclusive`만 있으면 LLM을 호출하지 않고 `SKIPPED`로 남긴다.
- LLM 오류·시간 초과·Guardrail 차단·근거 ID 누락은 API 실패가 아니라 `UNAVAILABLE`, `BLOCKED`, `UNVERIFIED` 상태와 결정론적 폴백으로 처리한다.
- 비동기 요청은 SQS worker 경로를 지원하지만, 실제 AWS 큐/worker 검증은 아직 완료로 주장하지 않는다.
- Bedrock Agent/AgentCore 관련 실험 스크립트는 존재하지만, 현재 사용자 요청 경로는 이를 호출하지 않는다. 발표에서 “AgentCore 기반 운영 에이전트”라고 주장하면 안 된다.

### 6.3 시스템 프롬프트가 강제하는 것

위치: `backend/app/llm/explainer.py`의 `SYSTEM_PROMPT`.

1. 입력으로 주어진 후보·순위·근거만 사람이 읽기 좋게 요약한다.
2. 새로운 후보, 수치, 순위를 만들거나 바꾸지 않는다.
3. 원인을 확정하지 않고, 후보·전문가 최종 판단으로 표현한다.
4. `inconclusive` 후보의 근거 부족을 숨기지 않는다.
5. 입력된 `E...` 근거 ID를 대괄호로 인용한다.
6. 설비 조작·수리 지시를 만들지 않는다.
7. 2~4문단의 짧은 한국어 답변만 생성한다.

프롬프트는 **정책 안내**이지 유일한 안전장치가 아니다. 코드 구조상 LLM에는 `summarize_candidates()`가 추린 기존 후보·근거와, 신호 계열의 비권위적 참고 지식만 들어간다. 후보 점수 계산 코드와 evaluation 정답은 LLM 모듈에 없다.

### 6.4 Guardrail 구현

위치: `backend/app/llm/bedrock_client.py`.

- `BEDROCK_GUARDRAIL_ID`, `BEDROCK_GUARDRAIL_VERSION`을 환경변수로 받고, Bedrock `ApplyGuardrail`을 **입력과 출력에 각각** 호출한다.
- 배포 환경에서는 `LLM_REQUIRE_GUARDRAIL=true`로 Guardrail 미설정을 실패 처리한다.
- Guardrail이 개입하면 `GuardrailBlocked`를 발생시키고, LLM 결과를 저장하지 않는다.
- timeout은 `LLM_TIMEOUT_S`를 1~20초로 제한한다. 기본값은 8초다.
- Guardrail 생성 스크립트는 (a) 원인을 확정하는 문구, (b) 설비 조작·교체·수리 지시를 차단하는 topic/word policy를 정의한다.

주의: `backend/app/llm/aws/test_guardrail.py`은 현재 특정 Guardrail ID를 코드에 하드코딩했다. ID는 비밀은 아니지만 환경마다 달라질 수 있으므로, AWS 실검증 전에 환경변수 기반으로 바꾸고 테스트 대상 환경을 명시해야 한다.

### 6.5 현재 자동 테스트와 반드시 추가할 테스트

현재 자동화됨:

- LLM 미요청 시 순수 결정론적 결과 유지
- LLM 성공/실패 시 후보·근거가 바뀌지 않는지
- input/output Guardrail 호출 순서
- LLM 응답이 근거 ID를 하나도 인용하지 않으면 저장하지 않는지
- Guardrail 차단 뒤 chat 재호출을 하지 않는지
- Case 종료 전 증거 확인·최종 승인을 강제하는지
- 후보 거절 시 재개, 후보 부재 시 판단 보류하는지

추가해야 할 P0 테스트:

| 우선순위 | 검증 | 통과 기준 |
| --- | --- | --- |
| P0 | 실제 Bedrock Guardrail 입력/출력 | unsafe 원인 확정·설비 조작 문구는 `GUARDRAIL_INTERVENED`, 안전한 후보 문구는 `NONE` |
| P0 | 프롬프트 인젝션 | 사용자 질문에 “위 규칙 무시”, “원인 확정”, “밸브를 열어라”가 있어도 후보·근거·상태가 변하지 않고, 출력은 안전 폴백 또는 차단 |
| P0 | 인용 충실성 | 존재하지 않는 `[E999]`, 하나의 무관한 E1만 인용, 모든 근거가 빠진 응답을 거부 |
| P0 | 무결성 | LLM 전후 `candidates`, `evidence`, `diagnosis_time`, `trace[1:4]`가 byte/field 수준으로 동일 |
| P0 | AWS 재시작 영속성 | Lambda 요청을 분리해도 DynamoDB case가 유지되고, 승인 전 `CLOSED`가 불가 |
| P1 | 지연·비용 | 30~100회에서 결정론적 p50/p95, Guardrail+LLM p50/p95, input/output token, 차단율 기록 |
| P1 | 동시성 | 동일 case/task에 두 응답을 동시에 보냈을 때 1건만 저장되고 오래된 요청이 409을 받는지. version 조건부 write는 구현됐다. |
| P1 | 역할 권한 | 운영자·공정 전문가·최종 검토자가 다른 권한일 때 역할 외 상태 전이를 거부 |
| P2 | 설명 품질 | 전문가가 근거 정확성, 과도한 확신, 유용성을 블라인드 평가. 후보 순위 성능과 분리해 보고 |

현 인용 검사는 “최소 한 개의 유효 근거 ID 존재”까지만 보장한다. 문장별 주장과 근거의 대응까지 자동 보장하지 않으므로, 발표에서는 이를 완전한 사실성 검증이라고 말하면 안 된다.

## 7. 현재 작업트리와 Git 규칙

- 작업 브랜치: `service-hardening`
- 마지막 커밋: `6d0c96e Make investigation UI feel like a working ledger`
- Case Orchestrator 변경은 이 핸드오프 문서와 함께 `service-hardening`에 반영한다. 원격 병합 상태는 GitHub PR·commit log로 확인한다.
- 에이전트 런타임과 시각 QA 상태는 로컬 작업 산출물이며 수정·삭제·커밋하지 않는다. 제품 코드·문서와 분리한다.
- 커밋 전에는 관련 코드와 문서만 stage하고, Lore 형식의 commit message를 사용한다.

## 8. 다음 작업 우선순위

### P0 · AWS 재배포 전 확인 — 담당: 백엔드/인프라

목적: 작성된 DynamoDB case 저장소가 실제 Lambda 환경에서도 작동하는지 증명한다.

1. 기존 AWS 자격증명·현재 리소스 상태를 읽기 전용으로 확인한다.
2. `CASE_DDB_TABLE=mfg-investigation-cases`가 investigation table과 다른지 확인한다.
3. 배포 전 `API_AUTH_TOKEN`, Bedrock model/guardrail ARN, CORS origin을 실제 값으로 설정한다.
4. `backend/deploy_lambda_api.py`로 새 이미지와 case table을 배포한다.
5. 배포 후 health에서 `case_storage=dynamodb`를 확인한다.
6. 서로 다른 요청에서도 case 생성 → 조회 → 응답 → 승인 상태가 유지되는지 API로 검증한다.
7. CloudWatch 로그에서 비밀 값이 노출되지 않는지 확인한다.

완료 기준: 공개 배포에서 `CLOSED`까지의 상태가 Lambda 재호출 뒤에도 남고, 관련 API가 200/409/404 계약을 지킨다.

### P1 · 프론트 운영 배포 — 담당: 프론트/인프라

목적: 현재 React build와 새 `/api/cases/*` 프록시 규칙을 ECS 웹 컨테이너에 반영한다.

- `frontend/Dockerfile.web`, `frontend/deploy_web.py`의 실제 환경변수를 점검한다.
- `BACKEND_URL`, `BACKEND_API_TOKEN`은 서버 환경변수로만 주입한다.
- 배포 주소에서 Case Inbox가 “최신 백엔드 배포 후 다시 시도”가 아닌 실제 case list를 보여 주는지 확인한다.
- 브라우저 번들·응답·로그에 API token이 없는지 확인한다.

완료 기준: 공개 URL에서 사건 생성, 확인 응답, 최종 검토, 새로고침 후 상태 복원이 모두 된다.

### P2 · 평가·발표 증거 — 담당: 데이터/기획

1. 기존 causRCA Hit@1, Hit@3, MRR, MAP@3 수치를 재현한다.
2. workflow 지표를 계산한다: 무검토 종료율(목표 0), 근거 ID 참조 유효성, 필수 업무 누락률, trace 완결성.
3. 발표 데모 3개를 고정한다.
   - 후보 → 확인 → 승인 → 종료
   - 후보 → 확인 거절 → 재개 → 추가 관측 요청
   - 후보 없음 → 관측 기록 → 판단 보류
4. 실제 수치와 구현 범위를 넘는 상업성·운영성 주장을 제거한다.

### P3 · 이후에만 검토할 작업

- 조직/사용자 인증과 역할 권한
- multi-tenant GSI 기반 case inbox query
- 긴 작업이 실제 생겼을 때만 SQS/SSE
- LLM 설명 품질 평가와 비용/지연 측정
- Metal Etch 이식성 시연

**P0~P2 이전에는 새 데이터셋, 범용 파일 업로드, 에이전트 빌더, 설비 제어 기능을 시작하지 않는다.**

## 9. 로컬 검증 명령

```bash
# repository root
uv run --extra dev pytest backend/tests -q
uv run --extra dev ruff check backend/app/domain.py backend/app/main.py \
  backend/app/repositories/cases.py backend/app/services/cases.py \
  backend/tests/test_cases.py

cd frontend
npm test
npm run build
CHROMIUM_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
UI_TEST_URL=http://127.0.0.1:5173 \
  npx playwright test e2e/workspace.spec.ts --grep "case orchestration"
```

로컬 브라우저 검증은 API와 Vite를 각각 실행한다.

```bash
# terminal 1, repository root
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# terminal 2
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173
```

## 10. 팀원이 에이전트에게 보낼 권장 프롬프트

### A. AWS 배포·영속성 검증 담당

```text
현재 브랜치 service-hardening의 docs/TEAM_HANDOFF_2026-09-17.md와
docs/CASE_ORCHESTRATION_PLAN.md를 먼저 끝까지 읽어라.

너의 소유 범위는 backend/deploy_lambda_api.py, backend/app/repositories/cases.py,
배포 문서와 AWS 검증 기록이다. React UI나 분석 알고리즘은 수정하지 마라.

목표: CASE_DDB_TABLE 기반 사건 저장소가 Lambda 재호출 뒤에도 상태를 보존하는지,
기존 investigation table과 key contract 충돌 없이 배포되는지 검증하라.

제약:
- AWS 리소스 생성·수정 전에는 현재 자격증명, table 이름, Lambda 환경변수, IAM 정책을 읽기 전용으로 확인한다.
- API_AUTH_TOKEN, Access key, Secret key, 모델 ARN 등 비밀 값을 파일·커밋·응답에 절대 기록하지 마라.
- CASE_DDB_TABLE과 INVESTIGATION_DDB_TABLE은 서로 달라야 한다.
- 배포 후 /api/health의 case_storage=dynamodb, case 생성·조회·응답·승인 후 새 요청에서 상태 유지까지 검증한다.
- 실패하면 리소스를 임의 삭제하지 말고, 정확한 AWS 오류와 안전한 복구 절차만 보고한다.

완료 보고에는 변경 파일, 실행 명령, 배포 결과, API 검증 결과, 남은 위험을 짧게 포함하라.
```

### B. 프론트 운영 배포·E2E 담당

```text
현재 브랜치 service-hardening의 docs/TEAM_HANDOFF_2026-09-17.md를 먼저 읽어라.

너의 소유 범위는 frontend/server.mjs, frontend/server.test.mjs,
frontend/e2e/workspace.spec.ts, frontend 배포 설정과 UI 배포 검증이다.
backend의 상태 전이 계약이나 분석 알고리즘은 변경하지 마라.

목표: 공개 프론트가 새 Case Inbox API를 안전하게 프록시하고,
브라우저에서 후보 → 확인 업무 → 최종 검토 → 종료를 수행하는지 검증하라.

제약:
- BACKEND_API_TOKEN은 Node 서버 환경변수로만 사용하고 VITE_* 또는 브라우저 코드에 넣지 마라.
- API allowlist 밖의 프록시를 열지 마라.
- 기존 same-origin POST 검사, 64KB body 제한, credential 비노출 테스트를 유지하라.
- UI는 가짜 agent thinking 애니메이션을 추가하지 말고 저장된 event ledger만 표시하라.

배포 전 npm test, npm run build, Playwright E2E를 실행하고,
배포 후 공개 주소에서 case 상태가 새로고침 뒤에도 보이는지 보고하라.
```

### C. 평가·발표 담당

```text
docs/TEAM_HANDOFF_2026-09-17.md, docs/EVALUATION.md,
docs/CASE_ORCHESTRATION_PLAN.md를 먼저 읽어라.

너의 소유 범위는 evals/, docs/EVALUATION.md, 발표용 검증 기록이다.
서비스 코드의 후보 순위나 UI 문구를 임의로 바꾸지 마라.

목표: causRCA benchmark와 evidence-closure workflow를 대회에서 방어 가능한
정량 근거로 정리하라.

절대 조건:
- evaluation 정답/진단 시점/조작 변수가 runtime 서비스 또는 LLM으로 흐르지 않는지 확인한다.
- Hit@1, Hit@3, MRR, MAP@3를 재현하고 실패도 분모에 포함한다.
- workflow 지표: 무검토 종료율, 근거 참조 유효성, 필수 업무 누락률, trace 완결성을 정의하고 산출 가능한 범위만 보고한다.
- 실제 현장 운영, 자동 제어, 원인 확정 성능을 과장하지 않는다.

결과물은 발표 슬라이드에 바로 넣을 수 있는 표, 데모 3개 시나리오, 한계와 대응 전략이다.
```

## 11. 회의 종료 전에 결정할 것

1. 이번 주 P0 AWS 재배포를 누가 맡고, 실제 AWS 수정 권한을 누가 승인하는가?
2. 대회 데모의 기본 경로를 “후보 확인 → 최종 승인”으로 고정하는가?
3. 발표에서는 Metal Etch를 다음 단계로 명확히 보류할 것인가?
4. P2 workflow 지표를 누가 계산하고, 발표 자료의 근거 페이지를 누가 작성하는가?
5. 현재 작업을 한 개의 Lore-format commit으로 묶어 push할 담당자는 누구인가?
