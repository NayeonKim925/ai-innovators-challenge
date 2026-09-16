"""Metal Etch (.mat) adapter — converts LAM 9600 wafer records into the shared
`Incident`/`Observation` contract defined in `app.domain`.

★ 재사용 근거 (ADR-0002) ★
웨이퍼 번호 파싱, 실험번호 추출, 경계 중복행 제거 로직은 `loaders/metal_etch_loader.py`
에서 실측 검증된 내용을 그대로 포팅했다. import로 재사용하지 않고 포팅한 이유는
`loaders/`가 `backend` 패키지 경계 밖(pyproject.toml의 `where=["backend"]`) 에 있어서,
backend를 독립 패키지로 빌드·배포할 때 `loaders`가 함께 따라오지 않기 때문이다.
로직은 동일하되, backend는 그 로직에 런타임 의존을 갖지 않는다.

★ v1 스코프 ★
`track_b_engine.py`와 동일하게 machine 그룹만 다룬다 (OES/RFM은 향후 확장 지점 —
`Capability.MULTI_SOURCE_EVIDENCE`는 실제로 여러 센서군을 합쳤을 때만 선언한다.
지금은 machine 하나뿐이므로 이 capability를 붙이지 않는다).

★ 데이터 격리 (DATA_CONTRACT.md) ★
이 모듈은 `fault_names`/`label_value`/`label_reliable`을 절대 `Incident`에 넣지
않는다. `build_metal_etch_dataset()`이 반환하는 `evaluation_labels`만 그 정보를
담고, 호출자는 이걸 `data/evaluation/metal_etch/`에만 써야 한다.

정상(calibration) 웨이퍼는 causRCA의 `expert_graph.gml`과 같은 역할이다 —
"조사 대상 사건"이 아니라, 분석 도구(`analytics/metal_etch_pca.py`)가 정상
운전 기준선을 계산할 때 참조하는 runtime 아티팩트로만 저장한다. 정상 웨이퍼에는
결함 라벨이 없으므로 평가 격리 대상이 아니다.

★ 시간축 ★
Metal Etch에는 실제 벽시계 타임스탬프가 없다. 원본 "Time" 컬럼은 스텝이 바뀌면
리셋되는 것으로 실측 확인됐다 (verify_metadata.py 검증 2b). 이 모듈은 그 컬럼을
신호로 노출하지 않고, 경계 중복행을 제거한 뒤의 행 순서(0, 1, 2, ...)를 단조증가
"process time" 대리축(`time_s`)으로 쓴다. "Step Number"는 신호로 그대로 남겨서
`analytics/metal_etch_pca.py`가 스텝별로 묶어 통계를 낼 수 있게 한다.
"""

from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from ..analytics.metal_etch_variables import EXCLUDED_SIGNALS
from ..domain import Capability, DatasetName, Incident, Observation, TimeRange

if TYPE_CHECKING:
    import numpy as np

# ★ 왜 조건부 임포트인가 (metal_etch_pca.py와 동일 패턴) ★
# numpy/scipy는 원본 .mat 파일을 파싱하는 "데이터 준비" 함수들
# (_drop_boundary_duplicate_row, _matrix_to_observations, _iter_wafer_records,
# build_metal_etch_dataset)에만 필요하다. 이 함수들은 scripts/prepare_metal_etch.py
# 에서만 호출되지, API 요청 경로에서는 절대 호출되지 않는다. 반면
# load_normal_baseline()은 이미 준비된 JSON을 읽어서 Pydantic으로 검증만 하고
# np./scipy. 참조가 전혀 없어서, numpy/scipy가 없어도 그대로 동작해야 한다
# (그래서 이 함수는 아래 _NUMPY_AVAILABLE 체크를 두지 않는다).
_NUMPY_AVAILABLE = (
    importlib.util.find_spec("numpy") is not None
    and importlib.util.find_spec("scipy") is not None
)


def _load_numeric_dependencies():
    """Load heavy .mat parsing dependencies only in offline preparation paths."""
    try:
        import numpy as np
        import scipy.io as scipy_io
    except ImportError as exc:  # pragma: no cover - guarded by the caller
        raise ImportError(
            "Metal Etch data preparation requires numpy and scipy; "
            "install with `pip install -e '.[metal-etch]'`."
        ) from exc
    return np, scipy_io

# inspect_failing_cases.py로 직접 눈으로 대조해서 확인된, 라벨과 실측 신호가
# 어긋난 웨이퍼 (flag_unreliable_labels.py와 동일한 목록). 추측으로 다른
# 라벨을 대신 넣지 않고 "불확실"로만 표시한다.
UNRELIABLE_ENTITY_IDS = frozenset({"2918", "2937", "3141", "3142", "3339"})


