# ADR-0005: 사람이 cutoff를 고르는 조사 도구에서, 에이전트가 이상을 스스로 감지·판단하는 워크스페이스로 전환

## 상태

승인됨 · 2026-09-22. 구현은 Phase 1(백엔드 탐지 에이전트)부터 시작하며, 상세 단계는 [AGENT_FAULT_DETECTION_PLAN.md](../AGENT_FAULT_DETECTION_PLAN.md)를 따른다.

## 배경

현재 서비스는 causRCA의 준비된 100개 fault 사건 중 하나를 사람이 고르고, 관측 타임라인에서 진단 cutoff(`diagnosis_time`)를 슬라이더로 직접 지정한 뒤 "조사 실행" 버튼을 눌러야 `rank_with_caus_tr`(전문가 인과그래프 기반 CausalPrioTimeRecencyRCA)가 원인 후보를 계산한다. 이 흐름에는 두 가지 구조적 문제가 있다.

1. **fault 탐지 자체가 없다.** causRCA의 `causes.json`에 `cause_start_at`이 있지만 서비스 코드 어디에서도 읽지 않는다(`data/evaluation`에만 존재, 접근 금지가 원칙이므로 당연하다). 대신 사람이 "몇 초부터 이상해 보이는지"를 스스로 판단해서 슬라이더를 움직인다. README의 "최근 알람 발생 시점으로 이동" 버튼도 결국 사람이 누르는 수동 shortcut일 뿐 자동 탐지가 아니다.
2. **에이전트가 실제 요청 경로에 없다.** `docs/decisions/ADR-0003`이 배포한 Bedrock AgentCore Runtime/Gateway는 명시적으로 "대회 제출용 증거이며 프로덕션 요청 경로의 일부가 아니다." LangGraph 워크플로우(`backend/app/workflows/investigation.py`)도 실제로는 매번 같은 순서로 도는 고정 DAG이며, 상황에 따라 다르게 판단하는 자율성이 없다.

이 대회는 "데이터 분석 정확도"가 아니라 "에이전트를 얼마나 잘 붙였는가"와 "데이터 활용성"을 보는 agentic AI 경진대회다. 현재 구현은 causRCA 데이터셋의 상당 부분(정상 운전 기록 170개, subsystem별 서브그래프, 사람이 읽는 노드 label)을 전혀 쓰지 않고 있고, 에이전트의 자율적 판단이 들어갈 지점이 없다.

## 결정

1. **탐지를 사람의 일이 아니라 에이전트의 일로 옮긴다.** 새 결정론적 신호 두 가지 — 알람 최초 활성화 시각(causRCA 자체의 Baro 휴리스틱과 동일 계열)과, `real_op` 170개 정상 기록으로 학습한 PCA 재구성오차(Metal Etch의 `metal_etch_pca.py` 패턴을 causRCA에 이식) — 를 계산하는 도구를 만들고, **LangGraph 기반 조건부 에이전트**가 두 신호와 최근 추세를 함께 보고 다음 행동(추가 관찰 / 오탐 검토 / RCA 실행 / 재시도)을 스스로 결정한다. 수치 계산은 여전히 결정론적 도구가 하고, 에이전트는 그 결과를 조합해 다음 단계를 고르는 오케스트레이션만 담당한다 (AGENTS.md 규칙 4 유지).
2. **Bedrock AgentCore는 지금 당장 실제 경로에 넣지 않는다.** ADR-0003의 배포 증거는 유지하되, 이번 전환의 핵심 자율성은 LangGraph 조건부 그래프에 둔다. AgentCore는 이후 이 그래프를 감싸는 production orchestration 계층으로 확장 가능하도록 인터페이스만 열어 둔다(구체적 재사용 지점은 계획 문서 6절).
3. **causRCA 데이터 활용을 확장한다.** `scripts/prepare_causrca.py`가 `real_op`(170개 정상 기록)를 읽어 PCA 기준선 학습용 runtime 자산으로 만들고, `<group>_nodes.csv`의 `label` 컬럼을 읽어 원시 tag ID 대신 사람이 읽는 변수 설명을 근거 문구에 쓴다. 평가 전용 필드(`cause_start_at`, `diagnoses` 등)는 계속 `data/evaluation`에만 두고 탐지 정확도 채점에만 쓴다.
4. **조사 진입점과 화면 구조를 재설계한다.** Case/Handover/Hypothesis/Open Item 도메인 모델과 API는 유지하되, 프론트엔드는 이를 각각의 메뉴로 노출하지 않고 `Monitor → Investigate → Handover` 3단계로 단순화한다. Investigate 화면은 에이전트가 생성한 하나의 investigation summary 안에서 근거·후보·미확인 항목을 progressive disclosure로 통합 표시한다. 진입 흐름은 "사건 목록 선택 → cutoff 슬라이더"에서 "재생 모니터링 → 에이전트 이상 감지 알림 → 자동 investigation 생성 → RCA → handover 초안 생성"으로 바뀐다.
5. **실시간은 재생 시뮬레이션으로 구현한다.** 실제 SSE/WebSocket 라이브 스트림 대신, 준비된 기록을 시간순으로 배속 재생하며 매 tick마다 탐지 에이전트가 재평가하는 방식을 채택한다. DESIGN.md의 "가짜 실시간 데이터 지양" 원칙에 맞춰, 화면에는 "재생 중(배속 Nx, 준비된 HIL 기록)"임을 항상 명시하고 실제 공장 실시간 데이터처럼 보이지 않게 한다.

