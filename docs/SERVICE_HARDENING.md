# 서비스 전환 구현 계획

이 문서는 Streamlit 연구 화면을 실제 서비스 흐름으로 전환하는 현재 기준선이다.

## 현재 반영된 단계

1. 런타임 JSON은 프로세스마다 다시 읽지 않고 저장소 인스턴스 안에서 캐시한다.
2. 조사 결과와 전문가 검토는 `INVESTIGATION_DDB_TABLE`이 설정되면 DynamoDB에 저장한다.
3. 증거 폐쇄형 사건 상태는 `CASE_DDB_TABLE`이 설정되면 별도 DynamoDB 테이블에 저장한다.
4. 공개 배포 스크립트는 `API_AUTH_TOKEN` 없이는 실행되지 않는다.
5. LLM 프롬프트에는 사용자 질문, 후보, 근거 ID·상세·출처가 들어간다.
6. 후보가 없거나 모두 `inconclusive`이면 LLM을 호출하지 않고 판단 보류를 반환한다.
7. 설정된 Bedrock Guardrail을 입력과 출력에 독립적으로 적용한다.
8. 저장된 조사에 한정한 `POST /api/investigations/{id}/chat`을 제공한다.
9. Streamlit 읽기 요청은 TTL 캐시하고, 조사 입력은 폼 제출로 묶으며 보고서를 JSON으로 내려받을 수 있다.
10. 선택적 LLM 요약은 `LLM_JOB_QUEUE_URL`이 설정된 AWS 환경에서 SQS + worker Lambda로 비동기 처리할 수 있다.

## 운영 흐름

```text
사건/관측값 조회
  -> cutoff 검증
  -> 결정론적 분석
  -> 근거 ID·내용 검증
  -> DynamoDB에 조사 저장
  -> (선택) SQS에 조사 ID만 발행 -> worker가 DynamoDB 결과를 읽고 Guardrail 입력 검사 -> Bedrock -> 출력 검사
  -> 전문가 검토/사건별 질문
```

LLM은 후보 순위나 수치를 계산하지 않는다. 후보가 새로 생기거나 근거 ID가 바뀌면
분석 도구와 검증 단계의 오류로 간주한다.

## 배포 설정

```bash
export API_AUTH_TOKEN="long-random-server-token"
export CORS_ORIGINS="https://your-frontend.example"
export BEDROCK_GUARDRAIL_ID="your-guardrail-id"
export BEDROCK_GUARDRAIL_VERSION="1"
export INVESTIGATION_DDB_TABLE="mfg-investigations"
export CASE_DDB_TABLE="mfg-investigation-cases"
export LLM_JOB_QUEUE_NAME="mfg-investigation-narrative-jobs"
python backend/deploy_lambda_api.py
```

Streamlit에는 `BACKEND_API_TOKEN`을 서버 환경변수로만 설정한다. 브라우저 번들,
Git 커밋, Docker 이미지 레이어에 토큰을 넣지 않는다.

비동기 요약을 요청할 때는 다음과 같이 호출한다.

```json
{
  "diagnosis_time": 212.1,
  "include_llm_narrative": true,
  "async_llm_narrative": true
}
```

응답은 `202`와 `llm_status=queued`이며, 같은 investigation ID를 `GET`해
`generated`, `blocked`, `unverified`, `unavailable` 중 최종 상태를 확인한다.

## 다음 단계

- CausTR의 무거운 의존성은 Lambda에 억지로 포함하지 않고 별도 분석 워커로 분리한다.
- 실제 AWS 계정에서 SQS → worker Lambda → DynamoDB 흐름을 한 번 검증하고 p50/p95를 기록한다.
- Streamlit은 운영 검증용으로 유지하고 React/TypeScript 화면에서 사건 타임라인,
  근거 패널, 채팅, 검토 상태를 하나의 작업 공간으로 재구성한다.
- 배포본에서 로컬과 동일한 후보·근거를 반환하는 계약 테스트와 p50/p95·토큰 비용을
  CI에 추가한다.
