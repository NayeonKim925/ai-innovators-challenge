# 증거 폐쇄형 사건 오케스트레이션 계획

> 상태: 기존 증거 폐쇄 흐름 구현 · Continuum 연속성 전환 중 · 기준일: 2026-09-19
> 연결 문서: [PRODUCT.md](PRODUCT.md), [ARCHITECTURE.md](ARCHITECTURE.md), [EVALUATION.md](EVALUATION.md)

## 1. 제품 전환

기존 MVP는 `사건 → 후보 → 근거 → 검토`를 보여 주는 조사 대시보드다. 이 흐름은 필요한 기반이지만, 결과를 한 번 표시하고 끝나면 일반적인 분석 화면처럼 보인다.

이번 전환의 핵심은 **후보를 제시하는 AI에서 멈추지 않고, 미완료 조사에서 필요한 확인 업무·Open Item·인계 Snapshot을 유지해 교대가 바뀌어도 사람의 판단을 이어 주는 사건 조사 워크스페이스**다.

```text
사건 접수
  → 결정론적 RCA 도구 실행
  → 근거 충분성 확인
  → [증거가 부족하면] 역할별 확인 업무 생성
  → 전문가 응답 기록
  → 재검토 가능 상태 또는 판단 보류
  → 명시적 전문가 검토 후에만 사건 종료
```

여기서 에이전트는 다수의 챗봇을 흉내 내는 구조가 아니다. 하나의 **Case Orchestrator**가 결정론적 분석 도구, 근거 검증, 사람 확인 업무, 상태 전이를 순서대로 호출하고 각각의 이벤트를 남긴다. LLM은 이후 근거가 닫힌 범위에서 설명·질문 정리에만 선택적으로 사용한다. 후보 순위·수치·종료 판단을 바꾸지 않는다.

## 2. MVP의 명확한 사용자 가치

| 사용자 | 기존 불편 | 새 흐름에서 얻는 것 |
| --- | --- | --- |
| 운영자 | 어떤 관찰을 누구에게 전달해야 하는지 모름 | 사건별로 필요한 추가 관찰 업무와 이유를 받음 |
| 공정·설비 전문가 | 분석 결과와 실제 확인 여부가 분리됨 | 근거가 연결된 확인 요청에 응답하고 판단 이력을 남김 |
| 데이터 분석가 | 모델 후보가 실제 검토로 이어졌는지 알기 어려움 | 분석 결과, 사용 도구, 근거, 사람 응답, 보류 사유를 하나의 사건으로 추적 |
| 관리자 | 승인 화면만 보고 조사가 충분했는지 알기 어려움 | 종료 전 증거 업무 완료 여부와 전문가 검토 여부를 확인 |

## 3. 안전 불변식

1. `CLOSED` 상태는 모든 필수 확인 업무가 완료되고, 사건이 `READY_FOR_REVIEW`이 된 뒤, 명시적 전문가 승인으로만 가능하다.
2. 근거 ID가 runtime 조사 결과에서 해석되지 않으면 후보는 생성하지 않는다.
3. 전문가의 `confirmed` 응답은 **후보의 실제 원인 확정**이 아니다. “제시된 관측·문서와 비교한 확인 응답”일 뿐이며 최종 검토를 별도로 요구한다.
4. `refuted`, `unavailable`, 후보 부재는 자동 확정 대신 `REOPENED` 또는 `ABSTAINED`로 남긴다.
5. 장비 제어, 정비 지시, 임의의 현장 사실 생성은 하지 않는다.
6. causRCA의 정답·조작 변수·진단 시점 등 `data/evaluation/` 정보는 Case Orchestrator와 LLM의 입력에 들어가지 않는다.

## 4. 상태 모델

```text
OPEN
  └─ 결정론적 분석 + 근거 검증
       ├─ 후보 존재 → AWAITING_EVIDENCE
       │     └─ 전문가 확인 완료 → READY_FOR_REVIEW
       │           ├─ 승인 → CLOSED
       │           └─ 거절 → REOPENED → 추가 관찰 업무
       └─ 후보 부재 → AWAITING_EVIDENCE
             └─ 관찰 업무 완료 → ABSTAINED

후보 확인이 거절되거나 불가능함
  → REOPENED → 추가 관찰 업무 → ABSTAINED 또는 새 cutoff로 새 사건 실행
```

`ABSTAINED`는 실패를 숨기는 상태가 아니라, 현재 관측 범위에서는 근거 있는 후보를 만들 수 없다는 정직한 결과다.

## 5. 단계별 구현 순서

### M6.0 · 계약과 종료 게이트 (현재)

