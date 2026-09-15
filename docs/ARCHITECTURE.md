# 아키텍처

```text
데이터셋 어댑터 → runtime 사건 계약 → 결정론적 분석 도구
                                      │            │
                                      ▼            ▼
                              근거 조립  ← 워크플로우 상태
                                      │
                                      ▼
                         API → 검토 가능한 보고서 → 사람의 판단 기록
```

## 백엔드 경계

- `domain`: API, 도구, 워크플로우가 공유하는 검증된 계약
- `data`: 데이터셋별 어댑터와 runtime 전용 저장소
- `analytics`: 결정론적 이상·원인 후보 순위 도구
- `workflows`: LangGraph 오케스트레이션. 수치 계산이나 장비 제어를 하지 않음
- `api`: HTTP 입력 검증과 직렬화만 담당
- `evals`: 평가 정답을 읽을 수 있는 benchmark 전용 코드

## API

- `GET /api/health`
- `GET /api/datasets`
- `GET /api/incidents`
- `GET /api/incidents/{incident_id}`
- `POST /api/incidents/{incident_id}/investigations` — `include_llm_narrative`(기본 `False`)를 요청하면 결정론적 결과 뒤에 `backend/app/llm/explainer.py`의 요약을 덧붙인다. LLM이 실패/미가용이면 `mode`는 `"deterministic"`로 남고 `llm_narrative`는 `None`이다. 응답에는 저장된 조사를 가리키는 `investigation_id`가 포함된다.
- `GET /api/investigations/{investigation_id}` — 저장된 조사 결과 조회
- `POST /api/investigations/{investigation_id}/reviews` — 전문가 승인/거절 기록 (approve/reject + comment + reviewer)
- `GET /api/investigations/{investigation_id}/report` — 조사 결과 + 기록된 모든 검토를 합쳐 반환

`POST .../investigations`은 `backend/app/services/investigations.py`(`run_investigation`)를 거친다. 이 서비스 계층이 결정론적 워크플로우(`workflows/investigation.py`, LLM import 없음)와 선택적 LLM 내러티브 단계를 분리해서, 워크플로우 자체는 여전히 수치 계산만 하고 LLM을 몰라도 되게 유지한다. 조사/검토는 `backend/app/repositories/investigations.py`의 프로세스 생명주기 in-memory 저장소에 쌓인다 — DB(SQLite/PostgreSQL) 도입은 `docs/IMPLEMENTATION_PLAN.md` 트랙 D의 후속 작업이다.

React 조사 UI(트랙 E)와 배포(트랙 F)는 이후 단계에서 구현합니다.
