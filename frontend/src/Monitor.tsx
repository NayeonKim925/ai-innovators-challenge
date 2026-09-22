import { useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Eye,
  Pause,
  Play,
  RotateCcw,
  ShieldAlert,
} from "lucide-react";
import {
  api,
  post,
  number,
  type Dataset,
  type DetectionDecision,
  type DetectResponse,
  type Incident,
  type IncidentSummary,
} from "./api";

const message = (e: unknown) =>
  e instanceof Error ? e.message : "요청을 처리하지 못했습니다.";

const DECISION_LABEL: Record<DetectionDecision, string> = {
  trigger_rca: "이상 확정 · 원인분석 실행됨",
  false_positive_review: "알람 발생 · 오탐 여부 확인 필요",
  elevated_watch: "이상 징후 · 집중 관찰 중",
  await_more_data: "정상 관찰 중",
};
const DECISION_TONE: Record<DetectionDecision, "danger" | "warn" | "watch" | "ok"> = {
  trigger_rca: "danger",
  false_positive_review: "warn",
  elevated_watch: "watch",
  await_more_data: "ok",
};
const TICK_MS = 500;

export function Monitor({
  onOpenCase,
}: {
  onOpenCase: (incidentId: string, diagnosisTime: number) => void;
}) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [dataset, setDataset] = useState("causrca");
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [observedUpToS, setObservedUpToS] = useState(0);
  const [speed, setSpeed] = useState(20);
  const [playing, setPlaying] = useState(false);
  const [detection, setDetection] = useState<DetectResponse | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [caseBusy, setCaseBusy] = useState(false);
  const revision = useRef(0);

  useEffect(() => {
    api<{ datasets: Dataset[] }>("/datasets")
      .then((d) => setDatasets(d.datasets))
      .catch(() => setDatasets([]));
  }, []);

  useEffect(() => {
    const ctl = new AbortController();
    setLoading(true);
    setError("");
    setSelected("");
    setIncident(null);
    setDetection(null);
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
  }, [dataset]);

  useEffect(() => {
    if (!selected) return;
    const ctl = new AbortController();
    revision.current++;
    setIncident(null);
    setDetection(null);
    setPlaying(false);
    api<Incident>(`/incidents/${encodeURIComponent(selected)}`, { signal: ctl.signal })
      .then((d) => {
        setIncident(d);
        setObservedUpToS(d.time_range_s.start);
      })
      .catch((e) => {
        if (!ctl.signal.aborted) setError(message(e));
      });
    return () => ctl.abort();
  }, [selected]);

  async function runDetection(upToS: number) {
    if (!incident) return;
    const rev = revision.current;
    setDetecting(true);
    try {
      const result = await post<DetectResponse>(
        `/incidents/${encodeURIComponent(incident.id)}/detect`,
        { observed_up_to_s: upToS },
      );
      if (rev !== revision.current) return;
      setDetection(result);
      if (result.detection.decision === "trigger_rca") setPlaying(false);
    } catch (e) {
      if (rev === revision.current) setError(message(e));
    } finally {
      if (rev === revision.current) setDetecting(false);
    }
  }

  // 재생 시뮬레이션: 준비된 HIL 기록을 시간순으로 배속 재생하며, 매 tick마다
  // 에이전트가 그 시점까지 관측된 신호만으로 재평가한다. 실제 실시간 스트림이
  // 아니라 재생임을 화면에 항상 표기한다 (DESIGN.md의 "가짜 실시간 데이터 지양").
  useEffect(() => {
    if (!playing || !incident) return;
    const id = setInterval(() => {
      setObservedUpToS((current) => {
        const next = Math.min(incident.time_range_s.end, current + speed * (TICK_MS / 1000));
        if (next >= incident.time_range_s.end) setPlaying(false);
        void runDetection(next);
        return next;
      });
    }, TICK_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, incident, speed]);

  if (loading) return <div className="empty">불러오는 중…</div>;
  if (error) return <div className="notice danger">{error}</div>;

  const range = incident?.time_range_s;
  const progressPct = range && range.end > range.start
    ? ((observedUpToS - range.start) / (range.end - range.start)) * 100
    : 0;
  const tone = detection ? DECISION_TONE[detection.detection.decision] : "ok";

  return (
    <div className="monitor">
      <div className="section-heading">
        <div>
          <h3>Monitor · 실시간 이상 탐지 (재생 시뮬레이션)</h3>
          <p>
            준비된 HIL 기록을 시간순으로 재생하며, 알람 활성화와 PCA 이상 점수 두 신호를
            에이전트가 함께 보고 다음 행동을 스스로 결정합니다. 실제 공장 실시간 데이터가
            아니라 causRCA 준비 데이터의 재생입니다.
          </p>
        </div>
      </div>

      <div className="monitor-controls">
        <select value={dataset} onChange={(e) => setDataset(e.target.value)}>
          {(datasets.length ? datasets : [{ dataset: "causrca", status: "", incident_count: 0 }]).map(
            (d) => (
              <option key={d.dataset} value={d.dataset}>
                {d.dataset}
              </option>
            ),
          )}
        </select>
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {incidents.map((i) => (
            <option key={i.id} value={i.id}>
              {i.title} ({i.id.slice(0, 12)})
            </option>
          ))}
        </select>
      </div>

      {incident && range && (
        <>
          <div className="monitor-playback">
            <button
              className="button primary"
              onClick={() => setPlaying((p) => !p)}
              disabled={observedUpToS >= range.end && !playing}
            >
              {playing ? <Pause size={16} /> : <Play size={16} />}
              {playing ? "일시정지" : "재생"}
            </button>
            <button
              className="text-button"
              onClick={() => {
                setPlaying(false);
                setObservedUpToS(range.start);
                setDetection(null);
              }}
            >
              <RotateCcw size={14} />
              처음부터
            </button>
            <label className="monitor-speed">
              배속
              <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                <option value={5}>5x</option>
                <option value={20}>20x</option>
                <option value={60}>60x</option>
                <option value={200}>200x</option>
              </select>
            </label>
            <span className="monitor-position">
              t = {number(observedUpToS, 1)}s / {number(range.end, 1)}s
            </span>
          </div>
          <div className="monitor-progress">
            <div className="monitor-progress-bar" style={{ width: `${progressPct}%` }} />
          </div>
          <input
            type="range"
            min={range.start}
            max={range.end}
            step={0.1}
            value={observedUpToS}
            onChange={(e) => {
              setPlaying(false);
              const v = Number(e.target.value);
              setObservedUpToS(v);
              void runDetection(v);
            }}
          />

          <div className={`monitor-status monitor-status-${tone}`}>
            <div className="monitor-status-icon">
              {tone === "danger" && <ShieldAlert size={20} />}
              {tone === "warn" && <AlertTriangle size={20} />}
              {tone === "watch" && <Eye size={20} />}
              {tone === "ok" && <Activity size={20} />}
            </div>
            <div>
              <strong>
                {detecting
                  ? "에이전트가 재평가하는 중…"
                  : detection
                    ? DECISION_LABEL[detection.detection.decision]
                    : "재생을 시작하면 에이전트가 신호를 관찰합니다."}
              </strong>
              {detection && (
                <p>
                  {detection.detection.onset_time_s !== null &&
                    `알람 활성화 시각 추정: t=${number(detection.detection.onset_time_s, 1)}s. `}
                  {detection.detection.anomaly_score !== null &&
                    detection.detection.anomaly_threshold !== null &&
                    `PCA 이상 점수: ${number(detection.detection.anomaly_score, 2)} (기준선 임계값 ${number(detection.detection.anomaly_threshold, 2)}). `}
                  {detection.detection.anomaly_score === null &&
                    "PCA 이상 신호는 준비되지 않았습니다 (real_op 기준선 미준비 또는 의존성 미설치)."}
                </p>
              )}
            </div>
          </div>

          {detection && detection.detection.evidence.length > 0 && (
            <ul className="monitor-evidence">
              {detection.detection.evidence.map((e) => (
                <li key={e.id}>
                  <strong>{e.title}</strong>
                  <p>{e.detail}</p>
                </li>
              ))}
            </ul>
          )}

          {detection?.investigation && (
            <div className="monitor-preview">
              <h4>원인 후보 (자동 실행됨, 사람 검토 전 우선순위일 뿐)</h4>
              <ol>
                {detection.investigation.candidates.slice(0, 3).map((c) => (
                  <li key={c.signal}>
                    <strong>{c.signal}</strong> — {c.reason}
                  </li>
                ))}
              </ol>
              <button
                className="button primary"
                disabled={caseBusy}
                onClick={async () => {
                  if (!incident || !detection.detection.onset_time_s) return;
                  setCaseBusy(true);
                  try {
                    onOpenCase(incident.id, detection.detection.onset_time_s);
                  } finally {
                    setCaseBusy(false);
                  }
                }}
              >
                조사 시작 (Investigate로 이동)
              </button>
            </div>
          )}

          {detection && !detection.investigation && detection.detection.decision !== "await_more_data" && (
            <p className="monitor-hint">
              에이전트가 아직 원인분석을 자동 실행하지 않았습니다 (
              {detection.detection.decision === "false_positive_review"
                ? "알람과 이상 점수가 서로 다른 결론을 내서 사람의 확인이 필요합니다."
                : "이상 징후는 있지만 아직 알람이 활성화되지 않았습니다."}
              ). 필요하면 재생을 계속하거나, Cases 메뉴에서 직접 진단 시점을 지정해 조사할 수 있습니다.
            </p>
          )}
        </>
      )}
    </div>
  );
}
