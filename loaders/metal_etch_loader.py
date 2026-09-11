"""
Eigenvector Metal Etch Data 로더 (LAM 9600 Metal Etcher, .mat 파일)
공식 페이지: https://eigenvector.com/resources/data-sets/metal-etch-data-for-fault-detection-evaluation/
데이터 자체에 대한 배경 설명은 저장소 루트의 METAL_ETCH_DATA.md 참고.

★ 실측으로 확정된 구조 (공식 페이지 명세와 다른 부분 포함) ★
파일은 3개이고, 공식 페이지 명세와 달리 실제로는 각각 필드 구성이 다르다.

    MACHINE_Data.mat (최상위 키 LAMDATA)
        calibration/calib_names: 정상 108개, test/test_names: 결함 21개
        variables: 변수 이름 21개  -- 공식 문서와 일치하는 유일한 파일

    OES_DATA.mat (최상위 키 OESDATA)
        calibration/calib_names: 정상 106개, test/test_names: 결함 20개
        variables 필드 없음 -- 대신 wave_axis(파장 축) 129개

    RFM_DATA.mat (최상위 키 RFMDATA)
        calibration/calib_names: 정상 106개, test/test_names: 결함 20개
        variables: 변수 이름 71개, units: 변수별 단위 71개 (공식 문서엔 없던 필드)

공통으로 있는 필드: INFORMATION(설명 텍스트), fault_names(결함 웨이퍼의
실제 결함 유형 라벨 -- RCA 엔진 결과를 대조 검증할 정답으로 쓴다).

세 실험(실험번호 29/31/33)은 몇 주 간격으로 진행돼 평균·공분산 구조가
다르다는 게 공식 문서에 명시돼 있다 -- 그래서 experiment_id를 스키마에
남겨, 2-2 이상탐지 엔진에서 "진짜 결함"과 "실험 간 드리프트"를 구분할
수 있게 한다.

★ 웨이퍼 이름 표기가 파일마다 다름 (실측 확인) ★
같은 웨이퍼라도 MACHINE=l3342.txm, OES=s3342.int, RFM=r3342.txt처럼
접두문자·확장자가 다르다. 원본 이름 그대로는 세 파일 간에 절대 안
겹치므로, 이름 중간의 숫자 4자리(_wafer_number())를 공통 entity_id로
쓴다. 이 숫자의 앞 두 자리가 실험번호(29/31/33)와 일치함도 확인됐다.

★ 세 그룹의 실제 겹침 (compare_wafer_sets()로 확인됨) ★
calibration 108개 중 104개는 machine·oes·rfm 전부 존재, 4개는 둘 중
하나에만 존재(OES 누락 2개, RFM 누락 2개는 서로 다른 웨이퍼). test
21개 중 20개는 셋 다 존재, 1개(2916번)는 MACHINE에만 존재.

★ 실측으로 해결된 이전 의문 ★
"세 파일의 시간축이 맞는지"는 미해결로 남겨뒀었는데, 조사 결과 각
웨이퍼의 마지막 행이 다음 웨이퍼의 첫 행과 완전히 동일하다는 걸
확인했다 (원본 실험을 연속으로 로깅한 뒤 웨이퍼 단위로 자르면서 경계를
양쪽에 포함시킨 것으로 보임 -- 128쌍 중 116쌍에서 확인, 나머지 12쌍은
정확히 calibration/test 배열 전환 지점이라 오히려 이 설명과 일치함).
그래서 _drop_boundary_duplicate_row()로 각 웨이퍼의 마지막 행을 버린다.
"""
import re
import numpy as np
import scipy.io


def _to_str_list(char_array) -> list:
    """MATLAB char 배열을 문자열 리스트로 정규화. 실제 반환 형태는
    파일을 열어서 확인 후 이 함수를 조정할 것."""
    if isinstance(char_array, str):
        return [char_array]
    return [str(row).strip() for row in char_array]


def _wafer_number(wafer_name: str) -> str:
    """실측 확인된 진짜 패턴:
        MACHINE: l + 숫자4자리 + .txm   (예: l3342.txm)
        OES    : s + 숫자4자리 + .int   (예: s3139.int)
        RFM    : r + 숫자4자리 + .txt   (예: r3314.txt)
    접두문자/확장자가 파일마다 달라서 원본 이름 그대로는 세 파일 간에
    절대 안 겹친다 -- 숫자 4자리만 뽑아내야 진짜 같은 웨이퍼를 찾을 수 있다.
    이 숫자를 공통 entity_id로 쓴다."""
    match = re.search(r"(\d{4})", wafer_name)
    if not match:
        raise ValueError(f"웨이퍼 번호를 못 찾음: {wafer_name!r} -- 실제 포맷이 예상과 다른지 확인할 것")
    return match.group(1)


