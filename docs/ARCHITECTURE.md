# 아키텍처

```text
데이터셋 어댑터 → runtime 사건 계약 → 결정론적 분석 도구
                                      │            │
                                      ▼            ▼
                              근거 조립  ← 워크플로우 상태
                                      │
                                      ▼
                         Case Orchestrator → Open Item/관측 → 사람의 판단 기록
                                             │
                                             ▼
                              Handover Snapshot → Resume/인수 → 조사 재개
```

## 백엔드 경계

- `domain`: API, 도구, 워크플로우가 공유하는 검증된 계약
- `data`: 데이터셋별 어댑터와 runtime 전용 저장소
- `analytics`: 결정론적 이상·원인 후보 순위 도구
- `workflows`: LangGraph 오케스트레이션. 수치 계산이나 장비 제어를 하지 않음
- `services/cases.py`: 결정론적 조사 결과를 증거 확인 업무·사건 상태·전문가 검토로 연결. LLM을 호출하지 않음
- `repositories/cases.py`: 사건 상태 저장소 경계. 로컬 연구 모드는 in-memory, `CASE_DDB_TABLE`이 설정된 AWS 환경은 별도 DynamoDB 테이블을 사용
- `api`: HTTP 입력 검증과 직렬화만 담당
- `evals`: 평가 정답을 읽을 수 있는 benchmark 전용 코드

## API

- `GET /api/health`
- `GET /api/datasets`
- `GET /api/incidents`
- `GET /api/incidents/{incident_id}`
- `POST /api/incidents/{incident_id}/investigations` — `include_llm_narrative`(기본 `False`)를 요청하면 결정론적 결과 뒤에 `backend/app/llm/explainer.py`의 요약을 덧붙인다. LLM이 실패/미가용이면 `mode`는 `"deterministic"`로 남고 `llm_narrative`는 `None`이다. 응답에는 저장된 조사를 가리키는 `investigation_id`가 포함된다. `diagnosis_time`을 사람이 직접 지정하는 수동 경로다.
- `POST /api/incidents/{incident_id}/detect` — [ADR-0005](decisions/ADR-0005-agent-first-fault-detection.md) / [AGENT_FAULT_DETECTION_PLAN.md](AGENT_FAULT_DETECTION_PLAN.md) Phase 1. 사람이 cutoff를 고르지 않고, `observed_up_to_s`(재생 시뮬레이터의 현재 위치)까지 관측된 알람만으로 `workflows/detection.py`의 탐지 에이전트가 fault onset을 스스로 추정한다. 활성 알람을 찾으면(`decision: "trigger_rca"`) 그 시각을 cutoff로 `run_investigation`을 자동 실행해 `investigation`/`investigation_id`까지 응답에 포함하고, 못 찾으면(`decision: "await_more_data"`) `investigation`은 `null`이다. `data/evaluation`의 `cause_start_at`은 이 경로 어디에서도 읽지 않는다 — 탐지 정확도는 `evals/run_fault_onset_benchmark.py`에서만 채점한다.
- `POST /api/incidents/{incident_id}/cases` — LLM 없이 첫 결정론적 AnalysisRun과 Open Item을 가진 Case를 연다.
- `POST /api/cases/{case_id}/observations`, `/analysis-runs`, `/open-items`, `/hypotheses/{hypothesis_id}/assessments` — 동일 Case의 사람 관찰·후속 Run·미확인 항목·가설 판단을 version 검사와 함께 기록한다.
- `POST /api/cases/{case_id}/handover-checks`, `/handovers`, `/handovers/{handover_id}/acceptance`, `/change-requests` — 결정론적 인계 점검, immutable Snapshot 발행, 인수 또는 설명 요청을 수행한다.
- `GET /api/cases/{case_id}/resume`, `POST /api/cases/{case_id}/chat` — 현재 Case 상태를 템플릿으로 제공하고, 선택적 AI 보조는 근거를 정리할 뿐 상태를 바꾸지 않는다.
- `GET /api/investigations/{investigation_id}` — 저장된 조사 결과 조회
- `POST /api/investigations/{investigation_id}/reviews` — 전문가 승인/거절 기록 (approve/reject + comment + reviewer)
- `GET /api/investigations/{investigation_id}/report` — 조사 결과 + 기록된 모든 검토를 합쳐 반환

`POST .../investigations`은 `backend/app/services/investigations.py`(`run_investigation`)를 거친다. 이 서비스 계층이 결정론적 워크플로우(`workflows/investigation.py`, LLM import 없음)와 선택적 LLM 내러티브 단계를 분리해서, 워크플로우 자체는 여전히 수치 계산만 하고 LLM을 몰라도 되게 유지한다. 조사/검토는 `INVESTIGATION_DDB_TABLE`이 설정되면 DynamoDB에, 그렇지 않으면 local in-memory 저장소에 쌓인다.

현재 React 조사 UI와 사건 인박스는 구현됐다. DynamoDB 사건 목록은 MVP 규모에서 paginated scan을 사용하며, 다중 조직 운영 전에는 조직·담당자 기준 인덱스 쿼리로 전환해야 한다.
