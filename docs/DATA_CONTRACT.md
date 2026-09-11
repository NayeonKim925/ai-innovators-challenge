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

## 근거 계약

모든 후보는 하나 이상의 `Evidence`를 참조해야 합니다. 근거에는 관측 신호·시점·결정론적 도구·인용 문서 중 무엇이 후보를 뒷받침하는지 담습니다. 근거 없는 후보는 유력 원인으로 순위화하지 않고 `inconclusive`로 처리합니다.