def _extract_experiment_id(wafer_name: str) -> str:
    """웨이퍼 번호(4자리)의 앞 두 자리가 실험번호(29/31/33)와 일치함을
    실측으로 확인함. 원본 이름이 아니라 _wafer_number()로 뽑은 숫자
    기준으로 앞 두 자리를 사용한다."""
    number = _wafer_number(wafer_name)
    return number[:2]


def _unwrap(mat: dict) -> dict:
    """최상위가 RFMDATA/MACHINEDATA/OESDATA 같은 이름의 struct 하나로
    감싸져 있는 걸 확인함 (문서 명세와 달리 한 겹 더 있음). 최상위에
    실데이터 키가 하나뿐이면 그 안으로 들어가서 진짜 필드를 꺼낸다."""
    top_keys = [k for k in mat.keys() if not k.startswith("__")]
    if len(top_keys) == 1 and isinstance(mat[top_keys[0]], dict):
        print(f"  (최상위 '{top_keys[0]}' 한 겹을 벗겨서 사용)")
        return mat[top_keys[0]]
    return mat


def inspect_metal_etch(path: str):
    mat = scipy.io.loadmat(path, simplify_cells=True)
    top_keys = [k for k in mat.keys() if not k.startswith("__")]
    print("최상위 키:", top_keys)
    inner = _unwrap(mat)
    print("실제 필드:", list(inner.keys()))
    for k, v in inner.items():
        print(f"  {k}: {type(v)}", f"len={len(v)}" if hasattr(v, "__len__") else "")
    return inner


def _drop_boundary_duplicate_row(matrix: np.ndarray) -> np.ndarray:
    """실측으로 확인된 사실: 이 데이터셋의 원본 .mat 파일은 각 웨이퍼의
    마지막 행이 다음 웨이퍼의 첫 행과 완전히 동일하다 (전체 실험을
    연속으로 로깅한 뒤 웨이퍼 단위로 자르면서 경계 지점을 양쪽에 한 번씩
    포함시킨 것으로 보임 -- 로더나 전처리 버그가 아니라 원본 데이터
    자체의 특성, 128쌍 중 116쌍에서 확인됨). 이 마지막 행은 이 웨이퍼
    자신의 진짜 마지막 측정치가 아니라 다음 웨이퍼 것이므로, 통계 계산
    전에 제거한다. 배열의 진짜 마지막 웨이퍼도 동일하게 한 행을 버리는데
    (그 경우 정말 자기 마지막 행일 수 있음), 전체 100여 행 중 1행 손실은
    무시할 만한 수준이라 조건 분기 없이 일괄 적용한다."""
    if matrix.shape[0] <= 1:
        return matrix
    return matrix[:-1]


def load_metal_etch_file(path: str, variable_group: str) -> list[dict]:
    """
    variable_group: "machine" | "oes" | "rfm" -- 어느 파일을 로드하는지 태깅용
    """
    raw = scipy.io.loadmat(path, simplify_cells=True)
    mat = _unwrap(raw)  # RFMDATA/MACHINEDATA/OESDATA 한 겹 벗기기

    calib_wafers = mat["calibration"]           # 정상 웨이퍼별 (시간 x 변수) 행렬 -- 개수는 파일마다 다름(모듈 docstring 참고)
    calib_names = _to_str_list(mat["calib_names"])
    test_wafers = mat["test"]                   # 결함 웨이퍼별 (시간 x 변수) 행렬
    test_names = _to_str_list(mat["test_names"])
    fault_names = _to_str_list(mat["fault_names"])
    # 실측 확인: 파일마다 "변수 정보"를 담는 필드 이름과 유무가 다르다.
    #   MACHINE(LAMDATA) : variables (21개, 문서와 일치)
    #   OES(OESDATA)     : variables 없음, 대신 wave_axis (129개 파장 채널)
    #   RFM(RFMDATA)     : variables (71개) + units (71개, 문서엔 없던 필드)
    variable_names = mat.get("variables")
    wave_axis = mat.get("wave_axis")      # OES 전용
    units = mat.get("units")              # RFM 전용

    records = []
    for name, matrix in zip(calib_names, calib_wafers):
        matrix = _drop_boundary_duplicate_row(np.asarray(matrix, dtype=float))
        records.append({
            "source_dataset": "metal_etch",
            "modality": "tabular_timeseries",
            "equipment_id": "LAM9600",
            "entity_id": _wafer_number(name),   # 원본 이름(l3342.txm 등) 대신 공통 웨이퍼 번호로 통일 -- 이게 세 파일 간 진짜 join key
            "source_name": name,                # 원본 이름은 디버깅용으로 보존
            "experiment_id": _extract_experiment_id(name),  # 29/31/33 -- 이상탐지 시 실험별 정규화 여부 결정에 사용
            "process_stage": "plasma_etch",
            "variable_group": variable_group,   # machine / oes / rfm -- 세 파일을 합칠 때 구분자
            "timestamp": None,                  # 절대시각 없음, 행렬 내 상대 시간 인덱스로 대체
            "label_type": "wafer_condition",    # test 레코드와 label_type을 통일 -- label_value로만 정상/결함을 구분
            "label_value": "normal",
            "features": matrix,
            "variable_names": variable_names,
            "wave_axis": wave_axis,
            "units": units,
        })

    for name, matrix, fault in zip(test_names, test_wafers, fault_names):
        matrix = _drop_boundary_duplicate_row(np.asarray(matrix, dtype=float))
        records.append({
            "source_dataset": "metal_etch",
            "modality": "tabular_timeseries",
            "equipment_id": "LAM9600",
            "entity_id": _wafer_number(name),
            "source_name": name,
            "experiment_id": _extract_experiment_id(name),
            "process_stage": "plasma_etch",
            "variable_group": variable_group,
            "timestamp": None,
            "label_type": "wafer_condition",    # calibration 레코드와 동일한 label_type -- 필터링 시 이 값 하나로 정상/결함 레코드를 함께 조회 가능
            "label_value": fault,               # 실제 결함 유형 라벨 -- RCA 엔진 결과와 대조할 정답
            "features": matrix,
            "variable_names": variable_names,
            "wave_axis": wave_axis,
            "units": units,
        })
    return records


