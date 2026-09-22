# Continuum UI/UX · AX 리서치 및 개편 계획

기준일: 2026-09-22  
대상: 제조 이상 조사·교대 연속성 워크스페이스

## 결론

Continuum의 현재 문제는 단순히 글씨가 작은 것이 아니라, 사건 인박스와 Case 상세에서 **현재 상태·다음 행동·미확인 항목·인수인계 상태의 위계가 약한 것**이다.

따라서 제품을 분석 대시보드가 아니라 다음 교대 담당자가 즉시 행동할 수 있는 **현장 운영 워크스페이스**로 재설계한다.

## 참고 레퍼런스

| 서비스 | 관찰한 패턴 | Continuum 적용 |
|---|---|---|
| [Honeywell Operations Management](https://process.honeywell.com/us/en/products/industrial-software/operational-excellence/operations-management) | 운영 로그북·공정 데이터·문제·교대 기록을 하나의 운영 흐름으로 연결 | 인수인계를 문서 작성이 아니라 상태 전이로 표현 |
| [Augury Industrial AI](https://www.augury.com/industrial-ai/) | 역할별 AI와 데이터에서 행동으로 이어지는 업무 화면 | 작업자 역할별 `지금 할 일`을 최상단에 표시 |
| [Siemens Insights Hub](https://www.siemens.com/en-us/products/insights-hub/capabilities/) | 자산·규칙·이벤트·작업 상태를 요약 타일과 빠른 링크로 제공 | 전체/즉시 조치/인수 대기/내 작업 요약 제공 |
| [Palantir AIP](https://www.palantir.com/docs/foundry/aip) | AI를 운영 데이터와 승인·감사·권한 흐름 안에 배치 | AI 제안과 사람이 확정한 Case 상태를 분리 |
| [Grafana annotations](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/annotate-visualizations/) | 이벤트를 시계열의 동일 시간축에 annotation으로 연결 | Alarm·Sensor·Observation·Handover를 하나의 Timeline에 표시 |
| [ServiceNow Now Assist To-dos](https://www.servicenow.com/docs/r/employee-service-management/employee-experience-foundation/emp-slate-inbox.html) | AI 우선순위와 `누가/무엇을/왜` 요약을 작업 카드에 제공 | Case 카드에 영향·다음 행동·담당자를 고정 |

## 확정 디자인 원칙

- 핵심 본문은 14px 이상, 주요 수치와 상태는 더 크게 표시한다.
- 색상만으로 상태를 구분하지 않고 텍스트·아이콘·배지 형태를 함께 사용한다.
- `Fact`, `Hypothesis`, `Unknown`, `AI Proposal`, `Confirmed`를 서로 다른 시각 언어로 구분한다.
- AI는 별도 챗봇 페이지가 아니라 현재 Case의 보조 패널로 배치한다.
- 모든 오류 화면은 원인과 다음 복구 행동을 함께 보여준다.
- 카드의 첫 줄은 사건명, 두 번째 줄은 현재 상태, 세 번째 줄은 다음 작업으로 통일한다.

## 구현 순서

### 1차 — 가독성·브랜드 기반

- Continuum 색상 토큰과 패널 대비 개선
- 사이드바·상단 헤더·워드마크 크기 조정
- 사건 인박스 제목을 `확인이 필요한 Case`로 변경
- 사건 카드에 `상태 / 확인 업무 / 다음 작업 / 업데이트 시각` 표시
- 빈 상태·오류 상태·로딩 상태의 시각적 차이 강화

### 2차 — Case Workspace 재배치

```text
Case header
  설비 · 사건 · 현재 설비 상태 · 담당자 · 인수 상태

Next action
  다음 담당자가 지금 해야 할 한 가지

Evidence timeline
  Sensor · Alarm · Observation · Handover

Investigation board
  확인된 사실 · 원인 후보 · 아직 모름 · 완료된 확인

AI assist rail
  질문하기 · 구조화 제안 · 유사 Case
```

### 3차 — AX 상호작용

- 사건 우선순위 자동 정렬
- `왜 이 작업이 먼저인가?` 근거 표시
- Handover 전 누락 검사 결과를 작업 목록으로 변환
- AI 제안 수락 전 미리보기·수정·거절 제공
- 교대 시작 시 `What changed / Still unknown / Your action`만 우선 노출

### 4차 — 검증

- 1280px 데스크톱에서 핵심 텍스트 14px 미만 금지
- 3초 안에 최우선 Case 식별 가능
- 카드만 읽고 현재 상태와 다음 행동 설명 가능
- 색상 없이도 Fact/Hypothesis/Unknown 구분 가능
- API 오류·빈 목록·데이터셋 미준비 상태를 별도 검증
- Playwright 스크린샷으로 데스크톱·좁은 화면 회귀 검증

## 현재 반영된 1차 변경

- 사건 인박스 문구를 사용자의 행동 중심으로 변경
- 전체 기본 글자 크기와 사건 카드의 제목·메타 정보 확대
- 상태 배지와 카운터의 대비·형태 개선
- 패널·입력·검색창의 클릭 영역과 시각적 그룹 강화
- Continuum 브랜드의 deep navy + teal + amber 운영 팔레트 적용

상세 리서치 원본과 현재 화면 캡처는 로컬 작업 산출물인 `.lazyweb/design-research/continuum-ui-2026-09-22/`에 있습니다.
