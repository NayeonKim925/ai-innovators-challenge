# ADR-0002: Metal Etch를 공식 어댑터로 통합하고 선택적 LLM 내러티브를 조건부로 도입

## 상태

승인 대기 (팀 리뷰 필요)

## 배경

ADR-0001은 causRCA를 핵심 benchmark로, Metal Etch를 "별도의 반도체 시연·이식성 어댑터"로 정했다. 이 결정은 지금도 유효하고 바뀌지 않는다.

그런데 실제로는 두 갈래 작업이 같은 저장소에서 독립적으로 진행됐다.

- `backend/app/`, `docs/`, `evals/`, `scripts/prepare_causrca.py` (이하 트랙 X): `IMPLEMENTATION_PLAN.md`의 M0~M1 단계를 따라 진행 중. causRCA 데이터 준비 스크립트(`scripts/prepare_causrca.py`)와 평가 지표(`evals/metrics.py`)는 존재하지만, `data/{raw,runtime,evaluation}/`는 아직 `.gitkeep`만 있는 빈 폴더다. `scripts/bootstrap_causrca.py`, `scripts/validate_data.py`, `evals/run_causrca_benchmark.py`는 계획서에는 있으나 아직 작성되지 않았다.
- 루트의 `.py` 스크립트들과 `reports/` (이하 트랙 Y): `loaders/metal_etch_loader.py`로 Metal Etch 원본 3종(`.mat`)을 실측 검증하며 로드하고, `track_b_engine.py`가 PCA 기반 원인후보 랭킹을 계산하고, `agent.py`/`agent_tools.py`가 AWS Bedrock Claude를 호출해 `reports/`에 사람이 읽을 보고서 5건을 이미 생성해 커밋했다.

두 트랙은 지금까지 파일이 겹치지 않아 git 충돌은 없었지만, 다음 세 지점이 아직 합의되지 않은 상태로 남아 있었다.

1. `PROJECT_GUIDE.md`가 이미 "루트 스크립트는 재사용 전 `backend/app/data/metal_etch_adapter.py`로 옮겨야 한다"고 적어뒀지만 아직 이전되지 않았다.
2. `backend/app/domain.py`에는 이미 `DatasetName.METAL_ETCH`와 `Capability.MULTI_SOURCE_EVIDENCE`가 정의돼 있지만 어떤 코드도 이 값을 실제로 만들어내지 않는다.
3. `IMPLEMENTATION_PLAN.md`는 "LLM 도입은 트랙 B의 baseline report와 트랙 D의 review API가 완료된 후"라는 게이트를 걸어뒀는데, `agent.py`는 이미 이 게이트 이전에 Bedrock Claude를 호출해 최종 보고서를 만들고 있다.

## 결정

### 1. Metal Etch를 공식 `backend/app` 어댑터로 승격한다

ADR-0001의 "Metal Etch는 성능 주장에 쓰지 않는 이식성 시연"이라는 제약은 그대로 유지한다. 다만 지금처럼 별도 루트 스크립트 + 별도 산출물(`reports/`)로 남겨두지 않고, causRCA와 동일한 `Incident`/`Evidence`/`Candidate` 계약을 쓰는 두 번째 데이터셋 어댑터로 편입한다.

- `backend/app/data/metal_etch_adapter.py`: `loaders/metal_etch_loader.py`의 실측 검증 로직(웨이퍼 번호 매칭, 경계 중복행 제거, 그룹별 필드 차이 처리)을 재사용해 `Incident`로 변환하는 순수 함수. `data/runtime/metal_etch/incidents.json`에는 관측 가능한 신호만 쓰고, `fault_names`/`label_value`/`label_reliable`은 `data/evaluation/metal_etch/labels.json`으로 분리한다 (`flag_unreliable_labels.py`가 만든 `label_reliable` 판정도 그대로 이 파일로 옮긴다).
- `scripts/prepare_metal_etch.py`: `scripts/prepare_causrca.py`와 동일한 CLI 패턴(원본 → runtime/evaluation 분리 쓰기).
- `backend/app/analytics/metal_etch_pca.py`: `track_b_engine.py`의 `build_baseline_model()`/`score_entity()` (PCA + contribution score)를 이식. `analytics/causrca.py`의 `rank_with_caus_tr(incident, diagnosis_time, limit=3) -> (candidates, evidence, warnings)`와 동일한 시그니처로 맞춰서 `workflows/investigation.py`에 대칭적인 분기를 추가한다.
- `docs/DATA_CONTRACT.md`, `docs/ARCHITECTURE.md`는 이 어댑터가 추가된 뒤 실제 경로·capability를 반영해 갱신한다.

