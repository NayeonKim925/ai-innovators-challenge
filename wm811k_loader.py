"""
WM-811K 로더 (LSWMD.pkl, Kaggle: qingyi/wm811k-wafer-map)

일반적으로 알려진 컬럼: waferMap, dieSize, lotName, waferIndex,
trainTestLabel, failureType. Kaggle 재업로드본마다 미세하게 다를 수 있으니
아래 print(raw.columns)로 실제 컬럼명을 먼저 확인한 뒤 진행할 것.

주의: 이 데이터셋은 센서/장비 정보가 전혀 없다. equipment_id, timestamp를
None으로 두는 게 정직한 표현이다. waferMap은 2D 배열(이미지)이라 다른
소스의 시계열 feature와 같은 방식으로 다루지 않는다 -- modality="image"로
구분해서 별도 처리 경로(CNN 등)로 보낸다.
"""
import pandas as pd


def load_wm811k(pickle_path: str) -> pd.DataFrame:
    raw = pd.read_pickle(pickle_path)
    print("실제 컬럼:", raw.columns.tolist())  # 예상과 다르면 아래 매핑을 수정할 것

    records = []
    for i, row in raw.iterrows():
        failure = row.get("failureType")
        # failureType이 빈 배열이면 라벨 없음(unlabeled)인 경우가 많음 -- 실행해서 실제 형태 확인 필요
        if isinstance(failure, str):
            label_value = failure
        elif hasattr(failure, "__len__") and len(failure) > 0:
            label_value = failure[0][0] if hasattr(failure[0], "__len__") else failure[0]
        else:
            label_value = "unlabeled"

        records.append({
            "source_dataset": "wm811k",
            "modality": "image",
            "equipment_id": None,  # 공개 데이터에 없는 정보
            "entity_id": f"{row.get('lotName')}_{row.get('waferIndex')}",
            "process_stage": "wafer_map_inspection",
            "timestamp": None,  # 실제 시각 정보 없음 -- 지어내지 않음
            "label_type": "defect_pattern",
            "label_value": label_value,
            "features": row.get("waferMap"),  # 2D 배열 그대로 보존, 별도 이미지 파이프라인에서 소비
        })
    return pd.DataFrame(records)


if __name__ == "__main__":
    import sys
    df = load_wm811k(sys.argv[1])
    print(df[["source_dataset", "entity_id", "label_value"]].head())
    print(df["label_value"].value_counts())
