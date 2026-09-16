# 제조 이상 조사 서비스

제조 공정에서 발생한 이상을 조사하기 위한 **근거 중심(evidence-first) 연구용 MVP**입니다. 현장 운영자, 공정·설비 전문가, 데이터 분석가가 같은 관측값·원인 후보·검토 이력을 확인할 수 있도록 설계합니다.

이 서비스는 설비를 제어하는 시스템이 아닙니다. 화면의 후보 신호는 조사 우선순위일 뿐, 확정된 물리적 원인이나 정비 지시가 아닙니다.

## 현재 구현 상태

- 런타임 사건, 근거, 후보, 실행 이력의 공통 계약: 구현 완료
- 서비스 입력과 평가 정답 간 데이터 누출 방지: 구현 완료
- FastAPI API와 제한된 LangGraph 조사 워크플로우: 구현 완료
- 활성 알람 최근순 기반의 투명한 기준선: 구현 완료
- causRCA 데이터 준비 및 benchmark 연동: 구현 완료(100개 사건 runtime/evaluation 분리)
- Metal Etch 이식성 어댑터: 다음 단계
- 전문가 검토 저장: 구현 완료
- 조사 UI: React/TypeScript UI 구현, 실제 API로 조사·검토·질문·보고서 흐름 검증. 기존 Streamlit은 비교·복구용으로 보존

UI 의사결정 원본은 [DESIGN.md](DESIGN.md), 실행 및 프록시 보안 경계는 [프론트 가이드](frontend/README.md), 레퍼런스 선택 근거는 [디자인 리서치](.lazyweb/quick-references/investigation-2026-09-17/report.md)에 있습니다.

## 제품·데이터 결정

MVP는 여러 제조 AI 기능을 나열하지 않고, **제조 이상을 협업으로 조사하는 하나의 워크플로우**에 집중합니다.

- **causRCA**는 원인 정답을 제공하므로 핵심 성능을 검증하는 주 benchmark입니다.
- **Metal Etch**는 구조가 다른 반도체 식각 데이터를 같은 조사 흐름으로 연결하는 이식성 어댑터입니다. causRCA와 데이터를 합치지 않으며, 핵심 원인 순위 성능 주장에도 사용하지 않습니다.
- **PHM, SECOM, WM-811K**는 MVP 기능이 아닌 후속 어댑터 후보입니다.

새 데이터셋이나 모델을 추가하기 전에는 [제품 범위](docs/PRODUCT.md), [데이터 계약](docs/DATA_CONTRACT.md), [평가 계획](docs/EVALUATION.md)을 읽어야 합니다.

팀 분업, 구현 순서, 파일별 완료 기준은 [구현 계획서](docs/IMPLEMENTATION_PLAN.md)를 기준으로 관리합니다.

## 로컬 실행

Python 3.10 이상이 필요합니다.

```sh
python -m pip install -e '.[dev]'
make test
make lint
make api
```

API는 `http://127.0.0.1:8000`, OpenAPI 문서는 `/docs`에서 확인합니다. 준비된 runtime 데이터가 없으면 `/api/datasets`는 `unprepared`를 반환하며, 서비스가 임의의 데모 사건을 만들지 않습니다.

### 조사·검토 UI (React)

API가 실행 중인 상태에서 별도 터미널에서 실행합니다. Node 22.18 이상을 권장합니다.

```sh
cd frontend
npm ci
npm run build
BACKEND_URL=http://127.0.0.1:8000 npm start
```

기본 웹 주소는 `http://localhost:8080`입니다. 브라우저는 같은 출처의 `/api`로 요청하고 Node 게이트웨이가 서버에서만 API 토큰을 붙입니다. 로컬 백엔드 인증을 켰다면 동일한 토큰을 서버 환경변수 `BACKEND_API_TOKEN`으로 설정합니다. `VITE_*` 변수에는 비밀키를 넣지 않습니다.

마지막 관측 시점에 활성 알람이 없다면 후보를 제시하지 않습니다. 화면의 **최근 알람 발생 시점으로 이동**은 관측 데이터의 마지막 `Alarm=True` 시점만 사용하며 평가 정답 시점을 읽지 않습니다. 조사 기록 목록은 이 브라우저에서 실행한 ID만 저장하고, 결과·검토는 API에서 읽습니다. 공유 검증 환경이며 사용자별 인증/권한 분리는 아직 없습니다.

### 기존 Streamlit UI (비교·복구용)

API가 실행 중인 상태에서 별도 터미널에서 실행합니다.

```sh
python -m pip install -e '.[frontend]'
make frontend
```

기본으로 `http://localhost:8000`의 백엔드에 연결합니다. 다른 포트/호스트를 쓰면 `BACKEND_URL` 환경변수로 지정합니다 (예: `$env:BACKEND_URL="http://127.0.0.1:8010"`). 이 앱은 `backend.app`을 import하지 않고 순수 HTTP로만 통신하므로, 배포 시 백엔드와 독립적으로 옮길 수 있습니다. 사건 선택 → cutoff 지정 → 조사 실행 → 후보/근거 확인 → 전문가 승인·거절 기록 → 보고서 확인까지 한 화면에서 이어집니다. 사건 상세는 짧게 캐시하고 관측값은 최근 500건만 미리 보여주므로, 채팅·검토 시 불필요한 대용량 재요청을 줄입니다. 분석 엔진은 전체 관측값을 사용합니다.

## 저장소 구조

```text
backend/app/domain.py      런타임에서 안전하게 쓸 공통 데이터 계약
backend/app/data/          데이터셋별 어댑터와 runtime 전용 저장소
backend/app/analytics/     결정론적 분석 도구
backend/app/workflows/     제한된 LangGraph 오케스트레이션
backend/tests/             API·워크플로우·데이터 누출 방지 테스트
data/                      Git에서 제외되는 raw/runtime/evaluation 영역
docs/                      기획·아키텍처·평가·ADR 문서
scripts/                   재현 가능한 데이터 준비 명령
```

## 데이터 안전성

평가 정답은 절대 `data/runtime/`에 들어가지 않습니다. runtime 저장소는 `root_cause`, `label_value`, `diagnosis_time` 등 정답성 필드를 거부하며, 이 규칙은 테스트로 검증합니다.

새 원본 데이터, 생성 산출물, 로컬 DB, 비밀키는 Git에서 제외됩니다. 기존에 추적된 Metal Etch 자산은 레거시 이전 대상이므로 더 늘리지 않습니다. 재현 가능한 다운로드 스크립트를 만든 뒤에만 Git 추적을 안전하게 해제합니다.

## 기존 Metal Etch 탐색 파일

루트의 Metal Etch 로더와 `processed/` 출력은 새 아키텍처보다 먼저 작성된 데이터 탐색 결과입니다. 현재는 연구 자료로만 보존하며, 서비스 API로 확장하지 않습니다. 재사용 시에는 전용 Metal Etch 어댑터로 이전하고 관측 데이터와 평가 라벨을 분리해야 합니다.
