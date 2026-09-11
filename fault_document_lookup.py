"""
트랙 C — RAG 문서 계층 (최소 구현)

★ 지금 수준에서 벡터 검색이 필요 없는 이유 ★
docs/fault_reference.md는 섹션이 6개(TCP/RF/Cl2/BCl3/Pr/He)뿐이고,
track_b_engine.py의 FAULT_KEYWORD_ALIASES와 정확히 같은 키를 쓴다.
이 정도 규모에서는 임베딩 기반 벡터 검색보다 딕셔너리 조회가 더 빠르고
더 정확하다 (검색 실패 가능성 자체가 없음). 문서가 나중에 훨씬
늘어나면(예: 실제 FMEA 데이터 추가) 그때 벡터 검색으로 바꾸면 된다.

★ 이 문서의 성격 (다시 강조) ★
아래 내용은 반도체 플라즈마 에칭 장비에 대한 일반적인 공학 지식을
AI가 정리한 것이며, LAM 9600 장비의 검증된 사내 매뉴얼이 아니다.
lookup()이 반환하는 결과에는 이 사실을 알리는 disclaimer가 항상
같이 붙는다.
"""

FAULT_REFERENCE = {
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

DISCLAIMER = ("AI가 정리한 일반 반도체 공정 지식이며, 이 장비의 검증된 "
              "사내 매뉴얼이 아닙니다. 참고용으로만 쓰고 최종 판단은 "
              "공정 엔지니어가 확인하세요.")


def lookup(fault_keyword: str) -> dict | None:
    """track_b_engine.py의 parse_fault_keyword()가 뽑아낸 키워드
    (TCP/RF/CL2/BCL3/PR/HE)를 그대로 받아서 참고 문서를 반환한다.
    못 찾으면 None -- 지어내지 않는다."""
    entry = FAULT_REFERENCE.get(fault_keyword.strip().upper())
    if entry is None:
        return None
    return {**entry, "disclaimer": DISCLAIMER}


def attach_reference_to_report(report_csv: str = "processed/track_b_root_cause_report.csv") -> None:
    """트랙 B의 원인후보 리포트(track_b_root_cause_report.csv)를 읽어서,
    각 행의 fault_keyword에 맞는 참고문서를 붙인 새 리포트를 만든다.
    이게 트랙 D 에이전트가 '근거 문서 검색' 단계에서 그대로 호출할
    함수의 원형이다."""
    import pandas as pd

    df = pd.read_csv(report_csv)
    docs = df["fault_keyword"].apply(lookup)
    df["reference_title"] = docs.apply(lambda d: d["title"] if d else None)
    df["reference_role"] = docs.apply(lambda d: d["role"] if d else None)
    df["reference_common_causes"] = docs.apply(lambda d: d["common_causes"] if d else None)
    df["reference_symptoms"] = docs.apply(lambda d: d["symptoms"] if d else None)

    out_path = report_csv.replace(".csv", "_with_reference.csv")
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    n_found = docs.notna().sum()
    print(f"{len(df)}건 중 {n_found}건에 참고문서 연결 완료 -> {out_path}")
    if n_found < len(df):
        missing = df.loc[docs.isna(), "fault_keyword"].unique().tolist()
        print(f"  참고문서 없는 키워드: {missing} -- fault_reference.md에 새 섹션 추가 필요")


if __name__ == "__main__":
    attach_reference_to_report()
