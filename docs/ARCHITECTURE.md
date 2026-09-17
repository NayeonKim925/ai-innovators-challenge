# 아키텍처

```text
데이터셋 어댑터 → runtime 사건 계약 → 결정론적 분석 도구
                                      │            │
                                      ▼            ▼
                              근거 조립  ← 워크플로우 상태
                                      │
                                      ▼
                         Case Orchestrator → 확인 업무 → 사람의 판단 기록
                                             │
                                             ▼
                                  API → 검토 가능한 보고서
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
- `POST /api/incidents/{incident_id}/investigations` — `include_llm_narrative`(기본 `False`)를 요청하면 결정론적 결과 뒤에 `backend/app/llm/explainer.py`의 요약을 덧붙인다. LLM이 실패/미가용이면 `mode`는 `"deterministic"`로 남고 `llm_narrative`는 `None`이다. 응답에는 저장된 조사를 가리키는 `investigation_id`가 포함된다.
- `POST /api/incidents/{incident_id}/cases` — LLM 없이 결정론적 조사를 저장하고, 근거 확인 업무가 포함된 사건을 연다.
- `GET /api/cases`, `GET /api/cases/{case_id}` — 사건, 확인 업무, 상태 이벤트, 최종 검토 조회
- `POST /api/cases/{case_id}/tasks/{task_id}/responses` — 역할별 근거 확인 응답 기록
- `POST /api/cases/{case_id}/reviews` — `READY_FOR_REVIEW` 사건만 최종 승인·거절 가능. 미완료 증거 업무가 있으면 종료 불가
- `GET /api/investigations/{investigation_id}` — 저장된 조사 결과 조회
- `POST /api/investigations/{investigation_id}/reviews` — 전문가 승인/거절 기록 (approve/reject + comment + reviewer)
- `GET /api/investigations/{investigation_id}/report` — 조사 결과 + 기록된 모든 검토를 합쳐 반환

`POST .../investigations`은 `backend/app/services/investigations.py`(`run_investigation`)를 거친다. 이 서비스 계층이 결정론적 워크플로우(`workflows/investigation.py`, LLM import 없음)와 선택적 LLM 내러티브 단계를 분리해서, 워크플로우 자체는 여전히 수치 계산만 하고 LLM을 몰라도 되게 유지한다. 조사/검토는 `INVESTIGATION_DDB_TABLE`이 설정되면 DynamoDB에, 그렇지 않으면 local in-memory 저장소에 쌓인다.

현재 React 조사 UI와 사건 인박스는 구현됐다. DynamoDB 사건 목록은 MVP 규모에서 paginated scan을 사용하며, 다중 조직 운영 전에는 조직·담당자 기준 인덱스 쿼리로 전환해야 한다.
