import { useEffect, useMemo, useState } from "react";
import { ArrowRight, Clock3, Layers3, ListChecks, RefreshCw, TriangleAlert } from "lucide-react";
import { api, datasetLabel, shortId } from "./api";
import type { CaseResume, IncidentSummary, Investigation, InvestigationCase } from "./api";
import { displayText } from "./presentation";
import {
  shiftTotals,
  summarizeShiftCase,
  visibleShiftCases,
} from "./shiftSummary";
import type { ShiftFilter, ShiftSort, ShiftStatusFilter } from "./shiftSummary";

const filters: { id: ShiftFilter; label: string }[] = [
  { id: "active", label: "진행 중" },
  { id: "assigned", label: "내 담당" },
  { id: "attention", label: "확인 필요" },
  { id: "handover", label: "인계 대기" },
  { id: "recent", label: "최근 변경" },
  { id: "all", label: "전체 Case" },
];
const statusLabels: Record<InvestigationCase["status"], string> = {
  awaiting_evidence: "확인 대기",
  ready_for_review: "검토 대기",
  reopened: "재개됨",
  abstained: "판단 보류",
  closed: "종료됨",
};
const hypothesisLabels = [
  ["supported", "지지"],
  ["not_supported", "지지되지 않음"],
  ["insufficient", "근거 부족"],
  ["unreviewed", "미평가"],
] as const;
const dateTime = (value: string | null) => value ? new Date(value).toLocaleString("ko-KR") : "기록 없음";
const handoverStatusLabel: Record<string, string> = {
  draft: "작성 중", published: "수락 대기", changes_requested: "설명 요청",
  accepted: "수락됨", superseded: "이전 인계",
};
function attentionLabel(reason: string): string {
  const open = reason.match(/^(\d+) unresolved open items$/);
  if (open) return `미해결 업무 ${open[1]}건`;
  const hypotheses = reason.match(/^(\d+) hypothesis unreviewed$/);
  if (hypotheses) return `미평가 원인 가설 ${hypotheses[1]}건`;
  return ({
    "handover awaiting acceptance": "인계 수락 대기",
    "handover change requested": "인계 설명 요청",
    "new analysis run since handover": "인계 이후 새 분석 실행",
    "case updated after handover": "인계 이후 조사 내용 변경",
  } as Record<string, string>)[reason] || reason;
}

