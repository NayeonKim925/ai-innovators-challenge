"""
2018 PHM Data Challenge (이온밀링 장비) 로더

★ 아래 컬럼명은 확정된 게 아니다 ★
PHM 챌린지는 릴리스마다 파일 구성이 조금씩 다르고, 정확한 컬럼 의미는
이미 확보한 GitHub 저장소(https://github.com/ninja1mmm/2018-phm-data-challenge)
의 로딩·라벨링 코드가 1차 근거다. 여기서 컬럼명을 임의로 단정하면 지금까지
지적받은 것과 같은 실수(모르는 걸 아는 척 채워넣기)가 되므로,
inspect_phm()으로 실제 파일을 먼저 열어본 뒤 load_phm()의 매개변수를 채운다.

권장 순서:
1. inspect_phm("다운로드한_파일_경로.csv") 실행 → 실제 컬럼명 확인
2. 위 GitHub 저장소 코드와 대조해서 equipment/run/시간/라벨 컬럼이 뭔지 확정
3. load_phm() 호출 시 그 컬럼명을 인자로 넘김
"""
import pandas as pd


def inspect_phm(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    print("컬럼 목록:", df.columns.tolist())
    print(df.head())
    print(df.dtypes)
    return df


def load_phm(
    path: str,
    equipment_col: str,
    run_col: str,
    time_col: str,
    label_col: str,
    stage: str = "ion_mill_hold",
) -> pd.DataFrame:
    """
    equipment_col / run_col / time_col / label_col:
    inspect_phm()과 GitHub 저장소 코드로 확인한 실제 컬럼명을 넣을 것.
    """
    df = pd.read_csv(path)
    feature_cols = [c for c in df.columns if c not in {equipment_col, run_col, time_col, label_col}]

    records = []
    for _, row in df.iterrows():
        records.append({
            "source_dataset": "phm2018",
            "modality": "tabular_timeseries",
            "equipment_id": str(row[equipment_col]),
            "entity_id": str(row[run_col]),
            "process_stage": stage,
            "timestamp": row[time_col],
            "label_type": "phm2018_challenge_label",  # 라벨 정의(TTF/제거율 등)는 저장소 문서로 확정 후 수정
            "label_value": row[label_col],
            "features": row[feature_cols].to_dict(),
        })
    return pd.DataFrame(records)


if __name__ == "__main__":
    import sys
    inspect_phm(sys.argv[1])
