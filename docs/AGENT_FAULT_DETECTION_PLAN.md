# 에이전트 기반 이상탐지 전환 계획

> 결정 기록: [ADR-0005](decisions/ADR-0005-agent-first-fault-detection.md) · 기준일: 2026-09-22
> 이 문서는 팀 공유용 실행계획이다. Shift/Handover 워크스페이스(ADR-0004)는 이번 범위에서 유지하며, 이 문서는 그 앞단(Monitor/Investigate 진입 흐름)만 다룬다.

## 0. 왜 지금 바꾸는가 (한 문단 요약)

지금 서비스는 causRCA의 준비된 fault 사건을 사람이 고르고, cutoff를 손으로 슬라이더로 맞춰야 원인 후보가 나온다. 이 대회는 "데이터를 정확히 분석했는가"가 아니라 "AI 에이전트를 얼마나 잘 붙였는가"와 "데이터 활용성"을 보는 경진대회이므로, 탐지 시점 선택과 원인분석 트리거를 사람에서 에이전트로 옮기고, 지금 안 쓰이는 causRCA 자산(정상 운전 170개, subsystem 서브그래프, 사람이 읽는 변수 라벨)을 실제로 사용한다.

## 1. 현재 상태 감사 (2026-09-22 기준 사실 확인)

| 항목 | 현재 상태 | 근거 |
| --- | --- | --- |
| fault 시작점 탐지 | 없음. 사람이 슬라이더로 cutoff 지정 | `backend/app/workflows/investigation.py:28` `cutoff = state["diagnosis_time"]` |
| `cause_start_at`/`cause_end_at` | 추출·사용 안 함 | `scripts/prepare_causrca.py`는 `diagnosis_at`만 evaluation으로 뽑음 |
| RCA(원인 랭킹) | 이미 구현됨, 인과그래프 사용 | `backend/app/analytics/causrca.py::rank_with_caus_tr` |
| `real_op` 정상 운전 170개 | 미사용 | `prepare_causrca.py`가 `dig_twin`만 읽음 |
| `<group>_nodes.csv`의 `label` 컬럼 | 미사용 (원시 tag ID 그대로 노출) | `causrca.py` Evidence 문구가 `node` 이름 그대로 사용 |
| subsystem별 서브그래프 | 미사용 (92노드 전체 그래프만 사용) | `prepare_causrca.py`가 `expert_graph/expert_graph.gml`만 복사 |
| `diagnoses`(고장 진단명) | 미사용 | evaluation_cases에 `ground_truth_nodes`만 저장 |
| Bedrock AgentCore | 배포는 됐지만 실제 요청 경로 미연결 | `docs/decisions/ADR-0003` "프로덕션 요청 경로의 일부가 아니다" |
| LangGraph 워크플로우 | 고정 순서 DAG, 조건 분기 없음 | `investigation.py`의 `validate_request → run_deterministic_analysis → evidence_check → ...` |
| Case/Handover/Hypothesis/Open Item | 상세하게 구현됨 | ADR-0004, `backend/app/services/cases.py` 등 |

## 2. 목표 아키텍처

```text
[Case Stream Simulator]
  준비된 causRCA 기록(fault 100 + normal 170)을 시간순으로 배속 재생
        │ tick마다 관측치 증분 공개
        ▼
[Fault Detection Agent]  ← 신규
  신호1: Alarm 최초 활성화 감지 (causRCA Baro 계열 휴리스틱)
  신호2: real_op 기준 PCA 재구성오차 (metal_etch_pca.py 패턴 이식)
  → 에이전트가 두 신호 + 최근 추세를 보고 다음 행동을 결정:
     - anomaly 상승 + alarm 없음 → 추가 관찰
     - alarm 발생 + anomaly 낮음 → 오탐 가능성 검토(추가 확인)
     - 둘 다 강함 → RCA 실행으로 전이
     - 근거 부족 → 재시도/윈도우 확장
        │ (RCA 실행 결정 시)
        ▼
[RCA Agent]  (기존 rank_with_caus_tr을 자동 트리거로 승격)
  감지된 시점을 cutoff로 causal graph 기반 원인 랭킹 자동 실행
  근거 약하면 재시도/폴백(recency baseline), 그래도 없으면 판단보류
        │
        ▼
[Investigation Summary]
  에이전트가 조립한 하나의 요약: 감지 근거 + 원인 후보 + 근거 + 남은 불확실성
        │ (사람이 검토·승인)
        ▼
[Case 생성 → Handover]  (ADR-0004 자산 재사용, 변경 없음)
```

