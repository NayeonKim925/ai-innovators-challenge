# Metal Etch Data — 데이터 설명

## 이게 뭔가요

LAM 9600 플라즈마 금속 에처(Metal Etcher)로 웨이퍼 129장을 처리하며 수집한
실측 공정 데이터. 정상 웨이퍼와 의도적으로 결함을 유발한 웨이퍼가 섞여 있어서,
"설비 센서 이상 → 웨이퍼 결과" 인과관계를 실제로 추적할 수 있는 몇 안 되는
공개 반도체 장비 데이터셋이다.

- 출처: Eigenvector Research, Inc.
  (https://eigenvector.com/resources/data-sets/metal-etch-data-for-fault-detection-evaluation/)
- 원 논문: B.M. Wise, N.B. Gallagher, S.W. Butler, D.D. White Jr., G.G. Barna,
  "A Comparison of Principal Components Analysis, Multi-way Principal
  Components Analysis, Tri-linear Decomposition and Parallel Factor Analysis
  for Fault Detection in a Semiconductor Etch Process", J. Chemometrics,
  13, 379-396 (1999).
- 다운로드 (로그인 불필요, 팀원 각자 로컬에 받을 것 — git에는 올리지 않음):
  - http://eigenvector.com/data/Etch/MACHINE_Data.mat
  - http://eigenvector.com/data/Etch/OES_DATA.mat
  - http://eigenvector.com/data/Etch/RFM_DATA.mat

## 파일 3개, 서로 다른 측정 장비

같은 129개 웨이퍼(정상 108 + 결함 21)를 세 종류의 센서 시스템으로 각각
측정한 결과가 별도 파일로 나뉘어 있다.

| 파일 | 측정 대상 | 실제 정상/결함 개수 |
|---|---|---|
| MACHINE_Data.mat | 장비 공정변수 (21개) | 108 / 21 (공식 문서와 일치) |
| OES_DATA.mat | 광방출분광(OES), 파장 채널 129개 | 106 / 20 |
| RFM_DATA.mat | RF 모니터 변수 (71개 + 단위) | 106 / 20 |

**공식 문서는 "108/21"이라고만 적혀 있지만, 실제로 열어보면 파일마다 개수가
다르다.** OES·RFM은 일부 웨이퍼에서 광학/RF 센서 기록이 빠져 있다.

## 팀이 직접 확인한 내부 구조 (공식 문서에 없던 부분)

1. **한 겹 더 감싸져 있음**: 각 .mat 파일을 열면 최상위에 `LAMDATA`
   (MACHINE) / `OESDATA` (OES) / `RFMDATA` (RFM) 라는 이름의 struct가 있고,
   그 안에 실제 필드(`calibration`, `test`, `calib_names` 등)가 들어있다.
2. **변수 정보 필드 이름이 파일마다 다름**: MACHINE·RFM은 `variables`
   필드를 쓰지만 OES는 `variables`가 없고 대신 `wave_axis`(파장 축, 129개)를
   쓴다. RFM에는 문서에 없던 `units`(변수별 단위) 필드도 있다.
3. **웨이퍼 이름 표기가 파일마다 다름**: 같은 웨이퍼라도
   MACHINE=`l3342.txm`, OES=`s3342.int`, RFM=`r3342.txt`처럼 접두문자와
   확장자가 다르다. **진짜 공통 키는 이름 중간의 숫자 4자리**다.
   앞 두 자리가 실험번호(29/31/33)와 일치한다 — 공식 문서에 "실험이 몇
   주 간격으로 진행돼 평균·공분산 구조가 다르다"고 적힌 그 실험번호다.
4. **fault_names 필드가 실제 결함 유형 라벨**: 21개(MACHINE 기준) 결함
   웨이퍼 각각에 구체적인 결함 유형이 붙어 있어서, RCA 엔진이 낸 원인후보를
   이 라벨과 대조해 정량 검증할 수 있다.

## 세 그룹의 실제 겹침 (숫자 4자리 기준으로 재확인함)

- calibration(정상) 108개 중 **104개는 machine·oes·rfm 전부 존재**,
  4개는 둘 중 하나만 존재 (2개는 OES 없음, 2개는 RFM 없음 — 서로 다른
  웨이퍼라 완전히 상쇄되진 않음)
- test(결함) 21개 중 **20개는 셋 다 존재**, 1개(2916번)는 MACHINE에만 존재

`preprocess.py`를 돌리면 `processed/metadata.csv`에 웨이퍼별로 이 존재
여부(`has_machine`/`has_oes`/`has_rfm`/`complete_case`)가 컬럼으로 정리된다.

## 전처리 실행 방법

1. 위 세 링크에서 .mat 파일을 받아 이 저장소 루트(스크립트와 같은 폴더)에 둔다.
2. `pip install scipy pandas numpy` (아직 없다면)
3. `python preprocess.py` 실행
4. `processed/` 폴더에 `metadata.csv`, `variable_names.json`, `features/`가 생성됨

## 이 데이터로 뭘 하려는지 (팀 프로젝트 맥락)

원인후보 랭킹 엔진(NL→SQL→Python 통계분석 + causRCA 기반 causal
discovery)의 입력으로 쓴다. `complete_case`가 true인 웨이퍼는 세 센서군을
전부 볼 수 있어서 원인 추적 데모의 메인 케이스로 쓰고, 나머지는 부분
데이터로도 알고리즘이 동작하는지 보는 보조 케이스로 쓴다. `fault_names`
라벨은 최종 EITL(전문가 승인) 단계 전에 알고리즘 정확도를 자체 점검하는
정답으로 쓴다.
