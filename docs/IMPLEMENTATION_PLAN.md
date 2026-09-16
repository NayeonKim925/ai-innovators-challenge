# 구현 계획서 · 제조 이상 조사 서비스

> 문서 상태: `실행 기준안` · 마지막 갱신: 2026-09-11  
> 대상: 팀원, 구현 에이전트, 발표·평가 담당자

## 1. 이번 MVP가 완성해야 하는 것

### 한 문장 정의

제조 공정 이상 사건에서 관측 데이터를 분석하고, 근거가 연결된 원인 후보를 제시하며, 현장·공정·데이터 담당자가 검토한 판단 이력을 남기는 **Human-in-the-loop 조사 서비스**를 만든다.

### MVP 사용자 흐름

```text
사건 선택
  → 진단 시점 지정
  → 결정론적 RCA 도구 실행
  → 후보별 관측 근거 확인
  → AI가 제한된 조사 초안 정리
  → 전문가가 승인·거절·수정
  → 보고서와 감사 이력 저장
```

### 이번 MVP에서 보여줄 가치

| 평가 관점 | 서비스에서 보여줄 증거 |
| --- | --- |
| 데이터 활용 | 출처·라이선스·전처리·runtime/evaluation 분리·정합성 검사 |
| 기술성 | FastAPI, LangGraph, 결정론적 RCA 도구, 구조화 API, 테스트 |
| 에이전틱 설계 | 도구 선택, 근거 조립, 판단 보류, 사람 검토 전송의 상태 기반 워크플로우 |
| 서비스성 | 역할별 조사 화면, 근거 단위 검토, 보고서·이력 |
| 신뢰성 | 정답 누출 차단, 근거 없는 주장 방지, benchmark, 실패 사례 공개 |

### 하지 않는 일

- 모든 제조 데이터셋을 즉시 지원하는 범용 분석 플랫폼
- LLM이 수치 분석·원인 점수를 임의로 만들어내는 구조
- 장비 자동 제어, 정비 지시, 실제 공장 운영 준비 완료 주장
- PHM·SECOM·WM-811K의 별도 문제를 이번 MVP에 억지로 포함

## 2. 데이터셋과 검증 전략

| 구분 | 데이터셋 | 역할 | 산출물 | 성능 주장 가능 여부 |
| --- | --- | --- | --- | --- |
| 핵심 | causRCA | 원인 후보 benchmark와 에이전트 도구 연동 | 100개 HIL 사건, CausTR 결과, Hit@k·MRR·MAP@3 | 가능 |
| 보조 | Metal Etch | 반도체 다중 센서 데이터 이식성 시연 | MACHINE/OES/RFM 사건 어댑터, 근거 화면 | 제한적 |
| 보류 | PHM·SECOM·WM-811K | 후속 확장 후보 | capability 설계 문서만 유지 | 불가 |

### 절대 지킬 데이터 경계

```text
data/raw/          원본 데이터. 준비 스크립트만 접근
data/runtime/      조사 시점에 관측 가능한 사건·센서값. 서비스와 LLM 접근 가능
data/evaluation/   원인 정답·진단 시점·split. 평가 코드만 접근 가능
data/processed/    재생성 가능한 중간 산출물. 서비스에는 명시적으로 export한 것만 전달
```

`root_cause`, `ground_truth`, `label_value`, `manipulated_variable`, `diagnosis_time`, `fault_name`, `split`은 runtime에 들어오면 안 된다. 자세한 규칙은 [DATA_CONTRACT.md](DATA_CONTRACT.md)를 단일 기준으로 사용한다.

## 3. 현재 상태와 우선순위

### 2026-09-16 배포 기준 현황

| 단계 | 상태 | 근거 |
| --- | --- | --- |
| M0 데이터 준비 | 완료 | `data/runtime/causrca/incidents.json`에 100개 HIL 사건, `data/evaluation/causrca/cases.json`에 정답 분리 |
| M1 benchmark | 기준선 완료 | time-recency 100건 실행: 실패 0, Hit@1 0.39, Hit@3 0.60, MRR 0.4833, MAP@3 0.3197 |
| M2 API·검토 저장 | 완료 | Lambda/API Gateway, DynamoDB 저장, review/report/chat API |
| M3 조사 UI | Streamlit MVP 완료 | ECS Express 공개 엔드포인트에서 사건 선택→조사→검토→보고서 흐름 확인 |
| M4 선택적 LLM 설명 | 조건부 구현 | Bedrock 설정은 있지만 기본값은 결정론적 모드, 비동기 큐는 권한 부족으로 비활성 |
| M5 Metal Etch 이식성 | 보류 | 어댑터 코드는 있으나 발표용 이식성 시나리오와 별도 검증이 남음 |