핵심 원칙(AGENTS.md 승계): 신호 계산(알람 감지, PCA 점수, 인과그래프 랭킹)은 전부 결정론적 도구. **에이전트가 하는 일은 "어떤 도구를 언제 호출하고 결과를 어떻게 조합해 다음 단계를 고를지"뿐**이며 숫자를 스스로 만들지 않는다.

## 3. Phase 1 — Alarm 기반 탐지 에이전트 (가장 먼저, 리스크 최소)

**목표**: 사람이 cutoff를 정하지 않아도, 알람 최초 활성화를 근거로 에이전트가 스스로 "이상 시작"을 감지하고 RCA를 자동 트리거하는 최소 경로를 완성한다.

- `backend/app/analytics/fault_onset.py` (신규): `estimate_fault_onset(incident, up_to_time_s)` — `kind == "Alarm"`이고 활성인 관측 중 최초 시각을 근거와 함께 반환. 근거 없으면 `None`.
- `backend/app/workflows/detection.py` (신규): LangGraph 조건부 그래프. 상태: `observed_so_far`, `onset_estimate`, `decision`. 분기: 알람 없음→관찰 지속 / 알람 있음→RCA 트리거로 전이하는 `TraceEvent` 기록.
- `backend/app/workflows/investigation.py` 수정: `diagnosis_time`을 사람이 넘긴 값 대신 detection 그래프가 넘긴 `onset_estimate`를 받을 수 있도록 파라미터 경로 확장 (기존 수동 cutoff 경로는 "수동 재조사" 용도로 유지 — 완전히 제거하지 않음, 4절 참고).
- `backend/app/data/runtime_repository.py`의 `FORBIDDEN_RUNTIME_KEYS`는 그대로 유지(신규 필드 없음, alarm 감지는 이미 runtime에 있는 `kind=="Alarm"` 관측만 사용).
- 평가: `evals/run_causrca_benchmark.py`에 "탐지 정확도" 지표 추가 — 이때만 `data/evaluation/causrca/cases.json`에 `cause_start_at`을 추가로 채워 넣어(현재 안 뽑고 있음) 추정 onset과 비교(MAE, ±N초 적중률).
- 테스트: (a) 알람 여러 개/없음/컷오프 이후만 있는 경우 단위 테스트, (b) 라벨 누출 테스트 — runtime 경로 어디서도 `cause_start_at`을 읽지 않는지 확인.

## 4. Phase 2 — PCA 이상신호 + 에이전트 의사결정 레이어 (완료, 2026-09-22)

**실제 결과 (causRCA 100 fault + 170 normal 전체 실행)**:
- `full_trigger_false_positive_rate` = **0%** (170개 정상 기록 전부에서 `trigger_rca`로 자동 오픈된 사례 없음 — 두 신호가 불일치할 때 자동 실행을 보류하는 4방향 판단이 실제로 작동)
- `any_false_positive_rate` ≈ 5.3% (`elevated_watch` 포함, PCA 임계값을 baseline 자체의 p95로 잡았을 때 통계적으로 예상되는 수준)
- fault 100건에 대한 alarm 기반 탐지는 Phase 1 결과(100% 탐지, lag 평균 24.3초)와 동일 — PCA는 alarm이 없을 때의 조기경보(elevated_watch) 및 alarm 있을 때의 오탐 검증(false_positive_review) 역할을 추가로 담당.

**구현 중 발견한 스키마 제약**: `Observation.kind`는 `Alarm/Measurement/Event` 세 값만 허용하는데, `scripts/prepare_causrca.py::read_observations`가 causRCA 원본의 `Binary/Continuous/Counter/Categorical` 타입 구분을 전부 `Event`로 뭉개버리고 있었다(Alarm만 보존). 그래서 PCA 인코딩은 `kind`가 아니라 **값 자체의 모양**(숫자로 파싱되는지, true/false 문자열인지)으로 인코딩 가능 여부를 판단하도록 구현했다 — `causrca_anomaly.py` 모듈 docstring에 상세 기록.

**목표**: 알람이 아직 안 뜬 "전조 단계"도 잡아내는 두 번째 신호를 추가하고, 두 신호를 사람이 아니라 에이전트가 종합 판단하게 한다.

- `data/manifests/`, `scripts/prepare_causrca.py` 확장: `real_op` 170개를 읽어 `data/runtime/causrca/normal_baseline.json`(Metal Etch의 `NormalWaferRecord` 패턴과 동일한 3필드 요약 스키마)으로 저장.
- `backend/app/analytics/causrca_pca.py` (신규, `metal_etch_pca.py` 이식): 정상기준선 대비 재구성오차 점수 계산. **주의**: causRCA 노드는 Binary/Alarm/Categorical이 다수라 Metal Etch(연속 센서 위주)와 인코딩 전처리가 다르다 — `causrca` 원본 레포의 `discretize.py::transform_non_continuous_values_in_df`와 동일한 인코딩 규칙을 이식해야 함.
- `backend/app/workflows/detection.py` 확장: 상태에 `anomaly_score` 추가. 의사결정 표(ADR-0005 결정 1번)를 조건부 엣지로 구현:
  - `anomaly_score 상승 & no_alarm` → `awaiting_more_data`
  - `alarm & low_anomaly_score` → `false_positive_review`
  - `alarm & high_anomaly_score` → `trigger_rca`
  - 두 신호 모두 근거 부족 → `retry_with_wider_window` (최대 재시도 횟수 제한, 무한루프 방지)
