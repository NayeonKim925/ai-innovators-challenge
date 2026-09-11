# 공통 스키마 파이프라인 — 설계 근거

전체 개발 프로세스와 진행 상황은 PROJECT_GUIDE.md를 먼저 보는 게 낫다.
이 문서는 "왜 스키마를 이런 원칙으로 설계했는가"에 대한 근거만 다룬다.

## 무엇을 검증했고 무엇을 바꿨나

기존 계획은 "PHM/Metal Etch/SECOM/WM-811K를 장비ID·타임스탬프·공정단계·lot/wafer
매핑으로 정규화"였다. 이 표현 그대로 실행하면 4개의 서로 무관한 공개 데이터셋이
실제로 연결된 것처럼 보이는 스키마를 만들게 된다 — 하지만 이들 사이에는 진짜
공유되는 장비ID나 lot/wafer ID가 없다.

**바뀐 원칙**: 공통 스키마 = "데이터가 이어진다"는 주장이 아니라 "서로 다른 포맷을
같은 인터페이스로 흡수하는 어댑터 패턴". source_dataset을 항상 남기고, 이 값이
다른 레코드끼리는 join하지 않는다.

## 데이터셋별 역할

| 데이터셋 | modality | 역할 |
|---|---|---|
| Metal Etch Data | tabular_timeseries | **메인 인과사슬 데모** — 같은 실험 안에서 설비센서와 웨이퍼결과가 실제로 연결된 유일한 소스 (정상/결함 정확한 개수는 파일별로 다름, METAL_ETCH_DATA.md 참고) |
| PHM 2018 | tabular_timeseries | 별도 모듈 — 다른 장비 유형(이온밀링)에도 같은 파이프라인이 붙는다는 일반성 증명 |
| SECOM | feature_vector | 별도 모듈 — 시계열이 아닌 feature vector 데이터도 같은 인터페이스로 흡수됨을 증명 |
| WM-811K | image | 별도 모듈 — 이미지 기반 결함 데이터까지 같은 스키마의 메타데이터 레이어에 태깅됨을 증명 |

## 실행 순서

1. `loaders/metal_etch_loader.py`는 실제 파일 구조 확인이 끝나서 바로
   `preprocess.py`로 실행 가능하다 (자세한 구조는 METAL_ETCH_DATA.md).
   `loaders/secom_loader.py`, `loaders/wm811k_loader.py`도 공개 포맷이
   명확해서 바로 실행 가능하다.
2. `loaders/phm_loader.py`는 실제 컬럼/필드명이 아직 불확실하므로
   `inspect_phm()`을 먼저 실행해서 구조를 확인한 뒤 `load_phm()`에 맞는
   컬럼명을 넣는다 (PHM/SECOM/WM-811K는 현재 스코프에서 후순위 — PROJECT_GUIDE.md 참고).
   PHM은 이미 확보한 GitHub 저장소(ninja1mmm/2018-phm-data-challenge)의
   로딩 코드가 1차 근거다.
3. 원본 feature(590차원 벡터, 2D 웨이퍼맵 등)는 `CANONICAL_META_COLUMNS`에
   넣지 않고 `(source_dataset, entity_id)`를 키로 별도 저장한다 — 서로 다른
   물리량을 같은 컬럼명으로 억지로 맞추지 않기 위함.

## NL→SQL 엔진에 연결할 때

AWS AI Innovators Challenge에서 만든 NL→SQL 엔진은 `CANONICAL_META_COLUMNS`
테이블 위에서 동작하게 한다. 원인후보 랭킹까지는 알고리즘이 하고, 최종 확정은
EITL(Expert-in-the-Loop) 단계에서 공정 엔지니어가 승인하는 구조는 그대로 유지한다.
