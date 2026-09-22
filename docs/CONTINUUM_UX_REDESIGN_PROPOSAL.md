# Continuum 사용자 흐름 및 Case Workspace UX 개편 기획안

> **구현 상태 (2026-09-22):** 4장의 Case Workspace 구조(4.1 Overview ~ 4.6 Handover)는 main에 구현 완료됐다. 화면 순서·용어만 바꿨고 6장에서 변경 금지로 명시한 domain/API는 그대로다. 5장(Shift 화면 역할)과 10장(첫 진입 화면 등 팀 논의 사항)은 아직 결정되지 않았다.

## 1. 기획 목적

현재 Continuum에는 Case Continuity를 구현하기 위한 주요 기능이 이미 존재한다.

- RCA 분석 및 Analysis Run
- Candidate / Evidence
- Operator Observation
- Open Item
- Evidence 확인 업무
- Hypothesis
- Handover
- Snapshot
- Resume / Handover Delta
- 동일 Case의 추가 분석(R2)

기능적으로는 Shift A에서 진행한 조사를 Shift B가 이어받을 수 있는 구조가 만들어져 있다.

다만 현재 UI에서는 이러한 기능이 각각 독립된 개념과 영역으로 노출되어 있어, 사용자가 실제 업무 순서를 직관적으로 이해하기 어렵다는 문제가 있다.

예를 들어 Case 화면에서:

- 분석 추가와 Run History가 먼저 등장하고
- 인계 당시 상태와 현재 상태 비교는 별도 영역에 있으며
- Open Item과 Evidence 확인 업무가 분리되어 있고
- Hypothesis와 Handover 기능도 서로 떨어져 있다.

이 때문에 기능은 존재하지만 사용자가 화면을 보면서

> **“지금 이 사건이 어디까지 진행됐고, 내가 다음에 무엇을 해야 하는가?”**

를 빠르게 파악하기 어렵다.

따라서 이번 개편에서는 새로운 도메인이나 기능을 추가하기보다, **기존 기능과 API는 그대로 유지하면서 사용자가 이해하는 순서를 정리하는 것**을 목표로 한다.

---

## 2. 핵심 사용자 흐름

Continuum의 사용자 경험을 다음 세 단계로 단순화하는 방향을 검토한다.

```text
Shift
"이번 교대에서 무엇을 확인해야 하지?"
        ↓
Case
"이 사건은 지금 어디까지 조사됐지?"
        ↓
Handover
"다음 교대에게 무엇을 넘겨야 하지?"
```

이 구조는 **제품의 화면 역할과 정보 흐름을 정리하기 위한 개념**이다.

즉, 이번 기획안만으로 “사용자가 서비스에 접속하면 무조건 Shift Workspace를 첫 화면으로 보여준다”는 결정을 확정하는 것은 아니다.

첫 진입 화면을 Shift Workspace로 둘지, Golden Case 또는 기존 조사 화면으로 둘지는 Golden Demo 동선과 함께 별도로 결정할 수 있다.

내부적으로는 Run, Resume, Snapshot, Delta, Open Item, Hypothesis 등의 기존 모델을 그대로 유지한다.

다만 사용자가 제품을 이해할 때는 이러한 내부 개념보다 **업무 흐름을 중심으로 화면을 구성**한다.

---

## 3. 현재 Case 화면의 문제

현재 Case 상세 화면은 기능별로 구현이 누적되면서 실제 업무 순서와 UI 순서가 일치하지 않는다.

예를 들어 현재 구조에서는:

```text
Case
├─ 분석 추가
├─ Run History
├─ Resume / 연속성 비교
├─ Observation
├─ Open Item
├─ Evidence Task
├─ Hypothesis
└─ Handover
```

와 같이 기능 단위로 화면이 구성되어 있다.

이 구조에서는 사용자가 먼저 기술적인 Analysis Run과 내부 상태를 이해해야 이후 조사 상태를 파악할 수 있다.

하지만 실제 작업자는 Case에 들어왔을 때 다음 순서로 생각할 가능성이 높다.

```text
이게 무슨 사건이지?
↓
이전 교대에서 어디까지 했지?
↓
그래서 지금 내가 뭘 해야 하지?
↓
현재 어떤 원인 가설을 보고 있지?
↓
분석 결과는 어떻게 변했지?
↓
다음 교대에는 무엇을 넘겨야 하지?
```

