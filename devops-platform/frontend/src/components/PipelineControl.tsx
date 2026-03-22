const STAGES = ["DEV", "QA", "STRESS", "APPROVAL", "DEPLOYMENT", "COMPLETED"] as const;

const STAGE_ICONS: Record<string, string> = {
  DEV: "🔬",
  QA: "🧪",
  STRESS: "⚡",
  APPROVAL: "✅",
  DEPLOYMENT: "🚢",
  COMPLETED: "🎉",
};

type Props = {
  pipelineId: string | null;
  deployKey: string;
  status: string;
  currentStage: string;
  loading: boolean;
  wsConnected: boolean;
  onDeployKey: (v: string) => void;
  onRefresh: () => void;
  onDeploy: () => void;
};

export default function PipelineControl({
  pipelineId,
  deployKey,
  status,
  currentStage,
  loading,
  wsConnected,
  onDeployKey,
  onRefresh,
  onDeploy,
}: Props) {
  const blocked = status === "BLOCKED";
  const failed = status === "FAILED";
  const done = status === "COMPLETED";

  const pillClass = (name: string): string => {
    const up = name.toUpperCase();
    const cur = currentStage.toUpperCase();
    const idx = STAGES.indexOf(up as (typeof STAGES)[number]);
    const curIdx = STAGES.findIndex((s) => cur.includes(s) || s === cur);

    if (blocked) return "stage-pill stage-pill-blocked";
    if (failed) return "stage-pill stage-pill-failed";
    if (done) return "stage-pill stage-pill-completed";
    if (idx >= 0 && curIdx >= 0) {
      if (idx < curIdx) return "stage-pill stage-pill-completed";
      if (idx === curIdx) return "stage-pill stage-pill-active";
    }
    return "stage-pill stage-pill-pending";
  };

  const badgeClass =
    status === "COMPLETED"
      ? "badge badge-completed"
      : status === "BLOCKED" || status === "FAILED"
        ? "badge badge-failed"
        : status === "PENDING"
          ? "badge badge-pending"
          : "badge badge-running";

  return (
    <div className="card" style={{ padding: "1.5rem" }}>
      {/* Card header */}
      <div className="card-header">
        <div className="card-header-icon">⚙️</div>
        <div>
          <h2 className="card-title">Pipeline Control</h2>
          <p style={{ fontSize: "0.7rem", color: "#9a8878", marginTop: "1px" }}>
            Monitor and manage the active pipeline
          </p>
        </div>
      </div>

      {/* Pipeline ID */}
      <div style={{ marginBottom: "1rem" }}>
        <label className="form-label" htmlFor="pipeline-id-field">Pipeline ID</label>
        <input
          id="pipeline-id-field"
          readOnly
          className="input-field input-field-mono"
          style={{ background: "#faf8f5", color: pipelineId ? "#1a1208" : "#b0a090" }}
          value={pipelineId || "—  trigger a pipeline first"}
        />
      </div>

      {/* Deploy key */}
      <div style={{ marginBottom: "1rem" }}>
        <label className="form-label" htmlFor="deploy-key">Deployment API Key</label>
        <div style={{ position: "relative" }}>
          <div style={{ position: "absolute", left: "0.75rem", top: "50%", transform: "translateY(-50%)", color: "#b0a090" }}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
          </div>
          <input
            id="deploy-key"
            className="input-field"
            style={{ paddingLeft: "2.25rem" }}
            placeholder="devops-approver-key"
            type="password"
            value={deployKey}
            onChange={(e) => onDeployKey(e.target.value)}
          />
        </div>
      </div>

      {/* Action buttons */}
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1.25rem" }}>
        <button
          id="refresh-status-btn"
          type="button"
          disabled={loading || !pipelineId}
          onClick={onRefresh}
          className="btn-secondary"
          style={{ flex: 1, justifyContent: "center" }}
        >
          {loading ? (
            <><div className="spinner spinner-dark" />Refreshing…</>
          ) : (
            <><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
            </svg>Refresh Status</>
          )}
        </button>
        <button
          id="trigger-deploy-btn"
          type="button"
          disabled={loading || !deployKey || !pipelineId}
          onClick={onDeploy}
          className="btn-primary"
          style={{ flex: 1, justifyContent: "center" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 16a 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.6 5.21h3a2 2 0 0 1 2 1.71"/>
            <polygon points="22 2 11 13 8 8 2 22"/>
          </svg>
          Deploy
        </button>
      </div>

      {/* Stage pills */}
      <div style={{ marginBottom: "1rem" }}>
        <span className="form-label" style={{ display: "block", marginBottom: "0.625rem" }}>Pipeline Stages</span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
          {STAGES.map((s) => (
            <span key={s} className={pillClass(s)} title={s}>
              <span style={{ marginRight: "0.25rem" }}>{STAGE_ICONS[s]}</span>
              {s}
            </span>
          ))}
        </div>
      </div>

      {/* Current status */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0.625rem 0.875rem",
        background: "#faf8f5",
        borderRadius: "10px",
        border: "1px solid rgba(0,0,0,0.06)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <div className={`ws-dot ${wsConnected ? "ws-dot-connected" : "ws-dot-disconnected"}`} />
          <span style={{ fontSize: "0.75rem", color: "#7a6b5a", fontWeight: 500 }}>
            {wsConnected ? "Live connection" : "Reconnecting…"}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span style={{ fontSize: "0.75rem", color: "#9a8878" }}>Status:</span>
          <span className={badgeClass}>{currentStage || status}</span>
        </div>
      </div>
    </div>
  );
}
