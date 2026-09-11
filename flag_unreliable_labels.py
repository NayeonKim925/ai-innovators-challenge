"""
inspect_failing_cases.py로 직접 대조한 결과, 라벨과 실측 신호가 어긋난
것으로 확인된 5개 웨이퍼를 metadata.csv에 label_reliable 컬럼으로
표시한다. 라벨을 추측해서 고치지 않고 "못 믿는다"로만 표시하는 이유는,
잘못 추측해서 고치면 새로운 오류를 만들 위험이 있기 때문이다.

실행: python flag_unreliable_labels.py
"""
import pandas as pd

META_PATH = "processed/metadata.csv"

# inspect_failing_cases.py 결과로 직접 눈으로 확인된, 라벨-실측 불일치 웨이퍼
# (부호 반대 또는 거의 무신호). 추측으로 다른 라벨을 대신 넣지 않고
# "불확실"로만 표시한다.
UNRELIABLE_ENTITY_IDS = [2918, 2937, 3141, 3142, 3339]


def main():
    meta = pd.read_csv(META_PATH)
    meta["label_reliable"] = ~meta["entity_id"].isin(UNRELIABLE_ENTITY_IDS)

    n_unreliable = (~meta["label_reliable"]).sum()
    n_reliable_faults = (meta["label_reliable"] & ~meta["is_normal"]).sum()
    print(f"신뢰 불가 라벨: {n_unreliable}개 ({UNRELIABLE_ENTITY_IDS})")
    print(f"신뢰 가능한 결함 라벨: {n_reliable_faults}개 (정상 108 + 나머지 결함 {n_reliable_faults})")
    print("트랙 B precision@k 계산 시 label_reliable == True인 행만 정답 대조에 쓸 것.")

    meta.to_csv(META_PATH, index=False, encoding="utf-8-sig")
    print(f"\n{META_PATH}에 label_reliable 컬럼 추가 완료")


if __name__ == "__main__":
    main()
