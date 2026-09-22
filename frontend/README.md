# 제조 이상 조사 웹 프론트엔드

이 디렉터리는 Streamlit 데모 UI와 React/Vite 웹 UI가 함께 놓이는 전환 구간입니다.
기존 `frontend/Dockerfile`은 Streamlit 데모용이고, `frontend/Dockerfile.web`은 React
프로덕션 번들을 서빙하는 Node 런타임용입니다.

## 런타임 구조

- 브라우저는 같은 출처의 `/api/*`로만 요청합니다.
- `server.mjs`가 `/api/*` 요청을 `BACKEND_URL`로 프록시합니다.
- `BACKEND_API_TOKEN`은 Node 서버에서만 백엔드 호출에 붙습니다. React 번들 또는 브라우저
  응답에 노출되지 않습니다.
- 이 토큰은 서버와 백엔드 사이의 공유 자격증명입니다. 사용자별 로그인이나 권한 분리를
  제공하는 인증 시스템은 아닙니다.
- `/_stcore/health`와 `/healthz`는 ECS Express Mode/로컬 헬스체크용으로 200을 반환합니다.

## 로컬 실행

Node 22.18 이상에서 아래처럼 실행합니다. 로컬 API도 먼저 실행해야 합니다.

```bash
cd frontend
npm ci
npm run build
BACKEND_URL=http://127.0.0.1:8000 node server.mjs
```

개발 중 Vite dev server를 쓰더라도 실제 배포 경계는 `server.mjs`입니다. API 토큰을
브라우저 환경 변수로 넣지 말고, 항상 서버 환경 변수로만 전달합니다.

## 테스트

```bash
cd frontend
npm test
npm run build
```

테스트는 정적 SPA 서빙, 헬스체크, `/api/*` 프록시, POST Origin 검사, 64KB body 제한,
토큰 비노출, 경로 이탈 방지를 검증합니다.

브라우저 E2E를 실행할 때 로컬 Chromium을 직접 지정해야 하는 환경에서는 아래처럼 실행합니다.

```bash
cd frontend
CHROMIUM_PATH=/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome npx playwright test
```

E2E 기본 주소는 `http://127.0.0.1:4187`입니다. `PORT=4187`로 웹 서버를 실행하거나
`UI_TEST_URL=http://localhost:8080`을 지정합니다. 실제 causRCA runtime 100건이 준비된
로컬 API를 사용하며, 검토 기록을 쓰므로 공유 운영 데이터가 아닌 로컬 검증 환경에서 실행합니다.
브라우저가 없다면 `npx playwright install chromium`으로 설치합니다.

`npm run test:e2e`는 로컬 준비 데이터와 실제 FastAPI 백엔드를 자동으로 띄운 뒤 React
production proxy를 통해 브라우저 시나리오를 실행합니다. 백엔드는 E2E 전용 in-memory
Case 저장소와 `data/runtime`만 사용하며, `API_AUTH_TOKEN`과 actor context header를
테스트 프로세스가 주입합니다. 따라서 이 테스트는 mock route가 아니라 브라우저 →
Node proxy → FastAPI → Case repository 전체 경계를 검증합니다. 인수인계 경로만 빠르게
확인하려면 `npm run test:e2e:real`을 사용합니다.

테스트는 기본적으로 기존 4187/4188 listener를 재사용하지 않아 잘못된 backend를 물고
실행되는 상황을 방지합니다. 이미 별도 서버를 띄운 환경에서 재사용하려면
`REUSE_E2E_SERVER=true`를 지정하고, 포트 충돌이 있으면 `UI_TEST_PORT`와
`BACKEND_TEST_PORT`를 함께 바꿉니다.

## 컨테이너 빌드

저장소 루트에서 실행합니다.

```bash
docker build -f frontend/Dockerfile.web -t mfg-investigation-frontend-web .
docker run --rm -p 8080:8080 \
  -e BACKEND_URL=http://host.docker.internal:8000 \
  -e BACKEND_API_TOKEN=dev-token \
  mfg-investigation-frontend-web
```

ECS 배포에서는 `BACKEND_URL`과 `BACKEND_API_TOKEN`을 컨테이너 환경 변수로 주입합니다.

기존 ECS 서비스의 네트워크·권한·환경값을 보존하고 React 이미지만 교체하려면 루트에서
`AWS_PROFILE=ai-innovators uv run --extra deploy python frontend/deploy_web.py`를 실행합니다.
이 스크립트는 새로운 AWS 리소스/IAM 권한을 생성하지 않으며 변경 전 이미지 URI를 기록합니다.
기존 `deploy_ecs_express.py`는 레거시 Streamlit 배포 경로이므로 React 업데이트에 사용하지 않습니다.

## 구현 범위와 경계

- 사건 선택, 관측 히스토그램, 진단 시점, 분석, 후보별 근거, 사건 인박스, 전문가 증거 확인, 최종 검토, 근거 질문, Markdown 보고서
- 브라우저 저장소에는 최근 조사 ID만 기록하고 결과는 API에서 조회
- 보고서는 백엔드 원문을 보존하고 UI의 알려진 고정 문구만 한국어로 표시
- 미준비 데이터·후보 없음·네트워크 오류·API 인증 오류를 구분
- 실제 사용자 인증/조직 권한·요청량 제한·JSON 내보내기·관측 페이지네이션은 후속 작업
- 로컬 사건 상태는 메모리에 보관합니다. 운영 배포에서는 `CASE_DDB_TABLE` 환경 변수를 설정해 별도 DynamoDB 사건 저장소를 사용합니다.
- [디자인 원본](../DESIGN.md), [화면 검증 결과](../docs/UI_IMPLEMENTATION.md)
