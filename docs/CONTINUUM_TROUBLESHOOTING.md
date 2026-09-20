# Continuum 구현 검토·트러블슈팅·후속 계획

> 기준일: 2026-09-19
> 범위: F0~F4 변경과 현재 로컬 검증 결과

## 1. 이번 검토에서 확인한 즉시 오류

### 수정 완료

1. **프론트 TypeScript 파싱 오류**
   - `frontend/src/api.ts`에서 `ExpertResponseOutcome`과 `ExpertTaskResponse` 선언이 끊겨 `outcome` 필드만 파일 본문에 남아 있었다.
   - 타입 선언을 복원하고 `EvidenceTask.open_item_id`, `HandoverSnapshot.payload`, 선택적 `expected_version` 타입을 추가했다.

2. **Open Item 종료 게이트 우회**
   - 기존에는 `READY_FOR_REVIEW` Case에 새 미해결 Open Item을 추가한 뒤에도 최종 승인으로 닫을 수 있었다.
   - 이제 최종 review 전에 모든 Open Item이 `resolved`인지 검사한다. `resolved` 전환에는 완료 메모 또는 연결된 관찰이 필요하다.

3. **Open Item·Hypothesis 근거 참조 검증 누락**
   - `E999` 같은 존재하지 않는 Evidence ID를 저장할 수 있었다.
   - 현재 AnalysisRun에 저장된 InvestigationResult의 Evidence namespace를 기준으로 검증하고, Handover linter도 invalid reference를 blocking finding으로 판정한다.

4. **Handover Snapshot version 비대칭**
   - Snapshot은 이전 Case version, Handover는 발행 후 version을 기록해 서로 다른 상태를 가리켰다.
   - Snapshot과 Handover가 모두 인계 대상인 발행 전 Case version을 가리키도록 맞췄다. 발행 이벤트 때문에 현재 Case version은 하나 증가하며, accept는 `handover.source_case_version + 1`인 경우에만 허용한다. 발행 후 추가 변경은 stale로 supersede한다.
   - Snapshot에는 ID 목록뿐 아니라 Run·Hypothesis·Open Item·Observation의 canonical payload와 hash를 함께 저장한다.

5. **Metal Etch가 PCA 실패 후 causRCA식 recency fallback으로 바뀌는 문제**
   - Metal Etch PCA baseline/dependency가 없을 때 `active_alarm_recency_baseline`으로 조용히 바뀌어 데이터셋별 분석 경계가 흐려졌다.
   - 이제 Metal Etch는 PCA 결과가 없으면 경고와 판단 보류를 유지하고, recency fallback은 causRCA 경로에만 적용한다.

## 2. 검증 결과

- Continuum Case·workflow 테스트: 통과
- 전체 Python 테스트 중 선택적 PCA 테스트 제외: **55 passed**
- 프론트 Node proxy/presentation/brand 테스트: **12 passed**
- 변경된 백엔드 파일의 ruff 검사: 통과 후 Snapshot 수정분을 재검사 중
- `git diff --check`: 통과
- 전체 ruff: 기존 루트 탐색 스크립트·AWS 실험·일부 analytics 파일을 포함해 약 110개 기존 오류가 있어 실패. 이번 Continuum 변경과 분리해야 한다.
- 전체 Metal Etch PCA 테스트: 현재 실행 환경에서 numpy/scikit-learn 선택 의존성이 준비되지 않아 baseline 후보 생성 테스트를 완료하지 못했다. Python 3.14 환경에서 선택 의존성 import 실행도 안정적으로 완료되지 않았으므로, 지원 Python 버전을 고정한 별도 환경에서 재검증해야 한다.
- React `npm run build`: 기존 `node_modules`에 `tsc`가 없었고 `npm ci`는 로컬 npm cache 권한/설치 환경에서 완료되지 않았다. 타입 선언 오류는 수정했지만 실제 build 성공은 아직 확인하지 못했다.
- AWS DynamoDB 영속성·실제 인증/권한·Playwright E2E: 실행하지 않았다.

## 3. 리뷰에서 남은 P1 리스크

1. **actor 인증**: `author`, `sender`, `accepted_by`, `reviewer`, `created_by`가 bearer token의 실제 사용자·역할과 연결되지 않는다. `exception_reason`으로 누구나 linter blocking을 우회할 수 있다.
2. **legacy write version 정책**: 기존 task response/review의 `expected_version`은 하위 호환을 위해 optional이다. Continuum 전용 mutation은 필수로 유지하고, legacy endpoint 완화 정책을 별도 ADR로 정해야 한다.
3. **AnalysisRun 고아 저장**: 새 Run의 InvestigationResult를 먼저 저장한 뒤 Case CAS가 실패하면 연결되지 않은 결과가 남을 수 있다. repository transaction 또는 보상 삭제/idempotency가 필요하다.
4. **lint 실행 이력**: 현재 일반 `handover-checks`는 결과만 반환하고 CaseEvent를 저장하지 않는다. 도구 호출 이력 완결성을 위해 lint 실행 event 또는 immutable lint result를 저장해야 한다.
5. **Snapshot/Resume 역사성**: Snapshot payload는 고정했지만 Resume 기본 응답은 현재 aggregate도 함께 읽는다. 수신자가 발행 당시 상태와 현재 변경을 구분하는 Delta 응답이 필요하다.
6. **DynamoDB aggregate 크기**: Case 전체 JSON에 Run·Observation·Open Item·Snapshot을 계속 누적하면 400KB 제한과 쓰기 충돌 위험이 있다. Event/Snapshot 분리와 GSI를 계측 후 결정해야 한다.