현재 공개 프론트는 React 완성본이 아니라 M3의 Streamlit 운영 UI다. 따라서 다음 고도화의 우선순위는 Streamlit에 기능을 계속 덧붙이는 것이 아니라, 이미 고정한 API 계약을 사용해 React 조사 UI를 구현하고 동일한 사건→근거→검토 흐름을 옮기는 것이다.

### 이미 구현됨

- 공통 사건·근거·후보·실행 이력 계약: `backend/app/domain.py`
- runtime 데이터의 정답 필드 거부: `backend/app/data/runtime_repository.py`
- FastAPI 기본 API: `backend/app/main.py`
- LangGraph 조사 흐름: `backend/app/workflows/investigation.py`
- 기준선 분석과 causRCA CausTR 선택적 어댑터: `backend/app/analytics/`
- causRCA runtime/evaluation 분리 준비 스크립트: `scripts/prepare_causrca.py`
- 초기 API·워크플로우·누출·지표 테스트: `backend/tests/`

### 다음 구현 순서

```text
M0 재현 가능한 데이터 준비
  ↓
M1 causRCA 결정론적 benchmark
  ↓
M2 조사 결과·전문가 검토 저장 API
  ↓
M3 React 조사 UI
  ↓
M4 근거 검증을 통과한 선택적 LLM 설명
  ↓
M5 Metal Etch 어댑터와 발표용 이식성 시연
```

M0~M1이 끝나기 전에는 LLM 기능이나 화려한 UI를 우선하지 않는다. 성능·근거·데이터 경계가 없는 UI는 대회에서 방어하기 어렵다.

## 4. 트랙별 작업 계획

팀 인원에 맞춰 한 사람이 여러 트랙을 맡아도 된다. 다만 같은 파일을 동시에 수정하지 않도록 아래 소유 범위를 지킨다.

### 트랙 A · 데이터 엔지니어링 및 재현성

**목적:** 누구나 같은 데이터 준비 결과를 얻고, 서비스가 정답을 보지 못하도록 보장한다.

| 작업 | 파일 | 완료 기준 |
| --- | --- | --- |
| causRCA 원본 다운로드·버전·라이선스·SHA256 manifest 작성 | `data/manifests/causrca.json`, `scripts/bootstrap_causrca.py` | 새 환경에서 고정 버전 다운로드와 해시 검증 성공 |
| runtime/evaluation 분리 준비 스크립트 강화 | `scripts/prepare_causrca.py` | 100 HIL 사건·170 정상 기록 검증, runtime에 금지 필드 0개 |
| 데이터 검증 CLI 작성 | `scripts/validate_data.py` | 파일 수·CSV 스키마·시간 정렬·경로 탈출·금지 필드 검사 |
| Metal Etch 레거시 이전 설계 | `backend/app/data/metal_etch_adapter.py`, `scripts/prepare_metal_etch.py` | MACHINE/OES/RFM을 하나의 사건으로 표현, 라벨은 evaluation 분리 |
| Git 추적 정리 | `.gitignore`, `data/README.md` | 원본 `.mat`, 생성 `.npy`, DB, 캐시가 새로 추적되지 않음 |

**주의:** 기존 `MACHINE_Data.mat`, `processed/`는 다운로드·재생성 경로가 마련된 뒤에만 Git 추적을 해제한다.

### 트랙 B · 분석 엔진과 정량 평가

**목적:** “AI가 그럴듯하게 말했다”가 아니라, 모든 사건에서 재현 가능한 후보 순위 성능을 만든다.

| 작업 | 파일 | 완료 기준 |
| --- | --- | --- |
| CausTR와 시간 최근순 기준선 실행 래퍼 정리 | `backend/app/analytics/causrca.py` | 입력은 runtime 관측값과 graph만 사용, 평가 파일 import 0건 |
| benchmark 실행 CLI | `evals/run_causrca_benchmark.py` | 100개 사례 전체 실행, 실패도 분모에 포함 |
| metric 집계·케이스별 리포트 | `evals/metrics.py`, `data/evaluation/reports/` | Hit@1·Hit@3·MRR·MAP@3, subsystem별 결과, 실패 목록 생성 |
| 기준선·CausTR·전체 워크플로우 비교 | `evals/ablation.py` | 비교 정의와 같은 입력 cutoff를 사용한 JSON 보고서 생성 |
| 실패 사례 분석 | `docs/research/FAILURE_ANALYSIS.md` | 최소 5개 실패 사례의 입력·후보·한계·개선 가설 기록 |