export function ShiftWorkspace({
  cases,
  casesAvailable,
  incidents,
  actor,
  onActorChange,
  onOpen,
}: {
  cases: InvestigationCase[];
  casesAvailable: boolean;
  incidents: IncidentSummary[];
  actor: string;
  onActorChange: (value: string) => void;
  onOpen: (item: InvestigationCase) => void;
}) {
  const [filter, setFilter] = useState<ShiftFilter>("active");
  const [sort, setSort] = useState<ShiftSort>("updated");
  const [status, setStatus] = useState<ShiftStatusFilter>("all");
  const [resumes, setResumes] = useState<Record<string, CaseResume>>({});
  const [investigations, setInvestigations] = useState<Record<string, Investigation>>({});
  const [candidateFailures, setCandidateFailures] = useState<string[]>([]);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [extraIncidentTitles, setExtraIncidentTitles] = useState<Record<string, string>>({});
  const [resumeFailures, setResumeFailures] = useState<string[]>([]);
  const [resumeLoading, setResumeLoading] = useState(false);
  const caseVersions = cases.map((item) => `${item.id}:${item.version}`).join("|");
  const caseDatasets = [...new Set(cases.map((item) => item.dataset))].sort().join("|");
  const currentInvestigationIds = [...new Set(cases.map((item) =>
    item.analysis_runs.find((run) => run.id === item.current_run_id)?.investigation_id,
  ).filter((id): id is string => Boolean(id)))].sort().join("|");

  useEffect(() => {
    const ctl = new AbortController();
    const datasets = caseDatasets.split("|").filter(Boolean);
    if (!datasets.length) return () => ctl.abort();
    Promise.all(datasets.map((dataset) => api<{ incidents: IncidentSummary[] }>(
      `/incidents?dataset=${encodeURIComponent(dataset)}`, { signal: ctl.signal },
    ).catch(() => ({ incidents: [] })))).then((groups) => {
      if (ctl.signal.aborted) return;
      setExtraIncidentTitles(Object.fromEntries(groups.flatMap((group) => group.incidents.map((item) => [item.id, item.title]))));
    });
    return () => ctl.abort();
  }, [caseDatasets]);

  useEffect(() => {
    const ctl = new AbortController();
    if (!casesAvailable || cases.length === 0) return () => ctl.abort();
    setResumeLoading(true);
    Promise.all(cases.map(async (item) => {
      try {
        return { id: item.id, resume: await api<CaseResume>(
          `/cases/${encodeURIComponent(item.id)}/resume`, { signal: ctl.signal },
        ) };
      } catch {
        return { id: item.id, resume: null };
      }
    })).then((results) => {
      if (ctl.signal.aborted) return;
      const next: Record<string, CaseResume> = {};
      for (const result of results) if (result.resume) next[result.id] = result.resume;
      setResumes(next);
      setResumeFailures(results.filter((result) => !result.resume).map((result) => result.id));
    }).finally(() => {
      if (!ctl.signal.aborted) setResumeLoading(false);
    });
    return () => ctl.abort();
  }, [caseVersions, casesAvailable]);

  useEffect(() => {
    const ctl = new AbortController();
    const ids = currentInvestigationIds.split("|").filter(Boolean);
    if (!casesAvailable || ids.length === 0) return () => ctl.abort();
    setCandidatesLoading(true);
    Promise.all(ids.map(async (id) => {
      try {
        return { id, result: await api<Investigation>(
          `/investigations/${encodeURIComponent(id)}`, { signal: ctl.signal },
        ) };
      } catch {
        return { id, result: null };
      }
    })).then((results) => {
      if (ctl.signal.aborted) return;
      const next: Record<string, Investigation> = {};
      for (const entry of results) if (entry.result) next[entry.id] = entry.result;
      setInvestigations(next);
      setCandidateFailures(results.filter((entry) => !entry.result).map((entry) => entry.id));
    }).finally(() => {
      if (!ctl.signal.aborted) setCandidatesLoading(false);
    });
    return () => ctl.abort();
  }, [currentInvestigationIds, casesAvailable]);

  const summaries = useMemo(() => cases.map((item) => {
    const currentRun = item.analysis_runs.find((run) => run.id === item.current_run_id);
    return summarizeShiftCase(item, resumes[item.id], currentRun ? investigations[currentRun.investigation_id] : null);
  }), [cases, resumes, investigations]);
  const totals = useMemo(() => shiftTotals(summaries), [summaries]);
  const visible = useMemo(() => visibleShiftCases(summaries, filter, sort, actor, status), [summaries, filter, sort, actor, status]);
  const byId = useMemo(() => new Map(cases.map((item) => [item.id, item])), [cases]);
  const incidentTitles = useMemo(() => new Map([
    ...incidents.map((item) => [item.id, item.title] as const),
    ...Object.entries(extraIncidentTitles),
  ]), [incidents, extraIncidentTitles]);

  if (!casesAvailable) return (
    <section className="shift-workspace" aria-label="교대 워크스페이스">
      <div className="notice danger" role="alert"><TriangleAlert size={17} /> Case 목록을 불러올 수 없습니다. 서버 연결을 확인하고 새로고침해 주세요.</div>
    </section>
  );

  return (
    <section className="shift-workspace" aria-label="교대 워크스페이스">
      <div className="shift-intro panel">
        <div>
          <span className="eyebrow">SHIFT CONTINUITY</span>
          <h2>교대 전체의 미해결 조사를 한곳에서</h2>
          <p>Case별 실제 상태와 최신 인계 기록을 모아 보여줍니다. 주의 사유와 다음 단계는 저장된 Case 값으로 계산합니다.</p>
        </div>
        <label className="shift-actor">담당자 / 교대
          <input aria-label="담당자 / 교대" value={actor} maxLength={80} onChange={(event) => onActorChange(event.target.value)} placeholder="예: Shift B" />
          <small>인증된 신원이 아닌 데모 입력값입니다. 담당 업무와 인계 수신자 이름에 적용됩니다.</small>
        </label>
      </div>

      <dl className="shift-totals" aria-label="교대 전체 요약">
        <div><dt>진행 중 Case</dt><dd>{totals.active_cases}</dd><small>종료되지 않은 사건</small></div>
        <div><dt>확인 필요</dt><dd>{totals.needs_attention_cases}</dd><small>주의 사유가 있는 Case</small></div>
        <div><dt>미해결 업무</dt><dd>{totals.unresolved_open_items}</dd><small>진행 중 Case의 업무</small></div>
        <div><dt>인계 대기</dt><dd>{totals.awaiting_handover}</dd><small>수락 대기 또는 설명 요청</small></div>
        <div><dt>최근 변경</dt><dd>{totals.recently_updated_cases}</dd><small>최근 24시간</small></div>
      </dl>

      <div className="shift-controls panel">
        <div className="shift-filter-list" role="group" aria-label="Case 필터">
          {filters.map((option) => <button key={option.id} type="button" className={filter === option.id ? "shift-filter active" : "shift-filter"} aria-pressed={filter === option.id} onClick={() => setFilter(option.id)}>{option.label}</button>)}
        </div>
        <div className="shift-selects">
          <label>상태
            <select aria-label="Case status" value={status} onChange={(event) => {
              const selected = event.target.value as ShiftStatusFilter;
              setStatus(selected);
              if (selected === "closed") setFilter("all");
            }}>
              <option value="all">모든 상태</option>
              {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>정렬
            <select aria-label="Case sort" value={sort} onChange={(event) => setSort(event.target.value as ShiftSort)}>
              <option value="updated">최근 변경순</option>
              <option value="unresolved">미해결 업무 많은순</option>
              <option value="attention">확인 필요 우선</option>
            </select>
          </label>
        </div>
      </div>

      <div className="shift-list-heading">
        <div><span className="eyebrow">CASES</span><h3>{visible.length}개 Case</h3></div>
        {resumeLoading ? <span role="status"><RefreshCw className="spin" size={15} /> 인계 변경 확인 중</span> : resumeFailures.length ? <span role="status">{resumeFailures.length}개 Case의 인계 변경 정보를 확인하지 못했습니다.</span> : null}
      </div>
      {visible.length === 0 ? <div className="shift-empty panel">이 필터에 해당하는 Case가 없습니다. 다른 필터를 선택하거나 새 사건 분석에서 Case를 생성해 주세요.</div> : (
        <div className="shift-case-grid">
          {visible.map((item) => {
            const handover = item.latest_handover;
            const incidentTitle = incidentTitles.get(item.incident_id);
            return <article className="shift-case-card panel" key={item.case_id} aria-label={`Case ${item.case_id}`}>
              <div className="shift-case-top">
                <div>
                  <span className="eyebrow">CASE · {datasetLabel(item.dataset)}</span>
                  <h3>{incidentTitle || `사건 ${shortId(item.incident_id)}`}</h3>
                  <p>Case {shortId(item.case_id)}</p>
                </div>
                <span className={`case-status ${item.status}`}>{statusLabels[item.status]}</span>
              </div>
              <div className="shift-attention"><strong><TriangleAlert size={14} /> 확인해야 하는 이유</strong>
                <div>{item.attention_reasons.length ? item.attention_reasons.map((reason) => <span className="shift-reason" key={reason}>{attentionLabel(reason)}</span>) : <span className="shift-clear">현재 계산된 주의 사유 없음</span>}</div>
              </div>
              <div className="shift-card-primary">
                <div><small><ListChecks size={14} /> 미해결 업무</small><strong>{item.unresolved_open_items.length}건</strong><span>담당 {item.open_item_assignees.length ? item.open_item_assignees.join(", ") : "미지정"}</span></div>
                <div><small><Clock3 size={14} /> 최근 인계</small><strong>{handover ? handoverStatusLabel[handover.status] : "발행 기록 없음"}</strong><span>{handover ? `${handover.sender} → ${handover.receiver}` : "이전 교대 기록 없음"}</span></div>
                <div><small><Layers3 size={14} /> 현재 분석</small><strong>{item.run_number ? `R${item.run_number} · cutoff ${item.current_run?.diagnosis_time}s` : "기록 없음"}</strong><span>{item.run_count}회 분석</span></div>
              </div>
              <div className="shift-case-footer">
                <p><strong>다음 해야 할 일</strong> {displayText(item.next_action)}</p>
                <div><small>Updated {dateTime(item.updated_at)}</small><button type="button" className="button secondary" onClick={() => { const source = byId.get(item.case_id); if (source) onOpen(source); }}>Case 이어서 조사 <ArrowRight size={15} /></button></div>
              </div>
              <details className="shift-case-details">
                <summary>조사 세부 정보</summary>
                <p className="shift-candidates"><strong>RCA 원인 후보 · 확정 원인 아님</strong> {item.current_candidate_signals === null
                  ? !item.current_run ? "분석 기록 없음" : candidatesLoading ? "RCA 결과 조회 중" : candidateFailures.includes(item.current_run.investigation_id) ? "RCA 결과를 불러오지 못했습니다" : "현재 분석의 RCA 결과 없음"
                  : item.current_candidate_signals.length ? item.current_candidate_signals.join(" · ") : "RCA 후보 없음"}</p>
                <div className="shift-case-columns">
                  <div><h4>인계 세부</h4><p>발행: {handover ? dateTime(handover.published_at) : "기록 없음"}</p><p>인계 후 조사 변경: {item.has_changes_since_handover === null ? "확인 불가" : item.has_changes_since_handover ? "있음" : "없음"}</p><p>새 분석: {item.new_run_since_handover === null ? "확인 불가" : item.new_run_since_handover ? "추가됨" : "없음"} · 변경 기록: {item.recent_changes === null ? "확인 불가" : `${item.recent_changes.length}건`}</p></div>
                  <div><h4>조사 기록</h4><p>원인 가설: {hypothesisLabels.map(([key, label]) => `${label} ${item.hypothesis_summary[key]}`).join(" · ")}</p><p>관찰 기록 {item.observation_count}건 · 최근 {dateTime(item.latest_observation_at)}</p></div>
                </div>
                <p className="shift-technical mono">사건 {item.incident_id} · Case {item.case_id} · 분석 {item.current_run?.id || "없음"}</p>
              </details>
            </article>;
          })}
        </div>
      )}
    </section>
  );
}
