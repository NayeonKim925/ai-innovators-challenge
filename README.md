# Continuum · 컨티뉴엄

**근무는 끝나도, 조사는 끊기면 안 됩니다.**

Continuum은 **제조 이상 조사·교대 연속성 워크스페이스**입니다. RCA가 제시한 Candidate와 Evidence를 출발점으로, 사람의 관찰·판단·미해결 업무와 분석 이력을 하나의 Case에 축적합니다. 다음 교대는 인계 당시와 현재 상태를 비교하고 같은 사건의 조사를 이어갈 수 있습니다. [브랜드 가이드](docs/BRAND.md)에서 이름·메시지·사용 규칙을 확인할 수 있습니다.

제조 공정에서 발생한 이상을 조사하기 위한 **근거 중심(evidence-first) 연구용 MVP**입니다. 현장 운영자, 공정·설비 전문가, 데이터 분석가가 같은 관측값·원인 후보·검토 이력을 확인할 수 있도록 설계합니다. RCA 모델 자체보다 **RCA 이후 교대 간 조사 연속성**에 제품의 초점을 둡니다.

이 서비스는 설비를 제어하는 시스템이 아닙니다. 화면의 후보 신호는 조사 우선순위일 뿐, 확정된 물리적 원인이나 정비 지시가 아닙니다.

## 현재 구현 상태

- 런타임 사건, 근거, 후보, 실행 이력의 공통 계약: 구현 완료
- 서비스 입력과 평가 정답 간 데이터 누출 방지: 구현 완료
- FastAPI API와 제한된 LangGraph 조사 워크플로우: 구현 완료
- 활성 알람 최근순 기반의 투명한 기준선: 구현 완료
- causRCA 데이터 준비 및 benchmark 연동: 구현 완료(100개 사건 runtime/evaluation 분리)
- Metal Etch 이식성 어댑터: 다음 단계
- 전문가 검토 저장: 구현 완료
- 사건 인박스와 증거 확인·최종 검토 게이트: 기본 흐름 구현 완료(로컬 in-memory, AWS용 DynamoDB 저장소 구현)
- **Case 조사 기록:** OperatorObservation, EvidenceTask, Open Item, Hypothesis Track, Case Q&A 구현
- **교대 인계와 Resume:** Handover Check·Snapshot 발행·수락·변경 요청, Resume API·React UI, At Handover/Current 비교와 `handover_delta` 구현
- **같은 Case의 후속 분석:** 다중 Analysis Run, R2 실행 UI, Run History, 현재 Run 전환, Run 단위 Evidence 참조 `(run_id, evidence_id)` 구현
- **Case 데이터 보호:** `expected_version`을 이용한 변경 충돌 방지, schema v3 및 기존 Case 읽기 호환 처리
- 조사 UI: React/TypeScript UI를 Continuum release path로 사용하고, 기존 Streamlit은 비교·복구용으로 보존
- **Actor Context와 인계 audit:** production에서 `X-Actor-Id`/`X-Actor-Role` 인증 헤더를 요구하고, 예외 발행 가능 역할을 policy로 제한하며 인계 이벤트에 actor·Case version·snapshot ID를 기록
- **Shift Workspace:** 담당자·보기 필터(조치 필요/인수 대기/내 Open Item/최신화 필요) 기준으로 Case를 우선순위 정렬하고, 현재 Run의 RCA 후보를 확인한 뒤 Case 상세로 바로 진입
- **Open Item·Hypothesis 항목별 관리 UI:** Case 상세에서 Open Item의 담당자·상태·보류 사유·완료 메모, Hypothesis의 지지/지지하지 않음/근거 부족/미검토 판단과 이유를 각각 독립적으로 기록
- **Proposal-only Context Structuring:** 교대 메모를 Observation/Open Item/Hypothesis 제안으로 만들고, 작성자 검토·수정·수락 후에만 Case에 반영

