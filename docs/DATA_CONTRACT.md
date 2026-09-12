# 데이터 계약과 격리 정책

## 데이터셋 경계

모든 사건에는 `source_dataset`이 필수입니다. 어댑터는 각 출처를 공통 계약으로 변환할 수 있지만, 출처가 다른 entity를 같은 생산 현장의 데이터처럼 join하면 안 됩니다.

## 저장 영역

| 영역 | 허용 내용 | 서비스 runtime 접근 |
| --- | --- | --- |
| `data/raw/` | 원본 다운로드 자료 | 준비 작업만 가능 |
| `data/runtime/` | 조사 cutoff 이전에 관측 가능한 사건·신호 | 가능 |
| `data/evaluation/` | 원인 정답, split, 진단 라벨 | 불가 |
| `data/processed/` | 재현 가능한 파생 산출물 | 명시적으로 export한 경우만 가능 |

## Runtime 사건 형식

```json
{
  "id": "case_123",
  "source_dataset": "causrca",
  "title": "준비된 사건",
  "time_range_s": {"start": 0.0, "end": 3600.0},
  "capabilities": ["time_series", "root_cause_ranking"],
  "observations": [
    {"time_s": 12.0, "signal": "P101", "value": "True", "kind": "Alarm"}
  ]
}
```

`label`, `label_value`, `root_cause`, `ground_truth`, `manipulated_variable`, `diagnosis_time`, `fault_name`, `split`은 runtime에 들어오면 안 되는 필드입니다.

## Metal Etch 정상 웨이퍼 기준선 (`data/runtime/metal_etch/normal_baseline.json`)

`analytics/metal_etch_pca.py`가 PCA 정상 운전 기준선을 학습할 때만 읽는 별도 runtime 파일입니다. `incidents.json`과 달리 이 파일의 각 항목은 `Incident`가 아니라 `data/metal_etch_adapter.py`의 `NormalWaferRecord`이며, 세 필드만 가진 요약 형태입니다.

```json
{
  "entity_id": "2901",
  "experiment_id": "29",
  "observations": [
    {"time_s": 0.0, "signal": "BCl3 Flow", "value": 750.0, "kind": "Measurement"}
  ]
}
```

정상(calibration) 웨이퍼에는 애초에 결함 라벨이 없으므로 `label_value`/`fault_name` 같은 필드를 담을 이유가 없습니다. `incidents.json`은 `JsonRuntimeRepository`가 `FORBIDDEN_RUNTIME_KEYS`로 명시적으로 검사하지만, `normal_baseline.json`은 이 검사를 거치지 않습니다 — 대신 `NormalWaferRecord`가 `extra="forbid"` 스키마(`entity_id`/`experiment_id`/`observations` 세 필드만 허용)라서, 금지 필드가 섞여 들어오면 Pydantic 검증 단계에서 곧바로 실패합니다. 두 파일 모두 최종적으로는 같은 목적(평가 정답이 runtime에 새지 않게 막는 것)을 이루지만, 검증 메커니즘 자체는 다르다는 점을 유의해야 합니다.

## 근거 계약

모든 후보는 하나 이상의 `Evidence`를 참조해야 합니다. 근거에는 관측 신호·시점·결정론적 도구·인용 문서 중 무엇이 후보를 뒷받침하는지 담습니다. 근거 없는 후보는 유력 원인으로 순위화하지 않고 `inconclusive`로 처리합니다.
