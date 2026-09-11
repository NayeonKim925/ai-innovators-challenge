"""
트랙 B — 이상탐지 + 원인후보 엔진 (Metal Etch / machine 그룹)

★ 방법론 근거 ★
PCA 기반 이상탐지 + contribution plot(재구성 오차 기여도로 원인 변수
순위를 매기는 방법)은 새로 고른 게 아니라, 이 Metal Etch Data를 만든
원 논문(Wise, Gallagher, Butler, White, Barna, "A Comparison of Principal
Components Analysis, ... for Fault Detection in a Semiconductor Etch
Process", J. Chemometrics, 1999)이 바로 이 데이터로 검증한 방법이다.
TEP 같은 다른 도메인에서 검증된 걸 빌려오는 게 아니라, 이 데이터 자체의
저자가 쓴 방법이라 도메인 타당성 문제가 없다.

★ 이 스크립트가 하는 일 ★
1. 정상(label_value == "normal") machine 웨이퍼들로 "정상 운전 기준"을
   학습 (StandardScaler + PCA)
2. 결함 웨이퍼마다 재구성 오차(SPE)를 변수별로 분해해서, 기여도가 큰
   변수 순서로 "원인후보 랭킹"을 만듦
3. fault_names 라벨("TCP +50" 등)에서 진짜 원인 키워드(TCP/RF/Cl2/...)를
   뽑아 실제 변수 이름과 매칭 -> 이게 "정답"
4. 원인후보 랭킹 안에 정답이 top-k 안에 들어오는지로 precision@k 계산

★ 왜 machine 그룹부터 시작하나 ★
OES(파장 129채널)나 RFM(71변수, 이름 불명확)과 달리 machine은 변수
개수가 21개로 적고, fault_names의 키워드(TCP/RF/Cl2/BCl3/Pr/He)가
장비 제어변수 이름과 직접 대응될 가능성이 가장 높다.

실행 전 준비물 (metadata.csv와 같은 위치에서 실행):
    processed/metadata.csv
    processed/variable_names.json
    processed/features/machine/<entity_id>.npy

실행:
    python track_b_engine.py
"""
import json
import re
from math import comb

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer

META_PATH = "processed/metadata.csv"
VAR_NAMES_PATH = "processed/variable_names.json"
FEATURES_DIR = "processed/features/machine"
VARIANCE_TO_KEEP = 0.90  # PCA에서 남길 누적 분산 비율


def load_variable_names() -> list:
    with open(VAR_NAMES_PATH, "r", encoding="utf-8") as f:
        info = json.load(f)
    names = info["machine"]["variable_names"]
    if names is None:
        raise ValueError(
            "variable_names.json의 machine.variable_names가 비어 있습니다. "
            "preprocess.py가 제대로 돈 게 맞는지 확인하세요."
        )
    if isinstance(names, str):
        # preprocess.py의 예전 버전이 numpy 배열을 json.dump(default=str)로
        # 직렬화해서 "['Time ' 'Step Number ' ...]" 같은 문자열 하나로 뭉개 놓은
        # 파일을 열었을 때의 안전장치. preprocess.py를 최신 버전으로 다시
        # 돌렸다면 이 분기는 안 타야 정상이다.
        names = re.findall(r"'([^']*)'", names)
    return [str(n).strip() for n in names]


# 실측 확인된 21개 변수 전체를 검토해서 확정한 fault 키워드 -> 변수 매핑.
# 부분 문자열 매칭(예: "RF"가 "TCP Rfl Pwr"의 "Rfl"에 걸림, "Pr"이
# "He Press"의 "Press"에 걸림)이 실제로 오매칭을 냈던 걸 확인하고
# 도메인 판단으로 직접 확정한 표다. 이 장비는 TCP RF(플라즈마 생성)와
# 바이어스 RF(웨이퍼 쪽, 그냥 "RF"로 불림)가 물리적으로 별도
# 서브시스템이라 TCP 계열 변수를 RF 정답에 넣으면 안 된다. He Chuck이
# fault_names에 별도 라벨로 있다는 것도 Pr(챔버 압력)과 He Press(헬륨
# 척 압력)를 구분해서 다뤄야 한다는 근거다.
FAULT_KEYWORD_ALIASES = {
    "TCP": ["TCP Tuner", "TCP Phase Err", "TCP Impedance", "TCP Top Pwr", "TCP Rfl Pwr", "TCP Load"],
    "RF": ["RF Btm Pwr", "RF Btm Rfl Pwr", "RF Tuner", "RF Load", "RF Phase Err", "RF Pwr", "RF Impedance"],
    "CL2": ["Cl2 Flow"],
    "BCL3": ["BCl3 Flow"],
    "PR": ["Pressure"],       # He Press는 제외 -- 별개 서브시스템
    "HE": ["He Press"],       # "He Chuck" 라벨 전용
}