**지표 정의:** 현 Metal Etch 코드의 `precision@k` 표현은 사용하지 않는다. “상위 k개 안에 정답이 하나라도 있는가”는 Hit@k로 명명한다.

### 트랙 C · 에이전틱 워크플로우와 신뢰성

**목적:** LLM이 분석을 대체하지 않고, 검증 가능한 도구와 사람의 판단을 연결한다.

| 작업 | 파일 | 완료 기준 |
| --- | --- | --- |
| LangGraph state 확장 | `backend/app/workflows/investigation.py`, `backend/app/workflows/state.py` | 각 노드 입력·출력·실행 이력이 Pydantic 계약으로 검증됨 |
| 근거 충분성 검증 노드 | `backend/app/workflows/evidence_check.py` | 근거 없는 후보는 `inconclusive`, 인용 ID가 없는 후보 0개 |
| LLM provider 추상화 | `backend/app/llm/` | OpenAI/Gemini 호출은 환경 변수 기반, API 키가 브라우저·로그에 없음 |
| 구조화 설명 생성 | `backend/app/llm/explainer.py` | 후보·근거·다음 확인 항목만 설명, 수치·원인 확정 문장 금지 |
| 폴백 정책 | `backend/app/workflows/investigation.py` | API 키·문서·도구가 없으면 결정론적 모드와 한계를 명시 |

**LLM 도입 게이트:** 트랙 B의 baseline report와 트랙 D의 review API가 완료된 후 시작한다.

### 트랙 D · 백엔드 API·저장·감사 이력

**목적:** 조사 결과와 전문가 판단을 재현 가능하게 저장한다.

| 작업 | 파일 | 완료 기준 |
| --- | --- | --- |
| DB 모델과 마이그레이션 도입 | `backend/app/db/`, `alembic/` | 로컬 SQLite와 배포용 PostgreSQL에서 동일 migration 실행 |
| 조사 run 저장 | `backend/app/repositories/investigations.py` | 요청·tool trace·후보·근거·경고·모드가 저장됨 |
| 검토 API | `backend/app/api/reviews.py` | approve/reject/correct, 수정에는 사유 필수, 동일 run 재검토 충돌 처리 |
| 보고서 export | `backend/app/services/reporting.py` | Markdown 보고서에 근거·검토 상태·한계가 포함됨 |
| 관측 로그 | `backend/app/observability/` | run ID, 단계, latency, provider·token 사용량만 기록하고 비밀·정답은 기록하지 않음 |

**목표 API:**

```text
GET  /api/health
GET  /api/datasets
GET  /api/incidents
GET  /api/incidents/{incident_id}
POST /api/incidents/{incident_id}/investigations
GET  /api/investigations/{investigation_id}
POST /api/investigations/{investigation_id}/reviews
GET  /api/investigations/{investigation_id}/report
```

### 트랙 E · React 조사 UI

**목적:** 분석 결과가 아니라 “근거를 보고 사람이 결정하는 경험”을 보여준다.

| 화면/기능 | 파일·영역 | 완료 기준 |
| --- | --- | --- |
| 사건 목록 | `frontend/src/features/incidents/` | 데이터셋·상태·시간 범위를 보고 사건 선택 가능 |
| 조사 화면 | `frontend/src/features/investigation/` | cutoff 지정, 실행 상태, 후보·근거·경고·trace 표시 |
| 근거 패널 | `frontend/src/features/evidence/` | 후보에서 근거로 이동, 신호·시점·출처가 보임 |
| 전문가 검토 | `frontend/src/features/review/` | 승인·거절·수정 사유 입력, 완료 후 상태 갱신 |
| 보고서 화면 | `frontend/src/features/report/` | 조사 결과를 Markdown으로 다운로드 |

**UI 원칙:** 채팅창은 보조 인터페이스다. 메인 화면은 `사건 → 신호 → 후보 → 근거 → 검토` 흐름이어야 한다. 로딩·실패·빈 상태·모바일 폭·키보드 접근성을 구현한다.

### 트랙 F · 품질·배포·발표 증거