def load_metal_etch_all(machine_path: str, oes_path: str, rfm_path: str) -> list[dict]:
    """세 파일을 각각 로드해서 하나의 레코드 리스트로 합친다.
    같은 웨이퍼라도 variable_group으로 구분되므로, entity_id가 같은
    레코드가 최대 3개(machine/oes/rfm)까지 나올 수 있다 -- 모듈
    docstring의 실측 겹침 결과대로 일부 웨이퍼는 2개만 나온다.
    행 단위로 강제 병합하지 않는 이유는 모듈 docstring의 '확인 안 된
    부분' 참고. entity_id 기준으로 inner join(3개 다 있는 것만)을
    할지 outer join(1개라도 있으면 포함)을 할지는 이 함수를 쓰는
    쪽(2-2 엔진)에서 결정한다."""
    return (
        load_metal_etch_file(machine_path, "machine")
        + load_metal_etch_file(oes_path, "oes")
        + load_metal_etch_file(rfm_path, "rfm")
    )


def compare_wafer_sets(machine_path: str, oes_path: str, rfm_path: str) -> None:
    """세 파일의 calib_names/test_names를 비교해서 어떤 웨이퍼가
    machine에는 있는데 oes·rfm에는 없는지 보여준다.

    ★ 주의: 원본 이름 그대로 비교하면 안 된다 ★
    MACHINE은 l3342.txm, OES는 s3342.int, RFM은 r3342.txt처럼 같은
    웨이퍼도 접두문자·확장자가 파일마다 달라서 문자열이 절대 안 겹친다.
    반드시 _wafer_number()로 뽑은 숫자 4자리로 비교해야 진짜 겹치는
    부분이 보인다."""
    def _names(path):
        raw = scipy.io.loadmat(path, simplify_cells=True)
        mat = _unwrap(raw)
        calib = {_wafer_number(n) for n in _to_str_list(mat["calib_names"])}
        test = {_wafer_number(n) for n in _to_str_list(mat["test_names"])}
        return calib, test

    m_calib, m_test = _names(machine_path)
    o_calib, o_test = _names(oes_path)
    r_calib, r_test = _names(rfm_path)

    print("=== calibration(정상) 웨이퍼 ===")
    print("MACHINE에만 있고 OES엔 없음:", m_calib - o_calib)
    print("MACHINE에만 있고 RFM엔 없음:", m_calib - r_calib)
    print("OES와 RFM이 서로 다른 부분:", o_calib.symmetric_difference(r_calib))

    print("=== test(결함) 웨이퍼 ===")
    print("MACHINE에만 있고 OES엔 없음:", m_test - o_test)
    print("MACHINE에만 있고 RFM엔 없음:", m_test - r_test)
    print("OES와 RFM이 서로 다른 부분:", o_test.symmetric_difference(r_test))


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 4:
        # 사용법: python metal_etch_loader.py MACHINE_Data.mat OES_DATA.mat RFM_DATA.mat
        compare_wafer_sets(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        # 사용법: python metal_etch_loader.py RFM_DATA.mat
        inspect_metal_etch(sys.argv[1])
