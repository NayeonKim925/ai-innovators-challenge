"""Streamlit demo UI for the manufacturing investigation service (2-C).

★ 설계 원칙 (docs/IMPLEMENTATION_PLAN.md 트랙 E) ★
"채팅창은 보조 인터페이스다. 메인 화면은 사건 → 신호 → 후보 → 근거 → 검토
흐름이어야 한다." 이 앱은 그 순서를 그대로 따른다: 데이터셋/사건 선택 →
진단 cutoff 지정 → 조사 실행(결정론적, 선택적 LLM 요약) → 후보와 근거 확인 →
전문가 승인/거절 기록 → 보고서 다운로드.

★ 왜 backend.app을 직접 import하지 않는가 ★
이 파일은 순수 HTTP 클라이언트다. FastAPI 서버(`backend/app/main.py`)를
별도 프로세스로 띄우고, 이 앱은 `requests`로만 통신한다. `backend.app`을
직접 import하면 domain/analytics/workflow 계층과 UI 계층이 섞이게 되는데,
이건 ARCHITECTURE.md가 명시적으로 금지하는 경계 위반이다 ("domain, data,
analytics, workflow, API 계층을 섞지 않습니다" -- API도 UI와 섞으면 안 된다는
확장 해석). 이렇게 분리해두면 배포 시 이 UI를 Streamlit Cloud 등 별도
서비스로 옮겨도 백엔드 코드가 따라올 필요가 없다.

★ LLM 미설정 상태 시연 (M3 DoD) ★
"include_llm_narrative" 체크박스를 기본 해제 상태로 둔다. 체크하지 않으면
백엔드는 LLM을 전혀 호출하지 않고, 체크해도 백엔드가 안전하게 폴백하면
`mode`는 그대로 "deterministic"으로 남는다 -- 이 앱은 그 값을 그대로
사용자에게 보여준다 (지어내지 않음).
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
BACKEND_API_TOKEN = os.getenv("BACKEND_API_TOKEN", "")
REQUEST_TIMEOUT_S = 15

st.set_page_config(page_title="제조 이상 조사", layout="wide")


@st.cache_resource
def _http_session() -> requests.Session:
    session = requests.Session()
    if BACKEND_API_TOKEN:
        session.headers.update({"Authorization": f"Bearer {BACKEND_API_TOKEN}"})
    return session


@st.cache_data(ttl=30, max_entries=100, show_spinner=False)
def _get_cached(path: str) -> dict[str, Any] | None:
    try:
        response = _http_session().get(f"{BACKEND_URL}{path}", timeout=REQUEST_TIMEOUT_S)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def _get(path: str) -> dict[str, Any] | None:
    payload = _get_cached(path)
    if payload is None:
        st.error(f"백엔드 요청 실패 ({path})")
    return payload


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        response = _http_session().post(
            f"{BACKEND_URL}{path}", json=payload, timeout=REQUEST_TIMEOUT_S
        )
        if response.status_code >= 400:
            detail = response.json().get("detail", response.text)
            st.error(f"백엔드 오류 ({response.status_code}): {detail}")
            return None
        return response.json()
    except requests.RequestException:
        st.error(f"백엔드 요청 실패 ({path})")
        return None


def _render_candidate(candidate: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> None:
    status = candidate["status"]
    badge = "🟡 판단 보류(inconclusive)" if status == "inconclusive" else "🟢 후보"
    with st.container(border=True):
        st.markdown(f"**#{candidate['rank']} · {candidate['signal']}** — {badge}")
        st.write(candidate["reason"])
        st.caption("근거:")
        for eid in candidate["evidence_ids"]:
            item = evidence_by_id.get(eid)
            if item is None:
                st.caption(f"- (근거 ID {eid}를 찾을 수 없음 -- 검증 실패로 표시되어야 함)")
                continue
            st.caption(f"- **{item['title']}** ({item['source']}): {item['detail']}")


def _render_trace(trace: list[dict[str, Any]]) -> None:
    for event in trace:
        latency = event.get("latency_ms")
        tokens = event.get("token_usage")
        latency_part = f", latency={latency}ms" if latency is not None else ""
        tokens_part = f", tokens={tokens}" if tokens is not None else ""
        st.caption(
            f"step {event['step']} · `{event['tool']}` -- "
            f"{event['detail']}{latency_part}{tokens_part}"
        )


st.title("제조 이상 조사")
st.caption(
    "관측값에서 검증 가능한 원인 후보와 근거를 정리합니다. 설비 제어는 하지 않으며, "
    "최종 판단은 담당 엔지니어가 확정합니다."
)

with st.sidebar:
    st.subheader("백엔드 연결")
    st.write(BACKEND_URL)
    health = _get("/api/health")
    if health:
        st.success(f"status={health['status']} · mode={health['mode']}")
    else:
        st.warning("백엔드에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인하세요.")
        st.code("uvicorn app.main:app --reload", language="bash")

datasets_payload = _get("/api/datasets")
if datasets_payload:
    st.subheader("데이터셋 상태")
    cols = st.columns(len(datasets_payload["datasets"]) or 1)
    for col, dataset in zip(cols, datasets_payload["datasets"]):
        with col:
            st.metric(dataset["dataset"], dataset["status"], f"{dataset['incident_count']}개 사건")

st.divider()
st.subheader("1. 사건 선택")

dataset_filter = st.selectbox(
    "데이터셋 필터", options=["(전체)", "causrca", "metal_etch"], index=0
)
if dataset_filter == "(전체)":
    incidents_path = "/api/incidents"
else:
    incidents_path = f"/api/incidents?dataset={dataset_filter}"
incidents_payload = _get(incidents_path)
incidents = incidents_payload["incidents"] if incidents_payload else []

if not incidents:
    st.info(
        "준비된 사건이 없습니다. `scripts/prepare_causrca.py` 등으로 "
        "runtime 데이터를 먼저 준비하세요."
    )
    st.stop()

incident_labels = {
    f"{item['id']} · {item['title']} ({item['source_dataset']})": item for item in incidents
}
selected_label = st.selectbox("사건", options=list(incident_labels.keys()))
selected_incident = incident_labels[selected_label]

incident_detail = _get(f"/api/incidents/{selected_incident['id']}")
if incident_detail is None:
    st.stop()

time_range = incident_detail["time_range_s"]
st.caption(
    f"시간 범위: {time_range['start']}s ~ {time_range['end']}s · "
    f"관측값 {len(incident_detail['observations'])}건 · "
    f"capability: {', '.join(incident_detail['capabilities']) or '없음'}"
)
with st.expander("관측값 보기 (조사 시점 이전에 실제로 관측 가능한 값만 포함)"):
    st.dataframe(incident_detail["observations"], use_container_width=True)

st.divider()
st.subheader("2. 진단 시점(cutoff) 지정 및 조사 실행")

col_cutoff, col_llm = st.columns([2, 1])
with col_cutoff:
    with st.form("investigation_form", clear_on_submit=False):
        diagnosis_time = st.slider(
            "진단 시점 (초)",
            min_value=float(time_range["start"]),
            max_value=float(time_range["end"]),
            value=float(time_range["end"]),
        )
        question = st.text_input("담당자 질문 (선택)", value="")
        submit_investigation = st.form_submit_button("조사 실행", type="primary")
with col_llm:
    include_llm_narrative = st.checkbox(
        "LLM 요약 포함 (Bedrock Claude, 선택)",
        value=False,
        help="체크하지 않으면 결정론적 분석만 실행됩니다. 체크해도 LLM이 "
        "새 원인후보를 만들거나 순위를 바꾸지 않습니다.",
    )

if st.session_state.get("selected_incident_id") != selected_incident["id"]:
    st.session_state.selected_incident_id = selected_incident["id"]
    st.session_state.investigation = None
    st.session_state.chat_history = []
if "investigation" not in st.session_state:
    st.session_state.investigation = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if submit_investigation:
    result = _post(
        f"/api/incidents/{selected_incident['id']}/investigations",
        {
            "diagnosis_time": diagnosis_time,
            "question": question,
            "include_llm_narrative": include_llm_narrative,
        },
    )
    st.session_state.investigation = result
    st.session_state.chat_history = []

investigation = st.session_state.investigation

if investigation:
    st.divider()
    st.subheader("3. 원인 후보와 근거")
    st.caption(f"조사 ID: `{investigation['investigation_id']}` · mode: `{investigation['mode']}`")

    if investigation["warnings"]:
        for warning in investigation["warnings"]:
            st.warning(warning)

    evidence_by_id = {item["id"]: item for item in investigation["evidence"]}
    if investigation["candidates"]:
        for candidate in investigation["candidates"]:
            _render_candidate(candidate, evidence_by_id)
    else:
        st.info("원인 후보가 산출되지 않았습니다 (판단 보류).")

    if investigation.get("llm_narrative"):
        st.markdown("##### AI 초안 요약 (검토 필요)")
        st.info(investigation["llm_narrative"])
    elif include_llm_narrative:
        st.caption(
            "LLM 요약을 요청했지만 생성되지 않았습니다 (미가용 또는 호출 실패) -- "
            "결정론적 결과만 표시합니다."
        )

    with st.expander("실행 이력 (tool trace)"):
        _render_trace(investigation["trace"])

    st.divider()
    st.subheader("4. 전문가 검토")
    with st.form("review_form"):
        reviewer = st.text_input("검토자 이름")
        decision = st.radio("판단", options=["approve", "reject"], horizontal=True)
        comment = st.text_area("사유 / 코멘트")
        submitted = st.form_submit_button("검토 기록 제출")
    if submitted:
        if not reviewer.strip():
            st.error("검토자 이름을 입력하세요.")
        else:
            review = _post(
                f"/api/investigations/{investigation['investigation_id']}/reviews",
                {"decision": decision, "comment": comment, "reviewer": reviewer},
            )
            if review:
                st.success(f"검토 기록됨: {review['decision']} by {review['reviewer']}")

    st.divider()
    st.subheader("5. 보고서")
    if st.button("보고서 불러오기"):
        report = _get(f"/api/investigations/{investigation['investigation_id']}/report")
        if report:
            st.json(report)
            st.download_button(
                "보고서 JSON 다운로드",
                data=json.dumps(report, ensure_ascii=False, indent=2),
                file_name=f"investigation-{investigation['investigation_id']}.json",
                mime="application/json",
            )
            if report["reviews"]:
                st.caption(f"기록된 검토 {len(report['reviews'])}건")
            else:
                st.caption("아직 기록된 검토가 없습니다.")

    st.divider()
    st.subheader("조사 결과에 대해 질문")
    st.caption("답변은 현재 조사 결과와 연결된 근거만 사용합니다. 설비 조작 지시는 제공하지 않습니다.")
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.write(message["content"])
            if message.get("evidence_ids"):
                st.caption(f"연결된 근거: {', '.join(message['evidence_ids'])}")
    chat_question = st.chat_input("예: 이 후보를 먼저 확인해야 하는 이유는?")
    if chat_question:
        st.session_state.chat_history.append({"role": "user", "content": chat_question})
        with st.spinner("근거를 확인해 답변을 생성하는 중..."):
            chat_result = _post(
                f"/api/investigations/{investigation['investigation_id']}/chat",
                {"question": chat_question},
            )
        if chat_result:
            st.session_state.chat_history.append(
                {
                    "role": "assistant",
                    "content": chat_result["answer"],
                    "evidence_ids": chat_result.get("grounded_evidence_ids", []),
                }
            )
        st.rerun()
