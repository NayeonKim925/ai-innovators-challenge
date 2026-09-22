# 평가 계획

## 주 benchmark: causRCA

서비스 runtime은 선택한 진단 cutoff 이전의 관측값만 받습니다. 원인 정답은 평가 스크립트만 읽을 수 있고, 서비스 코드나 LLM에는 전달되지 않습니다.

## 지표

- **fault 탐지 ([AGENT_FAULT_DETECTION_PLAN.md](AGENT_FAULT_DETECTION_PLAN.md))**:
  - Phase 1 — `evals/run_fault_onset_benchmark.py`가 알람 기반 onset 추정치와 `cause_start_at`(evaluation 전용)을 비교한다. `detection_rate`(활성 알람을 찾은 비율), `mean_lag_s`/`median_lag_s`(추정 시각 − 실제 원인 시작, 인과관계상 항상 양수가 정상), `hit_within_5s`/`hit_within_10s`. 실측(causRCA 100개 fault 사건 전체): detection_rate 100%, mean_lag ≈ 24.3초, median_lag ≈ 31.7초.
  - Phase 2 — `evals/run_false_positive_benchmark.py`가 `real_op` 170개 정상 운전 기록(fault 라벨 자체가 없음)에 대해 탐지 에이전트(알람+PCA 두 신호)를 실행해 오탐률을 잰다. `full_trigger_false_positive_rate`(자동으로 RCA를 트리거하는 `trigger_rca` 결정만 집계 — 자율성 안전성의 핵심 지표)와 `any_false_positive_rate`(`elevated_watch` 포함, 사람에게만 표시되고 Case를 자동으로 열지는 않는 약한 신호까지 포함)를 구분한다. 실측: **full_trigger_false_positive_rate 0%**(170개 전부, 두 신호가 서로 다른 결론을 낼 때 자동 트리거를 보류하는 4방향 판단 로직이 실제로 작동함을 확인), any_false_positive_rate ≈ 5.3%(PCA 임계값을 기준선 자체의 95th percentile로 잡았으므로 baseline 재대입 기준 통계적으로 예상되는 수준 — 진짜 held-out 일반화 성능은 아님, 스크립트 자체의 `limitations`에 명시).
- 원인 후보 순위: Hit@1, Hit@3, MRR, MAP@3
- 워크플로우: 올바른 도구 선택률, 구조화 출력 유효성, 실행 이력 완결성, 필수 증거 업무 누락률, 무검토 종료율(목표 0)
- 근거: 근거 없는 주장 비율, 인용·관측값 일치율, 판단 보류 품질
- 제품: Time-to-Context, 중요 Open Item 누락률, 인용·상태 추출 정확도, 인계 준비 시간, 검토자 합의도
- 연속성: stale Snapshot 수락 차단, 담당 공백 감지, 인계 후 변경 Delta 보존

## 필수 비교

1. 결정론적 분석만 사용
2. 결정론적 분석과 근거 조립 사용
3. 선택적 LLM 설명까지 포함한 전체 워크플로우

LLM은 수치 점수를 바꾸거나 평가 라벨에 접근하면 안 됩니다. 제공한 데이터와 코드만으로 재현할 수 없는 비교 결과는 발표 자료에 넣지 않습니다.

사건 오케스트레이션 평가의 상태 모델과 데모 경로는 [CASE_ORCHESTRATION_PLAN.md](CASE_ORCHESTRATION_PLAN.md)를 기준으로 한다. `confirmed` 응답은 원인 정답이 아니라 사람이 특정 관측 근거를 확인했다는 workflow 이벤트이므로, causRCA 순위 지표와 혼합하지 않는다.
