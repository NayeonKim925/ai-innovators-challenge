# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-09-17
- Primary product surfaces: React 조사 워크스페이스, 근거 상세, 검토·보고서, 보조 채팅.
- Evidence reviewed: `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, `backend/app/domain.py`, `frontend/app.py`. 팀 레포에는 기존 React 코드·로고·디자인 토큰 없음. 다른 프로젝트의 화면은 가져오지 않음.
- References: `.lazyweb/quick-references/investigation-2026-09-17/report.md`. Lazyweb MCP tools/list 연결 성공, health/search 단계 HTTP 429. 미확보 이미지를 참고했다고 주장하지 않음. 공식 Linear, Metabase, Grafana 자료를 보완 근거로 사용.
- Branding follow-up: 같은 날 Lazyweb health/search 재조회 성공. Rows·Dovetail·Tango의 브랜딩/워크스페이스 화면 메타데이터 확인. 해당 화면 이미지는 미다운로드·미검토이며 기존 시각 레퍼런스를 유지한다. 브랜드 결정은 `docs/BRAND.md`.

## Brand
- Name: **Cluephase / 클루페이즈**. Clue(단서) + Phase(조사 단계·공정). 이름과 메시지의 기준은 `docs/BRAND.md`, 코드 상수는 `frontend/src/brand.ts`.
- Promise: **신호를 근거로, 근거를 판단으로.** 제조 이상을 근거로 조사하고 전문가의 판단을 기록하는 워크스페이스.
- Personality: 정밀함, 침착함, 설명 가능성. 원인을 자동 확정한다는 인상을 주지 않는다.
- Wordmark: 기존 연결 신호 심볼 + Cluephase 텍스트. Pretendard 720, 자간 -0.6px. 좁은 화면에서도 이름을 생략하거나 줄바꿈하지 않는다. 색과 로고는 브랜드 위치에서만 사용하고 업무 용어는 그대로 둔다.
- Trust signals: 원본 사건 ID, 실제 관측 건수, 진단 시점, 근거 출처, 분석 방식, 검토자·시간.
- Avoid: 가짜 실시간 데이터, 확률처럼 보이는 순위 점수, 공장 실적 KPI, 과장된 AI 문구, 장식용 그래프.

## Product goals
- Goals: 사건을 선택하고 진단 시점을 정한 뒤 후보→근거→검토→보고서까지 마침.
- Non-goals: 범용 업로드, 설비 제어, 새 분석 알고리즘, 회원·조직 권한 관리.
- Success signals: 첫 화면에서 조사 시작 방법을 이해; 후보에서 근거까지 한 번 클릭; API 오류에서 복구 가능.

## Personas and jobs
- Primary personas: 공정 전문가(근거 검토), 분석가(관측값·실행 내역), 운영자(사건 탐색).
- User jobs: 사건 찾기, 조사 범위 설정, 원인 후보 검토, 판단 기록, 근거 기반 질문.
- Key contexts: 데스크톱 웹 중심, 한국어 업무 환경; 모바일에서 조회·검토 지원.

## Information architecture
- Primary navigation: 사건 조사 / 이 브라우저의 조사 기록 / 데이터셋 / 사용 안내.
- Core screens: 사건 목록 + 조사 작업 영역; 작업 영역의 관측·분석 결과·검토·질문 탭.
- Content hierarchy: 조사 대상→관측 사실→사용자 설정→실행→후보→근거→사람 판단. 채팅은 보조.
- 기록은 브라우저에 run ID만 보관, 실제 내용은 API 재조회. 팀 전체 기록으로 표시하지 않음.

## Design principles
- 첫 화면에 실제 사건과 관측 요약을 보여주고 실행 버튼을 명확히 배치.
- 후보 순위는 신뢰도 확률이 아님. 미실행 상태를 오류처럼 보이지 않게 설명.
- 상세는 점진적으로 공개; 출처·경고·방법은 숨기지 않음.
- Tradeoffs: 기획서의 협업 수정 기능은 API가 지원하는 승인/거절 범위까지만 UI 제공.

## Visual language
- Color: canvas #F5F7F8, surface #FFFFFF, sidebar #142D35, ink #18333B, muted #60747C, border #DEE6E9, accent #167D7B, accent-soft #E9F4F1, warning #946019 / #FFF5E3.
- Typography: Pretendard Variable (한글·영문, 로컬 호스팅), system sans fallback. 기본14px/1.5, 설명11~12px, 표10px, 작은 메타정보9px, 제목29px/1.3, 수치19px, 원본 ID monospace. 제목600~720, 본문400~500. 작은 메타정보의 가독성은 실제 사용자 검증 후 확대할 수 있다.
- Spacing/layout rhythm: 4px 기반, 주요 간격 8/12/16/24/32; sidebar208px, 목록280px, 본문 fluid.
- Shape/radius/elevation: 패널9px, 입력6px, 상태4px; 얇은 테두리와 미세한 그림자. 타임라인 배경만 거의 흰색의 약한 명도 변화.
- Motion: 버튼150ms, 로딩 회전 아이콘; 로딩 중 무한 가짜 진행률 금지.
- Imagery/iconography: Lucide 14~20px, 색상만으로 구분하지 않음. imagegen으로 만든 각진 연결 신호 로고, 생성 방향은 `docs/BRAND_ASSETS.md`에 보관.

## Components
- Existing components: 기존 FastAPI 계약 재사용. Streamlit UI는 별도 레거시로 보존.
- Implemented: App 내부의 사건목록·후보/근거·검토·채팅 영역, Timeline/ErrorBox/Empty 함수형 컴포넌트. 후속 변경이 커질 때 영역별 파일 분리를 수행한다.
- Variants and states: primary/secondary/ghost 버튼; ready/unprepared/검토대기/검토기록 상태; busy/error/empty.
- Ownership: `frontend/src/styles.css` 토큰, `frontend/src/App.tsx` 표현·흐름, `frontend/src/api.ts` 통신, `frontend/src/presentation.ts` 고정 문구 표시.

## Accessibility
- Target: WCAG 2.2 AA 지향; 자동 검사만으로 준수 인증하지 않음.
- Keyboard/focus: native 버튼·폼, visible focus, skip link, 탭 aria-selected/방향키/Home/End, 논리적 tab 순서.
- Contrast: 짙은 본문·흰 배경, 라벨과 아이콘 동시 사용.
- Screen reader: semantic landmarks, 폼 label, chart title/description와 표 대안, 오류 role=alert, 작업 상태 role=status.
- Reduced motion: prefers-reduced-motion 지원, 색·애니메이션만으로 상태 전달 금지.

## Responsive behavior
- >=1200px sidebar+사건목록+작업영역. 900~1199px 좁은 sidebar와 목록. <=900px 메뉴 상단 배치. <=650px 단일 열, 사건 목록 가로 탐색, 표 영역만 스크롤.
- 키보드 focus를 hover와 동등 처리. 보조 컨트롤의 터치 영역은 후속 접근성 검증에서 점검한다.

## Interaction states
- Loading: 사건 로딩/실행중 표시. 이전 사건 결과를 새 사건처럼 표시하지 않음.
- Empty: 데이터 미준비/검색0건/미실행/근거없음 각각 별도 문구.
- Error: 원인에 맞는 한국어 메시지, 재시도; 자동 POST 재시도 금지.
- Success: 저장된 검토 응답과 시간 표시, 보고서 다운로드 때 report 재조회. Markdown 다운로드 구현, JSON은 후속.
- Disabled: 수행 조건과 사유 제공. 미준비 데이터셋의 조사 버튼 비활성.
- Slow network: fetch timeout, GET 취소, 실제 처리 상태만 표시.

## Content voice
- Tone: 짧고 구체적인 한국어. '원인 후보', '검토 필요', '진단 시점' 일관 사용.
- 내부 API 주소·AWS 리소스·토큰은 업무 UI에서 제외. 분석 도구 이름은 실행 내역에서 제공.
- 준비 데이터는 공개 HIL 데이터임을 명시. 실시간 공장 운영 상태로 오해시키지 않음.

## Implementation constraints
- React19 + TypeScript + Vite, CSS tokens, Lucide. API는 같은 origin의 Node gateway 경유. 토큰은 서버 환경에만 보관.
- abort와 요청 세대 검증으로 오래된 응답 차단. 관측은 48개 구간 집계/검색 후 최대100개 표 표시. 원본 분석 입력은 수정하지 않음. 상세 캐시·페이지네이션은 후속.
- Cookie 없는 shared gateway는 개인별 인증/권한을 제공하지 않음. 운영 전 인증·rate limit 별도 필요.
- Verification: typecheck/build, gateway 테스트, 기존 Python 테스트, 실제 runtime 브라우저 E2E, 1440/390px 스크린샷과 visual-verdict.

## Open questions
- [ ] 상표·도메인 확인 / 팀 / Cluephase는 제품 작업명으로 적용, 상용 출시 전 별도 검토.
- [ ] 사용자별 로그인·조직 접근제어 / 후속 서비스 단계 / 공개 운영 전 필요.
- [ ] 전문가 후보 수정 API / 백엔드 / 현재 승인·거절까지만 제공.