class NormalWaferRecord(BaseModel):
    """정상(calibration) 웨이퍼 1장의 원시 관측값.

    `Incident`가 아니다 -- 조사 대상이 아니라 분석 도구가 참조하는 기준선
    아티팩트다. causRCA의 `expert_graph.gml`과 같은 위치(`data/runtime/`)에
    쓰지만, 별도 파일(`normal_baseline.json`)로 저장한다."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    experiment_id: str
    observations: list[Observation]


class MetalEtchEvaluationLabel(BaseModel):
    """평가 전용 라벨. `data/evaluation/metal_etch/`에만 쓴다."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    entity_id: str
    experiment_id: str
    label_value: str
    label_reliable: bool


@dataclass(frozen=True)
class MetalEtchDataset:
    incidents: list[Incident]
    normal_baseline: list[NormalWaferRecord]
    evaluation_labels: list[MetalEtchEvaluationLabel]


def _unwrap(mat: dict) -> dict:
    """최상위가 LAMDATA 같은 이름의 struct 하나로 감싸져 있는 걸 벗긴다
    (실측 확인됨, `loaders/metal_etch_loader.py` 동일 로직)."""
    top_keys = [k for k in mat.keys() if not k.startswith("__")]
    if len(top_keys) == 1 and isinstance(mat[top_keys[0]], dict):
        return mat[top_keys[0]]
    return mat


def _to_str_list(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(row).strip() for row in value]


def _wafer_number(wafer_name: str) -> str:
    """실측 확인된 패턴: 이름 중간의 숫자 4자리가 공통 웨이퍼 번호다
    (예: `l3342.txm` -> `3342`)."""
    match = re.search(r"(\d{4})", wafer_name)
    if not match:
        raise ValueError(f"웨이퍼 번호를 못 찾음: {wafer_name!r}")
    return match.group(1)


def _extract_experiment_id(wafer_name: str) -> str:
    """웨이퍼 번호 앞 두 자리가 실험번호(29/31/33)와 일치함이 실측 확인됨."""
    return _wafer_number(wafer_name)[:2]


def _drop_boundary_duplicate_row(matrix: np.ndarray) -> np.ndarray:
    """원본 .mat 파일은 각 웨이퍼의 마지막 행이 다음 웨이퍼의 첫 행과
    완전히 동일하다 (실측 확인, `loaders/metal_etch_loader.py` 동일 로직).
    이 마지막 행은 이 웨이퍼 자신의 진짜 마지막 측정치가 아니므로 제거한다."""
    if matrix.shape[0] <= 1:
        return matrix
    return matrix[:-1]


def _normalize_variable_names(raw) -> list[str]:
    """`scipy.io.loadmat`이 정상적으로 문자열 배열을 돌려주면 그대로 쓰지만,
    혹시 이 값이 numpy repr 문자열 하나로 뭉개진 형태
    (`"['Time          ' 'Step Number   ' ...]"`, `track_b_engine.py`에서
    실제로 발견됐던 문제)로 들어오면 방어적으로 파싱한다."""
    if isinstance(raw, str):
        return [name.strip() for name in re.findall(r"'([^']*)'", raw)]
    return [str(name).strip() for name in raw]


def _matrix_to_observations(
    matrix: np.ndarray, variable_names: list[str], *, exclude: frozenset[str]
) -> list[Observation]:
    np, _ = _load_numeric_dependencies()
    matrix = np.asarray(matrix, dtype=float)
    observations: list[Observation] = []
    for row_index, row in enumerate(matrix):
        for value, name in zip(row, variable_names):
            if name in exclude or not np.isfinite(value):
                continue
            observations.append(
                Observation(
                    time_s=float(row_index), signal=name, value=float(value), kind="Measurement"
                )
            )
    return observations


@dataclass(frozen=True)
class _RawWaferRecord:
    entity_id: str
    experiment_id: str
    is_normal: bool
    label_value: str | None
    matrix: np.ndarray