- `InvestigationCase`, `EvidenceTask`, `ExpertTaskResponse`, `CaseEvent` 도메인 계약
- in-memory case repository와 서비스 계층
- 사건 생성, 목록·상세 조회, 확인 업무 응답, 전문가 최종 검토 API
- 후보 확인 없이 종료할 수 없다는 회귀 테스트
- 기존 `/investigations` API와 benchmark 경계를 변경하지 않음

### M6.1 · 조건부 업무 계획과 재개 흐름

- 후보가 있으면 최상위 후보의 관측 근거에 연결된 `verify_candidate` 업무 생성
- 후보가 없거나 확인이 거절되면 `collect_observation` 업무 생성
- 응답에 따라 `READY_FOR_REVIEW`, `REOPENED`, `ABSTAINED`를 결정론적으로 전이
- 각 상태 전이를 사건 이벤트 로그에 기록

### M6.2 · 서비스 UI

- **Case Inbox**: 진행 중·재개됨·보류·종료 사건을 분리해 보여 줌
- **Agent Run Ledger**: 실제 실행된 분석 도구와 상태 이벤트를 시간순으로 표시
- **Human Action Queue**: 역할, 확인 이유, 연결된 근거, 응답 폼을 제공
- **Handoff Packet**: 후보, 근거, 경고, 미해결 업무, 검토 이력을 한 화면에서 전달
- 로딩 애니메이션으로 가짜 “에이전트 사고 과정”을 연출하지 않고, 저장된 이벤트만 표시

### M6.3 · 배포 영속성 (구현 완료, AWS 실배포 검증 전)

- `CASE_DDB_TABLE`이 설정되면 별도 DynamoDB case table에 사건 JSON과 갱신 시각을 저장
- 조사 결과 table과 사건 table을 분리해 key contract 충돌을 방지
- Lambda 역할에 case table의 `GetItem`·`PutItem`·`UpdateItem`·`Scan` 권한을 최소 추가
- 목록은 MVP 규모의 paginated scan이며, 조직·담당자·SLA가 생기기 전에는 GSI를 추가하지 않음
- 실제 AWS 계정에서 table 생성·Lambda 재시작 뒤에도 사건이 유지되는 검증은 배포 작업에서 별도 실행

### M6.4 · 비동기·LLM 확장 (조건부)

- 실제 장시간 작업이나 외부 도구가 생길 때만 SSE/큐를 도입
- LLM은 근거·사람 응답을 벗어나는 문장을 차단하는 설명 계층으로 한정
- AgentCore는 현재 Bedrock AgentCore 실험 코드와 별도이며, tool boundary와 권한 모델을 검증한 후에만 요청 경로에 연결

### M6.5 · 평가와 발표

- 기존 causRCA: Hit@1, Hit@3, MRR, MAP@3 유지
- 추가 workflow 지표: 근거 참조 유효성, 필수 업무 누락률, 무검토 종료율(목표 0), trace 완결성
- 데모 경로 3개를 고정
  1. 후보 → 확인 → 검토 승인 → 종료
  2. 후보 → 확인 거절 → 재개 → 추가 관찰 요청
  3. 후보 없음 → 추가 관찰 → 판단 보류

## 6. API 계약 (M6.0)

```text
POST /api/incidents/{incident_id}/cases
GET  /api/cases
GET  /api/cases/{case_id}
POST /api/cases/{case_id}/tasks/{task_id}/responses
POST /api/cases/{case_id}/reviews
```

`POST /cases`는 LLM을 호출하지 않고 기존 결정론적 조사 결과를 저장한 다음 확인 업무를 계획한다. 따라서 LLM API·Bedrock 가용성과 무관하게 전체 흐름을 시연할 수 있다.

## 7. 범위와 다음 단계

- **이번 MVP 데이터:** causRCA runtime 사건 하나의 계약을 중심으로 한다. Metal Etch는 동일 계약으로 연결되는 후속 이식성 시연이다.
- **저장소:** local 연구 모드는 in-memory 저장소로 계약·상태 전이를 검증한다. AWS 환경에서 `CASE_DDB_TABLE`을 설정하면 DynamoDB case repository가 Lambda 인스턴스 간 상태를 보존한다. 실제 AWS 배포 검증은 아직 완료 상태로 주장하지 않는다.
- **확장하지 않는 방향:** 임의 데이터 업로드, 범용 에이전트 생성기, 여러 데이터셋 간 인과 비교, 자동 조치.

이 제한은 범용성 부족이 아니라, 평가 데이터 누출 없이 재현 가능한 조사 흐름을 완성하기 위한 MVP의 의도된 경계다.
