"""
Metal Etch Data 전처리 스크립트

실행 전 준비물: MACHINE_Data.mat, OES_DATA.mat, RFM_DATA.mat 세 파일이
이 스크립트와 같은 폴더에 있어야 한다.
(다운로드 방법: METAL_ETCH_DATA.md 참고 -- 팀원 각자 로컬에 받아야 하며,
raw .mat 파일 자체는 git에 올리지 않는다 -- .gitignore 참고)

실행:
    python preprocess.py

출력 (전부 ./processed/ 에 생성, git에는 안 올라감):
    metadata.csv         -- 웨이퍼 단위 메타데이터 (실험번호, 라벨, 세 그룹 존재 여부)
    variable_names.json  -- 그룹별 변수 이름 / 단위 / 파장축
    features/<group>/<entity_id>.npy  -- 그룹별 원본 시계열 행렬 (웨이퍼당 1개 파일)

★ 왜 표 하나로 안 합치고 npy로 따로 저장하나 ★
machine(21변수)·oes(129파장채널)·rfm(71변수)은 변수 개수와 물리적 의미가
전부 달라서, 하나의 넓은 표로 합치면 서로 다른 물리량을 같은 컬럼처럼
보이게 만드는 실수가 된다. metadata.csv가 "이 웨이퍼에 어떤 그룹이
있는지"를 알려주는 색인 역할을 하고, 실제 시계열은 그룹별로 분리 보관한다.
"""
import json
import os
import numpy as np
import pandas as pd

from loaders.metal_etch_loader import load_metal_etch_all

MACHINE_PATH = "MACHINE_Data.mat"
OES_PATH = "OES_DATA.mat"
RFM_PATH = "RFM_DATA.mat"
OUT_DIR = "processed"


def main():
    for p in (MACHINE_PATH, OES_PATH, RFM_PATH):
        if not os.path.exists(p):
            raise FileNotFoundError(
                f"{p} 를 찾을 수 없습니다. 이 스크립트와 같은 폴더에 세 .mat 파일을 먼저 받아두세요."
            )

    records = load_metal_etch_all(MACHINE_PATH, OES_PATH, RFM_PATH)
    df = pd.DataFrame(records)

    os.makedirs(OUT_DIR, exist_ok=True)
    for group in ("machine", "oes", "rfm"):
        os.makedirs(f"{OUT_DIR}/features/{group}", exist_ok=True)

    # 그룹별 변수 정보는 그룹당 한 번만 있으면 되므로 대표 1행에서 추출
    variable_info = {}
    for group in df["variable_group"].unique():
        row = df[df["variable_group"] == group].iloc[0]
        variable_info[group] = {
            "variable_names": row.get("variable_names"),
            "wave_axis": row.get("wave_axis"),
            "units": row.get("units"),
        }
    with open(f"{OUT_DIR}/variable_names.json", "w", encoding="utf-8") as f:
        json.dump(variable_info, f, ensure_ascii=False, indent=2, default=str)

    # 웨이퍼 x 그룹 단위 원본 시계열은 npy로 개별 저장.
    # dtype을 object로 강제하지 않는다 -- 정상적인 (시간 x 변수) 숫자
    # 행렬이면 float 배열로 그대로 저장돼야 용량도 작고 다루기 쉽다.
    # allow_pickle=True는 혹시 배열 형태가 고르지 않아 numpy가 object로
    # 폴백하는 경우에 대한 안전장치로만 남겨둔다.
    for _, row in df.iterrows():
        out_path = f"{OUT_DIR}/features/{row['variable_group']}/{row['entity_id']}.npy"
        np.save(out_path, np.asarray(row["features"]), allow_pickle=True)

    # 웨이퍼 단위 메타데이터: 실험번호, 라벨, 그룹별 존재 여부를 한 표로
    meta_rows = []
    for entity_id, group_df in df.groupby("entity_id"):
        groups_present = set(group_df["variable_group"])
        first = group_df.iloc[0]
        meta_rows.append({
            "entity_id": entity_id,
            "experiment_id": first["experiment_id"],
            "label_value": first["label_value"],          # "normal" 또는 실제 결함 유형
            "is_normal": first["label_value"] == "normal",
            "has_machine": "machine" in groups_present,
            "has_oes": "oes" in groups_present,
            "has_rfm": "rfm" in groups_present,
            "complete_case": groups_present == {"machine", "oes", "rfm"},
        })
    meta_df = pd.DataFrame(meta_rows).sort_values("entity_id").reset_index(drop=True)
    meta_df.to_csv(f"{OUT_DIR}/metadata.csv", index=False, encoding="utf-8-sig")

    print(f"총 웨이퍼: {len(meta_df)}개")
    print(f"3개 그룹(machine/oes/rfm) 모두 있는 웨이퍼: {meta_df['complete_case'].sum()}개")
    print("라벨 분포:")
    print(meta_df["label_value"].value_counts().to_string())
    print(f"\n결과물 위치: ./{OUT_DIR}/metadata.csv, ./{OUT_DIR}/variable_names.json, ./{OUT_DIR}/features/")


if __name__ == "__main__":
    main()