# Time, Step Number는 물리 신호가 아니라 인덱스라서 PCA 입력에서 뺀다.
# 포함시키면 "몇 번째 스텝인가"라는 값이 이상탐지에 노이즈로 섞여
# 들어가고, 원인후보 순위에도 절대 답이 될 수 없는 항목이 계속 낀다.
EXCLUDE_FROM_PCA = {"Time", "Step Number"}


FEATURE_STATS = ["mean", "std", "max_dev"]

# 실측 확인(검증3): 129개 웨이퍼 중 128개가 스텝 4.0, 5.0으로만 구성됨.
# 검증5c에서 이 두 스텝을 뭉치지 않고 따로 기준값을 계산했더니 TCP 계열
# 부호 일치율이 17%->67%로 개선된 바 있어, 같은 방식을 원인후보 랭킹
# 엔진 자체에도 반영한다.
CANONICAL_STEPS = [4.0, 5.0]


def summarize_trajectory_step_aware(matrix: np.ndarray, step_col_idx: int) -> np.ndarray:
    """스텝을 하나로 뭉치지 않고, CANONICAL_STEPS 각각에 대해 따로
    [평균, 표준편차, 최대편차]를 계산해서 이어붙인다. 이렇게 하면
    "스텝5에서만 튀는 이상"이 스텝4 데이터에 희석되지 않는다.

    CANONICAL_STEPS에 없는 스텝만 가진 웨이퍼(128/129 중 1개 예외로
    확인됨)는 해당 스텝 블록을 NaN으로 채우고, main()에서 정상 웨이퍼
    평균으로 대체(imputation)한다."""
    matrix = np.asarray(matrix, dtype=float)
    n_vars = matrix.shape[1]
    blocks = []
    for step in CANONICAL_STEPS:
        sub = matrix[matrix[:, step_col_idx] == step]
        if len(sub) == 0:
            blocks.extend([np.full(n_vars, np.nan) for _ in FEATURE_STATS])
            continue
        mean = np.nanmean(sub, axis=0)
        std = np.nanstd(sub, axis=0)
        max_dev = np.nanmax(np.abs(sub - mean), axis=0)
        blocks.extend([mean, std, max_dev])
    return np.concatenate(blocks)


def expand_variable_names(variable_names: list) -> list:
    """summarize_trajectory_step_aware()의 concatenate 순서
    (스텝4: mean 전체->std 전체->max_dev 전체, 스텝5: 동일 순서)와
    반드시 같은 순서로 이름을 만들어야 한다."""
    return [f"{v} (step{step}_{stat})"
            for step in CANONICAL_STEPS for stat in FEATURE_STATS for v in variable_names]


def base_variable_name(expanded_name: str) -> str:
    """'RF Pwr (step5.0_std)' -> 'RF Pwr'. FAULT_KEYWORD_ALIASES는 원래
    변수 이름 기준으로 적어뒀으므로, 매칭할 때는 스텝·통계 접미사를
    떼고 비교해야 한다."""
    return re.sub(r" \(step[\d.]+_(mean|std|max_dev)\)$", "", expanded_name)


def load_group(entity_ids: list, step_col_idx: int) -> dict:
    """entity_id -> 요약된 feature 벡터(dict)로 로드. 파일이 없는
    entity_id는 건너뛰고 어떤 게 빠졌는지 출력한다 (조용히 무시하지 않음)."""
    result = {}
    missing = []
    for eid in entity_ids:
        path = f"{FEATURES_DIR}/{eid}.npy"
        try:
            matrix = np.load(path, allow_pickle=True)
            result[eid] = summarize_trajectory_step_aware(matrix, step_col_idx)
        except FileNotFoundError:
            missing.append(eid)
    if missing:
        print(f"  (참고) machine 데이터가 없는 웨이퍼 {len(missing)}개는 건너뜀: {missing}")
    return result


def parse_fault_keyword(label_value: str) -> str:
    """'TCP +50', 'RF -12', 'He Chuck' 같은 라벨에서 앞의 키워드만
    뽑는다. 부호+숫자 부분(+50, -12)은 원인 변수 이름이 아니라 얼마나
    바꿨는지를 나타내는 값이라 제외한다."""
    match = re.match(r"([A-Za-z0-9]+)", label_value.strip())
    return match.group(1) if match else label_value.strip()


