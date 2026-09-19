# Continuum 개발 전환 계획

> 상태: F0~F4 구현됨 · F5 환경/선택 의존성/배포 검증 진행 필요 · 작성일: 2026-09-19
> 트러블슈팅 및 후속 순서: [CONTINUUM_TROUBLESHOOTING.md](CONTINUUM_TROUBLESHOOTING.md)
> 기준: [Continuum 최종 기획](Continuum_Final_Plan.md), [제품 범위](PRODUCT.md), [아키텍처](ARCHITECTURE.md), [데이터 계약](DATA_CONTRACT.md), [평가 계획](EVALUATION.md), [ADR-0004](decisions/ADR-0004-continuum-case-continuity.md)

## 1. 전환 목표와 고정 경계

Continuum은 미완료 제조 이상 조사에서 다음 교대가 **같은 Case**의 분석 근거, 사람의 확인, 미확인 항목, 담당자와 인계 이력을 이어 보게 하는 워크스페이스다. 기존의 결정론적 후보 분석은 유지하고, 단일 분석 결과를 근거 확인 후 종료하는 현재 Case Orchestrator를 여러 분석 Run과 인계 상태를 보존하는 Case로 확장한다.

다음은 구현 중에도 변경하지 않는다.

- 후보 순위와 이상 점수는 runtime 관측값·명시한 cutoff·버전이 기록된 결정론적 분석만 계산한다. LLM은 순위·점수·권위 상태를 변경하지 않는다.
- `data/evaluation/`의 정답·조작 변수·진단 시점·split은 API, Case 저장, 검색 인덱스, LLM 입력에서 제외한다. 운영 메모는 `synthetic_demo`·`actual` 등 출처를 명시하며 runtime 센서 관측과 구분한다.
- 후보, 후보 지지 여부, 조사 검토 완료, 인수 수락, 실제 조치/결과는 서로 다른 상태다. 어떤 상태도 원인 확정·수리 완료·안전한 재가동을 뜻하지 않는다.
- 시스템은 설비 제어, 정비 지시, 현장 SOP 또는 필수 대면 인계를 대체하지 않는다.

## 2. 현 구현 검토와 전환 범위

| 현재 재사용 대상 | 현재 한계 | Continuum 변경 |
| --- | --- | --- |
| `analytics/`, `workflows/investigation.py`의 결정론적 분석·근거 검증 | `InvestigationResult`가 Case 하나에 한 번만 연결됨 | 결과를 불변 `AnalysisRun`으로 참조하고, 새 관측 뒤에 동일 Case에 새 Run을 추가 |
| `domain.py`의 Candidate, Evidence, EvidenceTask, CaseEvent, CaseReview | `InvestigationCase.investigation_id` 하나·Task 중심의 단일 폐쇄 흐름 | Case aggregate에 Run, 관찰, Open Item, 가설 추적, 인계와 Snapshot을 추가 |
| `services/cases.py`의 상태 전이와 optimistic locking | API 요청은 클라이언트가 본 version을 보내지 않음 | 모든 변경 요청에 `expected_version`; snapshot 수락에는 `expected_snapshot_id`와 `expected_case_version` 검사 |
| In-memory/Dynamo Case repository | Case 전체 JSON 저장·목록 scan, 담당자/인계 질의 없음 | MVP에서는 호환 reader로 aggregate 보존, 배포 전 event/snapshot·assignee 인덱스 설계/검증 |
| React Case Inbox, Evidence/Task 화면, Node proxy allowlist | 단일 investigation과 종료 게이트 중심 | Handover Review, Packet, Resume, 충돌 갱신 UX, Case Q&A 추가 |
| investigation chat·Bedrock guardrail/근거 인용 검증 | Case 상태·인계 delta를 읽지 않음 | 템플릿 Resume을 우선 생성하고, 선택적 Q&A는 권한 있는 Case 상태와 근거만 인용 |

### 반드시 해소할 갭

1. **다중 Run 보존:** 기존 `investigation_id`를 삭제하거나 재순위화하지 않는다. 과거 Case는 그 ID를 첫 `AnalysisRun`으로 읽어 하위 호환한다.
2. **미확인 상태:** EvidenceTask가 `completed`여도 `unavailable`이면 Open Item은 열린 상태로 남는다. `미실행`, `확인 불가`, `기록 없음`을 구별한다.
3. **원문과 구조화 결과:** 작업자 메모의 원문, 작성자, 발생/기록 시각, 적용 범위, 출처를 저장한다. AI 추출은 `ChangeProposal`로만 반환하고 사람 승인 전에는 상태를 바꾸지 않는다.
4. **인계와 종료 분리:** Handover accept/request-changes/publish와 Case review/close는 독립 상태 머신이다.
5. **동시성·권한:** 문자열 responder/reviewer는 개발용 표시일 뿐 권한 증명이 아니다. MVP에서도 actor identity와 역할을 서버에서 확인할 수 있는 경계를 만들며, 다중 조직 배포 전에는 실제 인증 공급자와 조직 스코프를 도입한다.