이 작업이 끝나기 전까지 루트 스크립트(`loaders/`, `preprocess.py`, `track_b_engine.py`, `agent.py` 등)는 참고용 프로토타입으로 남는다. 지우지 않는다 — 검증된 로직의 출처이자, 이식이 끝났다는 걸 보여주는 대조 자료로 유지한다.

### 2. LLM 내러티브 도입을 조건부로 앞당긴다

`agent.py`는 이미 M4 완료 기준(장비 제어 도구 없음, 근거 없는 값 지어내지 않음, "AI 초안 - 검토 필요" 고정 문구, 도구 결과만 정리)을 거의 만족한다. 이 자산을 버리지 않고, 다음 완화 조치를 선행 조건으로 걸어 정식 워크플로우 안으로 편입한다.

- `evidence_check` 노드를 LLM 노드보다 먼저 워크플로우에 추가한다. 근거 없는 후보는 `Candidate.status = "inconclusive"`로 강제한다 (스키마의 `evidence_ids` `min_length=1` 제약과 결합해 이중 방어).
- `InvestigationResult.mode`를 `Literal["deterministic"]`에서 `Literal["deterministic", "deterministic_with_llm_narrative"]`로 확장한다. LLM은 숫자·랭킹·후보 순서를 바꾸지 않고 `llm_narrative: str | None` 필드만 추가한다.
- API에는 `include_llm_narrative: bool = False` 옵션을 추가한다. 기본값은 항상 `False` — LLM 없이도 결정론적 모드가 완전히 동작한다는 M3 요구사항을 API 계약 레벨에서 보장한다.
- LLM 호출 여부, 모델, latency, token 사용량은 `TraceEvent`에 기록한다. 비밀키·정답 라벨은 기록하지 않는다.
- `agent.py`/`agent_tools.py`의 로직은 `backend/app/llm/explainer.py`와 `backend/app/llm/bedrock_client.py`로 이식한다.

## 이유

- `DatasetName.METAL_ETCH`, `Capability.MULTI_SOURCE_EVIDENCE`가 이미 코드에 정의돼 있다는 것은, 트랙 X 설계가 애초에 이 확장을 배제하지 않았다는 뜻이다. 이번 결정은 새 방향을 추가하는 게 아니라 이미 비워둔 자리를 채우는 것이다.
- 두 트랙을 하나로 합치지 않고 방치하면, "성능 주장은 causRCA로, 데모는 Metal Etch로"라는 ADR-0001의 구분이 실제 코드 구조에는 반영되지 않은 채 남는다. `reports/`가 이미 존재하는 상태에서 이걸 방치하면 발표 시점에 "이미 만든 것"과 "공식 아키텍처"가 따로 보이는 위험이 있다.
- LLM 게이트를 무조건 지키면 이미 동작하는 에이전트 자산을 활용하지 못한다. 반대로 게이트를 무시하면 신뢰성 원칙이 깨진다. `evidence_check` 선행 + 결정론적 모드 기본값 유지 + 근거·수치 불변이라는 세 가지 완화 조치로 두 요구를 동시에 만족시킨다.

## 결과

- ADR-0001의 결정(causRCA만 성능 지표에 사용, Metal Etch는 성능 주장 금지)은 변경하지 않는다.
- `data/runtime/`과 `data/evaluation/`의 격리 규칙, `FORBIDDEN_RUNTIME_KEYS` 검사는 Metal Etch 어댑터에도 동일하게 적용한다. 예외를 두지 않는다.
- `docs/WORKLOG.md`에 트랙 Y(Metal Etch 데모) 작업을 소급 기록한다 — 지금까지 이 작업은 공식 로그에 전혀 반영되지 않았다.
- `IMPLEMENTATION_PLAN.md`의 M4/M5 순서와 완료 기준은 이 ADR의 완화 조치를 반영해 갱신한다.
- 이 통합이 끝나면 루트 스크립트는 정식 소스가 아닌 참고 자료로 유지하되, `backend/app`이 유일한 서비스 진입점이 된다.