def match_keyword_to_variable(keyword: str, variable_names: list) -> list:
    """fault 키워드를 변수 이름과 매칭한다. variable_names는 이제
    'RF Pwr (mean)'처럼 통계 접미사가 붙어 있으므로, base_variable_name()
    으로 접미사를 뗀 뒤 비교한다.
    1순위: FAULT_KEYWORD_ALIASES에 있으면 그 표를 그대로 쓴다 (도메인
       판단으로 오매칭을 이미 걸러낸 정답).
    2순위: 표에 없는 새 키워드가 나오면 부분 문자열로 매칭하되,
       이건 검증 안 된 방식이라는 걸 화면에 경고로 남긴다."""
    key = keyword.strip().upper()
    if key in FAULT_KEYWORD_ALIASES:
        allowed = set(FAULT_KEYWORD_ALIASES[key])
        return [v for v in variable_names if base_variable_name(v) in allowed]

    print(f"  ⚠ '{keyword}'는 확정된 매칭표에 없어 부분 문자열로 대체 매칭함 (직접 검증 필요)")
    keyword_lower = keyword.lower()
    return [v for v in variable_names if keyword_lower in base_variable_name(v).lower()]


def rank_root_cause_candidates(
    faulty_vector: np.ndarray, scaler: StandardScaler, pca: PCA, variable_names: list
) -> pd.DataFrame:
    """정상 기준(scaler, pca)에 결함 웨이퍼 요약 벡터를 넣고, 변수별
    SPE(재구성 오차 제곱) 기여도로 원인후보 순위를 매긴다."""
    x_scaled = scaler.transform(faulty_vector.reshape(1, -1))
    x_projected = pca.transform(x_scaled)
    x_reconstructed = pca.inverse_transform(x_projected)
    residual_sq = (x_scaled - x_reconstructed) ** 2  # 변수별 SPE 기여도

    ranking = pd.DataFrame({
        "variable": variable_names,
        "contribution": residual_sq.flatten(),
    }).sort_values("contribution", ascending=False).reset_index(drop=True)
    ranking["rank"] = ranking.index + 1
    return ranking


def expected_random_precision(m: int, k: int, n: int) -> float:
    """N개 후보 중 정답 집합 크기가 m일 때, 무작위로 k개를 뽑아 하나라도
    맞을 확률 (초기하분포). precision@k가 이 값보다 뚜렷이 높아야
    알고리즘이 실제로 신호를 잡고 있다고 말할 수 있다 -- 예전에 19%가
    무작위(18.8%)와 구분 안 됐던 걸 매번 손으로 계산해서 확인했는데,
    이제 스크립트 자체가 매 실행마다 이 비교를 자동으로 보여준다."""
    if k >= n:
        return 1.0
    return 1 - comb(n - m, k) / comb(n, k)


def build_baseline_model():
    """정상 웨이퍼로 PCA 기준 모델을 한 번 학습해서, 이후 임의의
    entity_id를 몇 번이고 빠르게 채점할 수 있는 번들을 반환한다.
    (에이전트가 알람마다 이 무거운 학습을 새로 돌리지 않도록 분리한 것 --
    트랙 D의 agent_tools.py가 이 함수를 임포트해서 시작 시 한 번만 호출한다.)

    반환값: dict(meta, features, scaler, pca, pca_variable_names, keep_mask, imputer)
    """
    meta = pd.read_csv(META_PATH)
    if "label_reliable" not in meta.columns:
        meta["label_reliable"] = True  # flag_unreliable_labels.py 이전 구버전 metadata.csv 호환

    variable_names = load_variable_names()
    step_col_idx = variable_names.index("Step Number")

    keep_mask_base = np.array([v not in EXCLUDE_FROM_PCA for v in variable_names])
    keep_mask = np.tile(keep_mask_base, len(CANONICAL_STEPS) * len(FEATURE_STATS))
    expanded_names = expand_variable_names(variable_names)
    pca_variable_names = [v for v, keep in zip(expanded_names, keep_mask) if keep]

    all_ids = meta["entity_id"].tolist()
    features = load_group(all_ids, step_col_idx)

    normal_ids = meta.loc[meta["is_normal"], "entity_id"].tolist()
    normal_ids = [i for i in normal_ids if i in features]
    X_normal_raw = np.stack([features[i][keep_mask] for i in normal_ids])

    imputer = SimpleImputer(strategy="mean")
    X_normal = imputer.fit_transform(X_normal_raw)

    scaler = StandardScaler().fit(X_normal)
    X_normal_scaled = scaler.transform(X_normal)

    pca = PCA(n_components=VARIANCE_TO_KEEP, svd_solver="full")
    pca.fit(X_normal_scaled)

    return {
        "meta": meta,
        "features": features,
        "scaler": scaler,
        "pca": pca,
        "pca_variable_names": pca_variable_names,
        "keep_mask": keep_mask,
        "imputer": imputer,
    }


