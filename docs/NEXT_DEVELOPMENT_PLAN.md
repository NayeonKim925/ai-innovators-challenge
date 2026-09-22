# Continuum 다음 개발 계획

> 기준선: P0~P1 반영 및 P2-1 Gateway provider 구현 완료 · 기준일: 2026-09-21 · 최신 상태는 이 문서의 진행 기록을 따른다.
> 목적: 현재 구현된 Case 연속성 MVP를 실제 교대 업무를 검증할 수 있는 안전한 데모·확장 가능한 제품 기반으로 발전시킨다.

## 1. 현재 기준선

현재 Continuum은 다음 흐름을 구현하고 있다.

```text
RCA Run R1
  → Candidate · Evidence
  → Case 생성
  → Shift A의 Observation · Open Item
  → Handover Lint · Snapshot 발행
  → Shift B의 At Handover / Current / Delta 확인
  → 같은 Case의 Analysis Run R2
```

현재 확인된 기준선(P0~P1 완료, 5.1 진행 기록 참고):

- Backend 테스트 76개 통과
- Frontend 테스트 14개 통과
- Frontend build/typecheck 통과, Playwright 8개 통과
- R1/R2 Analysis Run, Handover Snapshot, Resume 비교 화면 구현
- `expected_version` 기반 충돌 제어 구현
- 현재 설비 상태 관찰(`is_current_state`)과 Handover 예외 역할 검증 보완
- actor context 계약과 인계 audit event(actor ID·role·Case version·snapshot ID) 구현, real-backend E2E로 인증 경계 검증
- Shift Workspace(담당자·보기 필터 기준 Case 우선순위 조회)와 Open Item/Hypothesis 항목별 상태 저장 UI 구현

아직 제품 완료로 볼 수 없는 항목:

- actor header가 실제 사내 인증 공급자·조직 scope와 아직 연결되지 않음(현재는 trusted header 기반)
- CI workflow는 추가했지만 원격 Actions 첫 실행과 운영 배포 검증은 아직 없음
- LLM Context Structuring, AI Handover Draft는 아직 authoritative 기능으로 구현하지 않음(P2 진행)
- Case Memory/RAG(P3)는 아직 설계 문서만 있음
- 실제 DynamoDB 운영 크기·CI 실행·배포 검증이 남아 있음(P4)
- Case Workspace 화면의 정보 우선순위 재배치는 [UX 개편안](CONTINUUM_UX_REDESIGN_PROPOSAL.md) 4.1~4.6 순서대로 구현 완료(main). 첫 진입 화면, Shift 화면 역할 등 나머지 논의 항목은 팀 논의 후 결정 예정

## 2. 우선순위 원칙

1. **업무 상태의 신뢰성**을 먼저 확보한다. AI 요약보다 버전·권한·출처·미확인 상태가 우선이다.
2. **실제 Shift A → Shift B 흐름**을 고정한 뒤 AI 기능을 추가한다.
3. LLM은 제안·질의응답에만 사용하고 Case의 상태·권한·인수 수락을 직접 변경하지 못하게 한다.
4. 실제 현장 데이터가 없으므로 합성 운영 기록과 causRCA 센서/알람 데이터를 명확히 분리한다.
5. 매 단계마다 테스트 가능한 작은 PR로 나누고, 통과한 계약은 변경하지 않는다.

## 3. 개발 단계

### P0 — Release Gate와 권한 경계 고정

목표: 데모에서 “누가 무엇을 인계·수락했는가”를 신뢰할 수 있고, 실제 Backend 연결 검증이 가능한 상태를 만든다.

#### 구현 작업

- `backend/app/main.py`
  - 현재 `X-Actor-Id`, `X-Actor-Role`을 임시 trusted context로 명시한다.
  - production 모드에서는 인증 middleware가 주입한 actor만 사용하도록 분리한다.
  - `sender`, `accepted_by`, `requested_by`, `author`를 body 표시값과 인증 actor로 구분한다.
  - 예외 발행 가능 역할과 Case 수정 가능 역할을 policy 함수로 분리한다.
- `backend/app/domain.py`
  - actor context와 권한 오류 응답 계약을 추가한다.
  - Handover audit event에 actor ID, role, Case version, snapshot ID를 남긴다.