## 3. 목표 도메인·상태 계약

### 3.1 Case aggregate

`InvestigationCase`는 불변 `id`, `incident_id`, `dataset`, `version`, `status`, `current_run_id`, 담당자/역할 참조와 다음 컬렉션을 가진다. `dataset`은 계속 하나만 허용한다.

| 객체 | 필수 필드와 규칙 |
| --- | --- |
| `AnalysisRun` | `id`, `investigation_id`, cutoff, 입력 incident 참조, 알고리즘/도구 버전, 생성자·시각. InvestigationResult와 Evidence는 immutable로 참조 |
| `OperatorObservation` | 원문, author, observed_at/recorded_at, scope, source kind/location, `actual|synthetic_demo|simulated` provenance. sensor Observation과 다른 이름공간 |
| `HypothesisTrack` | Run의 candidate 참조, 지지/반대 Evidence·Observation 참조, 사람 판단(`unreviewed|supported|not_supported|insufficient`), 변경 사유. 물리적 원인 확정 필드는 두지 않음 |
| `OpenItem` | 제목·근거 참조, `not_started|unavailable|not_recorded|resolved|on_hold`, assignee, due_at(선택), hold reason, completion evidence. `resolved`만 미확인 해소를 뜻함 |
| `MachineStateRecord` | 설비 상태 주장, 출처, 확인 시각, 적용 범위. Case 종료나 handover accept로 자동 생성하지 않음 |
| `Handover` | sender/receiver, source_case_version, snapshot_id, `draft|published|changes_requested|accepted|superseded`, exception/request reason, 발행·수락 시각 |
| `HandoverSnapshot` | 특정 Case version의 immutable 정규화 payload: current Run, 후보/근거, Open Item, 관찰, 담당자, 제약, linter 결과. 이후 변경은 새 Snapshot만 생성 |
| `CaseEvent` | action, actor, entity references, sequence, timestamp. 사람이 읽는 detail은 보조이고 delta 계산은 구조화 객체를 사용 |

기존 `EvidenceTask`는 즉시 삭제하지 않는다. P0에서는 Open Item을 만드는 legacy task adapter로 유지하고, 이후 UI에서 Open Item의 한 유형으로 표현한다.

### 3.2 상태 전이

- `CaseStatus`: `investigating`, `ready_for_review`, `on_hold`, `closed`. 기존 `awaiting_evidence`, `reopened`, `abstained`는 migration reader에서 각각 `investigating`, `investigating`, `on_hold`로 표시하되 원래 이벤트는 보존한다.
- `HandoverStatus`: `draft → published → accepted`, 또는 `published → changes_requested`, 이후 내용 변경 시 `superseded`. accepted handover가 있어도 Case는 `investigating`일 수 있다.
- `Case closed`는 모든 필수 Open Item이 resolved 또는 권한 있는 예외 기록을 가졌고 명시적 review가 완료된 경우에만 가능하다. 모든 대상의 실제 수리·안전 상태를 주장하지 않는다.
- 모든 쓰기 요청은 body의 `expected_version`을 요구한다. mismatch는 현재 Case와 재검토 안내를 포함한 HTTP 409을 반환한다. accept는 발행 Snapshot ID 및 Case version이 여전히 최신인지 함께 검증한다.

## 4. API·저장소 설계

### 4.1 P0 API (additive)

기존 조사 API는 유지한다. 기존 Case 생성은 첫 `AnalysisRun`과 기본 Open Item을 생성하도록 응답을 확장한다.

```text
POST /api/incidents/{incident_id}/cases
GET  /api/cases
GET  /api/cases/{case_id}
POST /api/cases/{case_id}/observations
POST /api/cases/{case_id}/analysis-runs
POST /api/cases/{case_id}/open-items
POST /api/cases/{case_id}/open-items/{open_item_id}/updates
POST /api/cases/{case_id}/hypotheses/{hypothesis_id}/assessments
POST /api/cases/{case_id}/handover-checks
POST /api/cases/{case_id}/handovers
POST /api/cases/{case_id}/handovers/{handover_id}/acceptance
POST /api/cases/{case_id}/handovers/{handover_id}/change-requests
GET  /api/cases/{case_id}/resume
POST /api/cases/{case_id}/reviews
```

