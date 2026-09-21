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
  observations: "Observation",
  open_items: "Open Item",
  hypotheses: "Hypothesis",
} as const;

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
    return `Case version ${delta.from_version} → ${delta.to_version}`;
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
    return `${label} ${delta.id}: ${previous.status} → ${current.status}`;
  }
  if (
    delta.kind === "updated" &&
    delta.entity === "hypotheses" &&
    previous &&
    current &&
    "judgment" in previous &&
    "judgment" in current
  ) {
    return `${label} ${delta.id}: ${previous.judgment} → ${current.judgment}`;
  }

  const verb =
    delta.kind === "added"
      ? "added"
      : delta.kind === "removed"
        ? "removed"
        : "updated";
  return `${label} ${delta.id} ${verb}`;
}
