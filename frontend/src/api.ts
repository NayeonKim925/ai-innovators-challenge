import { brand } from "./brand";

export interface Dataset {
  dataset: string;
  status: string;
  incident_count: number;
}
export interface IncidentSummary {
  id: string;
  source_dataset: string;
  title: string;
  time_range_s: { start: number; end: number };
  capabilities: string[];
}
export interface Observation {
  time_s: number;
  signal: string;
  value: string | number | boolean;
  kind: "Alarm" | "Event" | "Measurement";
}
export interface Incident extends IncidentSummary {
  observations: Observation[];
}
export interface Evidence {
  id: string;
  title: string;
  detail: string;
  source: string;
}
export interface Candidate {
  rank: number;
  signal: string;
  reason: string;
  evidence_ids: string[];
  status: "candidate" | "inconclusive";
}
export interface Trace {
  step: number;
  tool: string;
  detail: string;
  latency_ms: number | null;
  token_usage: number | null;
}
export interface Investigation {
  investigation_id: string;
  incident_id: string;
  dataset: string;
  diagnosis_time: number;
  question: string;
  mode: string;
  candidates: Candidate[];
  evidence: Evidence[];
  trace: Trace[];
  warnings: string[];
  next_action: string;
  llm_narrative: string | null;
  llm_status: string;
}
export interface Review {
  investigation_id: string;
  reviewer: string;
  decision: "approve" | "reject";
  comment: string;
  reviewed_at: string;
}
export interface Report {
  investigation_id: string;
  result: Omit<Investigation, "investigation_id">;
  reviews: Review[];
}
export type CaseStatus =
  | "awaiting_evidence"
  | "ready_for_review"
  | "reopened"
  | "abstained"
  | "closed";
export type ExpertResponseOutcome = "confirmed" | "refuted" | "unavailable";
export interface ExpertTaskResponse {
  outcome: ExpertResponseOutcome;
  comment: string;
  responder: string;
}
export interface EvidenceTask {
  id: string;
  kind: "verify_candidate" | "collect_observation";
  status: "pending" | "completed";
  requested_role: "operator" | "process_expert" | "equipment_expert";
  title: string;
  instructions: string;
  candidate_signal: string | null;
  evidence_ids: string[];
  trace_steps: number[];
  response: ExpertTaskResponse | null;
  created_at: string;
  completed_at: string | null;
}
export interface CaseEvent {
  sequence: number;
  event_type: string;
  detail: string;
  actor: "case_orchestrator" | "expert";
  evidence_ids: string[];
  trace_steps: number[];
  created_at: string;
}
export interface CaseReview {
  decision: "approve" | "reject";
  comment: string;
  reviewer: string;
  reviewed_at: string;
}
export interface InvestigationCase {
  id: string;
  incident_id: string;
  dataset: string;
  investigation_id: string;
  status: CaseStatus;
  version: number;
  next_action: string;
  tasks: EvidenceTask[];
  events: CaseEvent[];
  reviews: CaseReview[];
  created_at: string;
  updated_at: string;
}
export interface ChatResponse {
  answer: string;
  grounded_evidence_ids: string[];
  blocked: boolean;
  llm_status: string;
}
export interface Health {
  status: string;
  llm_provider: string;
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const timeout = AbortSignal.timeout(35000);
  const signal = options.signal
    ? AbortSignal.any([options.signal, timeout])
    : timeout;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      signal,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new Error(
      timeout.aborted
        ? "응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."
        : "서버에 연결할 수 없습니다. 네트워크 연결을 확인해 주세요.",
    );
  }
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: "서비스 인증 연결이 필요합니다. 관리자에게 문의해 주세요.",
      403: "이 요청을 처리할 수 없습니다. 페이지를 새로고침해 주세요.",
      404: "요청한 사건 또는 조사 기록을 찾을 수 없습니다.",
      422: "입력값이 올바르지 않습니다. 진단 시점과 내용을 확인해 주세요.",
      429: "요청이 많습니다. 잠시 후 다시 시도해 주세요.",
      503: "서비스가 준비 중입니다. 잠시 후 다시 시도해 주세요.",
    };
    throw new Error(
      messages[response.status] ||
        `요청을 완료하지 못했습니다 (${response.status}). 다시 시도해 주세요.`,
    );
  }
  return response.json() as Promise<T>;
}

export const post = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
export const datasetLabel = (name: string) =>
  name === "causrca" ? "causRCA" : name === "metal_etch" ? "Metal Etch" : name;
export const number = (value: number, digits = 0) =>
  value.toLocaleString("ko-KR", { maximumFractionDigits: digits });
export const shortId = (id: string) =>
  id
    .replace(/^case_/, "")
    .slice(0, 8)
    .toUpperCase();
export function download(filename: string, data: string, mime: string) {
  const url = URL.createObjectURL(new Blob([data], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function reportMarkdown(report: Report): string {
  const r = report.result;
  return [
    `# ${brand.name} · 제조 이상 조사 보고서`,
    `${brand.koreanName} | ${brand.tagline}`,
    `조사 ID: ${report.investigation_id}`,
    `사건: ${r.incident_id}`,
    `진단 시점: ${r.diagnosis_time}s`,
    `분석 모드: ${r.mode}`,
    `## 원인 후보`,
    ...r.candidates.map(
      (c) =>
        `### ${c.rank}. ${c.signal}\n${c.reason}\n상태: ${c.status}\n근거: ${c.evidence_ids.join(", ")}`,
    ),
    `## 근거`,
    ...r.evidence.map(
      (e) => `### ${e.id} · ${e.title}\n${e.detail}\n출처: ${e.source}`,
    ),
    `## 한계`,
    ...r.warnings.map((w) => `- ${w}`),
    `## 전문가 검토`,
    ...(report.reviews.length
      ? report.reviews.map(
          (v) =>
            `${v.reviewer} · ${v.decision} · ${v.reviewed_at}\n${v.comment}`,
        )
      : ["검토 기록 없음"]),
    "후보는 조사 우선순위이며 확정된 원인이나 설비 조작 지시가 아닙니다.",
  ].join("\n\n");
}