- `backend/tests/test_cases.py`
  - actor 누락, 허용되지 않은 역할, 정상 lead 예외 발행을 API 테스트로 고정한다.
  - 같은 `expected_version`을 사용한 동시 수정과 stale accept를 추가한다.
- `frontend/playwright.config.ts`
  - FastAPI와 React proxy를 함께 띄우는 local full-stack 실행 경로를 추가한다.
  - mock E2E와 real-backend E2E를 명시적으로 분리한다.
- CI
  - backend test → frontend test/typecheck/build → mock E2E 순서로 release gate를 만든다.

#### 완료 조건

- 권한 없는 actor는 exception publish를 할 수 없다.
- 인수 수락·설명 요청·관찰 기록에 실제 actor context가 audit trail에 남는다.
- 실제 API를 연결한 브라우저에서 Case 생성부터 Handover accept까지 재현된다.
- CI에서 같은 검증 명령을 재실행할 수 있다.

### P1 — Shift Workspace와 조사 업무 관리

목표: Case 하나를 열어야만 다음 업무를 찾는 구조에서, Shift B가 출근하자마자 자신이 이어받을 사건과 업무를 볼 수 있게 한다.

#### 구현 작업

- `backend/app/main.py`, `backend/app/services/cases.py`
  - `GET /api/shift-workspace?assignee=&status=`를 추가한다.
  - 미수락 Handover, 담당 Open Item, stale Snapshot, blocking finding을 우선순위와 함께 반환한다.
  - 기존 generic Open Item endpoint를 Shift Workspace의 항목별 상태 편집과 연결한다.
  - Hypothesis `supported / not_supported / insufficient` 판단 API를 UI 계약과 연결한다.
- `backend/app/repositories/cases.py`
  - MVP에서는 aggregate scan을 유지한다. 담당자·조직 인덱스와 DynamoDB key 설계는 운영 규모 검증(P4)에서 진행한다.
- `frontend/src/App.tsx`
  - Case Inbox를 Shift Workspace로 확장한다.
  - 카드에 `미수락 인계`, `내 Open Item`, `미확인`, `stale` 상태를 표시한다.
  - Open Item 상태 변경과 Hypothesis 판단을 Case 상세에서 바로 기록한다.
- `frontend/src/api.ts`, `frontend/src/resume.ts`
  - workspace 응답과 상태 라벨을 타입으로 고정한다.

#### 완료 조건

- Shift B는 첫 화면에서 자신이 맡은 Case와 다음 Action을 확인한다.
- 하나의 Case에서 Open Item 2개와 Hypothesis 2개를 각각 독립적으로 업데이트할 수 있다.
- 담당자 변경·보류·완료가 Case version과 함께 저장된다.
- 인계 수락과 Case 종료가 화면·API 양쪽에서 분리되어 있다.

#### P1 구현 기록

- `Shift Workspace`가 담당자와 보기 필터(`조치 필요`, `인수 대기`, `내 Open Item`, `최신화 필요`, `전체 관련 사건`)를 기준으로 Case를 우선순위 정렬한다.
- 각 Workspace 카드에서 인수 대기·담당 업무·stale Snapshot·차단 이슈를 확인하고 Case 상세로 바로 진입할 수 있다.
- Case 상세에서 모든 Open Item의 담당자·상태·보류 사유·완료 메모를 개별 저장할 수 있다.
- Case 상세에서 각 Hypothesis를 `지지`, `지지하지 않음`, `근거 부족`, `미검토`로 독립 판단하고 이유를 기록할 수 있다.
- 프론트 프록시 allowlist에 새 조회 경로를 추가하고 실제 FastAPI + React 경계 E2E에서 교대 큐를 검증했다.
- 검증: backend 69 passed, frontend 14 passed, frontend build/typecheck passed, Playwright 8 passed, 변경 파일 대상 Ruff passed.

### P2 — 근거 기반 AI 보조

목표: 작업자가 작성한 짧은 교대 메모를 구조화하고 질문에 답하되, AI가 Case를 직접 확정하지 못하게 한다.

#### 구현 작업

