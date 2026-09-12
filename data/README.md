# 로컬 데이터 준비

원본 데이터·runtime 사건·평가 정답은 Git에 올리지 않는다. `data/manifests/`만
버전 관리하며, 같은 원본을 재현하기 위한 DOI·버전·체크섬을 담는다.

## causRCA

```sh
python scripts/bootstrap_causrca.py
python scripts/prepare_causrca.py --source data/raw/causrca
python scripts/validate_data.py
python -m evals.run_causrca_benchmark --method time_recency
```

- `data/raw/causrca/`: Zenodo 원본과 다운로드 archive
- `data/runtime/causrca/`: 서비스가 읽는 관측값·전문가 그래프. 원인 정답과
  진단 시점은 포함하지 않는다.
- `data/evaluation/causrca/`: offline benchmark 전용 정답·진단 시점

causRCA의 fault 시나리오는 HIL 시뮬레이션이다. 발표에서 실제 공장 장애나
운영 성과로 과장하지 않는다.

`caus_tr` benchmark는 upstream의 선택 의존성을 추가로 요구한다.

```sh
python -m pip install -e '.[causrca]'
python -m evals.run_causrca_benchmark --method caus_tr
```
