"""
공통 스키마 정의 (canonical schema)

★ 읽고 시작할 것 ★
PHM 2018 / Metal Etch Data / SECOM / WM-811K는 서로 다른 fab, 다른 시기,
다른 장비에서 나온 4개의 독립된 공개 데이터셋이다. 이들 사이에는 실제로
공유되는 equipment_id, lot_id, wafer_id가 존재하지 않는다.

이 스키마로 정규화한다는 것은 "네 데이터가 실제로 이어진다"는 뜻이 아니라,
서로 다른 포맷의 데이터를 같은 하위 코드(에이전트 tool, NL→SQL 엔진,
대시보드)가 동일하게 다룰 수 있게 만드는 어댑터 패턴이다.

지켜야 할 규칙:
1. source_dataset은 절대 누락하지 않는다 — 이게 없으면 나중에 실수로
   서로 다른 소스를 join하는 사고가 난다.
2. source_dataset이 다른 두 레코드를 entity_id나 equipment_id로 join하지
   않는다. 데모 목적으로 인위적 연결을 만들 경우, "이건 실제 데이터가
   아니라 시연용 가상 연결"이라고 반드시 명시한다.
3. 실제로 설비센서 → 웨이퍼결과가 "같은 소스 안에서" 연결된 유일한 데이터는
   metal_etch뿐이다 (같은 실험, 같은 LAM9600 장비, 웨이퍼 129개 -- 정확한
   정상/결함 개수는 파일마다 다르며 loaders/metal_etch_loader.py와
   METAL_ETCH_DATA.md에 실측치 정리됨). 인과사슬을 보여주는 메인 데모는
   이 데이터 하나로 완결시킨다.
4. 원본 feature 컬럼명은 소스별로 그대로 보존한다. PHM의 센서와 SECOM의
   익명화된 590개 feature는 물리적으로 다른 것이므로 같은 이름
   (sensor_1...sensor_n)으로 억지로 맞추지 않는다.
"""

from dataclasses import dataclass, field
from typing import Optional, Literal, Any

Modality = Literal["tabular_timeseries", "feature_vector", "image"]
SourceDataset = Literal["phm2018", "metal_etch", "secom", "wm811k"]


@dataclass
class CanonicalRecord:
    source_dataset: SourceDataset     # 어느 데이터셋 출신인지 -- 항상 채울 것
    modality: Modality                # 원본 신호의 형태
    equipment_id: Optional[str]       # 장비 식별자 -- 없는 소스(SECOM, WM-811K)는 None, 지어내지 않는다
    entity_id: str                    # run_id / wafer_id / lot_id -- 그 소스에서 자연스러운 분석 단위
    process_stage: str                # 자유 텍스트 태그, 예: 'ion_mill_hold', 'plasma_etch', 'wafer_test', 'wafer_map_inspection'
    timestamp: Optional[str]          # 실제 시각이 없으면 None (가짜 시각을 만들지 않는다)
    label_type: str                   # 그 소스가 실제로 제공하는 라벨의 성격 (ttf, normal_fault, pass_fail, defect_pattern 등)
    label_value: Any                  # 라벨 값. 모르면 None으로 두고 TODO를 남긴다
    features: Any                     # 원본 feature. 소스마다 형태가 다르므로 dict/array/2D array 등 그대로 보존
    raw_ref: Any = field(default=None, repr=False)  # 디버깅용 원본 참조 (선택)


# NL→SQL 엔진이 소스에 관계없이 조회할 "메타데이터 테이블" 컬럼.
# 원본 feature(590차원 SECOM 벡터, 웨이퍼맵 2D 배열 등)는 이 테이블에 넣지 않고
# (source_dataset, entity_id)를 키로 별도 저장소에서 조회한다.
CANONICAL_META_COLUMNS = [
    "source_dataset",
    "modality",
    "equipment_id",
    "entity_id",
    "process_stage",
    "timestamp",
    "label_type",
    "label_value",
]