모든 상태 변경 body는 `expected_version`을 포함한다. Handover publish는 lint 결과를 응답에 포함하되, 미확인 Open Item 자체를 blocking error로 만들지 않는다. `unassigned`, `missing-current-state`, invalid reference, stale version과 상태 모순만 blocking으로 분류한다. 관리자 예외는 reason, actor, time을 별도 event로 기록한다.

### 4.2 저장·마이그레이션

1. 도메인 모델에 기본값과 `schema_version`을 먼저 추가한다. Dynamo 기존 JSON은 missing field를 legacy reader가 채운다.
2. 기존 Case의 `investigation_id`는 `analysis_runs[0]`로 projection하고 원본 ID는 저장/표시한다. 전체 table rewrite는 AWS 백업과 idempotent dry-run 검증 전에는 하지 않는다.
3. 로컬 in-memory와 Dynamo repository가 같은 read/write/conditional-conflict contract를 만족해야 한다. migration fixture로 legacy JSON을 읽어 round-trip 검증한다.
4. P0 저장은 Case aggregate에서 시작하되, Snapshot/Event 크기·DynamoDB 400KB 한계·쓰기 충돌을 계측한다. P0.5 전에는 append-only event/snapshot 테이블 및 `organization_id + assignee + updated_at` GSI 필요 여부를 ADR로 확정한다.
5. runtime Incident를 mutate하거나 교대 메모를 `data/runtime/`에 넣지 않는다. 데모 운영 기록은 seed fixture 또는 Case repository fixture로만 제공하고 provenance를 명시한다.

## 5. 구현 순서와 완료 기준

### F0 — 기준선·문서 정렬 (선행 PR)

- `PRODUCT.md`, `ARCHITECTURE.md`, `EVALUATION.md`, `CASE_ORCHESTRATION_PLAN.md`, README에 Continuum 목표·새 종료/인수 구분·지원 API를 반영한다.
- Streamlit legacy와 React+Node proxy 배포 경로 중 release 경로를 명확히 표기한다. `.env.example`에 `CASE_DDB_TABLE`을 추가한다.
- 기존 backend/frontend/Node/Playwright 검증 명령을 CI 후보로 문서화한다.

**완료:** 문서가 현재 구현과 목표 상태를 구분하고, 운영 검증 전 항목을 완료로 표현하지 않는다.

### F1 — Case 연속성 계약과 하위 호환 (P0-1)

- `domain.py`에 Case v2 객체, request/response 모델, actor context, expected version을 추가한다.
- `services/cases.py`를 `open_case`, `append_observation`, `start_analysis_run`, `update_open_item`, `assess_hypothesis`, `review_case` 중심으로 분리한다.
- 새 Run은 명시 cutoff로 기존 deterministic workflow를 호출하고 immutable result를 저장한다. 새 observation은 승인되기 전 분석 입력에 포함하지 않는다.
- legacy Task 응답을 Observation/Open Item/event로 projection하며 기존 endpoint와 test를 유지한다.

**완료:** 하나의 Case ID에서 R1/R2가 공존하고 R1 후보·근거가 바뀌지 않으며, stale write는 409이다.

### F2 — 인계 검사·Packet·수락 (P0-2)

- 순수 결정론 `handover_linter.py`를 도입한다: 참조 존재, 담당자, 필수 현재 상태, Open Item 전달, summary 상태 모순, snapshot freshness를 검사한다.
- Snapshot builder는 필수 필드를 템플릿으로 생성하고 snapshot hash/version을 고정한다. LLM 요약은 Snapshot payload를 대체하지 않는다.
- publish, change request, accept와 exception audit event를 서비스/API에 구현한다.

**완료:** 미확인 항목은 Packet에 남고, 담당자 누락은 publish를 막으며, 발행 뒤 Case가 바뀌면 이전 Packet accept가 409/`superseded`가 된다.

### F3 — Continuum 운영 UI (P0-3)

- `frontend/src/api.ts`에 v2 contract와 conflict error를 추가하고, `App.tsx`를 Case Workspace/Resume/Handover 구성요소로 분리한다.
- Inbox는 Case 상태, 수신/미수락 Packet, Open Item 수, 담당자를 보인다. Resume은 current status, current Run, 확인/미확인, 제약, 담당자, last handover delta를 템플릿으로 표시한다.
- 관찰 원문 작성, Open Item 배정·보류, Packet 검토/발행/수락/설명 요청, 409 refresh-and-retry UI를 제공한다.
- 후보·근거 보드는 Run 선택을 지원하며 “후보/근거 확인/원인 확정/수리 완료” 표기를 혼동하지 않게 한다.

