import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Bot,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  Database,
  FileSearch,
  ListChecks,
  Layers3,
  LoaderCircle,
  MessageSquare,
  Play,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  TriangleAlert,
  UserRoundCheck,
  X,
} from "lucide-react";
import {
  api,
  post,
  datasetLabel,
  download,
  number,
  reportMarkdown,
  shortId,
} from "./api";
import type {
  ChatResponse,
  CaseResume,
  Dataset,
  Health,
  Incident,
  IncidentSummary,
  InvestigationCase,
  Investigation,
  HypothesisTrack,
  OpenItem,
  OpenItemStatus,
  Report,
  Review,
  ExpertResponseOutcome,
  HandoverFinding,
  ShiftWorkspace,
  ShiftWorkspaceFilter,
  StructuringProposal,
} from "./api";
import { describeHandoverDelta, snapshotEntities } from "./resume";
import {
  displayCaseEventDetail,
  displayCaseEventType,
  displayText,
} from "./presentation";
import { brand } from "./brand";

type Page = "workspace" | "cases" | "history" | "datasets" | "guide";
type Tab = "signals" | "results" | "review" | "chat";
type Saved = { id: string; incident: string; at: string };
const message = (e: unknown) =>
  e instanceof Error ? e.message : "요청을 처리하지 못했습니다.";
const caseStatusLabel: Record<InvestigationCase["status"], string> = {
  awaiting_evidence: "확인 대기",
  ready_for_review: "검토 대기",
  reopened: "재개됨",
  abstained: "판단 보류",
  closed: "종료됨",
};
const shiftReasonLabel: Record<string, string> = {
  pending_handover: "인수 대기",
  assigned_open_item: "내 Open Item",
  unknown_state: "미확인 상태",
  stale_snapshot: "최신 상태 필요",
  blocking_finding: "차단 이슈",
};
function readHistory(): Saved[] {
  try {
    return JSON.parse(localStorage.getItem("investigation-history") || "[]")
      .filter(
        (x: Saved) =>
          x &&
          typeof x.id === "string" &&
          typeof x.incident === "string" &&
          typeof x.at === "string",
      )
      .slice(0, 30);
  } catch {
    return [];
  }
}
function ErrorBox({ text, retry }: { text: string; retry?: () => void }) {
  return (
    <div className="notice danger" role="alert">
      <TriangleAlert size={17} />
      <span>{text}</span>
      {retry && (
        <button className="text-button" onClick={retry}>
          다시 시도
        </button>
      )}
    </div>
  );
}
function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty">
      <FileSearch size={32} />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

