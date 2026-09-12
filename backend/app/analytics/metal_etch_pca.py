"""PCA-based root-cause candidate ranking for Metal Etch wafers.

★ 방법론 근거 (ADR-0002, track_b_engine.py에서 이식) ★
PCA 기반 이상탐지 + contribution score(재구성 오차 기여도로 원인 변수 순위를
매기는 방법)는 이 Metal Etch Data를 만든 원 논문(Wise, Gallagher, Butler,
White, Barna, "A Comparison of Principal Components Analysis, ... for Fault
Detection in a Semiconductor Etch Process", J. Chemometrics, 1999)이 이 데이터로
직접 검증한 방법이다.

★ analytics/causrca.py와의 대칭 구조 ★
`rank_with_caus_tr(incident, diagnosis_time, limit=3) -> (candidates, evidence, warnings)`
와 동일한 시그니처를 쓴다. `workflows/investigation.py`가 `source_dataset`으로
분기할 때 두 어댑터를 같은 방식으로 다룰 수 있게 하기 위함이다.

★ 정상 기준선은 반드시 data/runtime/에서만 읽는다 ★
이 모듈은 원본 `.mat`/`.npy`를 다시 읽지 않는다. `scripts/prepare_metal_etch.py`가
이미 만들어 둔 `data/runtime/metal_etch/normal_baseline.json`
(`metal_etch_adapter.load_normal_baseline`)만 사용한다. `data/evaluation/`은
이 모듈에서 import하지 않는다 -- fault label은 여기서 전혀 필요 없다
(정상 웨이퍼에는 애초에 라벨이 없다).

★ Time을 대리한 diagnosis_time cutoff ★
`Incident.observations`의 `time_s`는 경계 중복행을 제거한 �제 행 순서
(0, 1, 2, ...)다 (`metal_etch_adapter.py` 참고). `diagnosis_time`은 이 인덱스
기준 cutoff로 해석하며, `time_s <= diagnosis_time`인 관측값만 사용한다
(causrca.py의 `_latest_observations`와 동일한 규칙).

★ v1 한계 (track_b_engine.py와 동일) ★
스텝(4, 5)별로 평균·표준편차·최대편차를 계산해 이어붙이는 요약 방식을 쓴다.
평균만 쓰면 "언제 이상이 튀었는지"라는 시간 정보가 옅어진다는 한계가
`track_b_engine.py`에 이미 기록돼 있고, 이 모듈도 동일한 한계를 그대로 안고
있다. 다음 개선 지점은 시간 구간별 세분화다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from ..data.metal_etch_adapter import load_normal_baseline
from ..data.runtime_repository import runtime_root
from ..domain import Candidate, Evidence, Incident, Observation
from .metal_etch_variables import CANONICAL_STEPS, EXCLUDED_SIGNALS, FEATURE_STATS, MACHINE_SIGNALS

# machine 21변수 중 fault_names의 계열 키워드(TCP/RF/Cl2/BCl3/Pr/He)와 실제
# 대응되는 변수를 도메인 판단으로 확정한 표. 부분 문자열 매칭(예: "RF"가
# "TCP Rfl Pwr"의 "Rfl"에 걸림, "Pr"이 "He Press"의 "Press"에 걸림)이 오매칭을
# 낸다는 게 실측으로 확인돼서, 이 v1은 그 매칭을 쓰지 않고 후보 신호를
# MACHINE_SIGNALS 전체로 두고 순수하게 SPE 기여도로만 순위를 매긴다. 라벨
# 매칭은 evaluation 전용 영역(`evals/`)의 몫이지 이 analytics 모듈의 몫이 아니다.


def _step_aware_feature_vector(
    observations: list[Observation], step_index: dict[float, int]
) -> np.ndarray:
    """웨이퍼 한 장의 관측값을 스텝별 [평균, 표준편차, 최대편차] 벡터로
    요약한다 (`track_b_engine.summarize_trajectory_step_aware`와 동일한 방식,
    `np.nanmean`/`np.nanstd`로 2-pass 계산해 수치적으로 원본과 최대한 일치시킴).
    시간 순서에 따라 이어붙이므로, 반환 벡터의 길이는 항상
    len(CANONICAL_STEPS) * len(FEATURE_STATS) * len(MACHINE_SIGNALS)다."""
    n_vars = len(MACHINE_SIGNALS)
    n_steps = len(CANONICAL_STEPS)
    signal_position = {signal: index for index, signal in enumerate(MACHINE_SIGNALS)}

    step_by_time: dict[float, float] = {
        observation.time_s: float(observation.value)
        for observation in observations
        if observation.signal == "Step Number"
    }

    # 스텝별로 (시간 x 변수) 원본 행렬을 재구성한다 -- track_b_engine.py가
    # np.load()로 얻는 것과 같은 모양이다.
    rows_by_step: list[dict[float, np.ndarray]] = [dict() for _ in range(n_steps)]
    for observation in observations:
        var_index = signal_position.get(observation.signal)
        if var_index is None:
            continue
        step_value = step_by_time.get(observation.time_s)
        if step_value is None or step_value not in step_index:
            continue
        step_position = step_index[step_value]
        row = rows_by_step[step_position].setdefault(observation.time_s, np.full(n_vars, np.nan))
        row[var_index] = float(observation.value)

    blocks: list[np.ndarray] = []
    for step_position in range(n_steps):
        rows = rows_by_step[step_position]
        if not rows:
            blocks.extend([np.full(n_vars, np.nan) for _ in FEATURE_STATS])
            continue
        matrix = np.stack(list(rows.values()))
        mean = np.nanmean(matrix, axis=0)
        std = np.nanstd(matrix, axis=0)
        max_dev = np.nanmax(np.abs(matrix - mean), axis=0)
        blocks.extend([mean, std, max_dev])

    return np.concatenate(blocks)


def _expanded_signal_names() -> list[str]:
    return [
        f"{signal} (step{step:g}_{stat})"
        for step in CANONICAL_STEPS
        for stat in FEATURE_STATS
        for signal in MACHINE_SIGNALS
    ]


class _BaselineModel:
    __slots__ = ("scaler", "pca", "imputer", "signal_names")

    def __init__(
        self, scaler: StandardScaler, pca: PCA, imputer: SimpleImputer, signal_names: list[str]
    ) -> None:
        self.scaler = scaler
        self.pca = pca
        self.imputer = imputer
        self.signal_names = signal_names


_MODEL_CACHE: dict[Path, _BaselineModel] = {}


def _build_baseline_model(root: Path) -> _BaselineModel | None:
    normal_wafers = load_normal_baseline(root)
    if len(normal_wafers) < 2:
        return None

    step_index = {step: position for position, step in enumerate(CANONICAL_STEPS)}
    signal_names = _expanded_signal_names()
    raw = np.stack(
        [_step_aware_feature_vector(wafer.observations, step_index) for wafer in normal_wafers]
    )

    imputer = SimpleImputer(strategy="mean")
    imputed = imputer.fit_transform(raw)
    scaler = StandardScaler().fit(imputed)
    scaled = scaler.transform(imputed)

    n_components = min(0.90, scaled.shape[0] - 1, scaled.shape[1])
    pca = PCA(
        n_components=n_components if isinstance(n_components, float) else int(n_components),
        svd_solver="full",
    )
    pca.fit(scaled)
    return _BaselineModel(scaler=scaler, pca=pca, imputer=imputer, signal_names=signal_names)


def _get_baseline_model() -> _BaselineModel | None:
    root = runtime_root()
    if root not in _MODEL_CACHE:
        model = _build_baseline_model(root)
        if model is None:
            return None
        _MODEL_CACHE[root] = model
    return _MODEL_CACHE[root]


def rank_with_pca_contribution(
    incident: Incident, diagnosis_time: float, limit: int = 3
) -> tuple[list[Candidate], list[Evidence], list[str]]:
    """정상 웨이퍼 기준선 대비 재구성 오차(SPE)가 큰 신호 순으로 원인후보를 낸다.

    `diagnosis_time` 이전 관측값만 사용한다. 정상 기준선이 준비돼 있지 않으면
    (`scripts/prepare_metal_etch.py`를 안 돌렸으면) 빈 결과와 경고를 반환한다 --
    causRCA 어댑터의 폴백 패턴과 동일하다."""
    model = _get_baseline_model()
    if model is None:
        return (
            [],
            [],
            ["Metal Etch normal-wafer baseline is unavailable; run scripts/prepare_metal_etch.py."],
        )

    observed = [item for item in incident.observations if item.time_s <= diagnosis_time]
    if not observed:
        return (
            [],
            [],
            ["No observations are available before the diagnosis cutoff; the workflow abstains."],
        )

    step_index = {step: position for position, step in enumerate(CANONICAL_STEPS)}
    feature_vector = _step_aware_feature_vector(observed, step_index).reshape(1, -1)
    imputed = model.imputer.transform(feature_vector)
    scaled = model.scaler.transform(imputed)
    projected = model.pca.transform(scaled)
    reconstructed = model.pca.inverse_transform(projected)
    contribution = (scaled - reconstructed).flatten() ** 2

    latest_by_signal: dict[str, Observation] = {}
    for item in observed:
        if item.signal in EXCLUDED_SIGNALS:
            continue
        latest_by_signal[item.signal] = item

    order = np.argsort(contribution)[::-1]
    candidates: list[Candidate] = []
    evidence: list[Evidence] = []
    for rank, position in enumerate(order, start=1):
        if len(candidates) >= limit:
            break
        expanded_name = model.signal_names[position]
        base_signal = expanded_name.split(" (step")[0]
        item = latest_by_signal.get(base_signal)
        if item is None:
            continue
        evidence_id = f"E{len(evidence) + 1}"
        evidence.append(
            Evidence(
                id=evidence_id,
                title=f"PCA reconstruction deviation: {expanded_name}",
                detail=(
                    f"At t={item.time_s:g}, {base_signal} reported {item.value!r} before the "
                    f"diagnosis cutoff. Its step-aware reconstruction error "
                    f"(SPE contribution={contribution[position]:.3g}) was the largest among "
                    "observed signals."
                ),
                source="Deterministic PCA baseline fit on prepared normal-wafer runtime data",
            )
        )
        candidates.append(
            Candidate(
                rank=len(candidates) + 1,
                signal=base_signal,
                reason=(
                    "This signal's deviation from the normal-wafer PCA reconstruction was the "
                    "largest observed before the cutoff. It remains an investigation candidate, "
                    "not a confirmed cause."
                ),
                evidence_ids=[evidence_id],
            )
        )
    if not candidates:
        return (
            [],
            [],
            ["PCA baseline produced no observable candidates at the selected cutoff; abstaining."],
        )
    return candidates, evidence, []