- 매 분기 전이를 `TraceEvent`로 기록 (실행 이력 완결성 지표, EVALUATION.md).

## 5. Phase 3 — 프론트엔드 재설계: Monitor → Investigate → Handover

**목표**: Case/Handover/Hypothesis/Open Item을 각각의 메뉴로 노출하지 않고, 에이전트가 복잡성을 흡수한 3단계 흐름으로 재구성.

- **Monitor**: 재생 시뮬레이터 진행바(배속 조절), 현재 tick까지의 관측 요약, 탐지 에이전트 상태 배지("관찰 중" / "알람 감지, 검토 중" / "이상 확정, RCA 실행"). "준비된 HIL 기록의 재생 시뮬레이션"임을 항상 명시 (DESIGN.md 신뢰 신호 원칙).
- **Investigate**: 에이전트가 조립한 investigation summary 단일 화면. 후보/근거/미확인 항목을 별도 탭이 아니라 하나의 요약 카드 안에 배치하고, hypothesis 판단·open item 상세는 accordion/drawer로 progressive disclosure. 기존 API(`/cases/{id}/hypotheses/...`, `/open-items`)는 그대로 재사용, 화면 배치만 통합.
- **Handover**: 기존 Handover Snapshot/Resume 화면 그대로 유지 (ADR-0004 자산, 변경 없음). 다만 진입 경로가 Investigate 요약에서 "인계 초안 생성" 버튼으로 자연스럽게 이어지도록 연결.
- 기존 `frontend/src/App.tsx`의 라우팅/탭 구조를 3단계 흐름 기준으로 재배치. 백엔드 도메인/스키마는 변경하지 않는다(ADR-0005 결정 4번).

## 6. AgentCore 확장 지점 (지금 안 함, 인터페이스만 남김)

Phase 1~3의 LangGraph 그래프(`detection.py`, `investigation.py`)는 순수 함수형 노드로 구성해서, 추후 AgentCore Runtime이 이 그래프 전체를 감싸는 tool로 등록할 수 있게 한다. 지금 단계에서는 코드를 추가하지 않고, 그래프 상태(TypedDict)와 노드 함수 시그니처만 "외부에서 호출 가능한 단위"로 깔끔하게 유지한다.

## 7. 평가 지표 추가 (`docs/EVALUATION.md` 갱신 필요)

- 탐지 정확도: 추정 onset vs `cause_start_at`의 MAE, ±5초/±10초 적중률.
- 오탐률: `real_op`(정상 170개)를 흘렸을 때 에이전트가 잘못 알람을 올리는 비율 — **이상탐지 에이전트의 신뢰성을 보여주는 핵심 지표**이자 지금까지 전혀 측정 안 하던 것.
- 기존 Hit@1/Hit@3/MRR/MAP@3(원인 랭킹)은 그대로 유지, 탐지 성공 사건에 한해서만 계산.

## 8. 순서와 이유

1. Phase 1(Alarm 탐지, 백엔드만) → 리스크 가장 낮고, "에이전트가 스스로 이상을 찾는다"는 핵심 데모를 가장 빨리 보여줄 수 있음.
2. Phase 2(PCA + 의사결정 레이어) → Phase 1 위에 신호 하나 더 얹는 것이라 회귀 위험이 낮음.
3. Phase 3(프론트엔드 재설계) → 백엔드가 먼저 안정화된 뒤 진행해야 화면을 다시 갈아엎지 않는다.

## 미해결 질문 (팀 논의 필요)

- [ ] 오탐 검토(`false_positive_review`) 상태에서 에이전트가 "몇 초 더 기다릴지"의 기본값 — 데이터별로 다를 수 있어 subsystem별 튜닝이 필요할 수 있음.
- [ ] PCA 기준선의 인코딩 방식(연속/이산 혼합)을 causRCA 원본의 `discretize.py`와 얼마나 그대로 가져올지, 아니면 우리 스키마에 맞게 단순화할지.
- [ ] Phase 3에서 기존 Shift Workspace(담당자 필터·정렬)를 Monitor 화면과 어떻게 연결할지는 이번 범위 밖(사용자 지시: shift는 다음 단계).
