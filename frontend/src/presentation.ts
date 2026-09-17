// Presentation only: never rewrite stored evidence, identifiers, or exported reports.
const labels: Record<string, string> = {
  "Transparent recency baseline: an active alarm is an investigation candidate, not a confirmed root cause.":
    "현재 활성화된 알람을 최근 발생 순으로 정렬한 기준선입니다. 조사할 후보이며 확정된 원인은 아닙니다.",
  "Compare each candidate with process documentation and the observed signal history.":
    "각 후보를 공정 문서 및 관측 신호 이력과 대조해 확인하세요.",
  "Collect additional observations before proposing a root-cause candidate.":
    "원인 후보를 제안하려면 추가 관측이 필요합니다. 신호 이력과 진단 시점을 먼저 확인하세요.",
  "This is a research investigation aid. Candidates require explicit expert review.":
    "연구용 조사 보조 도구입니다. 모든 후보는 전문가의 명시적인 검토가 필요합니다.",
  "No active alarm was observed before the cutoff; the workflow abstains from a root-cause ranking.":
    "진단 시점에 활성 알람이 없어 원인 후보 순위를 제시하지 않았습니다.",
  "Prepared runtime observation": "준비된 런타임 관측 데이터",
  deterministic: "분석 도구 기반",
  deterministic_with_llm_narrative: "분석 도구 + AI 해설",
  not_requested: "AI 해설 미요청",
  unavailable: "AI 연결 불가",
  generated: "AI 해설 생성됨",
  blocked: "안전 범위 안내",
  unverified: "AI 해설 근거 검증 미통과",
  skipped: "AI 해설 생략",
  queued: "AI 해설 대기",
  running: "AI 해설 생성 중",
  "Ask the assigned expert to verify the top evidence-linked candidate.":
    "담당 공정 전문가에게 최상위 후보와 연결된 근거를 확인하도록 요청합니다.",
  "Collect additional observable context before opening a new investigation.":
    "추가 관측 맥락을 수집한 뒤 새 조사를 시작합니다.",
  "Collect additional observable context, then open a new investigation at an explicit cutoff.":
    "추가 관측 맥락을 수집한 뒤 명시적인 진단 시점으로 새 조사를 시작합니다.",
  "An expert reviewer must explicitly approve or reject this evidence-linked candidate.":
    "담당 전문가가 근거와 연결된 후보를 명시적으로 승인 또는 거절해야 합니다.",
  "No root-cause candidate is asserted. Reopen with newly observed runtime data if available.":
    "원인 후보를 주장하지 않습니다. 새 런타임 관측이 있을 때만 사건을 재개합니다.",
  "Case closed with an explicit expert review. The candidate remains evidence-linked, not an automated control decision.":
    "전문가의 명시적 검토로 사건을 종료했습니다. 후보는 근거와 연결된 조사 대상이며 자동 제어 판단이 아닙니다.",
};

const caseEventLabels: Record<string, string> = {
  analysis_completed: "분석 및 근거 검증 완료",
  evidence_task_created: "증거 확인 업무 생성",
  expert_response_recorded: "전문가 응답 기록",
  case_ready_for_review: "최종 검토 대기",
  case_reopened: "추가 관측으로 재개",
  case_abstained: "판단 보류",
  case_closed: "전문가 승인 후 종료",
};

const caseRoleLabels: Record<string, string> = {
  operator: "운영자",
  process_expert: "공정 전문가",
};

const taskKindLabels: Record<string, string> = {
  verify_candidate: "후보 근거 확인",
  collect_observation: "추가 관측 수집",
};

const responseOutcomeLabels: Record<string, string> = {
  confirmed: "확인 가능",
  refuted: "근거 불일치",
  unavailable: "확인 불가",
};
export function displayText(value: string): string {
  if (labels[value]) return labels[value];
  if (value.startsWith("Active alarm: "))
    return `활성 알람: ${value.slice(14)}`;
  const observation =
    /^At t=([\d.]+)s, (.+) reported (.+) before the diagnosis cutoff\.$/.exec(
      value,
    );
  if (observation)
    return `진단 시점 이전 ${observation[1]}초에 ${observation[2]} 신호에서 ${observation[3]} 값이 관측되었습니다.`;
  return value;
}

export function displayCaseEventType(eventType: string): string {
  return caseEventLabels[eventType] || eventType.replaceAll("_", " ");
}

export function displayCaseEventDetail(detail: string): string {
  if (
    detail ===
    "Completed deterministic analysis and evidence validation; no LLM was used."
  ) {
    return "결정론적 분석과 근거 검증을 완료했습니다. 이 단계에는 LLM을 사용하지 않았습니다.";
  }
  if (
    detail ===
    "Evidence verification is recorded. The candidate is review-ready, not an automatically confirmed root cause."
  ) {
    return "근거 확인 응답을 기록했습니다. 후보는 검토 가능 상태일 뿐 자동으로 확정된 원인이 아닙니다.";
  }
  if (
    detail ===
    "The candidate was not supported or could not be checked. The system did not infer an alternative cause."
  ) {
    return "후보 근거가 뒷받침되지 않거나 확인할 수 없었습니다. 시스템은 다른 원인을 추정하지 않았습니다.";
  }
  if (
    detail ===
    "Additional observation was recorded, but the existing result was not reranked and no root-cause candidate is asserted."
  ) {
    return "추가 관측을 기록했지만 기존 결과의 순위를 바꾸거나 원인 후보를 주장하지 않았습니다.";
  }
  if (
    detail ===
    "Closed after an explicit expert approval and completed evidence verification."
  ) {
    return "근거 확인과 전문가의 명시적 승인을 거쳐 사건을 종료했습니다.";
  }
  if (
    detail ===
    "Expert rejected the review-ready candidate; the case remains open for new evidence."
  ) {
    return "전문가가 검토 가능 후보를 거절했습니다. 새 근거를 위해 사건을 계속 엽니다.";
  }
  if (
    detail ===
    "Created a follow-up observation task because the previous evidence check did not support a review-ready candidate."
  ) {
    return "이전 근거 확인만으로는 검토 가능한 후보를 뒷받침할 수 없어 추가 관측 업무를 만들었습니다.";
  }
  const taskCreated = /^Created (\w+) task for (\w+);/.exec(detail);
  if (taskCreated) {
    const [, taskKind, role] = taskCreated;
    return `${caseRoleLabels[role] || role}에게 ${taskKindLabels[taskKind] || taskKind} 업무를 요청했습니다. 증거 확인이 끝날 때까지 사건은 열려 있습니다.`;
  }
  const responseRecorded = /^Recorded (\w+) response from (.+) for (\w+)\.$/.exec(
    detail,
  );
  if (responseRecorded) {
    const [, outcome, responder, taskKind] = responseRecorded;
    return `${responder}의 ${taskKindLabels[taskKind] || taskKind} 응답을 기록했습니다: ${responseOutcomeLabels[outcome] || outcome}.`;
  }
  return detail;
}