def _iter_wafer_records(path: Path) -> tuple[list[_RawWaferRecord], list[str]]:
    """MACHINE_Data.mat 하나를 읽어 (웨이퍼별 원시 레코드 목록, 변수 이름 목록)을 반환한다."""
    np, scipy_io = _load_numeric_dependencies()
    raw = scipy_io.loadmat(str(path), simplify_cells=True)
    mat = _unwrap(raw)
    variable_names = _normalize_variable_names(mat["variables"])

    records: list[_RawWaferRecord] = []
    for name, matrix in zip(_to_str_list(mat["calib_names"]), mat["calibration"]):
        entity_id = _wafer_number(name)
        records.append(
            _RawWaferRecord(
                entity_id=entity_id,
                experiment_id=_extract_experiment_id(name),
                is_normal=True,
                label_value=None,
                matrix=_drop_boundary_duplicate_row(np.asarray(matrix, dtype=float)),
            )
        )
    for name, matrix, fault in zip(
        _to_str_list(mat["test_names"]), mat["test"], _to_str_list(mat["fault_names"])
    ):
        entity_id = _wafer_number(name)
        records.append(
            _RawWaferRecord(
                entity_id=entity_id,
                experiment_id=_extract_experiment_id(name),
                is_normal=False,
                label_value=fault,
                matrix=_drop_boundary_duplicate_row(np.asarray(matrix, dtype=float)),
            )
        )
    return records, variable_names


def build_metal_etch_dataset(
    machine_path: Path, *, entity_ids: frozenset[str] | None = None
) -> MetalEtchDataset:
    """MACHINE_Data.mat을 읽어 `Incident`(결함 웨이퍼), 정상 웨이퍼 기준선,
    평가용 라벨로 분리한다.

    `entity_ids`를 주면 그 웨이퍼들만 포함한다 (데모·테스트에서 전체 129장 대신
    일부만 다루고 싶을 때 사용). 원본 파일은 그래도 전체를 읽는다 -- scipy가
    구조상 부분 로딩을 지원하지 않는다.

    이 함수는 `scripts/prepare_metal_etch.py`(오프라인 데이터 준비 CLI)에서만
    호출되고 API 요청 경로에는 절대 들어오지 않으므로, numpy/scipy가 없으면
    (`rank_with_pca_contribution()`처럼 조용히 폴백하지 않고) 즉시
    `ImportError`를 던진다 -- 준비 스크립트를 돌리는 사람이 원인을 바로 알 수
    있게 하는 게 API 폴백 경고보다 더 적절하다."""
    if not _NUMPY_AVAILABLE:
        raise ImportError(
            "Metal Etch data preparation requires numpy and scipy; "
            "install with `pip install -e '.[metal-etch]'`."
        )
    records, variable_names = _iter_wafer_records(machine_path)
    if entity_ids is not None:
        records = [r for r in records if r.entity_id in entity_ids]

    incidents: list[Incident] = []
    evaluation_labels: list[MetalEtchEvaluationLabel] = []
    normal_baseline: list[NormalWaferRecord] = []

    for record in records:
        observations = _matrix_to_observations(
            record.matrix, variable_names, exclude=EXCLUDED_SIGNALS
        )
        if not observations:
            continue
        time_range = TimeRange(start=observations[0].time_s, end=observations[-1].time_s)

        if record.is_normal:
            normal_baseline.append(
                NormalWaferRecord(
                    entity_id=record.entity_id,
                    experiment_id=record.experiment_id,
                    observations=observations,
                )
            )
            continue

        case_id = f"metal_etch_{record.entity_id}"
        incidents.append(
            Incident(
                id=case_id,
                source_dataset=DatasetName.METAL_ETCH,
                title=f"LAM 9600 wafer {record.entity_id} (experiment {record.experiment_id})",
                time_range_s=time_range,
                capabilities={Capability.TIME_SERIES, Capability.ROOT_CAUSE_RANKING},
                observations=observations,
            )
        )
        evaluation_labels.append(
            MetalEtchEvaluationLabel(
                case_id=case_id,
                entity_id=record.entity_id,
                experiment_id=record.experiment_id,
                label_value=record.label_value or "",
                label_reliable=record.entity_id not in UNRELIABLE_ENTITY_IDS,
            )
        )

    incidents.sort(key=lambda item: item.id)
    evaluation_labels.sort(key=lambda item: item.case_id)
    normal_baseline.sort(key=lambda item: item.entity_id)
    return MetalEtchDataset(
        incidents=incidents, normal_baseline=normal_baseline, evaluation_labels=evaluation_labels
    )


def load_normal_baseline(runtime_root: Path) -> list[NormalWaferRecord]:
    """`data/runtime/metal_etch/normal_baseline.json`을 읽는다.

    ★ 왜 원본 .mat/.npy를 다시 읽지 않는가 ★
    `analytics/metal_etch_pca.py`는 이 함수로 정상 운전 기준선을 가져온다.
    `data/runtime/`만 읽는다는 DATA_CONTRACT.md 원칙을 지키기 위해, 이미
    `scripts/prepare_metal_etch.py`가 준비해 둔 runtime 아티팩트만 읽고
    원본 데이터 경로에는 다시 의존하지 않는다."""
    path = runtime_root / "metal_etch" / "normal_baseline.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [NormalWaferRecord.model_validate(item) for item in payload]