def score_entity(entity_id: int, model: dict) -> pd.DataFrame | None:
    """build_baseline_model()이 반환한 번들로 특정 entity_id 하나를
    채점한다. 그 웨이퍼의 features가 없으면 None을 반환한다 (지어내지
    않음). 에이전트의 '원인후보 랭킹' 도구가 바로 이 함수를 부른다."""
    features = model["features"]
    if entity_id not in features:
        return None
    faulty_vec_raw = features[entity_id][model["keep_mask"]].reshape(1, -1)
    faulty_vec = model["imputer"].transform(faulty_vec_raw)[0]
    return rank_root_cause_candidates(
        faulty_vec, model["scaler"], model["pca"], model["pca_variable_names"]
    )


def main():
    model = build_baseline_model()
    meta = model["meta"]
    features = model["features"]
    n_candidates = len(model["pca_variable_names"])
    print(f"정상 웨이퍼로 PCA 기준 모델 학습 완료, 주성분 {model['pca'].n_components_}개로 "
          f"분산 {model['pca'].explained_variance_ratio_.sum():.1%} 설명")

    faulty_rows = meta.loc[~meta["is_normal"]]
    faulty_rows = faulty_rows[faulty_rows["entity_id"].isin(features)]
    print(f"결함 웨이퍼 {len(faulty_rows)}개 평가")

    results = []
    hits = {1: 0, 2: 0, 3: 0}
    evaluated = 0
    answer_set_sizes = []  # 무작위 기준선 계산용
    unmatched_labels = []
    n_excluded_unreliable = 0

    for _, row in faulty_rows.iterrows():
        eid = row["entity_id"]
        label = row["label_value"]
        reliable = bool(row["label_reliable"])
        keyword = parse_fault_keyword(label)
        true_variables = match_keyword_to_variable(keyword, model["pca_variable_names"])

        ranking = score_entity(eid, model)
        top3 = ranking.head(3)["variable"].tolist()

        if not true_variables:
            unmatched_labels.append((eid, label, keyword))
            match_rank = None
        else:
            matched = ranking[ranking["variable"].isin(true_variables)]
            match_rank = int(matched["rank"].min()) if len(matched) else None

        used_for_precision = reliable and (match_rank is not None)
        if not reliable:
            n_excluded_unreliable += 1
        if used_for_precision:
            evaluated += 1
            answer_set_sizes.append(len(true_variables))
            for k in (1, 2, 3):
                if match_rank <= k:
                    hits[k] += 1

        results.append({
            "entity_id": eid,
            "fault_label": label,
            "fault_keyword": keyword,
            "matched_variable": true_variables,
            "top1_candidate": top3[0] if len(top3) > 0 else None,
            "top3_candidates": top3,
            "true_variable_rank": match_rank,
            "label_reliable": reliable,
            "used_for_precision": used_for_precision,
        })

    result_df = pd.DataFrame(results)
    result_df.to_csv("processed/track_b_root_cause_report.csv", index=False, encoding="utf-8-sig")

    print("\n=== 결과 (label_reliable=False 5건 포함 전체 21건 랭킹) ===")
    print(result_df[["entity_id", "fault_label", "top1_candidate", "true_variable_rank",
                      "label_reliable"]].to_string(index=False))

    if n_excluded_unreliable:
        print(f"\n({n_excluded_unreliable}건은 label_reliable=False라 precision@k 집계에서 제외, "
              f"랭킹 자체는 위 표에 그대로 있음)")

    if unmatched_labels:
        print(f"\n★ 키워드가 변수 이름과 자동 매칭 안 된 라벨 {len(unmatched_labels)}건 (직접 확인 필요):")
        for eid, label, keyword in unmatched_labels:
            print(f"  entity_id={eid}, label='{label}', keyword='{keyword}' -> 변수 이름 목록에서 안 보임")

    if evaluated > 0:
        print(f"\n=== precision@k (신뢰 가능 + 매칭된 {evaluated}건 기준) ===")
        # 무작위 기준선: 정답 집합 크기가 케이스마다 달라서, 케이스별
        # 초기하분포 기대값을 평균낸다 (예전에 손으로 계산했던 것과 동일한 방법)
        for k in (1, 2, 3):
            actual = hits[k] / evaluated
            random_baseline = np.mean([
                expected_random_precision(m, k, n_candidates) for m in answer_set_sizes
            ])
            gap = actual - random_baseline
            verdict = "무작위보다 뚜렷이 높음" if gap > 0.15 else (
                "무작위와 구분 어려움 -- 주의" if gap > -0.05 else "무작위보다 낮음 -- 문제 있음")
            print(f"  precision@{k}: {actual:.1%} ({hits[k]}/{evaluated})  "
                  f"| 무작위 기대값: {random_baseline:.1%}  | {verdict}")
    else:
        print("\n키워드 자동 매칭이 하나도 안 돼서 precision@k를 계산 못 했습니다. "
              "위 '자동 매칭 안 된 라벨' 목록을 보고 변수 이름과 직접 대조해보세요.")

    print("\n결과 파일: processed/track_b_root_cause_report.csv")


if __name__ == "__main__":
    main()
