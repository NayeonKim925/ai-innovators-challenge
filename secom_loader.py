"""
UCI SECOM 로더
필요 파일 (https://archive.ics.uci.edu/dataset/179/secom):
    secom.data          -- 1567행 x 590열, 공백구분, 결측치는 'NaN' 문자열
    secom_labels.data   -- 1567행 x 2열: label(-1=pass, 1=fail), timestamp

주의: SECOM에는 장비 구분 정보가 없다. equipment_id를 None으로 두는 것이
정직한 표현이며, 임의의 장비명을 지어 넣지 않는다.
"""
import pandas as pd


def load_secom(data_path: str, labels_path: str) -> pd.DataFrame:
    features = pd.read_csv(data_path, sep=r"\s+", header=None)
    labels = pd.read_csv(labels_path, sep=r"\s+", header=None, names=["label", "timestamp"])

    if len(features) != len(labels):
        raise ValueError(
            f"secom.data({len(features)}행)와 secom_labels.data({len(labels)}행) 행 수가 다릅니다. "
            "파일이 올바른지 다시 확인하세요."
        )

    records = []
    for i in range(len(features)):
        records.append({
            "source_dataset": "secom",
            "modality": "feature_vector",
            "equipment_id": None,  # 공개 데이터에 없는 정보 -- 임의로 채우지 않음
            "entity_id": f"secom_unit_{i:05d}",
            "process_stage": "wafer_test",
            "timestamp": labels.iloc[i]["timestamp"],
            "label_type": "pass_fail",
            "label_value": "fail" if labels.iloc[i]["label"] == 1 else "pass",
            "features": features.iloc[i].tolist(),  # 590차원 원본 그대로 보존
        })
    return pd.DataFrame(records)


if __name__ == "__main__":
    import sys
    df = load_secom(sys.argv[1], sys.argv[2])
    print(df[["source_dataset", "entity_id", "timestamp", "label_value"]].head())
    print(f"총 {len(df)}행, fail 비율: {(df['label_value'] == 'fail').mean():.3%}")