**완료:** Shift A 기록 → linter 보완 → Packet 발행 → Shift B Resume/수락 → 같은 Case R2 추가 흐름을 브라우저 E2E로 재현한다.

### F4 — 제한적 AI 보조와 Case Q&A (P0-4)

- `Context Structuring`은 메모와 허용된 Case 컨텍스트만 받아 Observation/Open Item/Hypothesis 변경 **제안**을 반환한다. 수락 API만 authoritative mutation을 수행한다.
- `Case Q&A`는 DB의 현재 상태와 권한 있는 Run/Evidence/Observation 인용을 분리해 조합한다. 근거가 없으면 `이유 미기록`을 반환한다.
- 템플릿 Resume/Packet은 LLM 장애·차단·미설정에도 사용 가능해야 한다. 기존 guardrail, input size, citation validation, audit trace를 재사용한다.

**완료:** LLM 출력이 후보 순위·Case 상태를 직접 변경하지 못하고, 근거/권한 부족 질문에서 판단 보류가 검증된다.

### F5 — 품질·배포·평가 (P0-5)

- CI에서 backend unit/API, runtime label-leak, frontend proxy, frontend build, Playwright E2E를 실행한다.
- Dynamo persistent restart, legacy migration, conditional concurrent write, packet stale acceptance, repository item size를 실제 AWS 환경에서 별도 검증하고 결과를 기록한다.
- synthetic handover scenario set을 evaluation 전용으로 분리해 Time-to-Context, 중요한 Open Item 누락률, citation/state accuracy, conflict handling을 측정한다. causRCA Hit@k/MRR과 혼합하지 않는다.

**완료:** 최소 데모의 두 교대·2~3 후보·미확인 Open Item·담당자 누락·Snapshot 변경을 모두 재현하고, AWS 실검증 여부를 명시한다.

## 6. 테스트 매트릭스

| 범주 | 필수 사례 |
| --- | --- |
| 도메인/서비스 | R1/R2 불변성, Case ID 유지, candidate assessment와 cause 확정 분리, unavailable task가 Open Item을 남김, close gate |
| 버전/인계 | stale `expected_version`, duplicate accept, published packet 뒤 변경, change request, exception audit, Open Item delta 보존 |
| API/저장소 | legacy Case reader, InMemory/Dynamo 동일 전이, 404/422/409, actor/role denial, Dynamo restart·item-size 경고 |
| 데이터 보안 | runtime/fixture의 금지 label 재귀 검사, synthetic provenance 필수, evaluation import·LLM prompt·retrieval 접근 차단 |
| LLM | proposal-only, citation referential integrity, evidence 부족/guardrail/timeout fallback, template packet fallback |
| 프론트/프록시 | 새 endpoint allowlist, token 비노출, 409 refresh UX, keyboard/empty/error states |
| E2E | A 기록 → B 인수 → R2 재분석, 담당자 누락 차단, 미확인 전달, stale Snapshot 수락 차단 |

## 7. 오픈 결정과 리스크

| 결정/리스크 | 권장 처리 | 착수 전 확정 주체 |
| --- | --- | --- |
| 사용자·조직 인증 | P0 데모는 서버 주입 actor fixture로 제한하고, 공개 배포 전 OIDC/SSO·조직 스코프·role policy를 채택 | 제품/보안 담당 |
| Dynamo aggregate 크기와 조회 | P0 계측 후 Event/Snapshot 분리와 GSI를 ADR로 결정 | 백엔드/운영 담당 |
| Open Item 필수 규칙 | generic linter만 코드화하고, 설비별 SOP 필수 항목은 현장 인터뷰 뒤 configuration으로 추가 | 현장 전문가 |
| 운영 메모 데이터 | provenance가 있는 synthetic fixture만 사용; 실제 현장 기록 반입은 보안/보존 정책 확정 후 | 데이터/보안 담당 |
| 과거 사건 RAG | P1로 보류. Case별 권한 필터·출처 검증·evaluation 격리 없이는 도입하지 않음 | 제품/데이터 담당 |

## 8. 첫 구현 PR 권장 범위

가장 먼저 `F0`과 `F1`의 **도메인 계약 + legacy reader + 서비스/API expected_version + 단위/API 테스트**만 수행한다. UI, LLM, Dynamo schema 분리, 신규 데이터 fixture를 같은 PR에 넣지 않는다. 이 순서가 불변 Case 이력과 동시성 경계를 먼저 검증해 이후 Handover UI가 잘못된 상태를 전파하는 위험을 줄인다.
