import type {
  AnalysisRun,
  CaseResume,
  CaseStatus,
  Handover,
  HandoverDelta,
  HypothesisTrack,
  InvestigationCase,
  Investigation,
  OpenItem,
} from "./api";

export type ShiftFilter = "active" | "assigned" | "attention" | "handover" | "recent" | "all";
export type ShiftSort = "updated" | "unresolved" | "attention";
export type ShiftStatusFilter = "all" | CaseStatus;

export interface ShiftCaseSummary {
  case_id: string;
  incident_id: string;
  dataset: string;
  status: CaseStatus;
  current_run: AnalysisRun | null;
  run_number: number;
  run_count: number;
  current_candidate_signals: string[] | null;
  latest_handover: Handover | null;
  unresolved_open_items: OpenItem[];
  open_item_assignees: string[];
  hypothesis_summary: Record<HypothesisTrack["judgment"], number>;
  observation_count: number;
  latest_observation_at: string | null;
  recent_changes: HandoverDelta[] | null;
  new_run_since_handover: boolean | null;
  has_changes_since_handover: boolean | null;
  attention_reasons: string[];
  next_action: string;
  updated_at: string;
}

const active = (item: ShiftCaseSummary) => item.status !== "closed";
const normalized = (value: string | null | undefined) => (value || "").trim().toLocaleLowerCase();
const updatedMs = (item: ShiftCaseSummary) => Date.parse(item.updated_at) || 0;

export function summarizeShiftCase(
  item: InvestigationCase,
  resume?: CaseResume | null,
  investigation?: Investigation | null,
): ShiftCaseSummary {
  const currentRunIndex = item.analysis_runs.findIndex((run) => run.id === item.current_run_id);
  const currentRun = currentRunIndex < 0 ? null : item.analysis_runs[currentRunIndex];
  const handover = item.handovers.find((entry) => entry.id === item.current_handover_id) || null;
  const snapshot = handover
    ? item.handover_snapshots.find((entry) => entry.id === handover.snapshot_id) || null
    : null;
  const unresolved = item.open_items.filter((entry) => entry.status !== "resolved");
  const hypotheses = item.hypotheses;
  const hypothesisSummary = {
    supported: hypotheses.filter((entry) => entry.judgment === "supported").length,
    not_supported: hypotheses.filter((entry) => entry.judgment === "not_supported").length,
    insufficient: hypotheses.filter((entry) => entry.judgment === "insufficient").length,
    unreviewed: hypotheses.filter((entry) => entry.judgment === "unreviewed").length,
  };
  const currentResume = resume?.case_id === item.id && resume.case_version === item.version ? resume : null;
  const changes = handover && currentResume ? currentResume.handover_delta : null;
  const newRun = handover && snapshot ? snapshot.current_run_id !== item.current_run_id : null;
  // Accepting a packet increments the Case version, but is not itself new investigation work.
  const investigationChanges = changes?.some((change) => change.kind !== "case-version-changed") ?? null;
  const hasChanges = handover ? (newRun === true || investigationChanges === true
    ? true : newRun === null || investigationChanges === null ? null : false) : null;
  const reasons: string[] = [];
  if (unresolved.length) reasons.push(`${unresolved.length} unresolved open items`);
  if (hypothesisSummary.unreviewed) reasons.push(`${hypothesisSummary.unreviewed} hypothesis unreviewed`);
  if (handover?.status === "published") reasons.push("handover awaiting acceptance");
  if (handover?.status === "changes_requested") reasons.push("handover change requested");
  if (newRun) reasons.push("new analysis run since handover");
  if (investigationChanges) reasons.push("case updated after handover");
  const latestObservation = item.observations.reduce<string | null>((latest, entry) =>
    !latest || entry.recorded_at > latest ? entry.recorded_at : latest, null);

  return {
    case_id: item.id,
    incident_id: item.incident_id,
    dataset: item.dataset,
    status: item.status,
    current_run: currentRun,
    run_number: currentRunIndex + 1,
    run_count: item.analysis_runs.length,
    current_candidate_signals: currentRun && investigation?.investigation_id === currentRun.investigation_id
      ? [...investigation.candidates].sort((a, b) => a.rank - b.rank).map((candidate) => candidate.signal)
      : null,
    latest_handover: handover,
    unresolved_open_items: unresolved,
    open_item_assignees: [...new Set(unresolved.map((entry) => entry.assignee).filter((name): name is string => Boolean(name)))],
    hypothesis_summary: hypothesisSummary,
    observation_count: item.observations.length,
    latest_observation_at: latestObservation,
    recent_changes: changes,
    new_run_since_handover: newRun,
    has_changes_since_handover: hasChanges,
    attention_reasons: reasons,
    next_action: item.next_action,
    updated_at: item.updated_at,
  };
}

export function assignedToActor(item: ShiftCaseSummary, actor: string): boolean {
  const target = normalized(actor);
  if (!target) return false;
  return item.unresolved_open_items.some((entry) => normalized(entry.assignee) === target)
    || (item.latest_handover?.status !== "superseded" && normalized(item.latest_handover?.receiver) === target);
}

export function recentlyUpdated(item: ShiftCaseSummary, now = Date.now()): boolean {
  const age = now - updatedMs(item);
  return age >= 0 && age <= 24 * 60 * 60 * 1000;
}

export function shiftTotals(items: ShiftCaseSummary[], now = Date.now()) {
  const open = items.filter(active);
  return {
    active_cases: open.length,
    needs_attention_cases: open.filter((item) => item.attention_reasons.length > 0).length,
    unresolved_open_items: open.reduce((count, item) => count + item.unresolved_open_items.length, 0),
    awaiting_handover: open.filter((item) => item.latest_handover?.status === "published" || item.latest_handover?.status === "changes_requested").length,
    recently_updated_cases: open.filter((item) => recentlyUpdated(item, now)).length,
  };
}

export function visibleShiftCases(
  items: ShiftCaseSummary[],
  filter: ShiftFilter,
  sort: ShiftSort,
  actor: string,
  status: ShiftStatusFilter = "all",
  now = Date.now(),
): ShiftCaseSummary[] {
  return items.filter((item) => {
    if (status !== "all" && item.status !== status) return false;
    if (filter === "all") return true;
    if (!active(item)) return false;
    if (filter === "assigned") return assignedToActor(item, actor);
    if (filter === "attention") return item.attention_reasons.length > 0;
    if (filter === "handover") return item.latest_handover?.status === "published" || item.latest_handover?.status === "changes_requested";
    if (filter === "recent") return recentlyUpdated(item, now);
    return true;
  }).sort((a, b) => {
    if (sort === "unresolved") {
      const difference = b.unresolved_open_items.length - a.unresolved_open_items.length;
      if (difference) return difference;
    }
    if (sort === "attention") {
      const difference = Number(b.attention_reasons.length > 0) - Number(a.attention_reasons.length > 0);
      if (difference) return difference;
    }
    return updatedMs(b) - updatedMs(a) || a.case_id.localeCompare(b.case_id);
  });
}
