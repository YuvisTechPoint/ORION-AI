type Props = {
  artifacts: Record<string, unknown>;
};

const AGENT_CONFIG: Record<string, { icon: string; label: string; color: string }> = {
  code_analysis: { icon: "🔬", label: "Code Analysis", color: "#4a90d9" },
  security:      { icon: "🔒", label: "Security Scan", color: "#e74c3c" },
  qa:            { icon: "🧪", label: "QA Testing",    color: "#27ae60" },
  stress:        { icon: "⚡", label: "Stress Test",   color: "#f39c12" },
  deployment:    { icon: "🚢", label: "Deployment",    color: "#8e44ad" },
  monitoring:    { icon: "📡", label: "Monitoring",    color: "#16a085" },
};

function StageSummary({ stage, data }: { stage: string; data: unknown }) {
  const cfg = AGENT_CONFIG[stage];
  if (!data || typeof data !== "object") return null;
  const d = data as Record<string, unknown>;

  // Extract key metrics per stage
  const metrics: { label: string; value: string | number; highlight?: boolean }[] = [];

  if (stage === "code_analysis" && d.code_analysis) {
    const ca = d.code_analysis as Record<string, unknown>;
    if (ca.code_quality_score != null) metrics.push({ label: "Quality Score", value: `${ca.code_quality_score}/100`, highlight: Number(ca.code_quality_score) >= 60 });
    if (ca.complexity_rating) metrics.push({ label: "Complexity", value: String(ca.complexity_rating) });
    if (Array.isArray(ca.issues)) metrics.push({ label: "Issues", value: ca.issues.length });
  }
  if (stage === "security" && d.security) {
    const sec = d.security as Record<string, unknown>;
    if (sec.overall_risk) metrics.push({ label: "Risk", value: String(sec.overall_risk), highlight: sec.overall_risk === "low" });
    if (Array.isArray(sec.vulnerabilities)) metrics.push({ label: "Findings", value: sec.vulnerabilities.length });
  }
  if (stage === "qa" && d.qa) {
    const qa = d.qa as Record<string, unknown>;
    metrics.push({ label: "Exit Code", value: String(qa.exit_code ?? "?"), highlight: qa.exit_code === 0 });
  }
  if (stage === "stress" && d.stress) {
    const stress = d.stress as Record<string, unknown>;
    const m = stress.metrics as Record<string, unknown> | undefined;
    if (m) {
      if (m.p95_ms != null) metrics.push({ label: "P95", value: `${Number(m.p95_ms).toFixed(0)}ms`, highlight: Number(m.p95_ms) < 2000 });
      if (m.error_rate != null) metrics.push({ label: "Error Rate", value: `${(Number(m.error_rate) * 100).toFixed(1)}%`, highlight: Number(m.error_rate) < 0.05 });
      if (m.rps != null) metrics.push({ label: "RPS", value: Number(m.rps).toFixed(1) });
    }
  }
  if (stage === "deployment" && d.deployment) {
    const dep = d.deployment as Record<string, unknown>;
    if (dep.deployed_tag) metrics.push({ label: "Tag", value: String(dep.deployed_tag) });
    if (dep.rollback_available != null) metrics.push({ label: "Rollback", value: dep.rollback_available ? "Yes" : "No" });
  }
  if (stage === "monitoring" && d.monitoring) {
    const mon = d.monitoring as Record<string, unknown>;
    if (mon.health_status) metrics.push({ label: "Health", value: String(mon.health_status), highlight: mon.health_status === "healthy" });
    if (Array.isArray(mon.anomalies)) metrics.push({ label: "Anomalies", value: mon.anomalies.length });
  }

  return metrics.length > 0 ? (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", padding: "0.625rem 0.875rem 0" }}>
      {metrics.map(({ label, value, highlight }) => (
        <div key={label} style={{
          padding: "0.25rem 0.625rem",
          borderRadius: "6px",
          background: highlight === true ? "#e8f5e9" : highlight === false ? "#ffebee" : "#f0ece4",
          border: `1px solid ${highlight === true ? "#a5d6a7" : highlight === false ? "#ef9a9a" : "rgba(0,0,0,0.08)"}`,
          display: "flex", alignItems: "center", gap: "0.375rem",
        }}>
          <span style={{ fontSize: "0.65rem", color: "#9a8878", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</span>
          <span style={{
            fontSize: "0.75rem", fontWeight: 700,
            color: highlight === true ? "#2e7d32" : highlight === false ? "#c62828" : cfg.color,
            fontFamily: "'JetBrains Mono', monospace",
          }}>{String(value)}</span>
        </div>
      ))}
    </div>
  ) : null;
}

export default function AgentArtifacts({ artifacts }: Props) {
  const keys = ["code_analysis", "security", "qa", "stress", "deployment", "monitoring"];
  const hasAny = keys.some((k) => artifacts[k] != null);

  return (
    <div className="card" style={{ padding: "1.5rem" }}>
      {/* Header */}
      <div className="card-header">
        <div className="card-header-icon">📦</div>
        <div>
          <h2 className="card-title">Agent Artifacts</h2>
          <p style={{ fontSize: "0.7rem", color: "#9a8878", marginTop: "1px" }}>
            Structured output from each pipeline stage
          </p>
        </div>
      </div>

      {!hasAny && (
        <div style={{
          padding: "2rem 1rem",
          textAlign: "center",
          color: "#b0a090",
          fontSize: "0.8rem",
          background: "#faf8f5",
          borderRadius: "10px",
          border: "1px dashed rgba(0,0,0,0.1)",
        }}>
          <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>📂</div>
          Artifacts will appear here as stages complete
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
        {keys.map((k) => {
          const cfg = AGENT_CONFIG[k] || { icon: "📄", label: k, color: "#7a6b5a" };
          const data = artifacts[k];
          const hasData = data != null;

          return (
            <details key={k} id={`artifact-${k}`}>
              <summary>
                <span style={{ marginRight: "0.25rem" }}>{cfg.icon}</span>
                <span style={{ flex: 1 }}>{cfg.label}</span>
                {hasData ? (
                  <span style={{
                    marginLeft: "auto", marginRight: "0.5rem",
                    fontSize: "0.65rem", fontWeight: 700, padding: "1px 6px",
                    borderRadius: "4px", background: "#e8f5e9", color: "#2e7d32",
                  }}>✓ Complete</span>
                ) : (
                  <span style={{
                    marginLeft: "auto", marginRight: "0.5rem",
                    fontSize: "0.65rem", fontWeight: 600, padding: "1px 6px",
                    borderRadius: "4px", background: "#f0ece4", color: "#b0a090",
                  }}>Pending</span>
                )}
              </summary>
              {hasData && <StageSummary stage={k} data={data} />}
              <pre style={{
                maxHeight: "220px",
                overflowY: "auto",
                padding: "0.875rem",
                fontSize: "0.7rem",
                fontFamily: "'JetBrains Mono', monospace",
                color: "#5a4a35",
                background: "transparent",
                lineHeight: 1.6,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                borderTop: "1px solid rgba(0,0,0,0.06)",
              }}>
                {JSON.stringify(data ?? {}, null, 2)}
              </pre>
            </details>
          );
        })}
      </div>
    </div>
  );
}
