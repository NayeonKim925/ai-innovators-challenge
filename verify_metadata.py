"""
metadata.csv / entity_id 매칭 / label_value 정합성을 실제로 증명하는
검증 스크립트.

지금까지 확인한 건 "구조"가 맞다는 것(개수, 존재 여부)뿐이고,
"entity_id가 세 그룹에서 진짜 같은 물리적 웨이퍼를 가리키는가"와
"label_value가 정확한 entity_id에 붙어 있는가"는 증명되지 않은
상태였다. 이 스크립트는 그 두 가지를 실제로 검증한다.

실행 전 준비물 (metadata.csv와 같은 위치에서 실행):
    MACHINE_Data.mat, OES_DATA.mat, RFM_DATA.mat (원본 3개 파일)
    processed/metadata.csv
    processed/features/{machine,oes,rfm}/*.npy

실행:
    python verify_metadata.py
"""
import re

import numpy as np
import pandas as pd
import scipy.io
from scipy.stats import pearsonr, f_oneway

from loaders.metal_etch_loader import _unwrap

MACHINE_PATH = "MACHINE_Data.mat"
OES_PATH = "OES_DATA.mat"
RFM_PATH = "RFM_DATA.mat"
META_PATH = "processed/metadata.csv"
FEATURES_DIR = "processed/features"

MACHINE_VARIABLES = [
    "Time", "Step Number", "BCl3 Flow", "Cl2 Flow", "RF Btm Pwr", "RF Btm Rfl Pwr",
    "Endpt A", "He Press", "Pressure", "RF Tuner", "RF Load", "RF Phase Err", "RF Pwr",
    "RF Impedance", "TCP Tuner", "TCP Phase Err", "TCP Impedance", "TCP Top Pwr",
    "TCP Rfl Pwr", "TCP Load", "Vat Valve",
]

FAULT_KEYWORD_ALIASES = {
    "TCP": ["TCP Tuner", "TCP Phase Err", "TCP Impedance", "TCP Top Pwr", "TCP Rfl Pwr", "TCP Load"],
    "RF": ["RF Btm Pwr", "RF Btm Rfl Pwr", "RF Tuner", "RF Load", "RF Phase Err", "RF Pwr", "RF Impedance"],
    "CL2": ["Cl2 Flow"],
    "BCL3": ["BCl3 Flow"],
    "PR": ["Pressure"],
    "HE": ["He Press"],
}


# ---------------------------------------------------------------------------
# 검증 1: INFORMATION 필드 원문 읽기 -- 지금까지 한 번도 내용을 안 읽어봤다.
# ---------------------------------------------------------------------------
def check_1_print_information():
    print("=" * 70)
    print("검증 1: INFORMATION 필드 원문 (지금까지 미확인)")
    print("=" * 70)
    for path, label in [(MACHINE_PATH, "MACHINE"), (OES_PATH, "OES"), (RFM_PATH, "RFM")]:
        raw = scipy.io.loadmat(path, simplify_cells=True)
        mat = _unwrap(raw)
        info = mat.get("INFORMATION")
        print(f"\n--- {label}_Data.mat INFORMATION ---")
        if isinstance(info, str):
            print(info)
        else:
            for line in info:
                print(str(line).rstrip())


# ---------------------------------------------------------------------------
# 검증 2: Time 컬럼이 실제로 단조증가하는가 (행 순서가 시간 순서가 맞는가)
# ---------------------------------------------------------------------------
def check_2_time_monotonic():
    print("\n" + "=" * 70)
    print("검증 2: machine npy의 Time 컬럼이 단조증가하는가")
    print("=" * 70)
    time_idx = MACHINE_VARIABLES.index("Time")
    meta = pd.read_csv(META_PATH)
    bad = []
    for eid in meta["entity_id"]:
        try:
            matrix = np.load(f"{FEATURES_DIR}/machine/{eid}.npy", allow_pickle=True)
        except FileNotFoundError:
            continue
        time_col = np.asarray(matrix)[:, time_idx].astype(float)
        if not np.all(np.diff(time_col) >= 0):
            bad.append(eid)
    if bad:
        print(f"  ✗ 단조증가 안 하는 웨이퍼 {len(bad)}개: {bad} -- 행 순서가 시간순이 아닐 수 있음")
    else:
        print(f"  ✓ 전체 웨이퍼에서 Time이 단조증가함 -- 행 순서 = 시간 순서로 봐도 됨")


