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

## 초기 API

- `GET /api/health`
- `GET /api/datasets`
- `GET /api/incidents`
- `GET /api/incidents/{incident_id}`
- `POST /api/incidents/{incident_id}/investigations`

causRCA 데이터 준비와 결정론적 benchmark 연동 뒤에, 사람의 검토 저장과 React 조사 UI를 구현합니다.
