"""LLM tool layer — wraps deterministic analysis results for an LLM to summarize.

★ 이식 근거 (ADR-0002, 루트 agent_tools.py에서 이식) ★
루트의 `agent_tools.py`는 `track_b_engine.py`(레거시 루트 스크립트)를 직접 import해서
PCA 결과를 계산했다. 이 backend 버전은 그 레거시 의존을 없애고, 이미 존재하는
`backend/app/workflows/investigation.py`의 `investigate()` 결과(결정론적으로 계산된
`Candidate`/`Evidence`)를 그대로 넘겨받아 정리하는 방식으로 바꾼다. 이렇게 하면
"LLM이 수치를 새로 계산하지 않는다"는 AGENTS.md 원칙이 코드 구조로도 강제된다 --
이 모듈에는 PCA나 CausTR을 다시 계산하는 코드가 전혀 없다.

★ get_fault_reference의 참고문서 소스 ★
루트의 `fault_document_lookup.py`(`FAULT_REFERENCE` 딕셔너리)를 그대로 재사용한다.
이 문서는 AI가 정리한 일반 지식이며 검증된 사내 매뉴얼이 아니라는 disclaimer가
항상 함께 반환된다 (AGENTS.md: "AI가 생성한 도메인 문서를 권위 있는 RAG 근거로
사용하지 않습니다").
"""

from __future__ import annotations

from ..domain import Candidate, Evidence

# fault_document_lookup.py는 backend 패키지 경계 밖(저장소 루트)에 있다.
# metal_etch_adapter.py가 loaders/를 포팅했던 것과 같은 이유로, 이 모듈도
# 원본을 import로 재사용하지 않고 여기서 필요한 딕셔너리만 포팅한다 --
# backend를 독립 패키지로 배포할 때 루트 스크립트가 따라오지 않기 때문이다.
FAULT_REFERENCE: dict[str, dict[str, str]] = {
    "TCP": {
        "title": "TCP (Transformer Coupled Plasma) 계열",
        "role": "챔버 위쪽 코일에 고주파 전력을 걸어 플라즈마 자체를 만들어내는 시스템. 플라즈마 밀도와 라디칼 생성량을 결정한다.",
        "common_causes": "RF 발생기 자체의 출력 드리프트, 임피던스 매칭 네트워크 튜닝 불량, 코일 노후화.",
        "symptoms": "식각 속도 변화, 웨이퍼 표면 균일도 저하. 전력 과도 시 과식각, 부족 시 식각 부족.",
    },
    "RF": {
        "title": "RF (바이어스 RF, 웨이퍼 척 쪽) 계열",
        "role": "웨이퍼가 놓인 척 쪽에 걸리는 전력으로, 이온이 웨이퍼 표면에 부딪히는 에너지(이온 바이어스)를 조절한다. TCP와는 별개의 전원계다.",
        "common_causes": "바이어스 RF 발생기 이상, 척-웨이퍼 접촉 불량.",
        "symptoms": "식각 선택비·프로파일(옆면 각도) 변화, 과도하면 웨이퍼 손상 위험.",
    },
    "CL2": {
        "title": "Cl2 Flow (반응 가스)",
        "role": "알루미늄 등 금속 배선을 식각하는 주 반응가스.",
        "common_causes": "MFC(질량유량제어기) 드리프트, 가스 배관 막힘/누출.",
        "symptoms": "식각 속도·선택비 변화. 유량 부족 시 식각 정지, 과다 시 언더컷 증가.",
    },
    "BCL3": {
        "title": "BCl3 Flow (반응 가스)",
        "role": "자연산화막 제거 목적으로 보통 Cl2와 함께 조합되어 쓰이는 가스.",
        "common_causes": "MFC 드리프트, 가스 배관 막힘/누출.",
        "symptoms": "식각 속도·선택비 변화.",
    },
    "PR": {
        "title": "Pressure (챔버 압력)",
        "role": "플라즈마 밀도와 이온 평균자유행로에 영향을 준다.",
        "common_causes": "스로틀 밸브 이상, 펌프 성능 저하.",
        "symptoms": "식각 프로파일(수직/경사) 변화, 이방성 저하.",
    },
    "HE": {
        "title": "He Press (헬륨 척 냉각압력)",
        "role": "웨이퍼와 정전척 사이 열전달을 돕는 헬륨 backside 압력. 챔버 압력(Pressure)과는 다른 서브시스템.",
        "common_causes": "척 씰(seal) 누출, He 공급 라인 이상.",
        "symptoms": "웨이퍼 온도 불균일 -> 온도 의존적 식각 속도 편차, 심하면 척킹 실패.",
    },
}

FAULT_REFERENCE_DISCLAIMER = (
    "AI가 정리한 일반 반도체 공정 지식이며, 이 장비의 검증된 사내 매뉴얼이 "
    "아닙니다. 참고용으로만 쓰고 최종 판단은 공정 엔지니어가 확인하세요."
)

# 변수 이름의 첫 단어가 어느 계열(FAULT_REFERENCE의 키)에 속하는지 매칭하기
# 위한 접두어 표. 원본 agent_tools.py는 FAULT_KEYWORD_ALIASES(track_b_engine.py)를
# 뒤집어서 정확히 조회했는데, 이 backend 버전은 그 표를 import하지 않으므로
# (레거시 의존 제거) 변수 이름 접두어 매칭으로 단순화한다 -- Metal Etch의 21개
# 변수 이름(예: "TCP Tuner", "RF Load", "Cl2 Flow", "Pressure", "He Press")은
# 전부 계열 키워드로 시작하므로 이 방식으로 충분하다.
_KEYWORD_PREFIXES: dict[str, str] = {
    "TCP": "TCP",
    "RF": "RF",
    "CL2": "CL2",
    "BCL3": "BCL3",
    "PR": "PRESSURE",
    "HE": "HE",
}


def summarize_candidates(candidates: list[Candidate], evidence: list[Evidence], limit: int = 3) -> dict:
    """`investigate()`가 이미 계산한 결정론적 결과를 LLM에 넘길 최소 payload로
    정리한다. 숫자를 다시 계산하지 않고, 있는 값만 골라 담는다."""
    evidence_by_id = {item.id: item for item in evidence}
    top = candidates[:limit]
    return {
        "found": bool(top),
        "candidates": [
            {
                "rank": candidate.rank,
                "signal": candidate.signal,
                "status": candidate.status,
                "reason": candidate.reason,
                "evidence": [
                    {
                        "id": evidence_by_id[eid].id,
                        "title": evidence_by_id[eid].title,
                        "detail": evidence_by_id[eid].detail,
                        "source": evidence_by_id[eid].source,
                    }
                    for eid in candidate.evidence_ids
                    if eid in evidence_by_id
                ],
            }
            for candidate in top
        ],
    }


def get_fault_reference(variable_name: str) -> dict:
    """원인후보 변수 이름(예: 'TCP Top Pwr', 'RF Load')을 받아, 그 변수가
    속한 계열(TCP/RF/Cl2/BCl3/Pr/He)의 참고문서를 반환한다. 계열을 못
    찾으면 found=False -- 지어내지 않는다."""
    name = variable_name.strip().upper()
    for keyword, prefix in _KEYWORD_PREFIXES.items():
        if name.startswith(prefix):
            entry = FAULT_REFERENCE[keyword]
            return {
                "found": True,
                "variable": variable_name,
                **entry,
                "disclaimer": FAULT_REFERENCE_DISCLAIMER,
            }
    return {"found": False, "reason": f"'{variable_name}'이 속한 계열을 찾을 수 없습니다."}