따라서 UI도 이 사고 흐름을 따라가도록 재구성한다.

---

## 4. 제안하는 Case Workspace 구조

Case 상세 화면을 다음 순서로 재배치한다.

```text
1. Overview
2. 연속성
3. 해야 할 일
4. 원인 가설
5. 분석 이력
6. Handover
```

### 4.1 Overview

사용자가 Case를 열었을 때 가장 먼저 현재 상황을 이해할 수 있도록 한다.

주요 정보:

- Case 상태
- Incident
- 현재 분석
- 최근 Handover
- 미해결 업무 수
- 현재 Next Action

Case ID, Run ID, Investigation ID와 같은 기술적인 식별자는 필요한 경우 확인할 수 있지만 주요 정보보다 앞에 두지 않는다.

사용자가 이 영역에서 답을 얻어야 하는 질문은:

> **“지금 이 Case는 어떤 상태인가?”**

이다.

### 4.2 연속성

이전 교대의 인계 상태와 현재 상태를 비교하는 영역이다.

기존 Resume / Snapshot / Handover Delta 데이터는 그대로 사용한다.

사용자에게는 다음 세 가지로 표현한다.

```text
인계 당시
현재 상태
인계 이후 변경
```

즉 내부적으로는:

```text
Snapshot
Current Case
handover_delta
```

이지만 사용자에게 내부 데이터 모델 이름을 그대로 노출하지 않는다.

이 영역의 목적은 다음 질문에 답하는 것이다.

> **“이 Case를 인계받은 이후 무엇이 달라졌는가?”**

### 4.3 해야 할 일

현재 분리되어 있는 Open Item과 Evidence 확인 업무를 사용자 관점에서는 하나의 **업무 영역**으로 묶는다.

각 업무에서 다음 정보를 확인할 수 있도록 한다.

- 업무 내용
- 담당자
- 현재 상태
- 어떤 분석에서 발생했는지
- 연결된 Evidence
- 완료 또는 보류 여부

내부 데이터 구조는 기존대로 유지한다.

즉 Open Item과 EvidenceTask를 하나의 모델로 합치는 것이 아니라, **화면에서 사용자가 해야 할 일을 한 영역에서 확인하도록 하는 것**이다.

Evidence는 기존 Run scope를 유지한다.

```text
(run_id, evidence_id)
```

를 이용해 R1과 R2에서 동일한 Evidence ID가 존재하더라도 올바른 분석 결과를 열어야 한다.

이 영역이 답해야 하는 질문은:

> **“그래서 내가 지금 해야 할 일은 무엇인가?”**

이다.

### 4.4 원인 가설

기존 Hypothesis 기능은 유지하되 사용자에게는 `원인 가설`로 표현한다.

각 가설에서는 다음 정보를 보여준다.

- 어떤 Candidate와 연결되어 있는지
- 관련 Evidence
- 현재 판단
- 판단자
- 판단 이유

판단 상태는 기존 계약을 유지한다.

예:

- supported
- not_supported
- insufficient
- unreviewed

Candidate와 Hypothesis는 구분한다.

Candidate는 RCA 분석 결과이며,
Hypothesis는 그 Candidate를 바탕으로 사람이 검토하고 있는 Case-level 판단이다.

### 4.5 분석 이력

Analysis Run은 Case의 중요한 기술적 기록이지만 사용자가 Case에 들어오자마자 가장 먼저 확인해야 하는 정보는 아니다.

따라서 기존 화면 상단에서 아래쪽으로 이동한다.

사용자에게는 `Run History`보다 **분석 이력**이라는 표현을 우선 사용한다.

예:

```text
14:10 최초 분석
cutoff 140s

15:03 재분석 · 현재
cutoff 170s
```

R1 / R2와 Run ID는 필요할 경우 확인할 수 있는 보조 정보로 둔다.

### 4.6 Handover

Case 조사가 끝나거나 다음 교대로 넘겨야 할 시점에는 Handover 영역으로 이동한다.

주요 기능:

- 인계자
- 인수자
- Handover 사전 점검
- 현재 조사 상태 확인
- Open Item 전달
- Snapshot 생성
- Packet 발행
- 인수 확인 / 변경 요청

