type Props = {
  logs: string;
  onLogs: (v: string) => void;
  onAnalyze: () => void;
  loading: boolean;
  result: string | null;
  pipelineId: string | null;
};

export default function Monitoring({ logs, onLogs, onAnalyze, loading, result, pipelineId }: Props) {
  const parsed = (() => {
    if (!result) return null;
    try { return JSON.parse(result); } catch { return null; }
  })();

  const healthColor = (status: string) => {
    if (status === "healthy") return { bg: "#e8f5e9", color: "#2e7d32", border: "#a5d6a7" };
    if (status === "degraded") return { bg: "#fff3e0", color: "#e65100", border: "#ffb74d" };
    return { bg: "#ffebee", color: "#c62828", border: "#ef9a9a" };
  };

  return (
    <div className="card" style={{ padding: "1.5rem" }}>
      {/* Header */}
      <div className="card-header">
        <div className="card-header-icon">📡</div>
        <div>
          <h2 className="card-title">Monitoring &amp; Analysis</h2>
          <p style={{ fontSize: "0.7rem", color: "#9a8878", marginTop: "1px" }}>
            Paste runtime logs for AI anomaly detection
          </p>
        </div>
      </div>

      {/* Textarea */}
      <div style={{ marginBottom: "1rem" }}>
        <label className="form-label" htmlFor="monitor-logs-input">Runtime Log Lines</label>
        <textarea
          id="monitor-logs-input"
          className="input-field"
          style={{
            height: "160px",
            resize: "vertical",
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: "0.72rem",
            lineHeight: 1.6,
          }}
          placeholder={"2024-01-15 10:23:45 INFO  Application started\n2024-01-15 10:23:46 INFO  Health check OK\n2024-01-15 10:24:00 WARN  Response time elevated: 1250ms\n2024-01-15 10:24:15 ERROR Connection timeout to database"}
          value={logs}
          onChange={(e) => onLogs(e.target.value)}
        />
      </div>

      {/* Analyze button */}
      <button
        id="analyze-logs-btn"
        type="button"
        disabled={loading || !logs.trim() || !pipelineId}
        onClick={onAnalyze}
        className="btn-primary"
        style={{ width: "100%", justifyContent: "center", padding: "0.75rem" }}
      >
        {loading ? (
          <><div className="spinner" />Analyzing with AI…</>
        ) : (
          <>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            Analyze Logs with AI
          </>
        )}
      </button>

      {/* Results */}
      {parsed && (
        <div style={{ marginTop: "1rem" }} className="animate-fade-in">
          {/* Health status banner */}
          {parsed.health_status && (() => {
            const { bg, color, border } = healthColor(parsed.health_status);
            return (
              <div style={{
                background: bg, color, border: `1px solid ${border}`,
                borderRadius: "10px", padding: "0.625rem 0.875rem",
                marginBottom: "0.875rem",
                display: "flex", alignItems: "center", gap: "0.5rem",
              }}>
                <span style={{ fontSize: "1rem" }}>
                  {parsed.health_status === "healthy" ? "✅" : parsed.health_status === "degraded" ? "⚠️" : "🚨"}
                </span>
                <div>
                  <div style={{ fontWeight: 700, fontSize: "0.8rem" }}>
                    System Health: {parsed.health_status.toUpperCase()}
                  </div>
                  {parsed.summary && (
                    <div style={{ fontSize: "0.72rem", opacity: 0.8, marginTop: "2px" }}>{parsed.summary}</div>
                  )}
                </div>
              </div>
            );
          })()}

          {/* Alerts */}
          {parsed.alerts && parsed.alerts.length > 0 && (
            <div style={{ marginBottom: "0.875rem" }}>
              <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#7a6b5a", marginBottom: "0.5rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Active Alerts
              </div>
              {parsed.alerts.map((a: string, i: number) => (
                <div key={i} style={{
                  padding: "0.5rem 0.75rem",
                  background: "#fff3e0",
                  border: "1px solid #ffb74d",
                  borderRadius: "8px",
                  marginBottom: "0.375rem",
                  fontSize: "0.78rem",
                  color: "#e65100",
                  display: "flex", alignItems: "flex-start", gap: "0.5rem",
                }}>
                  <span>⚠️</span>
                  <span>{a}</span>
                </div>
              ))}
            </div>
          )}

          {/* Anomalies */}
          {parsed.anomalies && parsed.anomalies.length > 0 && (
            <div style={{ marginBottom: "0.875rem" }}>
              <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#7a6b5a", marginBottom: "0.5rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Anomalies ({parsed.anomalies.length})
              </div>
              {parsed.anomalies.slice(0, 5).map((a: Record<string, string>, i: number) => (
                <div key={i} style={{
                  padding: "0.5rem 0.75rem",
                  background: "#faf8f5",
                  border: "1px solid rgba(0,0,0,0.08)",
                  borderRadius: "8px",
                  marginBottom: "0.375rem",
                  fontSize: "0.75rem",
                }}>
                  <span style={{
                    display: "inline-block", padding: "1px 6px", borderRadius: "4px",
                    fontSize: "0.65rem", fontWeight: 700, marginRight: "0.5rem",
                    background: a.severity === "high" ? "#ffebee" : a.severity === "medium" ? "#fff3e0" : "#e8f5e9",
                    color: a.severity === "high" ? "#c62828" : a.severity === "medium" ? "#e65100" : "#2e7d32",
                  }}>
                    {(a.severity || "low").toUpperCase()}
                  </span>
                  {a.pattern || a.description}
                </div>
              ))}
            </div>
          )}

          {/* Raw JSON toggle */}
          <details style={{ marginTop: "0.5rem" }}>
            <summary style={{ fontSize: "0.75rem" }}>
              Raw JSON Response
            </summary>
            <pre style={{
              padding: "0.875rem",
              background: "#f8f6f2",
              fontSize: "0.7rem",
              color: "#5a4a35",
              overflowX: "auto",
              maxHeight: "200px",
              fontFamily: "'JetBrains Mono', monospace",
              borderTop: "1px solid rgba(0,0,0,0.06)",
            }}>
              {result}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}
