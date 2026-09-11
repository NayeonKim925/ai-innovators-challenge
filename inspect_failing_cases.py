"""
남은 미해결 구간(Pr, BCl3) 7건만 원본 값을 직접 눈으로 대조하는
최종 진단 스크립트. 통계 방법을 더 정교하게 만드는 대신, 표본이 너무
작은(3~4건) 구간은 사람이 직접 숫자를 보고 판단하는 게 맞다.

실행: python inspect_failing_cases.py
"""
import re

import numpy as np
import pandas as pd

MACHINE_VARIABLES = [
    "Time", "Step Number", "BCl3 Flow", "Cl2 Flow", "RF Btm Pwr", "RF Btm Rfl Pwr",
    "Endpt A", "He Press", "Pressure", "RF Tuner", "RF Load", "RF Phase Err", "RF Pwr",
    "RF Impedance", "TCP Tuner", "TCP Phase Err", "TCP Impedance", "TCP Top Pwr",
    "TCP Rfl Pwr", "TCP Load", "Vat Valve",
]
TARGET_VAR = {"PR": "Pressure", "BCL3": "BCl3 Flow"}
META_PATH = "processed/metadata.csv"
FEATURES_DIR = "processed/features/machine"


def main():
    meta = pd.read_csv(META_PATH)
    step_idx = MACHINE_VARIABLES.index("Step Number")

    # 정상 웨이퍼의 스텝별 평균 -- "정상이면 이 값 근처"라는 기준선
    normal_ids = meta.loc[meta["is_normal"], "entity_id"].tolist()
    normal_rows = [np.asarray(np.load(f"{FEATURES_DIR}/{eid}.npy", allow_pickle=True), dtype=float)
                   for eid in normal_ids]
    pooled = np.concatenate(normal_rows, axis=0)
    step_normal_mean = {
        step: pooled[pooled[:, step_idx] == step].mean(axis=0)
        for step in np.unique(pooled[:, step_idx])
    }

    for _, row in meta.loc[~meta["is_normal"]].iterrows():
        eid, label = row["entity_id"], row["label_value"]
        m = re.match(r"([A-Za-z0-9]+)\s*([+-]\d+)?", label.strip())
        if not m or not m.group(2):
            continue
        keyword = m.group(1).upper()
        if keyword not in TARGET_VAR:
            continue

        var_name = TARGET_VAR[keyword]
        var_idx = MACHINE_VARIABLES.index(var_name)
        matrix = np.asarray(np.load(f"{FEATURES_DIR}/{eid}.npy", allow_pickle=True), dtype=float)

        print(f"\n{'='*60}")
        print(f"entity {eid}, label='{label}' -> 확인할 변수: {var_name}")
        print(f"{'='*60}")
        for step in np.unique(matrix[:, step_idx]):
            this_vals = matrix[matrix[:, step_idx] == step, var_idx]
            normal_val = step_normal_mean[step][var_idx]
            print(f"  스텝 {step}: 이 웨이퍼 평균={this_vals.mean():.2f} "
                  f"(범위 {this_vals.min():.2f}~{this_vals.max():.2f}), "
                  f"정상 평균={normal_val:.2f}, 차이={this_vals.mean()-normal_val:+.2f}")
        print(f"  -> 라벨이 '{label}'이면 위 차이가 부호 있게(± 방향) 뚜렷해야 정상입니다.")
        print(f"     차이가 거의 0이거나 부호가 반대면, 이 라벨이 이 웨이퍼에 안 맞을 수 있습니다.")


if __name__ == "__main__":
    main()