## 결과

### 긍정적 결과

- 심사 시연 시 "사람이 정답을 알고 슬라이더를 맞춘다"는 인상 대신, 에이전트가 스스로 이상을 찾고 원인을 좁혀가는 흐름을 보여줄 수 있다.
- `real_op` 170개, subsystem 서브그래프, node label 등 지금 0% 활용 중인 causRCA 자산을 실제 기능으로 전환한다.
- 기존 Case/Handover/Analysis Run 백엔드 자산(ADR-0004)을 폐기하지 않고, 그 앞단 진입 흐름만 자동화·단순화한다.
- 탐지 신호(alarm/PCA) 각각을 결정론적으로 유지하므로, 벤치마크(Hit@1/MRR/MAP@3에 더해 탐지 정확도 지표)로 계속 검증 가능하다.

### 비용과 제약

- 프론트엔드 정보구조 전면 재설계이므로 기존 UI 컴포넌트·화면 테스트가 대량으로 바뀐다.
- PCA 기준선(2번째 탐지 신호)은 Alarm 기반 신호보다 구현·검증에 시간이 더 든다 — 계획 문서에서 Alarm 우선 → PCA 추가 → 통합의 순서로 리스크를 분리했다.
- "에이전트가 자동으로 Case를 연다"는 새 동작은 기존 "사람이 명시적으로 조사를 시작한다"는 불변식과 조율이 필요하다 — Case 생성 자체는 여전히 결정론적 트리거(신호 임계치 충족)에서만 발생하고, 사람의 최종 판단·검토 게이트(CASE_ORCHESTRATION_PLAN.md)는 그대로 유지한다.
- 재생 시뮬레이션은 실제 실시간 OPC UA 연동이 아니므로, 화면에 "준비된 기록의 재생"임을 계속 명시해야 DESIGN.md의 신뢰 신호 원칙을 지킬 수 있다.

## 대안

- **AgentCore를 지금 바로 실제 경로에 연결:** 더 인상적이지만, Bedrock Agents Classic 폐쇄 사례(ADR-0003)에서 보듯 AWS 신규 서비스 계정 제약과 8초대 지연이 있어 일정 리스크가 크다. 이번 전환에서는 채택하지 않고 이후 단계로 미룬다.
- **진짜 SSE/WebSocket 실시간 스트림 구현:** 데모 임팩트는 크지만 구현·디버깅 비용이 재생 시뮬레이션보다 훨씬 크고, 실제 공장 데이터가 아닌데 실시간처럼 보이는 위험(DESIGN.md 원칙 위반)도 커서 채택하지 않는다.
- **기존 화면 구조를 유지하고 탐지 기능만 추가:** 데이터 활용성은 개선되지만 "에이전트가 복잡성을 대신 처리한다"는 이번 전환의 UX 목표를 달성하지 못해 채택하지 않는다.