function Timeline({
  incident,
  cutoff,
}: {
  incident: Incident;
  cutoff: number;
}) {
  const bins = useMemo(() => {
    const arr = Array.from({ length: 48 }, () => ({ event: 0, alarm: 0 }));
    const { start, end } = incident.time_range_s;
    for (const o of incident.observations) {
      const i = Math.max(
        0,
        Math.min(
          47,
          Math.floor(((o.time_s - start) / (end - start || 1)) * 48),
        ),
      );
      if (o.kind === "Alarm") arr[i].alarm++;
      else arr[i].event++;
    }
    return arr;
  }, [incident]);
  const max = Math.max(1, ...bins.map((b) => b.event + b.alarm));
  const pct = Math.max(
    0,
    Math.min(
      100,
      ((cutoff - incident.time_range_s.start) /
        (incident.time_range_s.end - incident.time_range_s.start || 1)) *
        100,
    ),
  );
  return (
    <div className="timeline">
      <div className="section-heading">
        <div>
          <h3>관측 타임라인</h3>
          <p>시간대별 기록 수 · 실제 관측 데이터</p>
        </div>
        <div className="legend">
          <span>
            <i />
            이벤트·측정
          </span>
          <span>
            <i className="amber" />
            알람
          </span>
        </div>
      </div>
      <div
        className="chart"
        role="img"
        aria-label={`관측 기록 히스토그램. 전체 ${number(incident.observations.length)}개, 진단 시점 ${cutoff}초`}
      >
        <div className="bars">
          {bins.map((b, i) => (
            <div
              className="bin"
              key={i}
              title={`${number(incident.time_range_s.start + (i / 48) * (incident.time_range_s.end - incident.time_range_s.start), 1)}초 부근: ${b.event + b.alarm}개`}
            >
              <span
                style={{ height: `${(b.alarm / max) * 100}%` }}
                className="alarm-bar"
              />
              <span style={{ height: `${(b.event / max) * 100}%` }} />
            </div>
          ))}
        </div>
        <div className="cutoff" style={{ left: `${pct}%` }}>
          <span>진단 시점</span>
        </div>
      </div>
      <div className="axis">
        <span>{number(incident.time_range_s.start, 1)}s</span>
        <span>{number(incident.time_range_s.end / 2, 1)}s</span>
        <span>{number(incident.time_range_s.end, 1)}s</span>
      </div>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("workspace");
  const [tab, setTab] = useState<Tab>("signals");
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [dataset, setDataset] = useState("causrca");
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [selectionVersion, setSelectionVersion] = useState(0);
  const [incident, setIncident] = useState<Incident | null>(null);
  const [search, setSearch] = useState("");
  const [signalSearch, setSignalSearch] = useState("");
  const [cutoff, setCutoff] = useState(0);
  const [question, setQuestion] = useState("");
  const [includeAI, setIncludeAI] = useState(false);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [reload, setReload] = useState(0);
  const [run, setRun] = useState<Investigation | null>(null);
  const [busy, setBusy] = useState(false);
  const [evidenceId, setEvidenceId] = useState("");
  const [history, setHistory] = useState<Saved[]>(readHistory);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [reviewer, setReviewer] = useState("");
  const [comment, setComment] = useState("");
  const [reviewBusy, setReviewBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [chat, setChat] = useState<
    { question: string; response: ChatResponse }[]
  >([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [caseChat, setCaseChat] = useState<{ question: string; response: ChatResponse }[]>([]);
  const [caseChatInput, setCaseChatInput] = useState("");
  const [caseChatBusy, setCaseChatBusy] = useState(false);
  const [caseChatIncludeAI, setCaseChatIncludeAI] = useState(false);
  const [cases, setCases] = useState<InvestigationCase[]>([]);
  const [activeCase, setActiveCase] = useState<InvestigationCase | null>(null);
  const [casesAvailable, setCasesAvailable] = useState(true);
  const [shiftAssignee, setShiftAssignee] = useState("Shift B");
  const [workspaceFilter, setWorkspaceFilter] = useState<ShiftWorkspaceFilter>("action_required");
  const [shiftWorkspace, setShiftWorkspace] = useState<ShiftWorkspace | null>(null);
  const [shiftWorkspaceLoading, setShiftWorkspaceLoading] = useState(false);
  const [shiftWorkspaceError, setShiftWorkspaceError] = useState("");
  const [caseBusy, setCaseBusy] = useState(false);
  const [taskOutcome, setTaskOutcome] = useState<ExpertResponseOutcome>("confirmed");
  const [taskResponder, setTaskResponder] = useState("");
  const [taskComment, setTaskComment] = useState("");
  const [caseReviewer, setCaseReviewer] = useState("");
  const [caseComment, setCaseComment] = useState("");
  const [observationText, setObservationText] = useState("");
  const [observationAuthor, setObservationAuthor] = useState("");
  const [observationIsCurrentState, setObservationIsCurrentState] = useState(false);
  const [openItemAssignee, setOpenItemAssignee] = useState("");
  const [openItemDrafts, setOpenItemDrafts] = useState<Record<string, { status: OpenItemStatus; assignee: string; note: string }>>({});
  const [hypothesisReasons, setHypothesisReasons] = useState<Record<string, string>>({});
  const [structuringNote, setStructuringNote] = useState("");
  const [structuringAuthor, setStructuringAuthor] = useState("");
  const [structuringReviewer, setStructuringReviewer] = useState("Shift B");
  const [structuringIncludeAI, setStructuringIncludeAI] = useState(false);
  const [structuringProposals, setStructuringProposals] = useState<StructuringProposal[]>([]);
  const [structuringEdits, setStructuringEdits] = useState<Record<string, string>>({});
  const [structuringBusy, setStructuringBusy] = useState(false);
  const [handoverSender, setHandoverSender] = useState("");
  const [handoverReceiver, setHandoverReceiver] = useState("");
  const [handoverFindings, setHandoverFindings] = useState<HandoverFinding[]>([]);
  const [handoverBusy, setHandoverBusy] = useState(false);
  const [resume, setResume] = useState<CaseResume | null>(null);
  const [resumeLoading, setResumeLoading] = useState(false);
  const [resumeError, setResumeError] = useState("");
  const [analysisRunCutoff, setAnalysisRunCutoff] = useState(0);
  const [analysisRunCreator, setAnalysisRunCreator] = useState("");
  const [analysisRunQuestion, setAnalysisRunQuestion] = useState("");
  const [analysisRunBusy, setAnalysisRunBusy] = useState(false);
  const revision = useRef(0);
  const displayedRunRevision = useRef(0);
  const displayedCaseRunId = useRef<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    Promise.all([
      api<{ datasets: Dataset[] }>("/datasets", { signal: ctl.signal }),
      api<Health>("/health", { signal: ctl.signal }),
    ])
      .then(([d, h]) => {
        setDatasets(d.datasets);
        setHealth(h);
      })
      .catch(() => {});
    return () => ctl.abort();
  }, [reload]);
  useEffect(() => {
    let alive = true;
    api<{ cases: InvestigationCase[] }>("/cases")
      .then((result) => {
        if (!alive) return;
        setCases(result.cases);
        setCasesAvailable(true);
      })
      .catch(() => {
        if (alive) setCasesAvailable(false);
      });
    return () => {
      alive = false;
    };
  }, [reload]);
  useEffect(() => {
    let alive = true;
    setShiftWorkspaceLoading(true);
    setShiftWorkspaceError("");
    const params = new URLSearchParams({ status: workspaceFilter });
    if (shiftAssignee.trim()) params.set("assignee", shiftAssignee.trim());
    api<ShiftWorkspace>(`/shift-workspace?${params.toString()}`)
      .then((result) => {
        if (alive) setShiftWorkspace(result);
      })
      .catch((error) => {
        if (alive) setShiftWorkspaceError(message(error));
      })
      .finally(() => {
        if (alive) setShiftWorkspaceLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [reload, shiftAssignee, workspaceFilter]);
  useEffect(() => {
    const ctl = new AbortController();
    setLoading(true);
    setError("");
    setSelected("");
    setIncident(null);
    setRun(null);
    revision.current++;
    api<{ incidents: IncidentSummary[] }>(`/incidents?dataset=${dataset}`, {
      signal: ctl.signal,
    })
      .then((d) => {
        setIncidents(d.incidents);
        setSelected(d.incidents[0]?.id || "");
      })
      .catch((e) => {
        if (!ctl.signal.aborted) {
          setError(message(e));
          setIncidents([]);
        }
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoading(false);
      });
    return () => ctl.abort();
  }, [dataset, reload]);
  useEffect(() => {
    if (!selected) return;
    const ctl = new AbortController();
    revision.current++;
    setDetailLoading(true);
    setIncident(null);
    setRun(null);
    setTab("signals");
    setActionError("");
    setNotice("");
    setReviews([]);
    setChat([]);
    setSignalSearch("");
    api<Incident>(`/incidents/${encodeURIComponent(selected)}`, {
      signal: ctl.signal,
    })
      .then((d) => {
        setIncident(d);
        setCutoff(d.time_range_s.end);
      })
      .catch((e) => {
        if (!ctl.signal.aborted) setActionError(message(e));
      })
      .finally(() => {
        if (!ctl.signal.aborted) setDetailLoading(false);
      });
    return () => ctl.abort();
  }, [selected, selectionVersion]);
  useEffect(() => {
    if (!activeCase) {
      setResume(null);
      setResumeError("");
      setStructuringProposals([]);
      setStructuringEdits({});
      return;
    }
    const ctl = new AbortController();
    const runRevision = displayedRunRevision.current;
    setResumeLoading(true);
    setResumeError("");
    api<CaseResume>(`/cases/${encodeURIComponent(activeCase.id)}/resume`, {
      signal: ctl.signal,
    })
      .then(async (nextResume) => {
        if (ctl.signal.aborted) return;
        setResume(nextResume);
        if (!nextResume.current_run) {
          setRun(null);
          setEvidenceId("");
          return;
        }
        const investigation = await api<Investigation>(
          `/investigations/${encodeURIComponent(nextResume.current_run.investigation_id)}`,
          { signal: ctl.signal },
        );
        if (
          ctl.signal.aborted ||
          runRevision !== displayedRunRevision.current ||
          (displayedCaseRunId.current !== null &&
            displayedCaseRunId.current !== nextResume.current_run.id)
        ) return;
        displayedCaseRunId.current = nextResume.current_run.id;
        setRun(investigation);
        setEvidenceId(investigation.evidence[0]?.id || "");
      })
      .catch((error) => {
        if (!ctl.signal.aborted) setResumeError(message(error));
      })
      .finally(() => {
        if (!ctl.signal.aborted) setResumeLoading(false);
      });
    return () => ctl.abort();
  }, [activeCase?.id, activeCase?.version]);
  useEffect(() => {
    if (!activeCase) return;
    const ctl = new AbortController();
    api<{ case_id: string; case_version: number; proposals: StructuringProposal[] }>(
      `/cases/${encodeURIComponent(activeCase.id)}/structuring-proposals`,
      { signal: ctl.signal },
    )
      .then((result) => {
        if (ctl.signal.aborted) return;
        setStructuringProposals(result.proposals);
        setStructuringEdits((previous) => {
          const pending = new Set(result.proposals.map((proposal) => proposal.id));
          return Object.fromEntries(Object.entries(previous).filter(([id]) => pending.has(id)));
        });
      })
      .catch((error) => {
        if (!ctl.signal.aborted) setActionError(message(error));
      });
    return () => ctl.abort();
  }, [activeCase?.id, activeCase?.version]);
  useEffect(() => {
    if (resume?.current_run) {
      setAnalysisRunCutoff(resume.current_run.diagnosis_time);
    }
  }, [resume?.current_run?.id]);
  async function investigate() {
    if (!incident || busy) return;
    const rev = ++revision.current;
    setBusy(true);
    setActionError("");
    setNotice("");
    try {
      const r = await post<Investigation>(
        `/incidents/${incident.id}/investigations`,
        {
          diagnosis_time: cutoff,
          question,
          include_llm_narrative: includeAI,
          async_llm_narrative: false,
        },
      );
      if (rev !== revision.current) return;
      setRun(r);
      setEvidenceId(r.evidence[0]?.id || "");
      setReviews([]);
      setChat([]);
      setTab("results");
      const next = [
        {
          id: r.investigation_id,
          incident: r.incident_id,
          at: new Date().toISOString(),
        },
        ...history,
      ].slice(0, 30);
      setHistory(next);
      try {
        localStorage.setItem("investigation-history", JSON.stringify(next));
      } catch {
        setNotice(
          "조사는 완료됐지만 이 브라우저에 기록을 저장하지 못했습니다.",
        );
      }
    } catch (e) {
      if (rev === revision.current) setActionError(message(e));
    } finally {
      setBusy(false);
    }
  }
  function replaceCase(updated: InvestigationCase) {
    setActiveCase(updated);
    setCases((previous) => [
      updated,
      ...previous.filter((item) => item.id !== updated.id),
    ]);
  }
  function proposalText(proposal: StructuringProposal) {
    return structuringEdits[proposal.id] ??
      proposal.suggested_observation ??
      proposal.suggested_open_item_title ??
      proposal.suggested_reason ??
      proposal.source_text;
  }
  function proposalLabel(kind: StructuringProposal["kind"]) {
    return kind === "observation" ? "관찰 제안" : kind === "open_item" ? "Open Item 제안" : "가설 판단 제안";
  }
  async function createStructuringProposals() {
    if (!activeCase || !structuringNote.trim() || !structuringAuthor.trim() || structuringBusy) return;
    setStructuringBusy(true);
    setActionError("");
    try {
      const result = await post<{ case_id: string; case_version: number; proposals: StructuringProposal[] }>(
        `/cases/${encodeURIComponent(activeCase.id)}/structuring-proposals`,
        {
          expected_version: activeCase.version,
          note: structuringNote.trim(),
          author: structuringAuthor.trim(),
          provenance: "synthetic_demo",
          include_llm: structuringIncludeAI,
        },
      );
      setStructuringProposals(result.proposals);
      setStructuringEdits({});
      setStructuringNote("");
      setNotice(`AI 제안 ${result.proposals.length}건을 만들었습니다. Case 상태에는 아직 반영되지 않았습니다.`);
    } catch (error) {
      setActionError(message(error));
    } finally {
      setStructuringBusy(false);
    }
  }
  async function acceptStructuringProposal(proposal: StructuringProposal) {
    if (!activeCase || structuringBusy || proposal.case_version !== activeCase.version) return;
    setStructuringBusy(true);
    setActionError("");
    try {
      const edited = structuringEdits[proposal.id]?.trim();
      const updated = await post<InvestigationCase>(
        `/cases/${encodeURIComponent(activeCase.id)}/structuring-proposals/${encodeURIComponent(proposal.id)}/accept`,
        {
          expected_version: activeCase.version,
          accepted_by: structuringReviewer.trim() || shiftAssignee.trim() || "Shift B",
          edited_text: edited || undefined,
        },
      );
      replaceCase(updated);
      setStructuringProposals((previous) => previous.filter((item) => item.id !== proposal.id));
      setStructuringEdits((previous) => {
        const next = { ...previous };
        delete next[proposal.id];
        return next;
      });
      void refreshShiftWorkspace();
      setNotice(`${proposalLabel(proposal.kind)}을 검토 후 Case에 반영했습니다. 나머지 제안은 새 버전 확인이 필요합니다.`);
    } catch (error) {
      setActionError(message(error));
    } finally {
      setStructuringBusy(false);
    }
  }
  async function dismissStructuringProposal(proposal: StructuringProposal) {
    if (!activeCase || structuringBusy) return;
    setStructuringBusy(true);
    setActionError("");
    try {
      await post<{ proposal_id: string; status: string }>(
        `/cases/${encodeURIComponent(activeCase.id)}/structuring-proposals/${encodeURIComponent(proposal.id)}/dismiss`,
        { dismissed_by: structuringReviewer.trim() || shiftAssignee.trim() || "Shift B" },
      );
      setStructuringProposals((previous) => previous.filter((item) => item.id !== proposal.id));
      setNotice("제안을 보류했습니다. Case 상태는 변경되지 않았습니다.");
    } catch (error) {
      setActionError(message(error));
    } finally {
      setStructuringBusy(false);
    }
  }
  async function selectCase(nextCase: InvestigationCase) {
    if (caseBusy) return;
    setCaseBusy(true);
    setActionError("");
    try {
      setActiveCase(nextCase);
      displayedCaseRunId.current = null;
      setCaseChat([]);
      setRun(null);
      setEvidenceId("");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setCaseBusy(false);
    }
  }
  async function openShiftWorkspaceCase(caseId: string) {
    const cached = cases.find((item) => item.id === caseId);
    if (cached) {
      await selectCase(cached);
      return;
    }
    setCaseBusy(true);
    setActionError("");
    try {
      const loaded = await api<InvestigationCase>(`/cases/${encodeURIComponent(caseId)}`);
      replaceCase(loaded);
      setCaseBusy(false);
      await selectCase(loaded);
    } catch (error) {
      setActionError(message(error));
    } finally {
      setCaseBusy(false);
    }
  }
  function openItemDraft(item: OpenItem) {
    return openItemDrafts[item.id] || {
      status: item.status,
      assignee: item.assignee || "",
      note: item.status === "on_hold" ? item.hold_reason : item.completion_note,
    };
  }
  function updateOpenItemDraft(
    itemId: string,
    patch: Partial<{ status: OpenItemStatus; assignee: string; note: string }>,
  ) {
    setOpenItemDrafts((previous) => ({
      ...previous,
      [itemId]: { ...previous[itemId], ...patch } as { status: OpenItemStatus; assignee: string; note: string },
    }));
  }
  async function updateCaseOpenItem(item: OpenItem) {
    if (!activeCase || handoverBusy) return;
    const draft = openItemDraft(item);
    setHandoverBusy(true);
    setActionError("");
    try {
      const updated = await post<InvestigationCase>(
        `/cases/${encodeURIComponent(activeCase.id)}/open-items/${encodeURIComponent(item.id)}/updates`,
        {
          expected_version: activeCase.version,
          status: draft.status,
          assignee: draft.assignee.trim() || null,
          hold_reason: draft.status === "on_hold" ? draft.note.trim() : "",
          completion_note: draft.status === "resolved" ? draft.note.trim() : item.completion_note,
          observation_ids: item.observation_ids,
        },
      );
      replaceCase(updated);
      setNotice(`Open Item “${item.title}” 상태를 저장했습니다.`);
      void refreshShiftWorkspace();
    } catch (error) {
      setActionError(message(error));
    } finally {
      setHandoverBusy(false);
    }
  }
  async function assessCaseHypothesis(
    hypothesis: HypothesisTrack,
    judgment: HypothesisTrack["judgment"],
  ) {
    if (!activeCase || handoverBusy) return;
    setHandoverBusy(true);
    setActionError("");
    try {
      const updated = await post<InvestigationCase>(
        `/cases/${encodeURIComponent(activeCase.id)}/hypotheses/${encodeURIComponent(hypothesis.id)}/assessments`,
        {
          expected_version: activeCase.version,
          judgment,
          updated_by: shiftAssignee.trim() || handoverReceiver.trim() || "Shift B",
          change_reason: hypothesisReasons[hypothesis.id]?.trim() || "",
          supporting_observation_ids: hypothesis.supporting_observation_ids,
          opposing_evidence_ids: hypothesis.opposing_evidence_ids,
        },
      );
      replaceCase(updated);
      setNotice(`가설 “${hypothesis.candidate_signal}” 판단을 저장했습니다.`);
      void refreshShiftWorkspace();
    } catch (error) {
      setActionError(message(error));
    } finally {
      setHandoverBusy(false);
    }
  }
  async function refreshShiftWorkspace() {
    const params = new URLSearchParams({ status: workspaceFilter });
    if (shiftAssignee.trim()) params.set("assignee", shiftAssignee.trim());
    try {
      const result = await api<ShiftWorkspace>(`/shift-workspace?${params.toString()}`);
      setShiftWorkspace(result);
      setShiftWorkspaceError("");
    } catch (error) {
      setShiftWorkspaceError(message(error));
    }
  }
  async function showCaseRun(runId: string | null, nextEvidenceId = "") {
    if (!activeCase || caseBusy) return;
    const target = activeCase.analysis_runs.find(
      (item) => item.id === (runId || activeCase.current_run_id),
    );
    if (!target) {
      setActionError("연결된 Analysis Run을 찾을 수 없습니다.");
      return;
    }
    setCaseBusy(true);
    displayedRunRevision.current += 1;
    displayedCaseRunId.current = target.id;
    setActionError("");
    try {
      const investigation = await api<Investigation>(
        `/investigations/${encodeURIComponent(target.investigation_id)}`,
      );
      setRun(investigation);
      setEvidenceId(nextEvidenceId || investigation.evidence[0]?.id || "");
      setPage("workspace");
      setTab("results");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setCaseBusy(false);
    }
  }
  async function addCaseAnalysisRun() {
    if (
      !activeCase ||
      !analysisRunCreator.trim() ||
      analysisRunBusy ||
      analysisRunCutoff <= (resume?.current_run?.diagnosis_time ?? -1)
    ) return;
    setAnalysisRunBusy(true);
    displayedRunRevision.current += 1;
    setActionError("");
    try {
      const updated = await post<InvestigationCase>(
        `/cases/${encodeURIComponent(activeCase.id)}/analysis-runs`,
        {
          expected_version: activeCase.version,
          diagnosis_time: analysisRunCutoff,
          question: analysisRunQuestion,
          created_by: analysisRunCreator.trim(),
          idempotency_key: crypto.randomUUID(),
        },
      );
      const current = updated.analysis_runs.find(
        (item) => item.id === updated.current_run_id,
      );
      if (!current) throw new Error("새 Analysis Run이 Case에 기록되지 않았습니다.");
      displayedCaseRunId.current = current.id;
      const investigation = await api<Investigation>(
        `/investigations/${encodeURIComponent(current.investigation_id)}`,
      );
      replaceCase(updated);
      setRun(investigation);
      setEvidenceId(investigation.evidence[0]?.id || "");
      setAnalysisRunQuestion("");
      setNotice(
        `새 Analysis Run ${shortId(current.id)}을 추가했습니다. 이전 Run은 History에 보존됩니다.`,
      );
      setPage("workspace");
      setTab("results");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setAnalysisRunBusy(false);
    }
  }
  async function openCase() {
    if (!incident || caseBusy) return;
    setCaseBusy(true);
    setActionError("");
    try {
      const created = await post<InvestigationCase>(
        `/incidents/${encodeURIComponent(incident.id)}/cases`,
        { diagnosis_time: cutoff, question },
      );
      const investigation = await api<Investigation>(
        `/investigations/${encodeURIComponent(created.investigation_id)}`,
      );
      displayedCaseRunId.current = created.current_run_id;
      replaceCase(created);
      setCaseChat([]);
      setRun(investigation);
      setEvidenceId(investigation.evidence[0]?.id || "");
      setPage("cases");
      setNotice("조사 사건을 열고, 확인이 필요한 근거 업무를 생성했습니다.");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setCaseBusy(false);
    }
  }
  async function respondToEvidenceTask(taskId: string) {
    if (!activeCase || !taskResponder.trim() || caseBusy) return;
    setCaseBusy(true);
    setActionError("");
    try {
      const updated = await post<InvestigationCase>(
        `/cases/${encodeURIComponent(activeCase.id)}/tasks/${encodeURIComponent(taskId)}/responses`,
        {
          outcome: taskOutcome,
          responder: taskResponder.trim(),
          comment: taskComment,
          expected_version: activeCase.version,
        },
      );
      replaceCase(updated);
      setTaskComment("");
      setNotice("근거 확인 응답이 기록되었습니다. 다음 사건 상태를 확인하세요.");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setCaseBusy(false);
    }
  }
  async function reviewCase(decision: "approve" | "reject") {
    if (!activeCase || !caseReviewer.trim() || caseBusy) return;
    setCaseBusy(true);
    setActionError("");
    try {
      const updated = await post<InvestigationCase>(
        `/cases/${encodeURIComponent(activeCase.id)}/reviews`,
        {
          decision,
          reviewer: caseReviewer.trim(),
          comment: caseComment,
          expected_version: activeCase.version,
        },
      );
      replaceCase(updated);
      setCaseComment("");
      setNotice(
        decision === "approve"
          ? "전문가 승인 후 사건을 종료했습니다."
          : "검토가 거절되어 추가 관측 업무로 사건을 재개했습니다.",
      );
    } catch (e) {
      setActionError(message(e));
    } finally {
      setCaseBusy(false);
    }
  }
  async function recordCaseObservation() {
    if (!activeCase || !observationText.trim() || !observationAuthor.trim() || handoverBusy) return;
    setHandoverBusy(true);
    setActionError("");
    try {
      const updated = await post<InvestigationCase>(
        `/cases/${encodeURIComponent(activeCase.id)}/observations`,
        {
          expected_version: activeCase.version,
          original_text: observationText.trim(),
          author: observationAuthor.trim(),
          provenance: "synthetic_demo",
          is_current_state: observationIsCurrentState,
        },
      );
      replaceCase(updated);
      setObservationText("");
      setObservationIsCurrentState(false);
      setNotice("관찰 원문이 기록되었습니다. 센서값과 분리된 교대 기록입니다.");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setHandoverBusy(false);
    }
  }
  async function assignFirstOpenItem() {
    if (!activeCase || !openItemAssignee.trim() || handoverBusy) return;
    const item = activeCase.open_items.find((candidate) => candidate.status !== "resolved");
    if (!item) return;
    setHandoverBusy(true);
    setActionError("");
    try {
      const updated = await post<InvestigationCase>(
        `/cases/${encodeURIComponent(activeCase.id)}/open-items/${encodeURIComponent(item.id)}/updates`,
        {
          expected_version: activeCase.version,
          status: item.status,
          assignee: openItemAssignee.trim(),
          hold_reason: item.hold_reason,
          completion_note: item.completion_note,
          observation_ids: item.observation_ids,
        },
      );
      replaceCase(updated);
      void refreshShiftWorkspace();
      setNotice("Open Item 담당자가 지정되었습니다.");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setHandoverBusy(false);
    }
  }
  async function checkCaseHandover() {
    if (!activeCase || !handoverSender.trim() || !handoverReceiver.trim() || handoverBusy) return;
    setHandoverBusy(true);
    setActionError("");
    try {
      const result = await post<{ case: InvestigationCase; findings: HandoverFinding[]; blocking: boolean }>(
        `/cases/${encodeURIComponent(activeCase.id)}/handover-checks`,
        {
          expected_version: activeCase.version,
          sender: handoverSender.trim(),
          receiver: handoverReceiver.trim(),
        },
      );
      setHandoverFindings(result.findings);
      replaceCase(result.case);
      void refreshShiftWorkspace();
      setNotice(result.blocking ? "인계 전 보완이 필요합니다." : "인계 점검을 완료했습니다.");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setHandoverBusy(false);
    }
  }
  async function publishCaseHandover() {
    if (!activeCase || !handoverSender.trim() || !handoverReceiver.trim() || handoverBusy) return;
    setHandoverBusy(true);
    setActionError("");
    try {
      const updated = await post<InvestigationCase>(
        `/cases/${encodeURIComponent(activeCase.id)}/handovers`,
        {
          expected_version: activeCase.version,
          sender: handoverSender.trim(),
          receiver: handoverReceiver.trim(),
          exception_reason: "",
        },
      );
      replaceCase(updated);
      void refreshShiftWorkspace();
      setHandoverFindings(updated.handover_snapshots.at(-1)?.findings || []);
      setNotice("버전이 고정된 인계 Packet을 발행했습니다.");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setHandoverBusy(false);
    }
  }
  async function acceptCaseHandover() {
    if (!activeCase || handoverBusy) return;
    const handover = activeCase.handovers.at(-1);
    const snapshot = activeCase.handover_snapshots.find((item) => item.id === handover?.snapshot_id);
    if (!handover || handover.status !== "published" || !snapshot || !handoverReceiver.trim()) return;
    setHandoverBusy(true);
    setActionError("");
    try {
      const updated = await post<InvestigationCase>(
        `/cases/${encodeURIComponent(activeCase.id)}/handovers/${encodeURIComponent(handover.id)}/acceptance`,
        {
          expected_version: activeCase.version,
          snapshot_id: snapshot.id,
          accepted_by: handoverReceiver.trim(),
        },
      );
      replaceCase(updated);
      void refreshShiftWorkspace();
      setNotice("인계 상태를 확인하고 수락했습니다. 조사는 계속 진행할 수 있습니다.");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setHandoverBusy(false);
    }
  }
  async function requestCaseHandoverChanges() {
    if (!activeCase || handoverBusy) return;
    const handover = activeCase.handovers.at(-1);
    if (!handover || handover.status !== "published" || !handoverReceiver.trim()) return;
    setHandoverBusy(true);
    setActionError("");
    try {
      const updated = await post<InvestigationCase>(
        `/cases/${encodeURIComponent(activeCase.id)}/handovers/${encodeURIComponent(handover.id)}/change-requests`,
        {
          expected_version: activeCase.version,
          requested_by: handoverReceiver.trim(),
          reason: caseComment.trim() || "인계 자료의 설명이 더 필요합니다.",
        },
      );
      replaceCase(updated);
      setNotice("인계 설명 요청을 기록했습니다.");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setHandoverBusy(false);
    }
  }
  async function openHistory(id: string) {
    setBusy(true);
    setActionError("");
    try {
      const [r, report] = await Promise.all([
        api<Investigation>(`/investigations/${encodeURIComponent(id)}`),
        api<Report>(`/investigations/${encodeURIComponent(id)}/report`),
      ]);
      const d = await api<Incident>(
        `/incidents/${encodeURIComponent(r.incident_id)}`,
      );
      revision.current++;
      setIncident(d);
      setRun(r);
      setCutoff(r.diagnosis_time);
      setReviews(report.reviews);
      setEvidenceId(r.evidence[0]?.id || "");
      setChat([]);
      setTab("results");
      setPage("workspace");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function review(decision: "approve" | "reject") {
    if (!run || !reviewer.trim() || reviewBusy) return;
    const rev = revision.current;
    setReviewBusy(true);
    setActionError("");
    try {
      const v = await post<Review>(
        `/investigations/${run.investigation_id}/reviews`,
        { reviewer: reviewer.trim(), decision, comment },
      );
      if (rev !== revision.current) return;
      setReviews((p) => [...p, v]);
      setComment("");
      setNotice("전문가 검토가 저장되었습니다.");
    } catch (e) {
      if (rev === revision.current) setActionError(message(e));
    } finally {
      setReviewBusy(false);
    }
  }
  async function exportReport() {
    if (!run) return;
    setActionError("");
    try {
      const report = await api<Report>(
        `/investigations/${run.investigation_id}/report`,
      );
      download(
        `${brand.reportPrefix}-${shortId(run.incident_id)}.md`,
        reportMarkdown(report),
        "text/markdown",
      );
    } catch (e) {
      setActionError(message(e));
    }
  }
  async function ask() {
    if (!run || !chatInput.trim() || chatBusy) return;
    const rev = revision.current;
    const q = chatInput.trim();
    setChatBusy(true);
    setActionError("");
    try {
      const response = await post<ChatResponse>(
        `/investigations/${run.investigation_id}/chat`,
        { question: q },
      );
      if (rev !== revision.current) return;
      setChat((p) => [...p, { question: q, response }]);
      setChatInput("");
    } catch (e) {
      if (rev === revision.current) setActionError(message(e));
    } finally {
      setChatBusy(false);
    }
  }
  async function askCase() {
    if (!activeCase || !caseChatInput.trim() || caseChatBusy) return;
    const q = caseChatInput.trim();
    setCaseChatBusy(true);
    setActionError("");
    try {
      const response = await post<ChatResponse>(
        `/cases/${encodeURIComponent(activeCase.id)}/chat`,
        { question: q, include_llm: caseChatIncludeAI },
      );
      setCaseChat((previous) => [...previous, { question: q, response }]);
      setCaseChatInput("");
    } catch (e) {
      setActionError(message(e));
    } finally {
      setCaseChatBusy(false);
    }
  }
  const filtered = incidents.filter((x) =>
    x.id.toLowerCase().includes(search.toLowerCase()),
  );
  const observations = useMemo(
    () =>
      incident?.observations.filter(
        (o) =>
          o.time_s <= cutoff &&
          o.signal.toLowerCase().includes(signalSearch.toLowerCase()),
      ) || [],
    [incident, cutoff, signalSearch],
  );
  const latestAlarmTime = useMemo(() => {
    const times =
      incident?.observations
        .filter(
          (o) => o.kind === "Alarm" && String(o.value).toLowerCase() === "true",
        )
        .map((o) => o.time_s) || [];
    return times.length ? Math.max(...times) : null;
  }, [incident]);
  const evidence = run?.evidence.find((e) => e.id === evidenceId);
  const displayedAnalysisRun = activeCase?.analysis_runs.find(
    (item) => item.investigation_id === run?.investigation_id,
  );
  const snapshotObservations = snapshotEntities(
    resume?.current_snapshot || null,
    "observations",
  );
  const snapshotOpenItems = snapshotEntities(
    resume?.current_snapshot || null,
    "open_items",
  );
  const snapshotHypotheses = snapshotEntities(
    resume?.current_snapshot || null,
    "hypotheses",
  );
  const title = {
    workspace: "조사 워크스페이스",
    cases: "교대 워크스페이스",
    history: "조사 기록",
    datasets: "데이터셋",
    guide: "사용 안내",
  }[page];
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        본문으로 이동
      </a>
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          aria-label={`${brand.name} ${brand.koreanName} · 조사 홈`}
          onClick={(e) => {
            e.preventDefault();
            setPage("workspace");
          }}
        >
          <span className="brand-symbol">
            <img src="/brand-mark.png" alt="" />
          </span>
          <span className="brand-wordmark">
            {brand.name}<small>{brand.koreanName} · 근거 중심 조사</small>
          </span>
        </a>
        <div className="workspace-label">
          <span className="workspace-avatar" aria-hidden="true"><Layers3 size={15} /></span>
          <span>
            제조 이상 조사<small>공개 데이터 · 공유 검증 공간</small>
          </span>
        </div>
        <p className="nav-label">WORKSPACE</p>
        <nav aria-label="주 메뉴">
          {(
            [
              { id: "workspace", label: "사건 조사", icon: FileSearch },
              { id: "cases", label: "사건 인박스", icon: ListChecks },
              { id: "history", label: "조사 기록", icon: Clock3 },
              { id: "datasets", label: "데이터셋", icon: Database },
            ] as const
          ).map((n) => (
            <button
              key={n.id}
              className={page === n.id ? "nav-item active" : "nav-item"}
              onClick={() => setPage(n.id)}
              aria-current={page === n.id ? "page" : undefined}
            >
              <n.icon size={18} />
              {n.label}
              {n.id === "history" && history.length > 0 && (
                <span className="nav-count">{history.length}</span>
              )}
              {n.id === "cases" && cases.length > 0 && (
                <span className="nav-count">
                  {cases.filter((item) => item.status !== "closed").length}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="safety-note">
            <ShieldCheck size={20} />
            <strong>{brand.promise}</strong>
            <p>
              AI는 조사 후보를 제안하고
              <br />
              전문가가 최종 판단합니다.
            </p>
          </div>
          <button className="nav-item" onClick={() => setPage("guide")}>
            <CircleHelp size={18} />
            사용 안내
          </button>
          <div className="connection">
            <i className={health ? "online" : ""} />
            {health ? "분석 서버 연결됨" : "연결 확인 중"}
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            <Layers3 size={16} />
            <span>워크스페이스</span>
            <ChevronRight size={14} />
            <strong>{title}</strong>
          </div>
          <span className="environment">공개 연구 데이터 · 검증 환경</span>
        </header>
        <main id="main">
          <div className="page-heading">
            <div>
              <div className="eyebrow">INVESTIGATE WITH EVIDENCE</div>
              <h1>{title}</h1>
              <p>
                {page === "workspace"
                  ? "흩어진 공정 신호를 연결하고, 다음에 확인할 근거를 찾으세요."
                  : page === "cases"
                    ? "인수 대기와 담당 Open Item을 먼저 확인하고, 중단된 조사를 이어갑니다."
                  : page === "history"
                    ? "이 브라우저에서 실행한 조사를 다시 확인합니다."
                    : page === "datasets"
                      ? "사용 가능한 데이터와 지원 범위를 확인합니다."
                      : "관측에서 전문가 검토까지, 근거 중심으로 조사합니다."}
              </p>
            </div>
            <button
              className="button secondary"
              onClick={() => setReload((v) => v + 1)}
              disabled={busy}
            >
              <RefreshCw size={15} />
              새로고침
            </button>
          </div>
          {notice && (
            <div className="notice success" role="status">
              <Check size={16} />
              <span>{notice}</span>
              <button
                aria-label="알림 닫기"
                className="icon-button"
                onClick={() => setNotice("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {actionError && <ErrorBox text={actionError} />}
          {page === "workspace" && (
            <>
              <dl className="overview ledger-summary" aria-label="조사 환경 요약">
                <div>
                  <dt>분석 데이터</dt>
                  <dd>{datasetLabel(dataset)}</dd>
                </div>
                <div>
                  <dt>준비된 사건</dt>
                  <dd>{loading ? "—" : number(incidents.length)}건</dd>
                </div>
                <div>
                  <dt>판단 방식</dt>
                  <dd>근거 기반 · 전문가 검토</dd>
                </div>
                <div className="overview-caption">
                  <dt className="sr-only">입력 범위</dt>
                  <dd>진단 시점 이후 데이터 제외</dd>
                </div>
              </dl>
              <div className="workspace-grid">
                <section
                  className="incident-panel panel"
                  aria-label="사건 목록"
                >
                  <div className="incident-header">
                    <h2>
                      사건 목록 <span>{incidents.length}</span>
                    </h2>
                    <label className="sr-only" htmlFor="dataset">
                      데이터셋
                    </label>
                    <select
                      id="dataset"
                      value={dataset}
                      disabled={busy}
                      onChange={(e) => setDataset(e.target.value)}
                    >
                      {(datasets.length
                        ? datasets
                        : [{ dataset: "causrca" }]
                      ).map((d) => (
                        <option key={d.dataset} value={d.dataset}>
                          {datasetLabel(d.dataset)}
                        </option>
                      ))}
                    </select>
                    <label className="searchbox">
                      <Search size={15} />
                      <input
                        aria-label="사건 ID 검색"
                        placeholder="사건 ID 검색"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                    </label>
                  </div>
                  <div className="incident-list">
                    {loading ? (
                      <div className="loading">
                        <LoaderCircle className="spin" />
                        사건 불러오는 중
                      </div>
                    ) : error ? (
                      <ErrorBox
                        text={error}
                        retry={() => setReload((v) => v + 1)}
                      />
                    ) : filtered.length ? (
                      filtered.map((x) => (
                        <button
                          key={x.id}
                          disabled={busy}
                          onClick={() => {
                            setSelected(x.id);
                            setSelectionVersion((v) => v + 1);
                          }}
                          className={`incident-item ${incident?.id === x.id ? "selected" : ""}`}
                          aria-pressed={incident?.id === x.id}
                        >
                          <div>
                            <strong>사건 {shortId(x.id)}</strong>
                            <ChevronRight size={14} />
                          </div>
                          <p>
                            {datasetLabel(x.source_dataset)} ·{" "}
                            {number(
                              x.time_range_s.end - x.time_range_s.start,
                              1,
                            )}
                            초 관측
                          </p>
                        </button>
                      ))
                    ) : (
                      <Empty
                        title={search ? "검색 결과 없음" : "준비된 사건 없음"}
                        detail={
                          search
                            ? "다른 사건 ID로 검색해 주세요."
                            : "데이터 준비 후 사건을 불러올 수 있습니다."
                        }
                      />
                    )}
                  </div>
                  <div className="list-footer">
                    관측 데이터 기준 · 정답 라벨 미사용
                  </div>
                </section>
                <section className="detail-panel panel" aria-label="사건 상세">
                  {detailLoading ? (
                    <div className="loading tall">
                      <LoaderCircle className="spin" />
                      관측 데이터 불러오는 중
                    </div>
                  ) : !incident ? (
                    <Empty
                      title="조사할 사건을 선택하세요"
                      detail="왼쪽 목록에서 사건을 선택하면 관측 신호가 표시됩니다."
                    />
                  ) : (
                    <>
                      <div className="detail-heading">
                        <div>
                          <span className="eyebrow">
                            INCIDENT / {datasetLabel(incident.source_dataset)}
                          </span>
                          <h2>
                            사건 {shortId(incident.id)}{" "}
                            <span className="badge teal">
                              {run ? "조사 완료" : "조사 준비"}
                            </span>
                          </h2>
                          <p className="mono">{incident.id}</p>
                        </div>
                        {run && (
                          <button
                            className="button secondary compact"
                            onClick={exportReport}
                          >
                            <ArrowDownToLine size={15} />
                            보고서
                          </button>
                        )}
                      </div>
                      <div className="detail-facts">
                        <span>
                          <Clock3 size={14} />
                          {number(incident.time_range_s.end, 1)}초 관측
                        </span>
                        <span>
                          <Activity size={14} />
                          {number(incident.observations.length)}개 기록
                        </span>
                        <span>
                          <ShieldCheck size={14} />
                          전문가 검토 필요
                        </span>
                      </div>
                      <Timeline incident={incident} cutoff={cutoff} />
                      <div className="run-config">
                        <div className="cutoff-control">
                          {latestAlarmTime !== null && (
                            <button
                              className="text-button alarm-jump"
                              disabled={busy}
                              onClick={() => setCutoff(latestAlarmTime)}
                            >
                              최근 알람 발생 시점으로 이동 (
                              {number(latestAlarmTime, 1)}s)
                            </button>
                          )}
                          <label htmlFor="cutoff">
                            진단 시점 <span>이 시점까지의 관측만 분석</span>
                          </label>
                          <div>
                            <input
                              id="cutoff"
                              type="range"
                              min={incident.time_range_s.start}
                              max={incident.time_range_s.end}
                              step="any"
                              value={cutoff}
                              disabled={busy}
                              onChange={(e) =>
                                setCutoff(Number(e.target.value))
                              }
                            />
                            <input
                              aria-label="진단 시점 초"
                              className="time-input"
                              type="number"
                              min={incident.time_range_s.start}
                              max={incident.time_range_s.end}
                              step="any"
                              value={cutoff}
                              disabled={busy}
                              onChange={(e) =>
                                setCutoff(
                                  Math.max(
                                    incident.time_range_s.start,
                                    Math.min(
                                      incident.time_range_s.end,
                                      Number(e.target.value),
                                    ),
                                  ),
                                )
                              }
                            />
                            <span>s</span>
                          </div>
                        </div>
                        <label className="question-label">
                          조사 질문 <span>선택</span>
                          <input
                            value={question}
                            maxLength={2000}
                            disabled={busy}
                            onChange={(e) => setQuestion(e.target.value)}
                            placeholder="예: 이상 징후가 시작된 신호와 확인할 근거는?"
                          />
                        </label>
                        <div className="run-actions">
                          <label className="checkbox">
                            <input
                              type="checkbox"
                              checked={includeAI}
                              disabled={
                                busy ||
                                !health ||
                                health.llm_provider === "not_configured"
                              }
                              onChange={(e) => setIncludeAI(e.target.checked)}
                            />
                            AI 해설 포함{" "}
                            <span>
                              {health?.llm_provider === "not_configured"
                                ? "(연결 필요)"
                                : "(추가 시간 소요)"}
                            </span>
                          </label>
                          <button
                            className="button primary"
                            onClick={investigate}
                            disabled={busy}
                          >
                            {busy ? (
                              <LoaderCircle className="spin" size={16} />
                            ) : (
                              <Play size={15} />
                            )}{" "}
                            {busy ? "근거 분석 중…" : "조사 실행"}
                            {!busy && <ArrowRight size={15} />}
                          </button>
                        </div>
                      </div>
                      <div
                        className="tabs"
                        role="tablist"
                        aria-label="조사 내용"
                      >
                        {(
                          [
                            { id: "signals", label: "관측 신호" },
                            { id: "results", label: "분석 결과" },
                            { id: "review", label: "전문가 검토" },
                            { id: "chat", label: "근거에 질문" },
                          ] as const
                        ).map((t) => (
                          <button
                            role="tab"
                            id={`tab-${t.id}`}
                            aria-controls="tab-panel"
                            aria-selected={tab === t.id}
                            tabIndex={tab === t.id ? 0 : -1}
                            onKeyDown={(e) => {
                              const tabs: Tab[] = [
                                "signals",
                                "results",
                                "review",
                                "chat",
                              ];
                              const index = tabs.indexOf(t.id);
                              const next =
                                e.key === "ArrowRight"
                                  ? tabs[(index + 1) % 4]
                                  : e.key === "ArrowLeft"
                                    ? tabs[(index + 3) % 4]
                                    : e.key === "Home"
                                      ? tabs[0]
                                      : e.key === "End"
                                        ? tabs[3]
                                        : null;
                              if (next) {
                                e.preventDefault();
                                setTab(next);
                                document.getElementById(`tab-${next}`)?.focus();
                              }
                            }}
                            key={t.id}
                            onClick={() => setTab(t.id)}
                          >
                            {t.label}
                            {t.id === "results" && run && (
                              <span>{run.candidates.length}</span>
                            )}
                          </button>
                        ))}
                      </div>
                      <div
                        id="tab-panel"
                        role="tabpanel"
                        aria-labelledby={`tab-${tab}`}
                        className="tab-content"
                      >
                        {tab === "signals" && (
                          <>
                            <div className="section-heading">
                              <div>
                                <h3>관측 기록</h3>
                                <p>
                                  진단 시점 이전 {number(observations.length)}개
                                  · 최대 100개 표시
                                </p>
                              </div>
                              <label className="searchbox small">
                                <Search size={14} />
                                <input
                                  aria-label="신호 검색"
                                  placeholder="신호 검색"
                                  value={signalSearch}
                                  onChange={(e) =>
                                    setSignalSearch(e.target.value)
                                  }
                                />
                              </label>
                            </div>
                            <p className="table-hint">
                              표가 잘리면 좌우로 스크롤해 전체 값을 확인하세요.
                            </p>
                            <div
                              className="table-scroll"
                              tabIndex={0}
                              aria-label="관측 기록 표, 좌우 스크롤 가능"
                            >
                              <table>
                                <thead>
                                  <tr>
                                    <th>시점 (s)</th>
                                    <th>신호</th>
                                    <th>관측값</th>
                                    <th>유형</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {observations.slice(0, 100).map((o, i) => (
                                    <tr key={i}>
                                      <td className="mono muted">
                                        {number(o.time_s, 3)}
                                      </td>
                                      <td className="mono signal-name">
                                        {o.signal}
                                      </td>
                                      <td className="mono">
                                        {String(o.value)}
                                      </td>
                                      <td>
                                        <span
                                          className={`badge ${o.kind === "Alarm" ? "warning" : "neutral"}`}
                                        >
                                          {o.kind}
                                        </span>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                              {!observations.length && (
                                <Empty
                                  title="일치하는 관측이 없습니다"
                                  detail="진단 시점이나 신호 검색어를 변경해 주세요."
                                />
                              )}
                            </div>
                          </>
                        )}
                        {tab !== "signals" && !run && (
                          <Empty
                            title="먼저 조사를 실행해 주세요"
                            detail="진단 시점을 설정하고 조사 실행을 누르면 원인 후보와 근거를 확인할 수 있습니다."
                          />
                        )}
                        {tab === "results" && run && (
                          <>
                            <div className="section-heading">
                              <div>
                                <h3>우선 확인할 원인 후보</h3>
                                <p>
                                  진단 {number(run.diagnosis_time, 1)}s ·{" "}
                                  {displayText(run.mode)} · 확정 원인이 아닙니다
                                </p>
                                {displayedAnalysisRun && (
                                  <p className="mono">
                                    Run {shortId(displayedAnalysisRun.id)}
                                    {displayedAnalysisRun.id === activeCase?.current_run_id
                                      ? " · 현재 Run"
                                      : " · 과거 Run"}
                                  </p>
                                )}
                              </div>
                              <span className="badge teal">
                                근거 {run.evidence.length}개
                              </span>
                            </div>
                            <div className="results-grid">
                              <div className="candidate-list">
                                {!run.candidates.length && (
                                  <Empty
                                    title="이 시점에는 원인 후보를 제안할 수 없습니다"
                                    detail="활성 알람이 없거나 근거가 부족합니다. 관측 기록과 진단 시점을 확인하거나 추가 데이터를 확보하세요. 후보 없음은 정상 공정을 보장하지 않습니다."
                                  />
                                )}
                                {run.candidates.map((c) => (
                                  <button
                                    className={`candidate ${c.evidence_ids.includes(evidenceId) ? "chosen" : ""}`}
                                    key={`${c.rank}-${c.signal}`}
                                    onClick={() =>
                                      setEvidenceId(c.evidence_ids[0] || "")
                                    }
                                  >
                                    <span className="rank">
                                      {String(c.rank).padStart(2, "0")}
                                    </span>
                                    <div>
                                      <strong>{c.signal}</strong>
                                      <p>{displayText(c.reason)}</p>
                                      <small>
                                        {c.status === "inconclusive"
                                          ? "판단 보류"
                                          : "원인 후보"}{" "}
                                        · 근거 {c.evidence_ids.length}개
                                      </small>
                                    </div>
                                    <ChevronRight size={15} />
                                  </button>
                                ))}
                              </div>
                              <aside className="evidence-panel">
                                <div className="eyebrow">
                                  SUPPORTING EVIDENCE
                                </div>
                                {evidence ? (
                                  <>
                                    <h3>{displayText(evidence.title)}</h3>
                                    <p>{displayText(evidence.detail)}</p>
                                    <div className="evidence-source">
                                      {evidence.id}
                                      <br />
                                      출처: {displayText(evidence.source)}
                                    </div>
                                  </>
                                ) : (
                                  <p>후보를 선택해 연결된 근거를 확인하세요.</p>
                                )}
                                <div className="evidence-links">
                                  {run.evidence.map((e) => (
                                    <button
                                      key={e.id}
                                      onClick={() => setEvidenceId(e.id)}
                                      aria-pressed={evidenceId === e.id}
                                    >
                                      {e.id}
                                    </button>
                                  ))}
                                </div>
                              </aside>
                            </div>
                            {run.llm_narrative && (
                              <div className="narrative">
                                <h3>AI 조사 해설</h3>
                                <p>{run.llm_narrative}</p>
                              </div>
                            )}
                            <div className="next-action">
                              <ArrowRight size={18} />
                              <div>
                                <strong>다음 확인 사항</strong>
                                <p>{displayText(run.next_action)}</p>
                              </div>
                              <button
                                className="button primary compact"
                                disabled={caseBusy || !casesAvailable}
                                onClick={openCase}
                                title={
                                  casesAvailable
                                    ? undefined
                                    : "사건 오케스트레이션 API가 아직 연결되지 않았습니다."
                                }
                              >
                                {caseBusy ? (
                                  <LoaderCircle className="spin" size={15} />
                                ) : (
                                  <Bot size={15} />
                                )}
                                {caseBusy ? "사건 여는 중" : "확인 업무로 전환"}
                              </button>
                            </div>
                            {run.warnings.length > 0 && (
                              <details className="disclosure">
                                <summary>
                                  <TriangleAlert size={15} />
                                  분석 한계 및 주의사항 ({run.warnings.length})
                                </summary>
                                <ul>
                                  {run.warnings.map((w, i) => (
                                    <li key={i}>{displayText(w)}</li>
                                  ))}
                                </ul>
                              </details>
                            )}
                            <details className="disclosure">
                              <summary>
                                <Layers3 size={15} />
                                분석 실행 기록 ({run.trace.length}단계)
                              </summary>
                              {run.trace.map((t, i) => (
                                <div className="trace" key={i}>
                                  <span>{t.step}</span>
                                  <div>
                                    <strong>{t.tool}</strong>
                                    <p>{t.detail}</p>
                                  </div>
                                  {t.latency_ms != null && (
                                    <small>{number(t.latency_ms)}ms</small>
                                  )}
                                </div>
                              ))}
                            </details>
                            <p className="footnote">
                              AI 상태: {displayText(run.llm_status)} · 분석
                              결과는 설비 조작 지시가 아닙니다.
                            </p>
                          </>
                        )}
                        {tab === "review" && run && (
                          <>
                            <div className="section-heading">
                              <div>
                                <h3>전문가의 판단을 기록하세요</h3>
                                <p>
                                  검토는 조사 결과에 대한 의견이며 실제 원인
                                  확정이 아닙니다.
                                </p>
                              </div>
                              <ShieldCheck size={23} />
                            </div>
                            <form
                              onSubmit={(e) => {
                                e.preventDefault();
                                void review("approve");
                              }}
                              className="review-form"
                            >
                              <label>
                                검토자
                                <input
                                  value={reviewer}
                                  onChange={(e) => setReviewer(e.target.value)}
                                  maxLength={120}
                                  required
                                  placeholder="이름 또는 담당자 ID"
                                />
                              </label>
                              <label>
                                검토 의견
                                <textarea
                                  value={comment}
                                  onChange={(e) => setComment(e.target.value)}
                                  maxLength={2000}
                                  rows={4}
                                  placeholder="현장 맥락, 추가 확인 내용, 후보에 대한 의견을 남겨 주세요."
                                />
                              </label>
                              <div className="button-row">
                                <button
                                  className="button secondary"
                                  type="button"
                                  disabled={!reviewer.trim() || reviewBusy}
                                  onClick={() => review("reject")}
                                >
                                  <X size={16} />
                                  재검토 필요
                                </button>
                                <button
                                  className="button primary"
                                  disabled={!reviewer.trim() || reviewBusy}
                                >
                                  {reviewBusy ? (
                                    <LoaderCircle className="spin" size={16} />
                                  ) : (
                                    <Check size={16} />
                                  )}
                                  검토 승인
                                </button>
                              </div>
                            </form>
                            <h3 className="subheading">
                              검토 이력 <span>{reviews.length}</span>
                            </h3>
                            {reviews.length ? (
                              reviews.map((v, i) => (
                                <div className="review-entry" key={i}>
                                  <div>
                                    <strong>{v.reviewer}</strong>
                                    <span
                                      className={`badge ${v.decision === "approve" ? "teal" : "warning"}`}
                                    >
                                      {v.decision === "approve"
                                        ? "승인"
                                        : "재검토 필요"}
                                    </span>
                                    <time>
                                      {new Date(v.reviewed_at).toLocaleString(
                                        "ko-KR",
                                      )}
                                    </time>
                                  </div>
                                  <p>{v.comment || "별도 의견 없음"}</p>
                                </div>
                              ))
                            ) : (
                              <p className="muted">
                                아직 검토 기록이 없습니다.
                              </p>
                            )}
                          </>
                        )}
                        {tab === "chat" && run && (
                          <>
                            <div className="section-heading">
                              <div>
                                <h3>이 조사에 대해 질문하기</h3>
                                <p>
                                  현재 조사 근거를 바탕으로 답변합니다. 설비
                                  제어는 수행하지 않습니다.
                                </p>
                              </div>
                              <MessageSquare size={22} />
                            </div>
                            <div className="chat-messages" aria-live="polite">
                              {!chat.length && (
                                <div className="chat-intro">
                                  <MessageSquare size={26} />
                                  <strong>어떤 근거가 궁금하신가요?</strong>
                                  <button
                                    onClick={() =>
                                      setChatInput(
                                        "첫 번째 후보를 뒷받침하는 근거와 한계를 설명해 주세요.",
                                      )
                                    }
                                    className="suggestion"
                                  >
                                    첫 번째 후보의 근거와 한계는?{" "}
                                    <ArrowRight size={14} />
                                  </button>
                                </div>
                              )}
                              {chat.map((m, i) => (
                                <div className="chat-turn" key={i}>
                                  <p className="chat-question">{m.question}</p>
                                  <div className="chat-answer">
                                    <span className="eyebrow">
                                      조사 어시스턴트
                                    </span>
                                    <p>{m.response.answer}</p>
                                    <small>
                                      {m.response.blocked
                                        ? "안전 범위 안내"
                                        : "근거 기반 답변"}{" "}
                                      · {m.response.llm_status}
                                    </small>
                                    <div className="evidence-links">
                                      {m.response.grounded_evidence_ids.map(
                                        (id) => (
                                          <button
                                            key={id}
                                            onClick={() => {
                                              setEvidenceId(id);
                                              setTab("results");
                                            }}
                                          >
                                            {id}
                                          </button>
                                        ),
                                      )}
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                            <form
                              className="chat-form"
                              onSubmit={(e) => {
                                e.preventDefault();
                                void ask();
                              }}
                            >
                              <label className="sr-only" htmlFor="chat-input">
                                조사 질문
                              </label>
                              <input
                                id="chat-input"
                                value={chatInput}
                                maxLength={2000}
                                onChange={(e) => setChatInput(e.target.value)}
                                placeholder="이 조사 결과에서 궁금한 점을 질문하세요"
                              />
                              <button
                                className="button primary"
                                disabled={!chatInput.trim() || chatBusy}
                                aria-label="질문 보내기"
                              >
                                {chatBusy ? (
                                  <LoaderCircle className="spin" size={17} />
                                ) : (
                                  <Send size={17} />
                                )}
                              </button>
                            </form>
                          </>
                        )}
                      </div>
                    </>
                  )}
                </section>
              </div>
            </>
          )}
          {page === "cases" && (
            <section className="caseboard" aria-label="교대 워크스페이스 · 사건 인박스">
              {!casesAvailable ? (
                <Empty
                  title="사건 오케스트레이션을 연결하는 중입니다"
                  detail="현재 연결된 API에는 사건 상태 기능이 없습니다. 최신 백엔드 배포 후 다시 시도해 주세요."
                />
              ) : (
                <>
                  <section className="shift-workspace-panel panel" aria-label="내 교대 업무">
                    <div className="shift-workspace-heading">
                      <div>
                        <span className="eyebrow">SHIFT WORKSPACE</span>
                        <h2>이번 교대에서 바로 이어갈 일</h2>
                        <p>전체 사건을 다시 읽지 않고, 인수 대기와 내 Open Item부터 확인합니다.</p>
                      </div>
                      <form
                        className="shift-workspace-controls"
                        onSubmit={(event) => {
                          event.preventDefault();
                          void refreshShiftWorkspace();
                        }}
                      >
                        <label>
                          담당자 ID
                          <input
                            value={shiftAssignee}
                            onChange={(event) => setShiftAssignee(event.target.value)}
                            placeholder="Shift B"
                            maxLength={120}
                          />
                        </label>
                        <label>
                          보기
                          <select value={workspaceFilter} onChange={(event) => setWorkspaceFilter(event.target.value as ShiftWorkspaceFilter)}>
                            <option value="action_required">조치 필요</option>
                            <option value="handover">인수 대기</option>
                            <option value="open_items">내 Open Item</option>
                            <option value="stale">최신화 필요</option>
                            <option value="all">전체 관련 사건</option>
                          </select>
                        </label>
                        <button className="button secondary compact" disabled={shiftWorkspaceLoading}>
                          {shiftWorkspaceLoading ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}
                          새로고침
                        </button>
                      </form>
                    </div>
                    {shiftWorkspaceError && <p className="shift-workspace-error">워크스페이스를 불러오지 못했습니다. {shiftWorkspaceError}</p>}
                    {shiftWorkspace && (
                      <>
                        <div className="shift-workspace-summary" aria-label="교대 업무 요약">
                          <div><strong>{shiftWorkspace.summary.cases}</strong><span>사건</span></div>
                          <div><strong>{shiftWorkspace.summary.pending_handovers}</strong><span>인수 대기</span></div>
                          <div><strong>{shiftWorkspace.summary.assigned_open_items}</strong><span>내 Open Item</span></div>
                          <div><strong>{shiftWorkspace.summary.stale_snapshots}</strong><span>최신화 필요</span></div>
                          <div><strong>{shiftWorkspace.summary.blocking_findings}</strong><span>차단 이슈</span></div>
                        </div>
                        <div className="shift-workspace-list">
                          {shiftWorkspace.items.length ? shiftWorkspace.items.map((item) => (
                            <button
                              className="shift-workspace-item"
                              key={item.case_id}
                              onClick={() => void openShiftWorkspaceCase(item.case_id)}
                              disabled={caseBusy}
                            >
                              <div className="shift-workspace-item-main">
                                <strong>사건 {shortId(item.incident_id)}</strong>
                                <span>우선순위 {item.priority} · 버전 {item.case_version}{item.handover_receiver ? ` · 인수자 ${item.handover_receiver}` : ""}</span>
                              </div>
                              <div className="shift-workspace-reasons">
                                {item.reasons.map((reason) => <span className="badge neutral" key={reason}>{shiftReasonLabel[reason] || reason}</span>)}
                              </div>
                              <p>{item.next_action}</p>
                              <span className="shift-workspace-item-arrow"><ChevronRight size={16} /></span>
                            </button>
                          )) : (
                            <p className="shift-workspace-empty">현재 담당자에게 배정된 조치가 없습니다.</p>
                          )}
                        </div>
                      </>
                    )}
                  </section>
                  <div className="caseboard-grid">
                  <aside className="case-inbox panel" aria-label="사건 목록">
                    <div className="case-inbox-heading">
                      <div>
                        <span className="eyebrow">CASE INBOX</span>
                        <h2>진행 중 사건</h2>
                      </div>
                      <span className="badge neutral">{cases.length}</span>
                    </div>
                    <p>
                      후보만 보여 주지 않고, 아직 닫히지 않은 증거 업무를 중심으로 봅니다.
                    </p>
                    <div className="case-list">
                      {cases.length ? (
                        cases.map((item) => (
                          <button
                            className={`case-list-item ${activeCase?.id === item.id ? "selected" : ""}`}
                            key={item.id}
                            disabled={caseBusy}
                            onClick={() => void selectCase(item)}
                            aria-pressed={activeCase?.id === item.id}
                          >
                            <div>
                              <strong>사건 {shortId(item.incident_id)}</strong>
                              <span className={`case-status ${item.status}`}>
                                {caseStatusLabel[item.status]}
                              </span>
                            </div>
                            <p>{item.tasks.filter((task) => task.status === "pending").length}개 확인 업무 · {shortId(item.id)}</p>
                            <time>{new Date(item.updated_at).toLocaleString("ko-KR")}</time>
                          </button>
                        ))
                      ) : (
                        <Empty
                          title="열린 사건이 없습니다"
                          detail="사건 조사에서 근거 분석을 실행한 뒤 ‘확인 업무로 전환’을 선택해 보세요."
                        />
                      )}
                    </div>
                  </aside>
                  <section className="case-detail panel" aria-label="사건 상세">
                    {!activeCase ? (
                      <Empty
                        title="사건을 선택하세요"
                        detail="왼쪽 인박스에서 사건을 고르면 에이전트 실행 이력과 사람 확인 업무를 볼 수 있습니다."
                      />
                    ) : (
                      <>
                        <div className="case-detail-heading">
                          <div>
                            <span className="eyebrow">EVIDENCE-CLOSURE CASE</span>
                            <h2>사건 {shortId(activeCase.incident_id)}</h2>
                            <p className="mono">{activeCase.id}</p>
                          </div>
                          <span className={`case-status large ${activeCase.status}`}>
                            {caseStatusLabel[activeCase.status]}
                          </span>
                        </div>
                        <div className="case-next-action">
                          <Bot size={20} />
                          <div>
                            <strong>Case Orchestrator의 다음 단계</strong>
                            <p>{displayText(activeCase.next_action)}</p>
                          </div>
                        </div>
                        <section className="case-handover-panel">
                          <div className="section-heading">
                            <div>
                              <span className="eyebrow">CONTINUUM RESUME</span>
                              <h3>교대 인수인계 워크스페이스</h3>
                              <p>
                                Case {shortId(activeCase.id)} · 버전 {activeCase.version} · 인수와 조사 종료는 별도 상태입니다.
                              </p>
                            </div>
                            <RefreshCw size={21} />
                          </div>
                          {resumeLoading && (
                            <div className="resume-loading" role="status">
                              <LoaderCircle className="spin" size={16} /> 최신 인계 상태를 불러오는 중입니다.
                            </div>
                          )}
                          {resumeError && <ErrorBox text={`Resume을 불러오지 못했습니다. ${resumeError}`} />}
                          <div className="resume-grid">
                            <div>
                              <strong>현재 상태</strong>
                              <p>{caseStatusLabel[resume?.status || activeCase.status]} · 최종 원인 미확정</p>
                            </div>
                            <div>
                              <strong>현재 분석 Run</strong>
                              <p className="mono">{resume?.current_run?.id || activeCase.current_run_id || "기록 없음"}</p>
                              {resume?.current_run && <small>cutoff {resume.current_run.diagnosis_time}s</small>}
                            </div>
                            <div>
                              <strong>최신 Handover</strong>
                              <p>
                                {resume?.current_handover
                                  ? `${resume.current_handover.sender} → ${resume.current_handover.receiver} · ${resume.current_handover.status}`
                                  : "발행 기록 없음"}
                              </p>
                            </div>
                            <div>
                              <strong>남은 Open Item</strong>
                              <p>{(resume?.open_items || activeCase.open_items).filter((item) => item.status !== "resolved").length}개 · 인계 대상</p>
                            </div>
                          </div>
                          <section className="analysis-run-panel" aria-label="Analysis Run 추가 및 이력">
                            <div className="analysis-run-controls">
                              <div>
                                <span className="eyebrow">SAME CASE ANALYSIS</span>
                                <h4>더 늦은 시점으로 분석 이어가기</h4>
                                <p>새 Run을 추가해도 이전 Run과 연결된 근거 업무, Open Item, Hypothesis는 그대로 보존됩니다.</p>
                              </div>
                              <form
                                onSubmit={(event) => {
                                  event.preventDefault();
                                  void addCaseAnalysisRun();
                                }}
                              >
                                <label>
                                  새 cutoff (초)
                                  <input
                                    type="number"
                                    min={0}
                                    step="0.1"
                                    value={analysisRunCutoff}
                                    onChange={(event) => setAnalysisRunCutoff(Number(event.target.value))}
                                  />
                                </label>
                                <label>
                                  실행자
                                  <input
                                    value={analysisRunCreator}
                                    onChange={(event) => setAnalysisRunCreator(event.target.value)}
                                    placeholder="Shift B 담당자"
                                    maxLength={120}
                                  />
                                </label>
                                <label className="analysis-run-question">
                                  조사 질문 (선택)
                                  <input
                                    value={analysisRunQuestion}
                                    onChange={(event) => setAnalysisRunQuestion(event.target.value)}
                                    placeholder="추가 데이터까지 포함해 다시 확인"
                                    maxLength={2000}
                                  />
                                </label>
                                <button
                                  className="button primary"
                                  disabled={
                                    !analysisRunCreator.trim() ||
                                    analysisRunBusy ||
                                    activeCase.status === "closed" ||
                                    analysisRunCutoff <= (resume?.current_run?.diagnosis_time ?? -1)
                                  }
                                >
                                  {analysisRunBusy ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />}
                                  Add Analysis Run
                                </button>
                              </form>
                              {resume?.current_run && analysisRunCutoff <= resume.current_run.diagnosis_time && (
                                <small>현재 cutoff {resume.current_run.diagnosis_time}s보다 늦은 시점을 입력해 주세요.</small>
                              )}
                            </div>
                            <div className="analysis-run-history">
                              <strong>Run History</strong>
                              <ol>
                                {activeCase.analysis_runs.map((item, index) => (
                                  <li key={item.id}>
                                    <span className="run-order">R{index + 1}</span>
                                    <div>
                                      <code>{item.id}</code>
                                      <small>cutoff {item.diagnosis_time}s · {new Date(item.created_at).toLocaleString("ko-KR")}</small>
                                    </div>
                                    {item.id === activeCase.current_run_id && <span className="badge teal">현재</span>}
                                    <button
                                      className="button secondary compact"
                                      disabled={caseBusy}
                                      onClick={() => void showCaseRun(item.id)}
                                    >
                                      결과 보기
                                    </button>
                                  </li>
                                ))}
                              </ol>
                            </div>
                          </section>
                          {resume && (
                            <div className="continuity-comparison" aria-label="Handover 당시와 현재 상태 비교">
                              <section className="continuity-state at-handover">
                                <span className="eyebrow">AT HANDOVER</span>
                                <h4>Packet 발행 당시</h4>
                                {resume.current_snapshot ? (
                                  <>
                                    <p className="continuity-meta">
                                      Case 버전 {resume.current_snapshot.source_case_version} · Snapshot {shortId(resume.current_snapshot.id)}
                                    </p>
                                    <dl className="continuity-facts">
                                      <div><dt>Run</dt><dd className="mono">{resume.current_snapshot.current_run_id || "기록 없음"}</dd></div>
                                      <div><dt>Observation</dt><dd>{snapshotObservations.length}개</dd></div>
                                      <div><dt>Open Item</dt><dd>{snapshotOpenItems.length}개 · 미해결 {snapshotOpenItems.filter((item) => item.status !== "resolved").length}개</dd></div>
                                    </dl>
                                    <div className="continuity-list">
                                      <strong>Hypothesis</strong>
                                      {snapshotHypotheses.length ? (
                                        <ul>{snapshotHypotheses.map((item) => <li key={item.id}><span>{item.candidate_signal}</span><code>{item.judgment}</code></li>)}</ul>
                                      ) : <p>기록 없음</p>}
                                    </div>
                                  </>
                                ) : (
                                  <p className="continuity-empty">아직 발행된 Handover Snapshot이 없습니다.</p>
                                )}
                              </section>
                              <section className="continuity-state current">
                                <span className="eyebrow">CURRENT</span>
                                <h4>현재 Case</h4>
                                <p className="continuity-meta">
                                  Case 버전 {resume.case_version} · {caseStatusLabel[resume.status]}
                                </p>
                                <dl className="continuity-facts">
                                  <div><dt>Run</dt><dd className="mono">{resume.current_run?.id || "기록 없음"}</dd></div>
                                  <div><dt>Observation</dt><dd>{resume.observations.length}개</dd></div>
                                  <div><dt>Open Item</dt><dd>{resume.open_items.length}개 · 미해결 {resume.open_items.filter((item) => item.status !== "resolved").length}개</dd></div>
                                </dl>
                                <div className="continuity-list">
                                  <strong>미해결 Open Item</strong>
                                  {resume.open_items.some((item) => item.status !== "resolved") ? (
                                    <ul>{resume.open_items.filter((item) => item.status !== "resolved").map((item) => <li key={item.id}><span>{item.title}</span><code>{item.status}</code></li>)}</ul>
                                  ) : <p>없음</p>}
                                </div>
                                <div className="continuity-list">
                                  <strong>Hypothesis</strong>
                                  {resume.hypotheses.length ? (
                                    <ul>{resume.hypotheses.map((item) => <li key={item.id}><span>{item.candidate_signal}</span><code>{item.judgment}</code></li>)}</ul>
                                  ) : <p>기록 없음</p>}
                                </div>
                              </section>
                              <section className="handover-delta">
                                <span className="eyebrow">CHANGES SINCE HANDOVER</span>
                                <h4>인계 이후 변경</h4>
                                {!resume.current_snapshot ? (
                                  <p>Snapshot 발행 후 변경을 비교할 수 있습니다.</p>
                                ) : resume.handover_delta.length ? (
                                  <ul>
                                    {resume.handover_delta.map((delta, index) => (
                                      <li key={`${delta.kind}-${"id" in delta ? delta.id : index}`}>
                                        <ChevronRight size={14} />
                                        <span>{describeHandoverDelta(delta, resume)}</span>
                                      </li>
                                    ))}
                                  </ul>
                                ) : (
                                  <p>Handover 이후 기록된 변경이 없습니다.</p>
                                )}
                              </section>
                            </div>
                          )}
                          <section className="case-state-editor" aria-label="조사 상태 업데이트">
                            <div className="section-heading">
                              <div>
                                <span className="eyebrow">INVESTIGATION STATE</span>
                                <h3>남은 업무와 가설 상태</h3>
                                <p>각 Open Item과 Hypothesis는 Case 버전을 확인한 뒤 독립적으로 저장됩니다.</p>
                              </div>
                              <ShieldCheck size={20} />
                            </div>
                            <div className="state-editor-grid">
                              <div className="state-editor-column">
                                <strong className="state-editor-label">OPEN ITEMS <span>{activeCase.open_items.length}</span></strong>
                                {activeCase.open_items.length ? activeCase.open_items.map((item) => {
                                  const draft = openItemDraft(item);
                                  return (
                                    <div className="state-editor-card" key={item.id}>
                                      <div className="state-editor-card-heading">
                                        <strong>{item.title}</strong>
                                        <code>{item.status}</code>
                                      </div>
                                      <div className="state-editor-fields">
                                        <label>
                                          상태
                                          <select
                                            value={draft.status}
                                            onChange={(event) => updateOpenItemDraft(item.id, { status: event.target.value as OpenItemStatus })}
                                          >
                                            <option value="not_started">미착수</option>
                                            <option value="unavailable">확인 불가</option>
                                            <option value="not_recorded">미기록</option>
                                            <option value="on_hold">보류</option>
                                            <option value="resolved">완료</option>
                                          </select>
                                        </label>
                                        <label>
                                          담당자
                                          <input
                                            value={draft.assignee}
                                            onChange={(event) => updateOpenItemDraft(item.id, { assignee: event.target.value })}
                                            placeholder="Shift B"
                                            maxLength={120}
                                          />
                                        </label>
                                      </div>
                                      <label>
                                        {draft.status === "on_hold" ? "보류 사유" : draft.status === "resolved" ? "완료 메모" : "상태 메모"}
                                        <input
                                          value={draft.note}
                                          onChange={(event) => updateOpenItemDraft(item.id, { note: event.target.value })}
                                          placeholder="다음 담당자가 이해할 수 있는 근거를 남겨 주세요"
                                          maxLength={2000}
                                        />
                                      </label>
                                      <button className="button secondary compact" type="button" disabled={handoverBusy} onClick={() => void updateCaseOpenItem(item)}>
                                        {handoverBusy ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />}
                                        Open Item 저장
                                      </button>
                                    </div>
                                  );
                                }) : <p className="muted">현재 Open Item이 없습니다.</p>}
                              </div>
                              <div className="state-editor-column">
                                <strong className="state-editor-label">HYPOTHESES <span>{activeCase.hypotheses.length}</span></strong>
                                {activeCase.hypotheses.length ? activeCase.hypotheses.map((hypothesis) => (
                                  <div className="state-editor-card" key={hypothesis.id}>
                                    <div className="state-editor-card-heading">
                                      <strong>{hypothesis.candidate_signal}</strong>
                                      <code>{hypothesis.judgment}</code>
                                    </div>
                                    <label>
                                      판단
                                      <select
                                        value={hypothesis.judgment}
                                        disabled={handoverBusy}
                                        onChange={(event) => void assessCaseHypothesis(hypothesis, event.target.value as HypothesisTrack["judgment"])}
                                      >
                                        <option value="unreviewed">미검토</option>
                                        <option value="supported">지지</option>
                                        <option value="not_supported">지지하지 않음</option>
                                        <option value="insufficient">근거 부족</option>
                                      </select>
                                    </label>
                                    <label>
                                      판단 근거
                                      <input
                                        value={hypothesisReasons[hypothesis.id] ?? hypothesis.change_reason}
                                        onChange={(event) => setHypothesisReasons((previous) => ({ ...previous, [hypothesis.id]: event.target.value }))}
                                        placeholder="왜 이 상태로 판단했는지 기록"
                                        maxLength={2000}
                                      />
                                    </label>
                                    <small className="state-editor-footnote">AI 후보 · 최종 원인 확정 아님</small>
                                  </div>
                                )) : <p className="muted">현재 가설 후보가 없습니다.</p>}
                              </div>
                            </div>
                          </section>
                          <section className="structuring-panel" aria-label="AI 메모 구조화 제안">
                            <div className="section-heading">
                              <div>
                                <span className="eyebrow">REVIEWABLE AI SUGGESTION</span>
                                <h3>교대 메모를 검토 가능한 제안으로 정리</h3>
                                <p>AI 제안은 Case 상태와 분리되어 있습니다. 수정하거나 보류한 뒤, 수락한 항목만 저장됩니다.</p>
                              </div>
                              <Bot size={20} />
                            </div>
                            <form
                              className="structuring-capture"
                              onSubmit={(event) => {
                                event.preventDefault();
                                void createStructuringProposals();
                              }}
                            >
                              <label>
                                작성자
                                <input
                                  value={structuringAuthor}
                                  onChange={(event) => setStructuringAuthor(event.target.value)}
                                  placeholder="Shift A 담당자"
                                  maxLength={120}
                                />
                              </label>
                              <label>
                                검토자
                                <input
                                  value={structuringReviewer}
                                  onChange={(event) => setStructuringReviewer(event.target.value)}
                                  placeholder="Shift B 담당자"
                                  maxLength={120}
                                />
                              </label>
                              <label className="structuring-note-field">
                                교대 메모 원문
                                <textarea
                                  value={structuringNote}
                                  onChange={(event) => setStructuringNote(event.target.value)}
                                  placeholder="예: Tool은 육안상 이상 없음. Spindle vibration은 아직 확인하지 못해 다음 교대에서 확인 필요."
                                  maxLength={4000}
                                  rows={3}
                                />
                              </label>
                              <div className="structuring-capture-actions">
                                <label className="checkbox">
                                  <input
                                    type="checkbox"
                                    checked={structuringIncludeAI}
                                    onChange={(event) => setStructuringIncludeAI(event.target.checked)}
                                  />
                                  LLM 보조 사용 <span>(실패 시 결정론적 제안)</span>
                                </label>
                                <button className="button primary" disabled={!structuringNote.trim() || !structuringAuthor.trim() || structuringBusy}>
                                  {structuringBusy ? <LoaderCircle className="spin" size={15} /> : <Bot size={15} />}
                                  제안 생성
                                </button>
                              </div>
                            </form>
                            <div className="structuring-proposals" aria-live="polite">
                              {!structuringProposals.length ? (
                                <p className="muted">검토 대기 중인 제안이 없습니다. 메모를 입력하면 이곳에 표시됩니다.</p>
                              ) : (
                                structuringProposals.map((proposal) => {
                                  const stale = proposal.case_version !== activeCase.version;
                                  return (
                                    <article className={`structuring-proposal ${stale ? "stale" : ""}`} key={proposal.id}>
                                      <div className="structuring-proposal-heading">
                                        <div>
                                          <span className="badge teal">{proposalLabel(proposal.kind)}</span>
                                          <strong>원문 기반 제안</strong>
                                        </div>
                                        <code>Case v{proposal.case_version} · 신뢰도 {Math.round(proposal.confidence * 100)}%</code>
                                      </div>
                                      <p className="structuring-source">“{proposal.source_text}”</p>
                                      <label>
                                        저장 전 수정
                                        <textarea
                                          value={proposalText(proposal)}
                                          onChange={(event) => setStructuringEdits((previous) => ({ ...previous, [proposal.id]: event.target.value }))}
                                          maxLength={4000}
                                          rows={2}
                                          disabled={structuringBusy}
                                        />
                                      </label>
                                      {proposal.missing_evidence.length > 0 && (
                                        <p className="structuring-missing"><TriangleAlert size={14} /> 미확인 근거: {proposal.missing_evidence.join(" · ")}</p>
                                      )}
                                      {stale && <p className="structuring-stale"><TriangleAlert size={14} /> Case가 변경되어 오래된 제안입니다. 새 버전에서 다시 생성해 주세요.</p>}
                                      <div className="structuring-proposal-footer">
                                        <small>{proposal.generator === "llm" ? "LLM 제안" : "규칙 기반 제안"} · {proposal.provenance}</small>
                                        <div className="button-row">
                                          <button className="button secondary compact" type="button" disabled={structuringBusy} onClick={() => void dismissStructuringProposal(proposal)}>보류</button>
                                          <button className="button primary compact" type="button" disabled={structuringBusy || stale} onClick={() => void acceptStructuringProposal(proposal)}><Check size={14} /> 검토 후 저장</button>
                                        </div>
                                      </div>
                                    </article>
                                  );
                                })
                              )}
                            </div>
                          </section>
                          <div className="handover-forms">
                            <form
                              className="review-form"
                              onSubmit={(event) => {
                                event.preventDefault();
                                void recordCaseObservation();
                              }}
                            >
                              <h4>교대 기록 추가</h4>
                              <label>
                                작성자
                                <input
                                  value={observationAuthor}
                                  onChange={(event) => setObservationAuthor(event.target.value)}
                                  placeholder="Shift A 담당자"
                                  maxLength={120}
                                />
                              </label>
                              <label>
                                관찰 원문
                                <textarea
                                  value={observationText}
                                  onChange={(event) => setObservationText(event.target.value)}
                                  placeholder="완료한 확인, 미실시 점검, 확인하지 못한 이유를 원문으로 남겨 주세요."
                                  maxLength={4000}
                                  rows={3}
                                />
                              </label>
                              <label className="checkbox">
                                <input
                                  type="checkbox"
                                  checked={observationIsCurrentState}
                                  onChange={(event) => setObservationIsCurrentState(event.target.checked)}
                                />
                                현재 설비 상태를 함께 확인한 기록입니다
                              </label>
                              <button className="button secondary" disabled={!observationText.trim() || !observationAuthor.trim() || handoverBusy}>
                                {handoverBusy ? <LoaderCircle className="spin" size={15} /> : <ListChecks size={15} />}
                                관찰 기록
                              </button>
                            </form>
                            <div className="review-form">
                              <h4>담당자·인계 점검</h4>
                              <label>
                                첫 Open Item 담당자
                                <input
                                  value={openItemAssignee}
                                  onChange={(event) => setOpenItemAssignee(event.target.value)}
                                  placeholder="Shift B 담당자 ID"
                                  maxLength={120}
                                />
                              </label>
                              <button
                                className="button secondary"
                                disabled={!openItemAssignee.trim() || handoverBusy || !activeCase.open_items.some((item) => item.status !== "resolved")}
                                onClick={() => void assignFirstOpenItem()}
                              >
                                담당자 지정
                              </button>
                              <div className="form-divider" />
                              <label>
                                인계자
                                <input value={handoverSender} onChange={(event) => setHandoverSender(event.target.value)} placeholder="Shift A" maxLength={120} />
                              </label>
                              <label>
                                인수자
                                <input value={handoverReceiver} onChange={(event) => setHandoverReceiver(event.target.value)} placeholder="Shift B" maxLength={120} />
                              </label>
                              <div className="button-row">
                                <button className="button secondary" disabled={!handoverSender.trim() || !handoverReceiver.trim() || handoverBusy} onClick={() => void checkCaseHandover()}>
                                  사전 점검
                                </button>
                                <button className="button primary" disabled={!handoverSender.trim() || !handoverReceiver.trim() || handoverBusy} onClick={() => void publishCaseHandover()}>
                                  Packet 발행
                                </button>
                              </div>
                            </div>
                          </div>
                          {handoverFindings.length > 0 && (
                            <div className="disclosure">
                              <strong>인계 점검 결과</strong>
                              <ul>
                                {handoverFindings.map((finding) => (
                                  <li key={`${finding.code}-${finding.entity_id}`}>
                                    <span className={`badge ${finding.severity === "blocking" ? "warning" : "neutral"}`}>
                                      {finding.severity === "blocking" ? "보완 필요" : "전달"}
                                    </span>{" "}
                                    {finding.message}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                          {activeCase.handovers.length > 0 && (() => {
                            const handover = activeCase.handovers.at(-1)!;
                            const snapshot = activeCase.handover_snapshots.find((item) => item.id === handover.snapshot_id);
                            return (
                              <div className="case-next-action">
                                <ArrowDownToLine size={19} />
                                <div>
                                  <strong>최근 Handover Packet · {handover.status}</strong>
                                  <p>Snapshot {snapshot?.id || "없음"} · Case 버전 {handover.source_case_version} · {handover.receiver}</p>
                                </div>
                                {handover.status === "published" && (
                                  <div className="button-row">
                                    <button className="button secondary compact" disabled={handoverBusy} onClick={() => void requestCaseHandoverChanges()}>설명 요청</button>
                                    <button className="button primary compact" disabled={handoverBusy} onClick={() => void acceptCaseHandover()}><Check size={15} /> 인수 확인</button>
                                  </div>
                                )}
                              </div>
                            );
                          })()}
                        </section>
                        <section className="case-chat-panel">
                          <div className="section-heading">
                            <div>
                              <span className="eyebrow">CASE Q&amp;A</span>
                              <h3>현재 Case에 질문하기</h3>
                              <p>현재 상태·Open Item·저장된 관찰과 근거만 사용합니다. 이유가 기록되지 않으면 추정하지 않습니다.</p>
                            </div>
                            <MessageSquare size={21} />
                          </div>
                          <div className="chat-messages" aria-live="polite">
                            {!caseChat.length && <p className="muted">예: “지금까지 무엇을 확인했고 무엇이 남았나요?”</p>}
                            {caseChat.map((turn, index) => (
                              <div className="chat-turn" key={`${turn.question}-${index}`}>
                                <p className="chat-question">{turn.question}</p>
                                <div className="chat-answer">
                                  <span className="eyebrow">CASE RESUME</span>
                                  <p>{turn.response.answer}</p>
                                  <small>{turn.response.llm_status} · 근거 {turn.response.grounded_evidence_ids.join(", ") || "없음"}</small>
                                </div>
                              </div>
                            ))}
                          </div>
                          <form className="chat-form" onSubmit={(event) => { event.preventDefault(); void askCase(); }}>
                            <label className="checkbox">
                              <input type="checkbox" checked={caseChatIncludeAI} onChange={(event) => setCaseChatIncludeAI(event.target.checked)} />
                              근거 정리 AI 보조 <span>(실패 시 템플릿으로 폴백)</span>
                            </label>
                            <label className="sr-only" htmlFor="case-chat-input">Case 질문</label>
                            <input
                              id="case-chat-input"
                              value={caseChatInput}
                              maxLength={2000}
                              onChange={(event) => setCaseChatInput(event.target.value)}
                              placeholder="무엇이 확인됐고 무엇이 남았나요?"
                            />
                            <button className="button primary" disabled={!caseChatInput.trim() || caseChatBusy} aria-label="Case 질문 보내기">
                              {caseChatBusy ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}
                            </button>
                          </form>
                        </section>
                        <div className="case-content-grid">
                          <section className="human-queue">
                            <div className="section-heading">
                              <div>
                                <span className="eyebrow">HUMAN ACTION QUEUE</span>
                                <h3>전문가 확인 업무</h3>
                              </div>
                              <UserRoundCheck size={21} />
                            </div>
                            {activeCase.tasks.map((task) => (
                              <article
                                className={`evidence-task ${task.status}`}
                                key={task.id}
                              >
                                <div className="task-title">
                                  <div>
                                    <span className="task-role">
                                      {task.requested_role === "operator"
                                        ? "운영자"
                                        : task.requested_role === "process_expert"
                                          ? "공정 전문가"
                                          : "설비 전문가"}
                                    </span>
                                    <h3>{task.title}</h3>
                                  </div>
                                  <span className={`badge ${task.status === "pending" ? "warning" : "teal"}`}>
                                    {task.status === "pending" ? "응답 필요" : "응답 기록됨"}
                                  </span>
                                </div>
                                <p>{task.instructions}</p>
                                <div className="task-references">
                                  {task.evidence_ids.length ? (
                                    task.evidence_ids.map((id) => (
                                      <button
                                        key={id}
                                        onClick={() => void showCaseRun(task.run_id, id)}
                                      >
                                        근거 {id} · {shortId(task.run_id || activeCase.current_run_id || "legacy")}
                                      </button>
                                    ))
                                  ) : (
                                    <span>추가 관측 요청 · 분석 trace 2–3단계</span>
                                  )}
                                </div>
                                {task.status === "completed" && task.response ? (
                                  <div className="task-response">
                                    <strong>{task.response.responder}</strong>
                                    <span>{task.response.outcome === "confirmed" ? "확인 가능" : task.response.outcome === "refuted" ? "근거 불일치" : "확인 불가"}</span>
                                    <p>{task.response.comment || "별도 의견 없음"}</p>
                                  </div>
                                ) : (
                                  <div className="task-form">
                                    <label>
                                      응답자
                                      <input
                                        value={taskResponder}
                                        onChange={(event) => setTaskResponder(event.target.value)}
                                        placeholder="이름 또는 담당자 ID"
                                        maxLength={120}
                                      />
                                    </label>
                                    <label>
                                      확인 결과
                                      <select
                                        value={taskOutcome}
                                        onChange={(event) => setTaskOutcome(event.target.value as ExpertResponseOutcome)}
                                      >
                                        <option value="confirmed">근거 확인 가능</option>
                                        <option value="refuted">근거 불일치</option>
                                        <option value="unavailable">현재 확인 불가</option>
                                      </select>
                                    </label>
                                    <label className="task-form-note">
                                      관찰 또는 문서 위치
                                      <textarea
                                        value={taskComment}
                                        onChange={(event) => setTaskComment(event.target.value)}
                                        placeholder="확인한 관측값, 문서 위치 또는 확인하지 못한 이유를 남겨 주세요."
                                        maxLength={2000}
                                        rows={3}
                                      />
                                    </label>
                                    <button
                                      className="button primary"
                                      disabled={!taskResponder.trim() || caseBusy}
                                      onClick={() => void respondToEvidenceTask(task.id)}
                                    >
                                      {caseBusy ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />}
                                      응답 기록
                                    </button>
                                  </div>
                                )}
                              </article>
                            ))}
                          </section>
                          <aside className="agent-ledger">
                            <div className="section-heading">
                              <div>
                                <span className="eyebrow">AGENT RUN LEDGER</span>
                                <h3>실행 및 판단 이력</h3>
                              </div>
                              <Activity size={20} />
                            </div>
                            <ol>
                              {activeCase.events.map((event) => (
                                <li key={event.sequence}>
                                  <span>{String(event.sequence).padStart(2, "0")}</span>
                                  <div>
                                    <strong>{displayCaseEventType(event.event_type)}</strong>
                                    <p>{displayCaseEventDetail(event.detail)}</p>
                                    <small>{event.actor === "expert" ? "전문가 입력" : "오케스트레이터"} · {new Date(event.created_at).toLocaleString("ko-KR")}</small>
                                  </div>
                                </li>
                              ))}
                            </ol>
                          </aside>
                        </div>
                        {activeCase.status === "ready_for_review" && (
                          <section className="case-review-gate">
                            <div>
                              <span className="eyebrow">EXPLICIT REVIEW REQUIRED</span>
                              <h3>최종 검토가 남아 있습니다</h3>
                              <p>근거 확인 응답은 원인을 자동 확정하지 않습니다. 담당 전문가가 명시적으로 승인 또는 거절해야 사건 상태가 바뀝니다.</p>
                            </div>
                            <div className="case-review-form">
                              <input
                                value={caseReviewer}
                                onChange={(event) => setCaseReviewer(event.target.value)}
                                placeholder="최종 검토자"
                                maxLength={120}
                              />
                              <textarea
                                value={caseComment}
                                onChange={(event) => setCaseComment(event.target.value)}
                                placeholder="검토 의견 (선택)"
                                maxLength={2000}
                                rows={2}
                              />
                              <div className="button-row">
                                <button
                                  className="button secondary"
                                  disabled={!caseReviewer.trim() || caseBusy}
                                  onClick={() => void reviewCase("reject")}
                                >
                                  재개 요청
                                </button>
                                <button
                                  className="button primary"
                                  disabled={!caseReviewer.trim() || caseBusy}
                                  onClick={() => void reviewCase("approve")}
                                >
                                  {caseBusy ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />}
                                  검토 승인 후 종료
                                </button>
                              </div>
                            </div>
                          </section>
                        )}
                        {activeCase.reviews.length > 0 && (
                          <section className="case-review-history">
                            <h3>최종 검토 이력</h3>
                            {activeCase.reviews.map((review) => (
                              <div key={`${review.reviewer}-${review.reviewed_at}`}>
                                <strong>{review.reviewer}</strong>
                                <span className={`badge ${review.decision === "approve" ? "teal" : "warning"}`}>
                                  {review.decision === "approve" ? "승인" : "거절"}
                                </span>
                                <time>{new Date(review.reviewed_at).toLocaleString("ko-KR")}</time>
                                <p>{review.comment || "별도 의견 없음"}</p>
                              </div>
                            ))}
                          </section>
                        )}
                      </>
                    )}
                  </section>
                  </div>
                </>
              )}
            </section>
          )}
          {page === "history" && (
            <section className="panel standalone">
              {history.length ? (
                <>
                  <div className="section-heading">
                    <h2>최근 실행한 조사</h2>
                    <span className="badge neutral">이 브라우저에만 표시</span>
                  </div>
                  {history.map((h) => (
                    <button
                      disabled={busy}
                      className="history-item"
                      key={h.id}
                      onClick={() => openHistory(h.id)}
                    >
                      <FileSearch size={20} />
                      <div>
                        <strong>사건 {shortId(h.incident)}</strong>
                        <small>{h.id}</small>
                      </div>
                      <time>{new Date(h.at).toLocaleString("ko-KR")}</time>
                      <ChevronRight size={18} />
                    </button>
                  ))}
                </>
              ) : (
                <Empty
                  title="아직 실행한 조사가 없습니다"
                  detail="사건 조사 화면에서 첫 조사를 실행해 보세요."
                />
              )}
            </section>
          )}
          {page === "datasets" && (
            <section className="panel standalone">
              <h2>데이터 연결 현황</h2>
              <p className="muted">
                현재 API에 준비된 데이터만 분석합니다. 임의 파일 업로드는 아직
                지원하지 않습니다.
              </p>
              {datasets.map((d) => (
                <div className="dataset-row" key={d.dataset}>
                  <span className="metric-icon">
                    <Database size={22} />
                  </span>
                  <div>
                    <h3>{datasetLabel(d.dataset)}</h3>
                    <p>
                      {d.dataset === "causrca"
                        ? "공개 HIL 공정 관측 · 시간 기반 원인 후보 조사"
                        : "공정 데이터 어댑터 · 준비 상태 확인 필요"}
                    </p>
                  </div>
                  <span className="badge neutral">{d.status}</span>
                  <strong>{d.incident_count}건</strong>
                  <button
                    className="button secondary"
                    onClick={() => {
                      setDataset(d.dataset);
                      setPage("workspace");
                    }}
                  >
                    보기
                    <ArrowRight size={15} />
                  </button>
                </div>
              ))}
            </section>
          )}
          {page === "guide" && (
            <section className="panel standalone guide">
              <div className="guide-brand">
                <img src="/brand-mark.png" width="48" height="48" alt="" />
                <div><strong>{brand.name}</strong><span>{brand.koreanName} · {brand.descriptor}</span></div>
              </div>
              <p className="brand-tagline">{brand.tagline}</p>
              <h2>확인 가능한 근거로, 사람이 마무리하는 조사</h2>
              <p>
                이 서비스는 공정 관측에서 원인 후보와 조사 근거를 정리하는
                의사결정 보조 도구입니다. 공장의 실제 원인을 자동 확정하거나
                설비를 제어하지 않습니다.
              </p>
              {[
                "사건 선택: 공개 데이터에서 조사할 사건과 관측 범위를 확인합니다.",
                "진단 시점 설정: 해당 시점까지의 관측만 분석에 사용합니다.",
                "조사 실행: 분석 도구가 후보와 근거를 만들고, 선택적으로 LLM이 해설합니다.",
                "전문가 검토: 후보의 근거와 한계를 확인하고 승인 또는 재검토 의견을 기록합니다.",
                "보고서 내보내기: 근거와 검토 이력을 Markdown 파일로 저장합니다.",
              ].map((s, i) => (
                <div className="guide-step" key={s}>
                  <span>{i + 1}</span>
                  <p>{s}</p>
                </div>
              ))}
              <div className="notice">
                <ShieldCheck size={20} />
                <p>
                  현재는 공유 검증 환경입니다. 검토자 이름은 본인 인증이 아니며,
                  개인별 권한 관리와 실제 설비 연동은 제공하지 않습니다. 민감한
                  사내 정보는 입력하지 마세요.
                </p>
              </div>
            </section>
          )}
          <footer className="page-footer">
            <span>{brand.name} / {brand.descriptor}</span>
            <span>{brand.tagline}</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