- `backend/app/llm/bedrock_client.py`
  - 대회 제공 OpenAI-compatible Gateway와 직접 AWS Bedrock을 같은 Provider 경계로 지원한다.
  - `LLM_PROVIDER=competition_gateway`일 때 `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`을 사용한다.
  - Gateway 장애·SDK 미설치·키 미설정 시 기존 결정론적 결과로 폴백한다.
- `backend/app/main.py`
  - `/api/health`에서 활성 LLM provider와 모델 설정 상태를 노출한다.
- `backend/app/services/context_structuring.py` 신규
  - 입력: 원문 메모 + 허용된 현재 Case context
  - 출력: Observation/Open Item/Hypothesis 변경 제안
  - 모든 제안에 원문 span, Case version, confidence, missing evidence를 포함한다.
- `backend/app/main.py`
  - `POST /api/cases/{case_id}/structuring-proposals`를 추가한다.
  - `POST /api/cases/{case_id}/structuring-proposals/{proposal_id}/accept`만 실제 상태를 변경하게 한다.
- `backend/app/services/case_chat.py`
  - 현재 Resume, Snapshot, Open Item, Observation을 섞지 않고 출처별로 조합한다.
  - 근거가 없는 질문에는 `이유 미기록`을 반환한다.
  - LLM 장애·토큰 초과·guardrail 차단 시 결정론적 템플릿으로 폴백한다.
- `frontend/src/App.tsx`
  - “AI가 제안한 구조화 결과”와 “저장된 Case 상태”를 시각적으로 분리한다.
  - accept 전에는 Handover Packet과 Case aggregate가 변하지 않도록 한다.
- `frontend/resume.test.mjs`, `backend/tests/`
  - unsupported statement, citation 누락, 잘못된 Evidence ID, LLM timeout을 검증한다.

#### 완료 조건

- AI가 원인 확정·설비 제어·Case 종료를 수행하지 않는다.
- 모든 AI 주장에 Evidence/Observation 출처가 있거나 `이유 미기록`으로 표시된다.
- 동일 입력에서 LLM 미설정 상태도 동일한 기본 Resume을 제공한다.
- 작업자는 제안을 수정·거절한 뒤에만 상태를 저장할 수 있다.

#### P2-1 구현 기록 — Competition LLM Gateway Provider

- OpenAI-compatible Gateway 호출 경로를 기존 direct Bedrock 경로와 분리했다.
- 기본 provider는 `direct_bedrock`으로 유지하고, 대회 검증 시 `LLM_PROVIDER=competition_gateway`로 전환한다.
- 사용자에게 노출되는 내러티브/인계 답변은 기본 `bedrock-gpt-5.6-terra`, 대량 메모 구조화는 `bedrock-haiku`로 분리할 수 있다.
- 현재 내러티브 경로에서 Gateway의 Chat Completions 응답, 근거 ID 검증, 토큰 usage 추출을 지원한다.
- `openai` SDK는 `.[llm]` 선택 의존성 및 Lambda 이미지에 반영했다.
- 검증: backend 전체 71 passed, Gateway 응답 shape/health 설정 테스트 포함.
- 실제 Gateway smoke test는 팀 API key 입력 후에만 실행한다. 키는 저장소·채팅·프론트엔드에 올리지 않는다.

### P3 — Case Memory / RAG

목표: 해결된 과거 Case를 다음 조사에 참고하되, 권한·출처·평가 누출을 막는다.

#### 구현 작업

- P3 범위와 Case Memory 계약을 별도 설계 문서로 구체화한다.
- `knowledge/`는 매뉴얼·용어·검증된 Case를 구분하고 provenance를 저장한다.
- Case 해결 시 `Verified Resolution Case` projection을 생성한다.
- 검색 결과에 Case ID, 설비 범위, 당시 Observation, 최종 Human Decision, 적용 시점, 권한 범위를 함께 표시한다.
- evaluation label과 `data/evaluation/` 파일은 prompt·embedding·검색 인덱스에 들어가지 않도록 누출 테스트를 추가한다.

#### 완료 조건

