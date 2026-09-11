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

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

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
    # preprocess.py가 numpy 배열을 json.dump(..., default=str)로 저장했기 때문에
    # 여기서 실제로 받는 값은 파이썬 리스트가 아니라 numpy repr 문자열
    # ("['Time          ' 'Step Number   ' ...]") 그대로다. [str(n) for n in names]로
    # 문자열을 그냥 순회하면 글자 단위(363개)로 쪼개져서 21개 변수 이름이 나오지
    # 않는다 -- 이 부분만 문자열을 파싱하도록 고친다.
    if isinstance(names, str):
        names = re.findall(r"'([^']*)'", names)
    return [str(n).strip() for n in names]


def summarize_trajectory(matrix: np.ndarray) -> np.ndarray:
    """웨이퍼 한 장의 (시간 x 변수) 원본 행렬을 변수별 평균값 1개로
    요약한다. 시간 길이가 웨이퍼마다 달라도 이 요약 벡터의 길이(=변수
    개수)는 항상 같아서 PCA에 바로 넣을 수 있다.

    ★ 한계 ★ 평균만 쓰면 "언제 이상이 튀었는지"라는 시간 정보는
    버려진다. 1차 baseline이고, 다음 개선 지점은 표준편차·최대편차
    같은 통계량을 추가하거나 시간 구간별로 나눠 보는 것이다."""
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)
    return np.nanmean(matrix, axis=0)


def load_group(entity_ids: list) -> dict:
    """entity_id -> 요약된 feature 벡터(dict)로 로드. 파일이 없는
    entity_id는 건너뛰고 어떤 게 빠졌는지 출력한다 (조용히 무시하지 않음)."""
    result = {}
    missing = []
    for eid in entity_ids:
        path = f"{FEATURES_DIR}/{eid}.npy"
        try:
            matrix = np.load(path, allow_pickle=True)
            result[eid] = summarize_trajectory(matrix)
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
    """fault 키워드(TCP/RF/Cl2/...)가 변수 이름 문자열 안에 부분
    포함되는 변수들을 정답 후보로 반환. 대소문자 구분 안 함.
    매칭이 하나도 없으면 빈 리스트를 반환하고, main()에서 이걸 사람이
    직접 확인하도록 출력한다 -- 자동으로 넘겨짚지 않는다."""
    keyword_lower = keyword.lower()
    return [v for v in variable_names if keyword_lower in v.lower()]


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


def main():
    meta = pd.read_csv(META_PATH)
    variable_names = load_variable_names()
    print(f"machine 변수 {len(variable_names)}개: {variable_names}")

    # machine 그룹은 129개 웨이퍼 전부에 존재하는 것으로 확인됐음 (has_machine 전부 True)
    all_ids = meta["entity_id"].tolist()
    features = load_group(all_ids)

    normal_ids = meta.loc[meta["is_normal"], "entity_id"].tolist()
    normal_ids = [i for i in normal_ids if i in features]
    faulty_rows = meta.loc[~meta["is_normal"]]
    faulty_rows = faulty_rows[faulty_rows["entity_id"].isin(features)]

    print(f"정상 웨이퍼 {len(normal_ids)}개로 기준 모델 학습, 결함 웨이퍼 {len(faulty_rows)}개 평가")

    X_normal = np.stack([features[i] for i in normal_ids])
    scaler = StandardScaler().fit(X_normal)
    X_normal_scaled = scaler.transform(X_normal)

    pca = PCA(n_components=VARIANCE_TO_KEEP, svd_solver="full")
    pca.fit(X_normal_scaled)
    print(f"PCA 주성분 {pca.n_components_}개로 분산 {pca.explained_variance_ratio_.sum():.1%} 설명")

    results = []
    hits = {1: 0, 2: 0, 3: 0}
    evaluated = 0
    unmatched_labels = []

    for _, row in faulty_rows.iterrows():
        eid = row["entity_id"]
        label = row["label_value"]
        keyword = parse_fault_keyword(label)
        true_variables = match_keyword_to_variable(keyword, variable_names)

        ranking = rank_root_cause_candidates(features[eid], scaler, pca, variable_names)
        top3 = ranking.head(3)["variable"].tolist()

        if not true_variables:
            unmatched_labels.append((eid, label, keyword))
            match_rank = None
        else:
            matched = ranking[ranking["variable"].isin(true_variables)]
            match_rank = int(matched["rank"].min()) if len(matched) else None
            if match_rank is not None:
                evaluated += 1
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
        })

    result_df = pd.DataFrame(results)
    result_df.to_csv("processed/track_b_root_cause_report.csv", index=False, encoding="utf-8-sig")

    print("\n=== 결과 ===")
    print(result_df[["entity_id", "fault_label", "top1_candidate", "true_variable_rank"]].to_string(index=False))

    if unmatched_labels:
        print(f"\n★ 키워드가 변수 이름과 자동 매칭 안 된 라벨 {len(unmatched_labels)}건 (직접 확인 필요):")
        for eid, label, keyword in unmatched_labels:
            print(f"  entity_id={eid}, label='{label}', keyword='{keyword}' -> 변수 이름 목록에서 안 보임")

    if evaluated > 0:
        print(f"\n=== precision@k (매칭된 {evaluated}건 기준) ===")
        for k in (1, 2, 3):
            print(f"  precision@{k}: {hits[k] / evaluated:.1%} ({hits[k]}/{evaluated})")
    else:
        print("\n키워드 자동 매칭이 하나도 안 돼서 precision@k를 계산 못 했습니다. "
              "위 '자동 매칭 안 된 라벨' 목록을 보고 변수 이름과 직접 대조해보세요.")

    print("\n결과 파일: processed/track_b_root_cause_report.csv")


if __name__ == "__main__":
    main()
