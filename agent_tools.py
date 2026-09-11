"""
트랙 D 도구 계층 — 에이전트가 호출하는 실제 함수들.

여기서 하는 일은 두 가지뿐이다: 트랙 B(원인후보 랭킹)와 트랙 C(참고문서
조회)를 에이전트가 부르기 좋은 형태로 감싸는 것. 새로운 로직은 없다 --
전부 track_b_engine.py / fault_document_lookup.py를 그대로 재사용한다.

★ 설계 원칙: 라벨(fault_label) 정답을 에이전트에 절대 넘기지 않는다 ★
지금 쓰는 21개 결함 웨이퍼는 "이미 원인이 알려진 과거 사례"라서
fault_label이 metadata.csv에 있지만, 실제 알람 상황에서는 그 라벨이
없다(그게 바로 에이전트가 찾아야 할 답이다). 그래서 get_root_cause_ranking()은
센서 데이터로 계산한 랭킹만 반환하고, fault_label은 절대 반환하지 않는다.
정답과 대조하는 건 사람(EITL)이 하는 별도 영역이다.

★ PCA 모델을 요청마다 새로 학습하지 않는 이유 ★
build_baseline_model()은 무거운 연산(정상 웨이퍼 전체로 PCA 학습)이라
모듈이 처음 임포트될 때 한 번만 실행하고 캐싱한다. 에이전트가 알람을
100번 받아도 학습은 1번만 한다.
"""
from track_b_engine import build_baseline_model, score_entity, base_variable_name, FAULT_KEYWORD_ALIASES
from fault_document_lookup import lookup as lookup_fault_reference

_MODEL = None  # 지연 로딩 -- 이 모듈이 처음 쓰일 때 한 번만 학습

# 변수명 -> 계열 키워드 역조회 테이블. 변수명의 첫 단어를 추측해서 쓰면
# "Pressure"(PR 계열인데 단어 자체엔 PR이 없음) 같은 경우 못 찾는다.
# FAULT_KEYWORD_ALIASES가 이미 확정한 매핑을 그대로 뒤집어서 쓴다.
_VARIABLE_TO_KEYWORD = {
    var: keyword for keyword, variables in FAULT_KEYWORD_ALIASES.items() for var in variables
}


def _get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = build_baseline_model()
    return _MODEL


def get_root_cause_ranking(entity_id: int, top_k: int = 3) -> dict:
    """센서 데이터 기준 원인후보 top_k를 반환한다. fault_label(정답)은
    포함하지 않는다 -- 실제 알람 상황에서는 애초에 존재하지 않는 정보다."""
    model = _get_model()
    ranking = score_entity(entity_id, model)
    if ranking is None:
        return {"found": False, "reason": f"entity_id {entity_id}에 대한 machine 센서 데이터가 없습니다."}

    top = ranking.head(top_k)
    candidates = []
    for _, row in top.iterrows():
        candidates.append({
            "variable": base_variable_name(row["variable"]),  # 스텝/통계 접미사 뗀 원래 변수명
            "detail": row["variable"],                        # 어느 스텝·어느 통계량에서 튀었는지 원본 그대로
            "contribution_score": round(float(row["contribution"]), 2),
            "rank": int(row["rank"]),
        })
    return {"found": True, "entity_id": entity_id, "candidates": candidates}


def get_fault_reference(variable_name: str) -> dict:
    """원인후보 변수 이름(예: 'TCP Top Pwr', 'Pressure')을 받아서, 그
    변수가 속한 계열(TCP/RF/Cl2/BCl3/Pr/He)의 참고문서를 반환한다.
    변수명의 첫 단어를 추측하지 않고, FAULT_KEYWORD_ALIASES를 뒤집은
    표에서 정확히 조회한다 ('Pressure'처럼 계열명이 변수명 안에 없는
    경우도 정확히 찾아야 하므로)."""
    keyword = _VARIABLE_TO_KEYWORD.get(variable_name.strip())
    if keyword is None:
        return {"found": False, "reason": f"'{variable_name}'이 속한 계열을 찾을 수 없습니다."}
    doc = lookup_fault_reference(keyword)
    if doc is None:
        return {"found": False, "reason": f"'{variable_name}'({keyword} 계열)에 대한 참고문서가 없습니다."}
    return {"found": True, "variable": variable_name, **doc}


# Anthropic API tool_use에 그대로 넣을 수 있는 스키마.
# agent.py가 이 리스트를 messages.create(tools=...)에 전달한다.
TOOL_SCHEMAS = [
    {
        "name": "get_root_cause_ranking",
        "description": (
            "특정 웨이퍼(entity_id)의 machine 센서 데이터를 PCA 기반 "
            "이상탐지 엔진으로 분석해서, 원인일 가능성이 높은 변수 순서로 "
            "top_k개를 반환한다. 이건 후보 제시이지 확정된 원인이 아니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "integer", "description": "알람이 발생한 웨이퍼 번호"},
                "top_k": {"type": "integer", "description": "반환할 후보 개수 (기본 3)"},
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "get_fault_reference",
        "description": (
            "원인후보 변수 이름을 받아서 그 변수가 속한 서브시스템의 "
            "일반 참고 정보(역할, 흔한 원인, 증상)를 반환한다. 이 정보는 "
            "AI가 정리한 일반 지식이며 이 장비의 검증된 매뉴얼이 아니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "variable_name": {"type": "string", "description": "get_root_cause_ranking이 반환한 variable 값"},
            },
            "required": ["variable_name"],
        },
    },
]


if __name__ == "__main__":
    import json
    import sys

    entity_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2915
    ranking = get_root_cause_ranking(entity_id)
    print(json.dumps(ranking, ensure_ascii=False, indent=2))
    if ranking.get("found") and ranking["candidates"]:
        ref = get_fault_reference(ranking["candidates"][0]["variable"])
        print(json.dumps(ref, ensure_ascii=False, indent=2))
