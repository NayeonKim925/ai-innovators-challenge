# Continuum 다음 개발 계획

> 기준 커밋: `f1d60c6` · 기준일: 2026-09-21
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

현재 확인된 기준선:

- Backend 테스트 68개 통과
- Frontend 테스트 14개 통과
- Frontend build/typecheck 통과
- R1/R2 Analysis Run, Handover Snapshot, Resume 비교 화면 구현
- `expected_version` 기반 충돌 제어 구현
- 현재 설비 상태 관찰(`is_current_state`)과 Handover 예외 역할 검증 보완

아직 제품 완료로 볼 수 없는 항목:

- actor header가 실제 사내 인증 사용자·역할과 연결되지 않음
- 실제 Backend를 연결한 브라우저 E2E가 없음
- Shift 전체를 한 번에 보는 Inbox와 일반 Open Item 관리가 부족함
- Hypothesis 판단을 UI에서 직접 기록하는 흐름이 부족함
- LLM Context Structuring, AI Handover Draft는 아직 authoritative 기능으로 구현하지 않음
- 실제 DynamoDB 운영 크기·CI·배포 검증이 남아 있음

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
  - Open Item 생성·배정·보류·완료를 generic endpoint로 정리한다.
  - Hypothesis `supported / not_supported / insufficient` 판단 API를 UI 계약과 맞춘다.
- `backend/app/repositories/cases.py`
  - 현재 aggregate scan을 유지하되, `assignee`, `status`, `updated_at` 조회 인덱스 계약을 추가한다.
  - DynamoDB 구현에서는 조직 범위와 담당자 범위를 key 설계에 반영한다.
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

### P2 — 근거 기반 AI 보조

목표: 작업자가 작성한 짧은 교대 메모를 구조화하고 질문에 답하되, AI가 Case를 직접 확정하지 못하게 한다.

#### 구현 작업

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

다음 작업은 P0의 첫 번째 PR로 시작한다. 범위는 actor context 계약, exception audit 테스트, Playwright real-backend 실행 경로까지로 제한한다. P0가 끝나기 전에는 새로운 LLM 기능이나 RAG 인덱스를 추가하지 않는다.

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

## 5. 첫 PR의 체크리스트

- [x] `CaseActor` 또는 동등한 actor context 계약 정의
- [x] exception publish의 허용 역할·거부 응답 테스트
- [x] body의 표시용 사용자와 인증 actor의 불일치 테스트
- [x] `handover-checks`, publish, accept, change request audit event 검증
- [x] FastAPI test app와 React proxy의 full-stack Playwright 실행 스크립트
- [ ] CI workflow 업로드 권한 확인
- [ ] `make test`, frontend test/build, targeted Ruff, Playwright 명령을 문서화
- [ ] P0 완료 후 이 문서의 상태와 실제 통과 로그 갱신

## 6. 하지 않을 것

- LLM이 센서만 보고 root cause를 확정하도록 만들지 않는다.
- 인수 수락을 Case 종료나 설비 재가동 승인으로 해석하지 않는다.
- 실제 현장 기록처럼 합성 Shift 메모를 표시하지 않는다.
- 권한 필터·누출 검증 없이 RAG를 먼저 공개하지 않는다.
- DynamoDB 운영 검증 전 aggregate 구조를 무리하게 분리하지 않는다.