# ---------------------------------------------------------------------------
# 검증 3: Step Number의 실제 값 분포/패턴
# ---------------------------------------------------------------------------
def check_3_step_number_pattern():
    print("\n" + "=" * 70)
    print("검증 3: Step Number 컬럼 패턴 (스텝별 분리 가능한 구조인지)")
    print("=" * 70)
    step_idx = MACHINE_VARIABLES.index("Step Number")
    meta = pd.read_csv(META_PATH)
    step_sets = {}
    for eid in meta["entity_id"]:
        try:
            matrix = np.load(f"{FEATURES_DIR}/machine/{eid}.npy", allow_pickle=True)
        except FileNotFoundError:
            continue
        step_col = np.asarray(matrix)[:, step_idx]
        step_sets[eid] = tuple(sorted(np.unique(step_col)))

    from collections import Counter
    pattern_counts = Counter(step_sets.values())
    print(f"  전체 {len(step_sets)}개 웨이퍼의 스텝 값 조합 분포 (상위 5개):")
    for pattern, cnt in pattern_counts.most_common(5):
        print(f"    스텝 {pattern}: {cnt}개 웨이퍼")
    print("  -> 대부분의 웨이퍼가 같은 스텝 조합을 쓴다면, 그 스텝 경계로")
    print("     나눠서 통계 내는 게 안전하다.")


def check_2b_time_monotonic_per_step():
    """검증2의 개선판. Time이 스텝이 바뀔 때 리셋되는 방식일 수 있으므로,
    전체가 아니라 '같은 스텝 번호로 묶인 구간 안에서만' 단조증가하는지
    확인한다. 이게 통과하면 검증2의 실패는 데이터 오류가 아니라 스텝별
    리셋 때문이라는 뜻이다."""
    print("\n" + "=" * 70)
    print("검증 2b: 스텝 구간 '안에서만' Time이 단조증가하는가 (검증2 재해석)")
    print("=" * 70)
    time_idx = MACHINE_VARIABLES.index("Time")
    step_idx = MACHINE_VARIABLES.index("Step Number")
    meta = pd.read_csv(META_PATH)
    bad = []
    for eid in meta["entity_id"]:
        try:
            matrix = np.asarray(np.load(f"{FEATURES_DIR}/machine/{eid}.npy", allow_pickle=True), dtype=float)
        except FileNotFoundError:
            continue
        steps, time_col = matrix[:, step_idx], matrix[:, time_idx]
        ok = True
        for step_val in np.unique(steps):
            segment = time_col[steps == step_val]
            if not np.all(np.diff(segment) >= 0):
                ok = False
                break
        if not ok:
            bad.append(eid)
    if bad:
        print(f"  ✗ 스텝 구간 안에서도 역행하는 웨이퍼 {len(bad)}개: {bad}")
        print("     -> 이건 스텝 리셋으로 설명 안 됨, 진짜 순서 문제일 가능성")
    else:
        print("  ✓ 스텝 구간 안에서는 전부 단조증가함")
        print("     -> 검증2의 실패는 스텝이 바뀔 때 Time이 리셋되는 정상 동작이었던 것으로 보임")