**남은 주요 작업:** Shift Workspace의 다중 Case 필터·정렬 UX 고도화, 실제 사내 인증 공급자·조직 scope 연동, Case Q&A의 근거 인용·평가 고도화, Case Memory/RAG, 실시간 설비 데이터 연결, production 수준의 DynamoDB 구조·운영 검증. Case 화면의 정보 우선순위를 업무 흐름(Overview→연속성→해야 할 일→원인 가설→분석 이력→Handover) 중심으로 재배치하는 [UX 개편안](docs/CONTINUUM_UX_REDESIGN_PROPOSAL.md)은 팀 논의 중이며 아직 전체 확정·구현되지 않았습니다. **AI Handover Draft와 AI Shift Brief는 향후 계획**이며 현재 기능이 아닙니다. 현재 진행 중인 단계와 완료 기준은 [다음 개발 계획](docs/NEXT_DEVELOPMENT_PLAN.md)에서, 그 이전 전환 배경은 [전환 계획](docs/CONTINUUM_DEVELOPMENT_PLAN.md)과 [트러블슈팅](docs/CONTINUUM_TROUBLESHOOTING.md)에서 확인합니다.

UI 의사결정 원본은 [DESIGN.md](DESIGN.md), 실행 및 프록시 보안 경계는 [프론트 가이드](frontend/README.md)에 있습니다. 외부 레퍼런스 캡처와 에이전트 작업 상태는 로컬 작업 산출물로 저장소에 포함하지 않습니다.

## Continuum 흐름

```text
Machine/HIL Alarm·Event observations
    → RCA Run R1 (선택한 cutoff까지 분석)
    → Candidate + Evidence (조사 우선순위와 관측 근거)
    → Case
    → Shift A 조사: Observation · Hypothesis · Open Item
    → Handover Snapshot 발행
    → Shift B Resume: At Handover ↔ Current ↔ handover_delta
    → 같은 Case에 Analysis Run R2 추가
    → 이전 Run과 인계 이력을 보존하며 추가 조사
```

RCA Run은 관측 데이터에서 후보와 근거를 계산합니다. 작업자의 확인·관찰·가설 판단과 인계는 별도의 사람 입력 및 Case 기록이며, RCA 결과가 이를 대신 확정하지 않습니다.

- **Case:** 하나의 이상 사건을 여러 교대가 이어서 조사하는 전체 기록
- **Run:** 특정 cutoff까지의 데이터로 실행한 한 번의 RCA 분석
- **Resume:** 다음 교대가 Case의 현재 상태를 이어받는 화면
- **Snapshot:** Handover 발행 당시의 Case 상태
- **`handover_delta`:** Snapshot과 현재 Case의 차이
- **Open Item:** 아직 완료되지 않은 조사 업무

### causRCA 데이터와 데모 기록의 경계

causRCA는 실제 제조 작업자의 Shift A/B 교대 인수인계 기록을 제공하지 않습니다. 현재 데모에서 **causRCA 기반** 데이터는 HIL에서 준비한 Alarm/Event observation과 이를 입력으로 계산한 RCA Candidate, runtime observation에 연결된 Evidence입니다. **Synthetic 또는 사용자 입력** 데이터는 Shift A/B 역할, OperatorObservation, 작업자의 점검 행동, Hypothesis 판단, Open Item 담당자 지정, Handover 행위와 내용입니다. 이런 기록을 causRCA에서 관측된 실제 현장 행동으로 해석해서는 안 됩니다.

## 제품·데이터 결정

MVP는 여러 제조 AI 기능을 나열하지 않고, **제조 이상을 협업으로 조사하는 하나의 워크플로우**에 집중합니다.

- **causRCA**는 평가 영역에 분리된 원인 정답을 제공하므로 핵심 성능을 검증하는 주 benchmark입니다. 서비스 runtime에는 그 정답을 제공하지 않습니다.
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

사건 인박스는 후보를 “확정 원인”으로 바꾸지 않습니다. 전문가의 증거 확인과 명시적인
최종 검토를 거쳐야만 사건을 종료할 수 있습니다. 로컬 연구 모드는 메모리 저장소를 사용하고,
AWS 배포에서는 `CASE_DDB_TABLE`로 별도 DynamoDB 사건 저장소를 활성화합니다.

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
