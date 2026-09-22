"""PCA-based anomaly scoring for causRCA, using the 170 real_op recordings as
a normal-operation baseline (AGENT_FAULT_DETECTION_PLAN.md Phase 2).

★ Why this exists ★
Phase 1's alarm-activation detector (`analytics/fault_onset.py`) only fires
once a discrete Alarm node has already latched True. This module gives the
detection agent a second, earlier-warning signal: how far a recording's
current state has drifted from normal operation, using the same
PCA-reconstruction-error method as `analytics/metal_etch_pca.py` (mirroring
its structure deliberately, so a reviewer can compare the two side by side).

★ Why real_op, not dig_twin, is the baseline ★
`real_op` recordings have no `causes.json`/`*_description.json` beside them
at all (Glob-confirmed) -- they carry no fault label to leak, so the full
recording is a safe runtime artifact (`scripts/prepare_causrca.py` writes it
straight to `data/runtime/causrca/normal_baseline.json`, never
`data/evaluation/`).

★ v1 scope limitation ★
The shared runtime `Observation.kind` (`Alarm` / `Measurement` / `Event`)
collapses causRCA's original per-node `type` column (Binary/Continuous/
Counter/Categorical) during `scripts/prepare_causrca.py::read_observations` --
only `Alarm` survives that mapping, everything else becomes `Event`. So this
module cannot pick encodable nodes by `kind`; instead `_encode()` infers
encodability from each observation's VALUE (a `true`/`false` string, or a
number) rather than its (lost) original type. A `Categorical` node whose
codes happen to look numeric (e.g. `Prog_LineNo`) is treated as an ordinal
number rather than decoded via causRCA's `categorical_encoding.json` -- a
real v1 approximation, not an oversight (see AGENT_FAULT_DETECTION_PLAN.md's
open questions). A genuinely non-numeric string (e.g. `Prog_Name`) is
dropped from the feature set entirely.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..data.causrca_adapter import load_normal_baseline
from ..data.runtime_repository import runtime_root
from ..domain import Evidence, Incident, Observation

try:
    import numpy as np
    from sklearn.decomposition import PCA
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

# A feature must appear (with an encodable value) in at least this share of
# normal recordings to be trusted as part of the shared baseline feature
# space (real_op recordings don't all touch the same subsystems).
_MIN_FEATURE_COVERAGE = 0.8
_MIN_BASELINE_RECORDINGS = 5
_TRUE_STRINGS = frozenset({"true", "1"})
_FALSE_STRINGS = frozenset({"false", "0"})


def _encode(item: Observation) -> float | None:
    """Infer a numeric encoding from the observed VALUE, not `item.kind`
    (see module docstring: the original causRCA type is lost by the time an
    `Observation` reaches this module). `Alarm` kind is still handled first
    since its True/False semantics are authoritative regardless of value text.
    """
    text = str(item.value).strip().lower()
    if item.kind == "Alarm" or text in _TRUE_STRINGS or text in _FALSE_STRINGS:
        return 1.0 if text in _TRUE_STRINGS else 0.0
    try:
        return float(text)
    except ValueError:
        return None


def _latest_by_signal(
    observations: list[Observation], up_to_time_s: float
) -> dict[str, Observation]:
    latest: dict[str, Observation] = {}
    for item in observations:
        if item.time_s > up_to_time_s:
            continue
        current = latest.get(item.signal)
        if current is None or item.time_s >= current.time_s:
            latest[item.signal] = item
    return latest


def _last_known_state_vector(
    observations: list[Observation], up_to_time_s: float, feature_names: list[str]
) -> np.ndarray:
    latest = _latest_by_signal(observations, up_to_time_s)
    vector = np.full(len(feature_names), np.nan)
    for index, name in enumerate(feature_names):
        item = latest.get(name)
        if item is not None:
            encoded = _encode(item)
            if encoded is not None:
                vector[index] = encoded
    return vector


class _BaselineModel:
    __slots__ = ("scaler", "pca", "imputer", "feature_names", "median_spe", "p95_spe")

    def __init__(
        self,
        scaler: StandardScaler,
        pca: PCA,
        imputer: SimpleImputer,
        feature_names: list[str],
        median_spe: float,
        p95_spe: float,
    ) -> None:
        self.scaler = scaler
        self.pca = pca
        self.imputer = imputer
        self.feature_names = feature_names
        self.median_spe = median_spe
        self.p95_spe = p95_spe


_MODEL_CACHE: dict[Path, _BaselineModel] = {}


def _select_feature_names(normal: list) -> list[str]:
    presence: Counter[str] = Counter()
    for record in normal:
        latest = _latest_by_signal(record.observations, float("inf"))
        presence.update(name for name, item in latest.items() if _encode(item) is not None)
    threshold = _MIN_FEATURE_COVERAGE * len(normal)
    return sorted(name for name, count in presence.items() if count >= threshold)


def _build_baseline_model(root: Path) -> _BaselineModel | None:
    normal = load_normal_baseline(root)
    if len(normal) < _MIN_BASELINE_RECORDINGS:
        return None

    feature_names = _select_feature_names(normal)
    if len(feature_names) < 2:
        return None

    raw = np.stack(
        [
            _last_known_state_vector(record.observations, float("inf"), feature_names)
            for record in normal
        ]
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

    reconstructed = pca.inverse_transform(pca.transform(scaled))
    residuals = np.sum((scaled - reconstructed) ** 2, axis=1)
    return _BaselineModel(
        scaler=scaler,
        pca=pca,
        imputer=imputer,
        feature_names=feature_names,
        median_spe=float(np.median(residuals)),
        p95_spe=float(np.percentile(residuals, 95)),
    )


def _get_baseline_model() -> _BaselineModel | None:
    root = runtime_root()
    if root not in _MODEL_CACHE:
        model = _build_baseline_model(root)
        if model is None:
            return None
        _MODEL_CACHE[root] = model
    return _MODEL_CACHE[root]


def compute_anomaly_score(
    incident: Incident, up_to_time_s: float
) -> tuple[float | None, float | None, Evidence | None, list[str]]:
    """Return `(score, elevated_threshold, evidence, warnings)`.

    `score` is the total PCA reconstruction error (SPE) of the incident's
    current state against the real_op normal-operation baseline.
    `elevated_threshold` is that baseline's own 95th-percentile SPE -- the
    detection agent (`workflows/detection.py`) treats `score >= threshold` as
    "elevated." Either value is `None` when the baseline or its dependencies
    are unavailable, matching the fallback pattern in `analytics/causrca.py`
    and `analytics/metal_etch_pca.py`.
    """
    if not _SKLEARN_AVAILABLE:
        return None, None, None, [
            "PCA anomaly-score dependencies (numpy/scikit-learn) are unavailable."
        ]
    model = _get_baseline_model()
    if model is None:
        return None, None, None, [
            "causRCA normal-operation baseline is unavailable; run scripts/prepare_causrca.py."
        ]
    observed = [item for item in incident.observations if item.time_s <= up_to_time_s]
    if not observed:
        return None, None, None, ["No observations are available before the cutoff."]

    vector = _last_known_state_vector(observed, up_to_time_s, model.feature_names).reshape(1, -1)
    imputed = model.imputer.transform(vector)
    scaled = model.scaler.transform(imputed)
    reconstructed = model.pca.inverse_transform(model.pca.transform(scaled))
    contribution = ((scaled - reconstructed) ** 2).flatten()
    residual = float(contribution.sum())
    top_signal = model.feature_names[int(np.argmax(contribution))]

    evidence = Evidence(
        id="E_pca_anomaly",
        title=f"Deviation from normal-operation baseline (largest contributor: {top_signal})",
        detail=(
            f"Reconstruction error (SPE)={residual:.3g} vs. normal-operation baseline "
            f"(typical={model.median_spe:.3g}, elevated threshold={model.p95_spe:.3g}). "
            f"{top_signal} contributed the most to this deviation."
        ),
        source="Deterministic PCA baseline fit on prepared causRCA real_op runtime data",
    )
    return residual, model.p95_spe, evidence, []
