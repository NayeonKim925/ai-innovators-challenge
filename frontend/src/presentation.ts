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