- “비슷한 사건에서 무엇을 확인했나?” 질문에 과거 Case 출처가 표시된다.
- 권한 없는 Case는 검색 결과에 나타나지 않는다.
- 검색 결과는 현재 Case 상태를 자동 변경하지 않는다.
- 유사도만으로 원인을 확정하지 않고, 사람이 참고 Case를 선택한다.

### P4 — 운영 배포와 데이터 규모 검증

목표: 데모 성공을 운영 가능한 아키텍처로 확장할 수 있는지 판단한다.

#### 구현 작업

- `backend/app/repositories/cases.py`
  - Case aggregate 크기와 Snapshot/Event 누적 크기를 계측한다.
  - DynamoDB 400KB 경계, conditional write, restart persistence를 검증한다.
- Event/Snapshot 분리 여부를 ADR로 결정한다.
- 실제 인증 공급자, 조직 scope, role mapping을 연결한다.
- GitHub Actions workflow를 권한이 있는 인증으로 업로드한다.
- 운영 로그에 Case ID, actor, version, snapshot ID, proposal ID를 남기되 원문 민감정보는 마스킹한다.

#### 완료 조건

- 실제 DynamoDB에서 legacy Case read → v3 round-trip이 통과한다.
- 두 worker의 동시 write 중 하나는 409로 안전하게 거절된다.
- 운영 환경에서 인증·조직 경계·audit log를 확인할 수 있다.
- AWS 검증 전에는 제품 문서에서 운영 완료라고 표현하지 않는다.

## 4. 권장 실행 순서

```text
P0 권한·실제 E2E·CI
  ↓
P1 Shift Workspace·Open Item/Hypothesis 관리
  ↓
P2 Proposal-only AI 보조·Case Q&A 고도화
  ↓
P3 권한 필터가 있는 Case Memory/RAG
  ↓
P4 DynamoDB·인증·운영 배포
```

다음 작업은 P2 후속으로, 실제 현장 메모를 상태 제안으로 바꾸는 Proposal-only AI 보조를 확장한다. P2에서도 LLM 제안은 accept 전까지 Case aggregate와 Handover Packet을 변경하지 않는다.

## 5.1 진행 기록

### 2026-09-21 — P0 Unit 1: Actor Context + Handover Audit

- `ActorRole`과 `ActorContext` 계약을 추가했다.
- handover lint, publish, change request, acceptance 이벤트에 `actor_id`와 `actor_role`을 남긴다.
- production에서는 `X-Actor-Id`와 `X-Actor-Role` 헤더를 요구하고, local research 환경에서는 body 표시자 기반 fallback을 사용한다.
- exception publish의 lead/supervisor 역할 검증과 actor audit 회귀 테스트를 고정했다.
- 검증: backend 68 passed, frontend 14 passed, frontend build passed, 변경 파일 대상 Ruff passed.
- 다음 유닛: FastAPI + React proxy를 실제 backend로 연결하는 full-stack Playwright E2E 경로.

### 2026-09-21 — P0 Unit 2: Real Backend E2E

- Playwright가 실제 FastAPI와 React production proxy를 독립적으로 실행하도록 구성했다.
- E2E 프로세스에 production API token과 actor context header를 주입해 인증 경계를 함께 검증한다.
- Case 생성 → 관찰 기록 → Open Item 담당자 지정 → Handover lint → Packet 발행 → 다음 Shift 인수 확인 흐름을 추가했다.
- 저장된 Case event에서 `handover_published`, `handover_accepted`와 actor identity를 직접 검증한다.
- mock 기반 기존 Continuum 시나리오와 real-data workspace 시나리오도 함께 회귀 검증한다.
- 검증: Playwright 8 passed, backend 68 passed, frontend 14 passed, frontend build passed, 변경 파일 대상 Ruff passed.
- 테스트는 기본적으로 기존 listener를 재사용하지 않으며 `UI_TEST_PORT`, `BACKEND_TEST_PORT`, `REUSE_E2E_SERVER`로 실행 환경을 제어한다.
- 다음 유닛: P0 잔여 CI 실행 경로 정리 후 P1 Shift Workspace의 Open Item/Hypothesis 운영 UI를 고도화한다.

### 2026-09-21 — P1: Shift Workspace + Investigation State Editing

