"""Shared pytest fixtures.

★ 왜 합성 .mat 픽스처를 쓰는가 ★
실제 `MACHINE_Data.mat`은 `.gitignore`로 커밋되지 않아 CI/다른 개발자
환경에는 없다. 테스트가 그 파일에 의존하면 로컬에서만 통과하고 CI에서는
항상 실패한다. 이 픽스처는 `MACHINE_Data.mat`과 같은 구조(최상위 LAMDATA
struct, calibration/calib_names/test/test_names/fault_names/variables 필드,
경계 중복행)를 최소 크기로 재현해서, `metal_etch_adapter.py`의 파싱 로직을
원본 파일 없이도 검증한다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import scipy.io


def _wafer(rows: list[list[float]]) -> np.ndarray:
    return np.array(rows, dtype=float)


@pytest.fixture
def synthetic_machine_mat(tmp_path: Path) -> Path:
    """3개 변수(Time, Step Number, BCl3 Flow)만 가진 축소판 MACHINE_Data.mat.

    calib_names 2개(2901, 2902), test_names 1개(2915, fault_names="TCP +50")로
    구성한다. 각 웨이퍼의 마지막 행은 다음 웨이퍼의 첫 행과 동일하게 만들어서
    (`_drop_boundary_duplicate_row`가 실제로 지울 대상이 있는지) 검증한다.
    """
    # 2901: [t=0,step=4,BCl3=750], [t=1,step=4,BCl3=751], [t=2,step=5,BCl3=752]
    # 마지막 행 [2,5,752]는 2902의 첫 행과 동일해야 한다 (경계 중복행 실측 규칙)
    calib_2901 = _wafer([[0, 4, 750], [1, 4, 751], [2, 5, 752]])
    calib_2902 = _wafer([[2, 5, 752], [3, 5, 753], [4, 4, 754]])
    # test cell 배열의 원소가 1개뿐이면 scipy.io.loadmat(simplify_cells=True)가
    # 차원을 squeeze해서 행렬이 아니라 개별 값이 돼 버린다 (실제 MACHINE_Data.mat은
    # test가 21개라 이 문제가 없지만, 이 축소판 픽스처는 최소 2개를 넣어서 같은
    # 함정에 빠지지 않게 한다).
    test_2915 = _wafer([[0, 4, 900], [1, 4, 901], [2, 5, 902]])
    test_2916 = _wafer([[0, 4, 910], [1, 5, 911]])

    mdict = {
        "LAMDATA": {
            "calibration": np.array([calib_2901, calib_2902], dtype=object),
            "calib_names": np.array(["l2901.txm", "l2902.txm"], dtype=object),
            "test": np.array([test_2915, test_2916], dtype=object),
            "test_names": np.array(["l2915.txm", "l2916.txm"], dtype=object),
            "fault_names": np.array(["TCP +50", "RF -12"], dtype=object),
            "variables": np.array(["Time", "Step Number", "BCl3 Flow"], dtype=object),
        }
    }
    path = tmp_path / "MACHINE_Data.mat"
    scipy.io.savemat(str(path), mdict)
    return path
