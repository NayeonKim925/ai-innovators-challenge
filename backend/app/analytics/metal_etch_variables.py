"""Single source of truth for MACHINE_Data.mat's 21 variable names.

★ 실측 확인 근거 ★
이 21개 이름은 `variable_names.json`(machine 그룹)에서 실측으로 확인된 값이며,
`track_b_engine.py`/`verify_metadata.py`에서 동일하게 쓰였다. `metal_etch_adapter.py`와
`metal_etch_pca.py`가 모두 이 목록을 참조해서, 변수 이름이 두 곳에서 따로
어긋나는 일이 없게 한다.
"""

from __future__ import annotations

ALL_MACHINE_VARIABLES: tuple[str, ...] = (
    "Time",
    "Step Number",
    "BCl3 Flow",
    "Cl2 Flow",
    "RF Btm Pwr",
    "RF Btm Rfl Pwr",
    "Endpt A",
    "He Press",
    "Pressure",
    "RF Tuner",
    "RF Load",
    "RF Phase Err",
    "RF Pwr",
    "RF Impedance",
    "TCP Tuner",
    "TCP Phase Err",
    "TCP Impedance",
    "TCP Top Pwr",
    "TCP Rfl Pwr",
    "TCP Load",
    "Vat Valve",
)

# "Time"은 스텝 경계에서 리셋되는 인덱스성 컬럼이라 Observation으로 노출하지
# 않는다 (`metal_etch_adapter.py`가 이 값으로 필터링). 실측 근거는
# `verify_metadata.py`의 검증 2b 참고.
EXCLUDED_SIGNALS: frozenset[str] = frozenset({"Time"})

# "Step Number"는 신호로는 노출하지만(스텝별 통계를 내려면 필요), PCA
# contribution 랭킹의 "물리적 원인 후보" 대상에서는 뺀다 -- 몇 번째 스텝인지는
# 절대 원인이 될 수 없는 인덱스이기 때문이다 (`track_b_engine.py`의
# `EXCLUDE_FROM_PCA` 동일 근거).
STEP_INDEX_SIGNAL = "Step Number"

MACHINE_SIGNALS: tuple[str, ...] = tuple(
    name
    for name in ALL_MACHINE_VARIABLES
    if name not in EXCLUDED_SIGNALS and name != STEP_INDEX_SIGNAL
)

# 실측 확인(verify_metadata.py 검증3): 129개 웨이퍼 중 128개가 스텝 4.0, 5.0으로만
# 구성됨. 이 두 스텝을 뭉치지 않고 따로 기준값을 계산하는 게 검증5c에서
# TCP 계열 부호 일치율을 끌어올린 근거였다.
CANONICAL_STEPS: tuple[float, ...] = (4.0, 5.0)

FEATURE_STATS: tuple[str, ...] = ("mean", "std", "max_dev")
