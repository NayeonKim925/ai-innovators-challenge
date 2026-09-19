# ADR-0004: Continuum은 다중 분석 Run과 버전 고정 인계 상태를 가진 Case 연속성 워크스페이스로 전환

## 상태

승인됨 · 2026-09-19. 구현은 아직 시작되지 않았으며, 상세 단계는 [Continuum 개발 전환 계획](../CONTINUUM_DEVELOPMENT_PLAN.md)을 따른다.

## 배경

현재 서비스는 결정론적 분석 결과를 하나의 `InvestigationCase`에 연결하고, EvidenceTask 응답과 최종 전문가 검토를 거쳐 종료하는 증거 폐쇄형 흐름이다. 이 구조는 근거·사람 검토·낙관적 저장의 기반을 제공하지만, 미완료 조사가 교대를 넘길 때 필요한 다중 분석 이력, 미확인 항목, 담당자, 인계 Snapshot과 수락 상태를 표현하지 못한다.

Continuum의 제품 가치는 AI가 원인을 확정하는 데 있지 않다. 동일 Case의 관측·후보·근거·사람 판단·미확인 항목을 다음 담당자가 재구성 없이 검토하고 조사를 이어갈 수 있게 하는 데 있다.

## 결정

1. `InvestigationCase`를 단일 `investigation_id` 모델에서 다중 immutable `AnalysisRun`과 `current_run_id`를 가진 aggregate로 확장한다. 기존 investigation은 과거 Run으로 보존하며 재작성·재순위화하지 않는다.
2. `OperatorObservation`, `OpenItem`, `HypothesisTrack`, `Handover`, `HandoverSnapshot`, 구조화 `CaseEvent`를 추가한다. 후보 지지 여부, 조사 검토 완료, 인수 수락, 실제 설비 상태/결과는 별도 상태로 유지한다.
3. Handover Snapshot은 특정 Case version의 immutable payload로 발행한다. 모든 쓰기 요청은 `expected_version`을 요구하고, 인수 수락은 최신 Case version과 Snapshot ID를 검증한다.
4. Handover linter의 필드·참조·version·담당자 검사는 결정론적 서버 코드로 수행한다. LLM은 메모 구조화, 설명, 보완 제안만 하고 권위 상태·후보 순위·수치를 직접 변경하지 않는다.
5. `unavailable` 응답 또는 미실시 작업은 Task 완료 여부와 무관하게 Open Item으로 남긴다. 미확인 자체는 인계 차단 사유가 아니며, 담당자 누락·필수 현재 상태 누락·상태 모순·오래된 Snapshot만 일반 발행/수락을 차단한다.
6. 런타임 관측과 운영 메모는 출처를 구분한다. evaluation 정답은 계속 runtime API, Case 저장, LLM 및 검색 입력에서 제외한다.

## 결과

### 긍정적 결과

- 교대 전후의 조사 상태가 하나의 Case ID에 축적되며, 기존 결정론적 분석·Evidence·사람 검토 자산을 재사용한다.
- Packet/Resume은 LLM이 없어도 템플릿과 고정 Snapshot으로 생성된다.
- stale write와 stale acceptance를 서버가 명시적으로 막아 인계 중 조용한 정보 손실을 줄인다.
- 기존 종료 게이트를 보존하면서 인수 수락과 조사 종료를 혼동하지 않는다.

### 비용과 제약

- Pydantic/domain, repository, service, API, React 타입/UI, proxy allowlist, backend/frontend/E2E 테스트가 함께 변경되는 큰 계약 전환이다.
- 현재 DynamoDB의 Case 전체 JSON 저장과 scan은 장기 Case, Snapshot, assignee inbox에 적합하지 않을 수 있다. P0 계측 후 append-only event/snapshot과 GSI 분리 여부를 별도 ADR로 결정한다.
- 문자열 actor는 실제 권한 증명이 아니므로 공개·다중 조직 배포 전에 authentication/authorization 도입이 필요하다.
- 실제 현장 SOP, 담당자 규칙, 설비 상태/정비 완료 판정은 구현으로 가정하지 않고 사용자 검증과 구성으로 정한다.

## 대안

- **새로운 독립 Handover 서비스로 재구축:** 현재 분석·근거·Case 이벤트 자산을 중복하고 동일 조사 이력의 연결을 약화하므로 채택하지 않는다.
- **LLM 중심 멀티에이전트로 전환:** 수치 분석·권위 상태의 재현성과 감사 가능성을 낮추므로 채택하지 않는다.
- **기존 EvidenceTask만 확장:** 미확인, 담당자, Snapshot, 다중 Run, 인수 수락을 Task 완료 상태에 과적재하므로 채택하지 않는다.
- **인계 수락을 Case 종료로 처리:** 인수와 원인 확정·수리 완료를 혼동하므로 채택하지 않는다.

## 검증

구현 전후 모두 runtime/evaluation 누출 테스트를 유지한다. P0 완료의 최소 증거는 같은 Case의 R1/R2 불변 보존, Open Item의 미확인 전달, 담당 공백 linter, Snapshot 변경 뒤 stale accept 차단, A→B 인수→동일 Case 재개 E2E다. AWS 영속성과 권한 모델의 실제 검증은 별도 실행 로그 없이는 완료로 주장하지 않는다.
