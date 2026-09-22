import type {
  CaseResume,
  HandoverDelta,
  HandoverSnapshot,
  HypothesisTrack,
  OpenItem,
  OperatorObservation,
} from "./api";

export type SnapshotEntity =
  | OperatorObservation
  | OpenItem
  | HypothesisTrack;

export function snapshotEntities(
  snapshot: HandoverSnapshot | null,
  field: "observations",
): OperatorObservation[];
export function snapshotEntities(
  snapshot: HandoverSnapshot | null,
  field: "open_items",
): OpenItem[];
export function snapshotEntities(
  snapshot: HandoverSnapshot | null,
  field: "hypotheses",
): HypothesisTrack[];
export function snapshotEntities(
  snapshot: HandoverSnapshot | null,
  field: "observations" | "open_items" | "hypotheses",
): SnapshotEntity[];
export function snapshotEntities(
  snapshot: HandoverSnapshot | null,
  field: "observations" | "open_items" | "hypotheses",
): SnapshotEntity[] {
  const value = snapshot?.payload[field];
  return Array.isArray(value) ? (value as SnapshotEntity[]) : [];
}

const entityLabel = {
  observations: "관찰 기록",
  open_items: "미해결 업무",
  hypotheses: "원인 가설",
} as const;
const openItemStatusLabel: Record<string, string> = {
  not_started: "시작 전", unavailable: "확인 불가", not_recorded: "기록 없음",
  on_hold: "보류", resolved: "완료",
};
const hypothesisJudgmentLabel: Record<string, string> = {
  unreviewed: "미평가", supported: "지지", not_supported: "지지되지 않음",
  insufficient: "근거 부족",
};
const displayValue = (labels: Record<string, string>, value: unknown) => labels[String(value)] || String(value);

function findSnapshotEntity(
  resume: CaseResume,
  delta: Exclude<HandoverDelta, { kind: "case-version-changed" }>,
) {
  return snapshotEntities(resume.current_snapshot, delta.entity).find(
    (item) => item.id === delta.id,
  );
}

function findCurrentEntity(
  resume: CaseResume,
  delta: Exclude<HandoverDelta, { kind: "case-version-changed" }>,
) {
  if (delta.entity === "observations") {
    return resume.observations.find((item) => item.id === delta.id);
  }
  return resume[delta.entity].find((item) => item.id === delta.id);
}

export function describeHandoverDelta(
  delta: HandoverDelta,
  resume: CaseResume,
): string {
  if (delta.kind === "case-version-changed") {
    return `기록 버전 ${delta.from_version} → ${delta.to_version}`;
  }

  const label = entityLabel[delta.entity];
  const previous = findSnapshotEntity(resume, delta);
  const current = findCurrentEntity(resume, delta);

  if (
    delta.kind === "updated" &&
    delta.entity === "open_items" &&
    previous &&
    current &&
    "status" in previous &&
    "status" in current
  ) {
    return `${label} ${delta.id}: ${displayValue(openItemStatusLabel, previous.status)} → ${displayValue(openItemStatusLabel, current.status)}`;
  }
  if (
    delta.kind === "updated" &&
    delta.entity === "hypotheses" &&
    previous &&
    current &&
    "judgment" in previous &&
    "judgment" in current
  ) {
    return `${label} ${delta.id}: ${displayValue(hypothesisJudgmentLabel, previous.judgment)} → ${displayValue(hypothesisJudgmentLabel, current.judgment)}`;
  }

  const verb = delta.kind === "added" ? "추가" : delta.kind === "removed" ? "삭제" : "변경";
  return `${label} ${delta.id} ${verb}`;
}