def check_5b_label_sign_consistency_signed_peak():
    """검증5의 개선판. 전체 구간 평균 대신, 정상 대비 '가장 크게 벗어난
    시점의 부호 있는 값(signed peak deviation)'을 쓴다. 검증5가 낮게
    나온 게 매칭 문제인지 평균 방식의 한계인지 구분하기 위한 것."""
    print("\n" + "=" * 70)
    print("검증 5b: signed peak deviation 기준 부호 일치 검사 (검증5 재해석)")
    print("=" * 70)
    meta = pd.read_csv(META_PATH)
    normal_ids = meta.loc[meta["is_normal"], "entity_id"].tolist()

    normal_rows = []
    for eid in normal_ids:
        try:
            matrix = np.load(f"{FEATURES_DIR}/machine/{eid}.npy", allow_pickle=True)
        except FileNotFoundError:
            continue
        normal_rows.append(np.asarray(matrix, dtype=float))
    pop_mean = np.concatenate(normal_rows, axis=0).mean(axis=0)  # 시점 단위로 풀링한 정상 기준
    pop_std = np.concatenate(normal_rows, axis=0).std(axis=0)
    pop_std[pop_std == 0] = 1e-9

    faulty_rows = meta.loc[~meta["is_normal"]]
    match_count, checkable_count = 0, 0

    for _, row in faulty_rows.iterrows():
        eid, label = row["entity_id"], row["label_value"]
        m = re.match(r"([A-Za-z0-9]+)\s*([+-]\d+)?", label.strip())
        if not m or not m.group(2):
            continue
        keyword, signed = m.group(1).upper(), m.group(2)
        expected_sign = 1 if signed.startswith("+") else -1
        if keyword not in FAULT_KEYWORD_ALIASES:
            continue
        try:
            matrix = np.asarray(np.load(f"{FEATURES_DIR}/machine/{eid}.npy", allow_pickle=True), dtype=float)
        except FileNotFoundError:
            continue

        devs = matrix - pop_mean  # (시간 x 변수), 정상 기준 대비 편차
        z = devs / pop_std
        candidate_idx = [MACHINE_VARIABLES.index(v) for v in FAULT_KEYWORD_ALIASES[keyword]]

        # 후보 변수들 중, 전체 시간에 걸쳐 |z|가 가장 큰 (시점, 변수) 하나를 고른다
        sub_z = z[:, candidate_idx]
        flat_idx = np.argmax(np.abs(sub_z))
        t_idx, c_idx = np.unravel_index(flat_idx, sub_z.shape)
        best_var = MACHINE_VARIABLES[candidate_idx[c_idx]]
        actual_sign = 1 if sub_z[t_idx, c_idx] > 0 else -1

        checkable_count += 1
        ok = actual_sign == expected_sign
        match_count += int(ok)
        mark = "✓" if ok else "✗"
        print(f"  {mark} entity {eid} label='{label}' -> {best_var} 시점{t_idx} "
              f"(z={sub_z[t_idx, c_idx]:+.2f}, 기대 부호={'+' if expected_sign>0 else '-'})")

    if checkable_count:
        print(f"\n  부호 일치 {match_count}/{checkable_count}건 ({match_count/checkable_count:.1%})")
        print("  (검증5의 50%보다 이게 유의미하게 높다면, 매칭 자체는 맞고")
        print("   평균 방식이 신호를 죽이고 있었다는 뜻)")
    else:
        print("  체크 가능한 라벨이 없음")


