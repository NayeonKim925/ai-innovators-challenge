# 작업 현황

`IMPLEMENTATION_PLAN.md`의 M0~M5와 트랙 A~F를 기준으로 업데이트합니다. 완료가 아닌 작업은 상태를 `진행 중`, `대기`, `차단됨` 중 하나로 표시합니다.

| 날짜 | 트랙 | 작업 | 담당 | 상태 | PR/커밋 | blocker / 다음 행동 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-11 | 공통 | 공통 계약·초기 API·문서 기반 구축 | Codex | 완료 | `f71f3c8` | M0 데이터 준비 시작 |
| 2026-09-11 | 공통 | 팀 공유용 구현 계획서 작성 | Codex | 완료 | 예정 | 담당자·실제 일정 확정 필요 |
| 2026-09-12 | M0 / 트랙 A | causRCA 고정 manifest·안전 bootstrap·runtime/evaluation 검증 구현 | Codex | 완료 | 작업 중 | 100 HIL / 170 정상 수와 정답 격리 검증 완료 |
| 2026-09-12 | M1 / 트랙 B | 100개 전체 시간 최근순 baseline benchmark 구현 | Codex | 진행 중 | 작업 중 | baseline 결과 산출 후 CausTR 의존성 설치·실행 필요 |

## 회의 결정 기록

| 날짜 | 결정 | 이유 | 영향 문서/코드 |
| --- | --- | --- | --- |
| 2026-09-11 | causRCA를 주 benchmark로, Metal Etch를 이식성 어댑터로 사용 | 원인 정답의 검증 가능성과 반도체 시연을 분리 | `docs/decisions/ADR-0001-primary-dataset.md` |