Handover는 Case 종료와 동일한 개념으로 취급하지 않는다.

인수가 완료되어도 Case 조사는 계속될 수 있다.

이 영역의 질문은:

> **“다음 교대가 이 조사를 이어가기 위해 무엇을 넘겨야 하는가?”**

이다.

---

## 5. Shift 화면의 역할 정리

Shift 화면은 개별 Case의 상세 내용을 모두 보여주는 화면이 아니다.

여러 Case가 존재할 경우 사용자가 어떤 Case를 확인해야 하는지 빠르게 판단하도록 돕는다.

따라서 Case 카드에서 우선 보여줄 정보는 다음과 같다.

- Case 식별 정보
- 현재 상태
- 확인이 필요한 이유
- 미해결 업무
- 최근 Handover
- 현재 분석
- 다음 행동

예:

```text
Case A

확인 필요
- 미해결 업무 2건
- 인계 이후 새로운 분석 발생

현재 분석
- cutoff 170s

최근 인계
- Shift A → Shift B

다음 행동
- LP 계통 확인 업무 진행
```

반대로 다음 정보는 기본 화면에서 우선 노출하지 않는다.

- 전체 Observation
- 상세 Hypothesis 집계
- Raw Run ID
- Raw Incident ID
- 상세 Delta
- 기술적인 내부 식별자

필요할 경우 펼쳐서 확인할 수 있도록 한다.

Shift 카드가 답해야 하는 핵심 질문은:

> **“왜 내가 이 Case를 열어봐야 하는가?”**

이다.

---

## 6. 용어 정리

내부 데이터 모델은 변경하지 않는다.

사용자 화면에서만 다음과 같이 표현한다.

| 내부 개념 | 사용자 표현 |
|---|---|
| Resume | 별도 기능명으로 강조하지 않고 Case 연속성 영역에 포함 |
| Snapshot | 인계 당시 / 인계 당시 상태 |
| handover_delta | 인계 이후 변경 |
| Analysis Run | 분석 / 분석 이력 |
| Open Item | 미해결 업무 |
| EvidenceTask | 확인 업무 |
| Hypothesis | 원인 가설 |

Candidate와 Evidence는 RCA 결과와 연결되어 있으므로 기존 의미를 유지한다.

---

## 7. 이번 개편에서 변경하지 않는 것

이번 작업은 새로운 서비스 구조를 만드는 작업이 아니다.

다음 항목은 변경하지 않는다.

- Case domain
- Analysis Run 모델
- Resume API
- Snapshot
- handover_delta 계산
- Open Item 데이터 모델
- EvidenceTask 데이터 모델
- Hypothesis 데이터 모델
- Run-scoped Evidence
- Handover 상태 전이
- 기존 Backend API

즉 이번 변경의 핵심은:

> **Backend 구조 변경이 아니라 기존 기능을 사용자가 이해하는 업무 순서에 맞게 재배치하는 것**

이다.

---

## 8. 기대 효과

### Case 진입 시 현재 상태 파악이 쉬워진다

기존에는 Run과 개별 기능을 이해해야 전체 상황을 파악할 수 있었다.

개편 후에는 Overview에서 현재 Case 상태를 먼저 확인한다.

### 인수받은 조사 맥락을 쉽게 이해할 수 있다

`인계 당시 → 현재 → 인계 이후 변경` 흐름을 통해 이전 교대 이후 변화가 명확하게 보인다.

### 사용자의 다음 행동이 명확해진다

Open Item과 Evidence 확인 업무가 한 영역에서 보이므로 지금 해야 할 일을 찾기 쉬워진다.

### 내부 구현 복잡도가 사용자에게 그대로 노출되지 않는다

Run, Snapshot, Resume, Delta 등의 기술적인 개념은 그대로 존재하지만 사용자는 업무 중심 언어로 제품을 사용할 수 있다.

### Golden Demo의 흐름이 명확해진다

```text
RCA
→ Case
→ 현재 조사 상태 이해
→ 해야 할 일 수행
→ Handover
→ 다음 교대가 이어서 조사
```

라는 Continuum의 핵심 메시지를 화면 순서 자체로 보여줄 수 있다.

---