def check_5c_label_sign_consistency_step_aware():
    """★ 결정적 테스트 ★
    검증5/5b는 스텝4·스텝5를 하나로 뭉쳐서 '정상값'을 계산했다. 이 두
    스텝이 서로 다른 공정 구간(baseline이 다를 가능성)이라면, 뭉쳐서
    계산한 평균·표준편차 자체가 신호를 희석시켰을 수 있다 -- 트랙 B의
    precision@k가 낮았던 것과 같은 원인일 가능성. 이 검사는 스텝별로
    따로 기준값을 계산해서 같은 스텝끼리만 비교한다.

    이 결과가 검증5b보다 뚜렷이 높으면(예: 80%+): 매칭 자체는 문제없고
    통계 방식이 원인이었다는 뜻 -- metadata.csv를 신뢰하고 넘어가도 됨.
    이 결과도 여전히 낮으면: 통계 방식 문제가 아니라 매칭 자체를
    의심해야 하는 근거가 됨."""
    print("\n" + "=" * 70)
    print("검증 5c: 스텝별 기준값으로 재계산한 부호 일치 검사 (결정적 테스트)")
    print("=" * 70)
    step_idx = MACHINE_VARIABLES.index("Step Number")
    meta = pd.read_csv(META_PATH)
    normal_ids = meta.loc[meta["is_normal"], "entity_id"].tolist()

    normal_rows = []
    for eid in normal_ids:
        try:
            matrix = np.load(f"{FEATURES_DIR}/machine/{eid}.npy", allow_pickle=True)
        except FileNotFoundError:
            continue
        normal_rows.append(np.asarray(matrix, dtype=float))
    pooled = np.concatenate(normal_rows, axis=0)

    # 스텝별로 따로 기준값 계산 (검증5/5b와의 핵심 차이)
    step_baseline = {}
    for step_val in np.unique(pooled[:, step_idx]):
        subset = pooled[pooled[:, step_idx] == step_val]
        std = subset.std(axis=0)
        std[std == 0] = 1e-9
        step_baseline[step_val] = (subset.mean(axis=0), std)
    print(f"  스텝별 기준값 계산 완료: {list(step_baseline.keys())}")

    faulty_rows = meta.loc[~meta["is_normal"]]
    match_count, checkable_count = 0, 0
    per_entity_results = []

    for _, row in faulty_rows.iterrows():
        eid, label = row["entity_id"], row["label_value"]
        m = re.match(r"([A-Za-z0-9]+)\s*([+-]\d+)?", label.strip())
        if not m or not m.group(2):
            continue
        keyword, signed = m.group(1).upper(), m.group(2)
        expected_sign = 1 if signed.startswith("+") else -1
        if keyword not in FAULT_KEYWORD_ALIASES:
            continue
        try:
            matrix = np.asarray(np.load(f"{FEATURES_DIR}/machine/{eid}.npy", allow_pickle=True), dtype=float)
        except FileNotFoundError:
            continue

        # 각 행을 '그 행의 스텝에 맞는' 기준값으로 z-score 계산 (스텝을 섞지 않음)
        z = np.zeros_like(matrix)
        for step_val, (mean, std) in step_baseline.items():
            mask = matrix[:, step_idx] == step_val
            z[mask] = (matrix[mask] - mean) / std

        candidate_idx = [MACHINE_VARIABLES.index(v) for v in FAULT_KEYWORD_ALIASES[keyword]]
        sub_z = z[:, candidate_idx]
        flat_idx = np.argmax(np.abs(sub_z))
        t_idx, c_idx = np.unravel_index(flat_idx, sub_z.shape)
        best_var = MACHINE_VARIABLES[candidate_idx[c_idx]]
        actual_sign = 1 if sub_z[t_idx, c_idx] > 0 else -1

        checkable_count += 1
        ok = actual_sign == expected_sign
        match_count += int(ok)
        mark = "✓" if ok else "✗"
        print(f"  {mark} entity {eid} label='{label}' -> {best_var} "
              f"(z={sub_z[t_idx, c_idx]:+.2f}, 기대 부호={'+' if expected_sign>0 else '-'})")

        # TCP Top Pwr(사람이 직접 조작하는 유일한 TCP 변수) 자체의 부호도
        # 따로 기록 -- 아래 breakdown에서 TCP 후보를 좁힐 때 쓴다
        top_pwr_sign_ok = None
        if keyword == "TCP":
            top_pwr_idx = MACHINE_VARIABLES.index("TCP Top Pwr")
            top_pwr_z = z[:, top_pwr_idx]
            peak_t = np.argmax(np.abs(top_pwr_z))
            top_pwr_sign_ok = (1 if top_pwr_z[peak_t] > 0 else -1) == expected_sign

        per_entity_results.append({
            "entity_id": eid, "keyword": keyword, "ok": ok,
            "best_var": best_var, "top_pwr_sign_ok": top_pwr_sign_ok,
        })

    if checkable_count:
        ratio = match_count / checkable_count
        print(f"\n  부호 일치 {match_count}/{checkable_count}건 ({ratio:.1%})")
        if ratio >= 0.8:
            print("  -> 검증5b보다 뚜렷이 높음: 매칭은 문제없고 통계 방식이 원인이었음. 트랙 B로 진행해도 됨.")
        elif ratio <= 0.6:
            print("  -> 여전히 낮음: 통계 방식 문제가 아니라 매칭 자체를 의심해야 함.")
        else:
            print("  -> 애매한 구간: 판단하려면 사람이 직접 몇 건을 눈으로 대조해보는 게 낫다.")

        print("\n  --- 계열(키워드)별 세부 breakdown ---")
        by_family = {}
        for r in per_entity_results:
            by_family.setdefault(r["keyword"], []).append(r["ok"])
        for fam, results in sorted(by_family.items()):
            n_ok = sum(results)
            print(f"    {fam}: {n_ok}/{len(results)} ({n_ok/len(results):.0%})")
        print("  -> 특정 계열 하나만 유독 낮다면, 매칭 전체가 아니라 그 계열의")
        print("     FAULT_KEYWORD_ALIASES 정의 자체를 의심하는 게 우선이다")
        print("     (전체가 골고루 낮아야 '매칭 자체가 깨졌다'는 가설에 힘이 실린다).")

        if "TCP" in by_family:
            print("\n  --- TCP 후보를 'TCP Top Pwr' 하나로 좁히면? (사람이 직접 조작하는 유일한 변수) ---")
            print("     (나머지 5개는 자동 임피던스 매칭 보정 신호라 방향성이 보장 안 될 수 있음)")
            tcp_narrow_ok, tcp_narrow_total = 0, 0
            for r in per_entity_results:
                if r["keyword"] != "TCP":
                    continue
                tcp_narrow_total += 1
                if r["best_var"] == "TCP Top Pwr" and r["ok"]:
                    tcp_narrow_ok += 1
                elif r["best_var"] != "TCP Top Pwr":
                    # 다른 변수가 1등이었지만, TCP Top Pwr 자체의 부호는 맞는지 별도 확인
                    tcp_narrow_ok += int(r["top_pwr_sign_ok"])
            print(f"     TCP Top Pwr 단독 기준 일치: {tcp_narrow_ok}/{tcp_narrow_total} "
                  f"({tcp_narrow_ok/tcp_narrow_total:.0%})")