**목적:** “로컬에서 한 번 실행됨”을 넘어 재현성과 시연 신뢰도를 확보한다.

| 작업 | 파일 | 완료 기준 |
| --- | --- | --- |
| CI | `.github/workflows/ci.yml` | lint, typecheck, backend test, frontend build 자동 실행 |
| 컨테이너화 | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` | 새 환경에서 한 명령으로 로컬 실행 |
| 배포 후보 검증 | `docs/DEPLOYMENT.md` | AWS App Runner 또는 ECS/Fargate 중 하나를 선택한 근거·비용·한계 기록 |
| 서비스 품질 평가 | `docs/USER_TEST_PLAN.md` | 최소 5명 대상 task completion·이해도·시간 측정 계획 |
| 발표 근거 패키지 | `docs/presentation/` | 문제 근거, 데이터 출처, architecture, benchmark, 데모 시나리오, 한계 슬라이드 근거 정리 |

## 5. 역할 배정 템플릿

실제 이름은 팀 회의에서 채운다. 한 사람이 여러 칸을 맡을 경우 우선순위는 A → B → D → E → C → F다.

| 역할 | 주 소유 트랙 | 보조 트랙 | PR에서 반드시 확인할 것 |
| --- | --- | --- | --- |
| 데이터·분석 담당 | A, B | F | 출처·라이선스·split·지표·누출 검사 |
| 백엔드 담당 | D | C | API 계약·오류 처리·DB migration·감사 이력 |
| 에이전트/LLM 담당 | C | D | tool boundary·근거 검증·비용·폴백 |
| 프론트엔드 담당 | E | D | API 상태·근거 가시성·접근성·빈 상태 |
| PM·발표·QA 담당 | F | A, B | 문제 근거·데모 스토리·성능 주장 근거·회귀 테스트 |

## 6. 마일스톤별 Definition of Done

### M0 · 데이터 준비 완료

- [ ] `python scripts/bootstrap_causrca.py`로 고정 버전 원본을 확보한다.
- [ ] `python scripts/prepare_causrca.py ...`가 100 HIL·170 정상 기록을 검증한다.
- [ ] `python scripts/validate_data.py`가 runtime 금지 필드 0개를 보장한다.
- [ ] 데이터 manifest에 URL, 라이선스, 버전, SHA256, 생성 날짜가 있다.

### M1 · benchmark 완료

- [ ] CausTR와 시간 최근순 기준선을 100개 사례 전부에서 실행한다.
- [ ] 실패 사례도 점수 분모에서 제외하지 않는다.
- [ ] JSON 결과에 Hit@1, Hit@3, MRR, MAP@3와 케이스별 순위가 있다.
- [ ] 서비스 runtime 코드가 `data/evaluation/`을 import하지 않는 테스트가 있다.

### M2 · 검토 가능한 API 완료

- [ ] 조사 실행 결과가 DB에 저장된다.
- [ ] 후보마다 최소 하나의 근거 ID가 있다.
- [ ] 사용자는 승인·거절·수정할 수 있고 수정에는 사유가 필요하다.
- [ ] 보고서가 결과·근거·경고·검토 상태를 포함한다.

### M3 · 데모 UI 완료

- [ ] 사건 선택부터 보고서 다운로드까지 브라우저에서 완료한다.
- [ ] 원인 후보를 클릭하면 해당 근거·시점·출처가 표시된다.
- [ ] LLM 미설정 상태도 결정론적 모드로 정상 시연된다.
- [ ] 로딩·오류·빈 데이터 상태를 별도로 처리한다.

### M4 · LLM 품질 게이트 통과

> ADR-0002에 따라 evidence_check 선행, 결정론적 모드 기본 유지, 수치 불변을 완화 조치로 두고 M5보다 먼저 조건부로 시작할 수 있다. 아래 기준은 그대로 유지한다.

- [ ] `evidence_check` 노드가 LLM 노드보다 먼저 실행되고, 근거 없는 후보는 `inconclusive`로 처리된다.
- [ ] LLM은 도구 결과와 승인된 문서 근거만 입력으로 사용하고, 후보 순위·수치를 변경하지 않는다.
- [ ] 근거 없는 문장은 제거 또는 판단 보류된다.
- [ ] LLM 사용 여부·모델·token·latency가 trace에 남는다.
- [ ] `include_llm_narrative` 기본값이 `False`이며, LLM 없는 결과와 있는 결과를 API·발표에서 구분한다.

### M5 · 이식성·발표 완료

- [ ] Metal Etch 어댑터(`backend/app/data/metal_etch_adapter.py`)가 동일 사건 계약을 생성한다.
- [ ] `backend/app/analytics/metal_etch_pca.py`가 causRCA 분기와 대칭적인 시그니처로 `investigation.py`에 연결된다.
- [ ] causRCA 성능과 Metal Etch 시연 결과를 섞지 않는다 (ADR-0001 유지).
- [ ] 데모는 데이터 준비 실패 없이 재현된다.
- [ ] 문제 정의, benchmark, 실패 사례, 한계가 발표 자료에 포함된다.
- [ ] 루트 스크립트(`loaders/`, `track_b_engine.py`, `agent.py` 등)에서 이식된 로직은 `backend/app` 안에서 동일하게 재현되고, 루트 스크립트는 참고 자료로만 남는다.

## 7. 공동 작업 규칙

1. 작업 시작 전 `AGENTS.md`, 관련 `docs/` 문서, 대상 모듈의 테스트를 읽는다.
2. 한 PR은 한 트랙의 한 단위만 변경한다. 데이터 준비와 UI 변경을 한 PR에 섞지 않는다.
3. API 계약을 바꾸면 백엔드·프론트엔드·테스트·문서를 같은 PR에서 갱신한다.
4. 데이터 형식 변경 시 `docs/DATA_CONTRACT.md`와 manifest를 함께 갱신한다.
5. 평가 결과가 바뀌면 코드 버전·데이터 해시·실행 명령을 결과 파일에 기록한다.
6. 외부 LLM 키, 원본 데이터, 캐시, 로컬 DB는 커밋하지 않는다.
7. “원인이다”, “정확하다”, “현장 적용 가능하다” 같은 표현은 benchmark와 근거가 있을 때만 사용한다.

## 8. 리스크와 대응

| 리스크 | 영향 | 대응 |
| --- | --- | --- |
| causRCA upstream 의존성이 실행되지 않음 | 핵심 benchmark 지연 | 시간 최근순 기준선 유지, upstream commit·환경을 고정, 실패도 보고 |
| LLM 설명이 근거를 넘어섬 | 신뢰성 하락 | 구조화 출력, evidence check, 판단 보류, LLM 없는 모드 유지 |
| Metal Etch 라벨을 정확한 RCA 정답처럼 사용 | 성능 주장 왜곡 | headline metric은 causRCA만 사용, Metal Etch는 이식성 시연으로 한정 |
| UI를 먼저 만들어 데이터·평가가 비어 있음 | 데모만 그럴듯해짐 | M0~M1 완료를 UI 본격 개발의 선행 조건으로 둠 |
| 여러 사람이 동일 파일을 수정 | 충돌·설계 불일치 | 트랙별 소유 영역, 작은 PR, API 계약 문서 단일 기준 |
| AWS 배포가 개발 시간을 과점유 | 핵심 기능 미완성 | 로컬 재현·benchmark·시연 안정화 후 배포, AWS는 마지막 트랙 |

## 9. 발표용 데모 시나리오

1. causRCA 사건 하나를 선택한다.
2. 진단 cutoff 이전의 관측값만 서비스에 전달됨을 보여준다.
3. CausTR 또는 명시된 기준선이 후보와 근거를 생성한다.
4. 후보별 신호·시점·그래프/도구 출처를 확인한다.
5. 전문가는 승인 또는 수정 사유를 남긴다.
6. 보고서에서 AI의 한계와 사람이 최종 판단한 사실을 확인한다.
7. benchmark 화면에서 모든 100개 사례의 정량 결과와 실패 사례를 보여준다.
8. Metal Etch 어댑터 화면으로 전환해 동일 사건 계약이 다른 제조 데이터 구조에도 적용됨을 시연한다.

## 10. 첫 팀 회의에서 확정할 항목

- 트랙별 담당자와 리뷰어
- 대회 마감일 기준 M0~M5의 실제 날짜
- causRCA 원본·upstream을 팀이 공유할 안전한 저장 위치
- UI를 담당할 사람과 디자인 결정 방식
- 행사 제공 LLM API의 provider, 모델, 예상 token budget
- AWS 배포를 평가 전 데모에 포함할지와 책임자

이 항목들이 정해지면 `docs/WORKLOG.md`에 담당자·시작일·PR 링크·blocker를 기록하며 진행한다.
