# 작업 현황

`IMPLEMENTATION_PLAN.md`의 M0~M5와 트랙 A~F를 기준으로 업데이트합니다. 완료가 아닌 작업은 상태를 `진행 중`, `대기`, `차단됨` 중 하나로 표시합니다.

| 날짜 | 트랙 | 작업 | 담당 | 상태 | PR/커밋 | blocker / 다음 행동 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-11 | 공통 | 공통 계약·초기 API·문서 기반 구축 | Codex | 완료 | `f71f3c8` | M0 데이터 준비 시작 |
| 2026-09-11 | 공통 | 팀 공유용 구현 계획서 작성 | Codex | 완료 | 예정 | 담당자·실제 일정 확정 필요 |

## 회의 결정 기록

| 날짜 | 결정 | 이유 | 영향 문서/코드 |
| --- | --- | --- | --- |
| 2026-09-11 | causRCA를 주 benchmark로, Metal Etch를 이식성 어댑터로 사용 | 원인 정답의 검증 가능성과 반도체 시연을 분리 | `docs/decisions/ADR-0001-primary-dataset.md` |
| 2026-09-12 | Metal Etch를 backend/app의 공식 어댑터로 승격하고, evidence_check 선행 조건으로 LLM 내러티브를 조건부 도입 | 루트 스크립트로 이미 완성된 PCA+Bedrock 데모 자산을 공식 아키텍처에 편입, ADR-0001의 성능 주장 제약은 유지 | `docs/decisions/ADR-0002-metal-etch-integration.md` |

## 소급 기록 · 트랙 Y (Metal Etch 데모, 2026-09-11~12)

공식 M0~M5 로그에는 반영되지 않았던 병행 작업. ADR-0002 작성 계기로 소급 기록.

| 날짜 | 트랙 | 작업 | 담당 | 상태 | 관련 파일 |
| --- | --- | --- | --- | --- | --- |
| 2026-09-11 | Y (데이터) | Metal Etch 원본 3종(.mat) 로딩, 웨이퍼 번호 매칭, 경계 중복행 제거 | Nayeon Kim | 완료 (루트 스크립트) | `loaders/metal_etch_loader.py`, `preprocess.py` |
| 2026-09-11 | Y (검증) | 라벨-실측 정합성 검증, 신뢰도 낮은 라벨 5건 표시 | Nayeon Kim | 완료 (루트 스크립트) | `verify_metadata.py`, `inspect_failing_cases.py`, `flag_unreliable_labels.py` |
| 2026-09-11 | Y (분석) | PCA 기반 이상탐지 + contribution score 원인후보 랭킹 | Nayeon Kim | 완료 (루트 스크립트) | `track_b_engine.py` |
| 2026-09-11 | Y (RAG) | 결함 계열별(TCP/RF/Cl2/BCl3/Pr/He) 참고 지식 키워드 조회 | Nayeon Kim | 완료 (루트 스크립트) | `fault_document_lookup.py`, `fault_reference_rag.md` |
| 2026-09-11 | Y (에이전트) | AWS Bedrock Claude 호출 에이전트, entity 5건 데모 보고서 생성 | Nayeon Kim | 완료 (루트 스크립트, 공식 아키텍처 미편입) | `agent.py`, `agent_tools.py`, `run_demo_batch.py`, `reports/` |
| 2026-09-12 | 공통 | Metal Etch 통합 ADR 작성 | Nayeon Kim | 완료 | `docs/decisions/ADR-0002-metal-etch-integration.md` |
| 2026-09-12 | A/B | Metal Etch를 backend/app 어댑터로 이식 (metal_etch_adapter.py, metal_etch_pca.py, prepare_metal_etch.py) | 미배정 | 대기 | ADR-0002 후속 |
| 2026-09-12 | C | LLM 내러티브(explainer.py, evidence_check 노드) 편입 | 미배정 | 대기 | ADR-0002 후속 |