## 4. 이어서 개발할 순서

### T0. 실행 환경·프론트 build 복구

1. 프로젝트가 지원할 Python 버전을 3.12 또는 검증된 버전으로 고정한다.
2. `frontend/npm ci`가 깨끗한 npm cache에서 완료되는지 확인하고 `npm run build`를 실행한다.
3. `npm test`, backend targeted test, `git diff --check`를 release gate로 고정한다.
4. build가 통과하기 전에는 UI 기능을 더 추가하지 않는다.

### T1. 선택적 Metal Etch 의존성·분기 검증

1. `metal-etch` extra의 numpy/scipy/scikit-learn 버전을 지원 Python에서 설치한다.
2. `test_metal_etch_pca.py` baseline 생성 테스트를 통과시킨다.
3. baseline 미준비·dependency 미준비·관측 cutoff 이전 데이터 없음의 세 가지 결과가 모두 판단 보류와 명시 경고를 반환하는지 확인한다.
4. causRCA와 Metal Etch의 후보 순위·평가 결과를 섞지 않는다.

### T2. 서버 불변식 강화

1. 인증 middleware에서 actor context를 주입하고, actor 문자열 body를 표시용 보조 필드로 낮춘다.
2. exception으로 linter를 우회할 수 있는 역할과 audit event를 정의한다.
3. legacy task/review 외 Continuum write에서 `expected_version`을 필수화하고, 409 응답에 current version·재조회 경로를 포함한다.
4. Evidence ID와 Observation ID를 모든 mutation에서 namespace별로 검증한다.
5. AnalysisRun 저장의 idempotency key와 CAS 실패 보상 전략을 추가한다.

### T3. Handover/Resume 완성

1. `handover-checks` 실행 결과를 actor·시각·Case version·finding hash가 있는 immutable event로 남긴다.
2. `published Snapshot`과 현재 Case의 차이를 `Delta`로 계산해 Resume에 `발행 당시 / 인계 후 변경 / 현재 남은 항목`을 분리한다.
3. Snapshot hash 재계산·payload referential integrity·stale acceptance 회귀 테스트를 추가한다.
4. 미확인 Open Item 전달은 허용하되 담당 공백·현재 상태 누락·무효 참조만 blocking하는 규칙을 현장 설정과 분리한다.

### T4. DynamoDB·동시성 검증

1. legacy Case JSON reader와 v2 round-trip fixture를 추가한다.
2. 두 worker가 같은 version으로 관찰·인계·수락을 동시에 쓰는 테스트를 만든다.
3. Case item 크기와 Snapshot/Event 누적량을 계측한다.
4. 400KB 한계 전에 aggregate 유지와 append-only table 분리 중 하나를 ADR로 결정한다.
5. 실제 AWS에서 table restart/persistence/conditional update를 실행 로그와 함께 검증한다.

### T5. 사용자 흐름 E2E·release gate

Playwright에서 다음 한 경로를 고정한다.

1. Shift A가 Case를 연다.
2. 결정론적 Run의 후보·근거를 확인한다.
3. 관찰 원문과 미확인 Open Item을 기록하고 담당자를 지정한다.
4. Handover linter를 실행하고 Packet을 발행한다.
5. Shift B가 Resume에서 Snapshot·Open Item·제약을 확인한다.
6. 변경이 발생하면 이전 Snapshot 수락이 차단된다.
7. 새 관찰 이후 동일 Case에 R2를 추가하고 R1이 보존되는지 확인한다.
8. 인수 수락 후에도 Case가 자동 종료되지 않음을 확인한다.

### T6. CI·문서 정리

1. 전체 ruff 기준선을 이번 변경과 무관한 legacy 스크립트까지 한 번에 고치지 말고, release 경로와 `backend/app`·`frontend/src`를 분리한다.
2. CI에 backend targeted test, runtime 누출 검사, proxy test, TypeScript build, E2E를 순서대로 추가한다.
3. AWS 실검증 전에는 README·발표 문서에 운영 완료라고 쓰지 않는다.
4. Time-to-Context, Open Item 누락률, citation/state accuracy를 causRCA Hit@k와 별도 지표로 기록한다.

## 5. 후속 실행 기록 · 2026-09-19

- T0: Python 3.12 전용 `.venv312`에서 backend 의존성과 Metal Etch 선택 의존성을 설치했다. `tsc --noEmit`은 통과했고 Vite `dist/index.html` 및 hashed asset 생성도 확인했다.
- T1: `test_metal_etch_pca.py` 5개, API 10개, Case 14개, workflow 5개를 Python 3.12 환경에서 통과시켰다.
- T2: `idempotency_key`, CAS 실패 보상 삭제, Evidence 참조 검증, production trusted actor header 요구를 추가했다.
- T3: handover lint 실행 Event, Snapshot canonical payload, Resume `handover_delta`를 추가했다.
- T4: legacy Dynamo JSON projection, stale write 충돌 테스트, idempotency 재시도 테스트를 추가했다.
- T5: runtime fixture에 의존하지 않는 `frontend/e2e/continuum-smoke.spec.ts`를 추가했다. Playwright 실행은 브라우저 다운로드가 완료되지 않고 시스템 Chrome 실행도 현재 환경에서 `node`/프로세스 문제로 종료되어 통과를 주장하지 않는다.

- T6: release-path CI 구성을 준비했지만, 현재 GitHub OAuth 토큰에 `workflow` scope가 없어 `.github/workflows/ci.yml` 업로드가 거부됐다. CI workflow는 로컬 커밋에서 제외했으며, `workflow` 권한이 있는 인증으로 별도 업로드해야 한다.