def check_6_experiment_separation(group_name: str):
    """entity_id/experiment_id 배정이 실제 물리적 그룹과 맞는지, 검증4와
    다른 독립적인 방법으로 확인한다. 문서에 '실험이 몇 주 간격으로
    진행돼 평균·공분산 구조가 다르다'고 명시돼 있으므로, 이 그룹
    (oes/rfm) 자체의 데이터에서도 experiment_id별로 유의미하게 다른
    분포가 보여야 한다. 이 통계적 성질은 row 개수 같은 별도 가정 없이
    검증할 수 있어서 검증4의 약점을 보완한다."""
    print(f"\n  [{group_name}]")
    meta = pd.read_csv(META_PATH)
    data_by_exp = {}
    for eid, exp in zip(meta["entity_id"], meta["experiment_id"]):
        try:
            matrix = np.asarray(np.load(f"{FEATURES_DIR}/{group_name}/{eid}.npy", allow_pickle=True), dtype=float)
        except FileNotFoundError:
            continue
        data_by_exp.setdefault(exp, []).append(np.nanmean(matrix, axis=0))

    arrays = {exp: np.stack(v) for exp, v in data_by_exp.items() if len(v) >= 2}
    if len(arrays) < 2:
        print("    그룹이 부족해서 계산 불가")
        return

    n_dims = next(iter(arrays.values())).shape[1]
    sig_count = 0
    for d in range(n_dims):
        groups = [arr[:, d] for arr in arrays.values()]
        try:
            _, p = f_oneway(*groups)
            if p < 0.05:
                sig_count += 1
        except Exception:
            continue
    ratio = sig_count / n_dims
    verdict = "강한 증거" if ratio > 0.5 else ("약한 신호" if ratio > 0.2 else "증거 없음")
    print(f"    전체 {n_dims}개 차원 중 실험 간 유의미하게 다른 차원 {sig_count}개 "
          f"({ratio:.0%}) -> {verdict}")


# ---------------------------------------------------------------------------
# 검증 4: entity_id가 세 그룹에서 같은 물리적 웨이퍼인가
#   -> machine의 시계열 길이(행 수)가 길수록 oes/rfm도 길어야 한다.
#      상관관계가 높으면 entity_id 매칭이 진짜 같은 run을 가리킨다는 강한 증거.
#      0에 가까우면 매칭이 틀렸다는 증거.
# ---------------------------------------------------------------------------
def check_4_cross_group_row_count_correlation():
    print("\n" + "=" * 70)
    print("검증 4: entity_id가 세 그룹에서 같은 물리적 웨이퍼인가 (row 개수 상관관계)")
    print("=" * 70)
    meta = pd.read_csv(META_PATH)
    complete = meta[meta["complete_case"]]["entity_id"].tolist()

    rows = {"machine": [], "oes": [], "rfm": []}
    used_ids = []
    for eid in complete:
        try:
            n_machine = np.load(f"{FEATURES_DIR}/machine/{eid}.npy", allow_pickle=True).shape[0]
            n_oes = np.load(f"{FEATURES_DIR}/oes/{eid}.npy", allow_pickle=True).shape[0]
            n_rfm = np.load(f"{FEATURES_DIR}/rfm/{eid}.npy", allow_pickle=True).shape[0]
        except FileNotFoundError:
            continue
        rows["machine"].append(n_machine)
        rows["oes"].append(n_oes)
        rows["rfm"].append(n_rfm)
        used_ids.append(eid)

    print(f"  complete_case {len(used_ids)}개로 계산")
    if len(used_ids) < 2:
        print(f"  ⚠ 비교 가능한 웨이퍼가 {len(used_ids)}개뿐이라 상관계수 계산 불가 (2개 이상 필요)")
        return
    for group in ("oes", "rfm"):
        machine_arr, group_arr = np.array(rows["machine"]), np.array(rows[group])
        if machine_arr.std() == 0 or group_arr.std() == 0:
            print(f"  machine vs {group}: row 개수에 변동이 없어 상관계수 계산 불가 "
                  f"(machine std={machine_arr.std():.2f}, {group} std={group_arr.std():.2f})")
            continue
        r, p = pearsonr(machine_arr, group_arr)
        verdict = "강한 증거 (같은 run일 가능성 높음)" if r > 0.5 else (
            "약한 신호, 추가 확인 필요" if r > 0.2 else "증거 없음 -- entity_id 매칭 재검토 필요")
        print(f"  machine vs {group} row 개수 상관계수 r={r:.3f} (p={p:.4f}) -> {verdict}")