## 9. 회귀 검증 범위

화면 구조와 용어를 변경하더라도 기존 기능은 모두 유지되어야 한다.

다음 흐름을 회귀 테스트한다.

```text
Case 진입
↓
인계 당시 / 현재 / 인계 이후 변경 확인
↓
Open Item 처리
↓
Hypothesis 판단
↓
R1 Evidence 확인
↓
R2 추가 분석
↓
R2 Evidence 확인
↓
분석 이력 확인
↓
Handover 사전 점검
↓
Packet 발행
↓
Handover 수락
```

특히 Run-scoped Evidence는 반드시 유지한다.

```text
R1의 E1 → R1 Evidence
R2의 E1 → R2 Evidence
```

검증 항목:

- frontend unit test
- TypeScript typecheck
- production build
- browser E2E
- Case continuity
- Open Item 처리
- Hypothesis 판단
- R1/R2 추가 분석
- Evidence scope
- Handover

추가로 UX 변경이 다음 계약을 깨뜨리지 않는지 Backend/API 회귀 검증에 포함한다.

- `expected_version` 충돌 방지와 stale accept 거절
- `X-Actor-Id`/`X-Actor-Role` 및 Handover audit 기록
- Handover publish/accept/change-request 상태 전이
- `(run_id, evidence_id)` 기준의 Run-scoped Evidence 조회
- AI 제안은 accept 전까지 Case aggregate와 Handover Packet을 변경하지 않는 경계

---

## 10. 팀 논의가 필요한 사항

### 1. 사용자 흐름

Continuum의 주요 화면 역할을

```text
Shift → Case → Handover
```

로 정의하는 것이 적절한가?

이 질문은 **서비스 첫 진입 화면을 Shift로 확정한다는 의미가 아니다.**

Golden Demo에서는 필요하면 Golden Case로 바로 진입할 수 있다.

### 2. Case 상세 정보 우선순위

Case 화면을

```text
Overview
→ 연속성
→ 해야 할 일
→ 원인 가설
→ 분석 이력
→ Handover
```

순으로 구성하는 것이 실제 사용 흐름에 맞는가?

### 3. 내부 용어 노출 수준

Resume, Snapshot, Delta, Run 등의 내부 개념을 주요 UI 용어로 노출하기보다 사용자 업무 용어로 표현하는 방향에 동의하는가?

### 4. Shift 화면의 역할

Shift 화면에서는 Case의 모든 세부 내용을 보여주기보다,

> 확인해야 하는 Case와 그 이유를 빠르게 파악하는 역할

로 제한하는 것이 적절한가?

### 5. 첫 진입 화면

Golden Demo의 첫 화면을 다음 중 어디로 둘지는 별도로 결정한다.

- Shift Workspace
- Golden Case
- 기존 RCA/Investigation 화면

이번 UX 개편의 핵심은 첫 진입 화면 자체보다 **Case 안에서 정보를 읽는 순서와 화면 간 역할을 명확히 하는 것**이다.

---

## 11. 제안

이번 개편에서는 새로운 기능이나 데이터 모델을 추가하지 않는다.

기존 구현을 유지하면서 사용자 흐름과 정보 우선순위만 정리한다.

최종적으로 사용자가 Continuum을 다음 세 질문으로 이해할 수 있도록 하는 것을 목표로 한다.

```text
Shift
"이번 교대에서 무엇을 확인해야 하지?"

Case
"이 사건은 어디까지 조사됐고 지금 무엇을 해야 하지?"

Handover
"다음 교대에게 무엇을 넘겨야 하지?"
```

이 문서는 UX 논의를 위한 제안이며, 현재 화면의 동작을 변경하지 않는다. 팀이 구조를 확정하면 Case Workspace의 정보 우선순위 개편을 작은 UI 단위로 구현한다.

P2-1의 OpenAI-compatible 대회 Gateway 연결 경로는 이미 구현되어 있다. 다음 구현 단계는 그 경로를 사용한 Proposal-only Context Structuring과 Case Q&A이며, API 키·모델 허용 목록의 외부 검증이 끝나기 전에도 결정론적 폴백과 AI 권한 경계를 유지한다. LLM은 Case/Handover 상태를 직접 변경하거나 원인을 확정하지 않는다.
