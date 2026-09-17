# 데이터 활용 타당성

> 배점 대응: 데이터 활용성(적합성·타당성, 처리 프로세스) 10점

## 왜 두 데이터셋을 함께 쓰는가

이 프로젝트는 causRCA(정답 라벨이 있는 100건 HIL 시뮬레이션 benchmark)와 Metal Etch(정답이 불확실한 실제 LAM 9600 반도체 식각 장비 데이터)를 동시에 사용합니다. 하나만 쓰면 다음과 같은 반박에 답할 수 없기 때문입니다.

- **causRCA만 쓴다면**: "이 성능 수치는 시뮬레이션 환경에서만 유효한 것 아닌가? 실제 현장 데이터에도 같은 아키텍처가 작동하는가?"라는 질문에 답할 수 없습니다. causRCA는 HIL(Hardware-In-the-Loop) 시뮬레이션이므로, `data/README.md`에도 명시했듯 "실제 공장 장애나 운영 성과로 과장하지 않는다"는 제약이 있습니다.
- **Metal Etch만 쓴다면**: 원인 후보 순위가 실제로 정확한지 정량적으로 검증할 방법이 없습니다. Metal Etch의 fault label(`TCP +50` 등)은 변수 단위의 정밀한 정답이 아니라 결함 유형 이름 수준이라, Hit@k 같은 지표를 신뢰 있게 계산하기 어렵습니다 (`docs/decisions/ADR-0001-primary-dataset.md`).

두 데이터셋을 같은 `Incident`/`Evidence`/`Candidate` 계약 위에서 동시에 굴리면, "정량적으로 검증된 벤치마크(causRCA) + 정답 없는 실제 산업 데이터에서의 이식성 실증(Metal Etch)"이라는 두 가지 주장을 하나의 아키텍처로 함께 뒷받침할 수 있습니다. 이것이 causRCA를 핵심 benchmark로, Metal Etch를 이식성 어댑터로 명확히 역할을 나눈 이유입니다 (성능 수치는 causRCA만 사용, 두 데이터셋의 결과를 섞지 않음 — `docs/PRODUCT.md`).

## 데이터 처리 프로세스

```text
[원본]                    [어댑터]                          [분리된 저장 영역]
MACHINE_Data.mat  ──▶ metal_etch_adapter.py           ──▶ data/runtime/metal_etch/
(causRCA: HIL CSV)      build_metal_etch_dataset()          incidents.json (관측값만)
                        causrca: prepare_causrca.py          normal_baseline.json (PCA 기준선)
                                │
                                └────────────────────────▶ data/evaluation/metal_etch/
                                    fault_names/label_reliable  labels.json (정답 라벨만)
```

1. **원본 → 어댑터**: `metal_etch_adapter.py`/`scripts/prepare_causrca.py`가 원본 파일을 읽어 공통 `Incident` 계약(신호·시점·종류)으로 변환합니다.
2. **격리**: 변환 과정에서 `fault_names`, `label_value`, `label_reliable` 같은 정답성 필드는 `Incident`에 절대 포함되지 않고, `evaluation_labels`라는 별도 구조로만 반환됩니다. 이 값은 `data/evaluation/`에만 쓰여야 하며, 서비스 코드는 이 경로를 import하지 않습니다.
3. **강제 검증**: `backend/app/data/runtime_repository.py`의 `FORBIDDEN_RUNTIME_KEYS`가 `data/runtime/`에서 읽은 JSON에 `label`, `root_cause`, `diagnosis_time` 등의 키가 하나라도 있으면 즉시 예외를 던집니다. 이 검증은 `test_runtime_contract.py`로 테스트가 고정돼 있어, 이후 어떤 어댑터를 추가해도 같은 규칙이 자동으로 적용됩니다.

## 약점을 숨기지 않고 명시: 라벨 신뢰도 문제

Metal Etch의 결함 웨이퍼 21건 중 **5건(2918, 2937, 3141, 3142, 3339)은 `label_reliable=False`**로 표시돼 있습니다 (`metal_etch_adapter.py`의 `UNRELIABLE_ENTITY_IDS`). 이 5건은 실측 신호를 직접 대조했을 때 fault label과 실제 관측값 변화가 일치하지 않는 것으로 확인된 웨이퍼입니다(`inspect_failing_cases.py`/`flag_unreliable_labels.py`).

이 5건을 조용히 삭제하거나 라벨을 추측으로 수정하지 않고, **신뢰도 플래그를 붙여서 그대로 데이터셋에 포함**시킨 이유는 다음과 같습니다.

- 라벨을 임의로 "고치면" 우리가 새로운 오류를 데이터에 주입할 위험이 있습니다. 원인을 모르면 "모른다"고 남겨두는 것이 데이터 자체에 대한 정직한 태도입니다.
- 이 플래그 자체가 "우리는 데이터 타당성을 스스로 검증했다"는 메타인지의 증거입니다. 21건 중 5건(약 24%)의 라벨에 의문을 제기하고 이를 공개한 팀과, 모든 라벨을 무비판적으로 정답처럼 쓰는 팀은 데이터 리터러시 수준에서 다르게 평가받아야 합니다.
- `MetalEtchEvaluationLabel.label_reliable` 필드로 구조화돼 있어서, 이후 평가 스크립트가 신뢰 가능한 16건만 골라 쓰거나 21건 전체를 쓰는 것을 명시적으로 선택할 수 있습니다. 데이터 품질 문제를 코드 밖 지식이 아니라 스키마 안의 필드로 만들어 둔 것입니다.