# ---------------------------------------------------------------------------
# 검증 5: 결함 라벨의 부호(+/-)와 실측 편차 방향이 일치하는가
#   -> 방향까지 맞으면 label_value가 entity_id에 정확히 붙었다는 가장 강한 증거.
#      family 6~7개 중 어느 변수가 진짜 정답인지도 이걸로 좁힐 수 있다.
# ---------------------------------------------------------------------------
def check_5_label_sign_consistency():
    print("\n" + "=" * 70)
    print("검증 5: 결함 라벨 부호(+/-)와 실측 편차 방향 일치 검사")
    print("=" * 70)
    meta = pd.read_csv(META_PATH)
    normal_ids = meta.loc[meta["is_normal"], "entity_id"].tolist()

    normal_means = []
    for eid in normal_ids:
        try:
            matrix = np.load(f"{FEATURES_DIR}/machine/{eid}.npy", allow_pickle=True)
        except FileNotFoundError:
            continue
        normal_means.append(np.nanmean(np.asarray(matrix, dtype=float), axis=0))
    normal_means = np.stack(normal_means)
    pop_mean = normal_means.mean(axis=0)
    pop_std = normal_means.std(axis=0)
    pop_std[pop_std == 0] = 1e-9  # 0나눗셈 방지

    faulty_rows = meta.loc[~meta["is_normal"]]
    match_count, checkable_count = 0, 0

    for _, row in faulty_rows.iterrows():
        eid, label = row["entity_id"], row["label_value"]
        m = re.match(r"([A-Za-z0-9]+)\s*([+-]\d+)?", label.strip())
        if not m or not m.group(2):
            continue  # He Chuck처럼 부호 없는 라벨은 이 검사 대상 아님
        keyword, signed = m.group(1).upper(), m.group(2)
        expected_sign = 1 if signed.startswith("+") else -1
        if keyword not in FAULT_KEYWORD_ALIASES:
            continue

        try:
            matrix = np.load(f"{FEATURES_DIR}/machine/{eid}.npy", allow_pickle=True)
        except FileNotFoundError:
            continue
        wafer_mean = np.nanmean(np.asarray(matrix, dtype=float), axis=0)
        z = (wafer_mean - pop_mean) / pop_std

        candidate_idx = [MACHINE_VARIABLES.index(v) for v in FAULT_KEYWORD_ALIASES[keyword]]
        best_idx = candidate_idx[np.argmax(np.abs(z[candidate_idx]))]
        best_var = MACHINE_VARIABLES[best_idx]
        actual_sign = 1 if z[best_idx] > 0 else -1

        checkable_count += 1
        ok = actual_sign == expected_sign
        match_count += int(ok)
        mark = "✓" if ok else "✗"
        print(f"  {mark} entity {eid} label='{label}' -> 가장 크게 튄 후보: {best_var} "
              f"(z={z[best_idx]:+.2f}, 기대 부호={'+' if expected_sign>0 else '-'})")

    if checkable_count:
        print(f"\n  부호 일치 {match_count}/{checkable_count}건 "
              f"({match_count/checkable_count:.1%}) -- 이게 낮으면 label-entity_id "
              f"매칭 자체를 의심해야 함")
    else:
        print("  부호가 있는 라벨을 하나도 못 찾음 -- 정규식 파싱 확인 필요")


if __name__ == "__main__":
    check_1_print_information()
    check_2_time_monotonic()
    check_2b_time_monotonic_per_step()
    check_3_step_number_pattern()
    check_5_label_sign_consistency()
    check_5b_label_sign_consistency_signed_peak()
    check_5c_label_sign_consistency_step_aware()

    # machine 단독 스코프 결정에 따라 검증4·6(oes/rfm 교차검증)은 기본
    # 실행에서 뺐다. oes/rfm을 다시 쓰기로 하면 아래 주석을 풀 것.
    # check_4_cross_group_row_count_correlation()
    # check_6_experiment_separation("oes")
    # check_6_experiment_separation("rfm")