- `GET /api/shift-workspace`를 추가해 담당자별 인수 대기, 담당 Open Item, stale Snapshot, blocking finding을 조치 우선순위로 제공한다.
- 기존 Case version/CAS 계약을 유지한 채 Open Item의 배정·보류·완료와 Hypothesis 판단을 항목별 UI에서 저장하도록 연결했다.
- React proxy allowlist와 real-backend E2E를 확장해 새 Workspace 조회가 실제 API 경계를 통과하는지 검증했다.
- 검증: backend 69 passed, frontend 14 passed, frontend build/typecheck passed, Playwright 8 passed, 변경 파일 대상 Ruff passed.

### 2026-09-21 — P2 Unit 1: Proposal-only Context Structuring Contract

- `POST /api/cases/{case_id}/structuring-proposals`가 작업자 메모를 Observation/Open Item 제안으로 구조화한다.
- 제안에는 원문 span, Case version, confidence, missing evidence, provenance를 포함하며 생성만으로 Case aggregate를 변경하지 않는다.
- `POST /api/cases/{case_id}/structuring-proposals/{proposal_id}/accept`만 기존 결정론적 Case mutation을 호출하고, stale version은 409로 거절한다.
- 대회 Gateway가 설정된 경우에만 구조화 LLM을 선택적으로 호출하며, JSON 검증·guardrail·SDK/키 오류 시 결정론적 제안으로 폴백한다. LLM은 새 Hypothesis를 만들 수 없고 기존 Hypothesis ID만 참조한다.
- React proxy allowlist와 API 회귀 테스트를 추가했다. UI에 저장된 상태와 AI 제안 화면을 분리하는 작업은 다음 P2 Unit에서 진행한다.
- 검증: backend 75 passed, frontend 14 passed, frontend build/typecheck passed, Ruff passed.

### 2026-09-21 — P2 Unit 2: Reviewable Structuring Queue UI

- 구조화 제안을 Case aggregate와 분리된 repository 계약으로 저장한다. 로컬은 in-memory, 배포 환경은 `STRUCTURING_PROPOSAL_DDB_TABLE`로 DynamoDB를 선택한다.
- Case 상세에서 교대 메모를 제안으로 생성하고, 원문·Case version·신뢰도·미확인 근거를 확인한 뒤 내용을 수정할 수 있다.
- `검토 후 저장`만 기존 결정론적 Observation/Open Item/Hypothesis 전이를 호출한다. Case version이 달라진 stale 제안은 수락할 수 없고, `보류`는 Case를 변경하지 않는다.
- GET 조회로 Case 재진입 시 검토 대기 제안을 복원하고, React proxy allowlist에 조회·보류 경로를 추가했다.
- 검증: backend 76 passed, changed-file Ruff passed, frontend 14 passed, frontend typecheck/build passed.

## 5. 첫 PR의 체크리스트

- [x] `CaseActor` 또는 동등한 actor context 계약 정의
- [x] exception publish의 허용 역할·거부 응답 테스트
- [x] body의 표시용 사용자와 인증 actor의 불일치 테스트
- [x] `handover-checks`, publish, accept, change request audit event 검증
- [x] FastAPI test app와 React proxy의 full-stack Playwright 실행 스크립트
- [x] CI workflow 파일 추가
- [ ] GitHub Actions 첫 실행 및 업로드 권한 확인
- [ ] `make test`, frontend test/build, targeted Ruff, Playwright 명령을 문서화
- [ ] P0 완료 후 이 문서의 상태와 실제 통과 로그 갱신
- [x] P1 Shift Workspace API와 프론트 큐 연결
- [x] P1 Open Item/Hypothesis 항목별 상태 저장 UI
- [x] P1 real-backend E2E에서 교대 큐 노출 검증

## 6. 하지 않을 것

- LLM이 센서만 보고 root cause를 확정하도록 만들지 않는다.
- 인수 수락을 Case 종료나 설비 재가동 승인으로 해석하지 않는다.
- 실제 현장 기록처럼 합성 Shift 메모를 표시하지 않는다.
- 권한 필터·누출 검증 없이 RAG를 먼저 공개하지 않는다.
- DynamoDB 운영 검증 전 aggregate 구조를 무리하게 분리하지 않는다.
