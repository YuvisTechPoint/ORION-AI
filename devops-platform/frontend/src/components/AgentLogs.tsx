import { useEffect, useRef } from "react";

type Line = { ts: string; level: string; message: string; stage?: string };

type Props = {
  lines: Line[];
  connected?: boolean;
};

function levelColor(level: string): string {
  switch (level.toUpperCase()) {
    case "BLOCKED": return "log-line-blocked";
    case "ERROR": return "log-line-error";
    case "WARNING": return "log-line-warning";
    case "INFO": return "log-line-info";
    default: return "log-line-info";
  }
}

function levelPrefix(level: string): string {
  switch (level.toUpperCase()) {
    case "BLOCKED": return "[ BLOCKED ]";
    case "ERROR":   return "[  ERROR  ]";
    case "WARNING": return "[ WARNING ]";
    case "INFO":    return "[  INFO   ]";
    default:        return "[  INFO   ]";
  }
}

function formatTs(ts: string): string {
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts.slice(0, 19);
    return d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts.slice(0, 19);
  }
}

export default function AgentLogs({ lines, connected }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" });
  }, [lines]);

  return (
    <div className="card" style={{ padding: "1.5rem" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" }}>
        <div className="card-header" style={{ marginBottom: 0 }}>
          <div className="card-header-icon">📋</div>
          <div>
            <h2 className="card-title">Agent Log Stream</h2>
            <p style={{ fontSize: "0.7rem", color: "#9a8878", marginTop: "1px" }}>
              Real-time events from all pipeline agents
            </p>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <span style={{
            fontSize: "0.68rem", color: "#7a6b5a",
            background: "#f0ece4", padding: "0.25rem 0.625rem",
            borderRadius: "9999px", fontWeight: 600,
          }}>
            {lines.length} events
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "0.7rem", color: connected ? "#2e7d32" : "#9a8878" }}>
            <div className={`ws-dot ${connected ? "ws-dot-connected" : "ws-dot-disconnected"}`} />
            {connected ? "Streaming" : "Offline"}
          </div>
        </div>
      </div>

      {/* Log area */}
      <div
        ref={ref}
        id="agent-log-viewer"
        className="log-viewer"
        style={{ height: "320px", padding: "1rem" }}
      >
        {lines.length === 0 ? (
          <div style={{ color: "#4a5568", fontStyle: "italic", padding: "0.5rem 0" }}>
            ▶ Waiting for pipeline events… Connect trigger a pipeline to start.
          </div>
        ) : (
          lines.map((l, i) => (
            <div
              key={i}
              className={`${levelColor(l.level)} animate-slide-in`}
              style={{
                marginBottom: "2px",
                padding: "1px 0",
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
              }}
            >
              <span style={{ color: "#6b7280", userSelect: "none" }}>{formatTs(l.ts)} </span>
              <span style={{ fontWeight: 700, userSelect: "none" }}>{levelPrefix(l.level)} </span>
              {l.stage && (
                <span style={{ color: "#9ca3af", userSelect: "none" }}>[{l.stage}] </span>
              )}
              <span>{l.message}</span>
            </div>
          ))
        )}
      </div>

      {/* Legend */}
      <div style={{
        display: "flex", gap: "1.25rem", marginTop: "0.75rem",
        padding: "0.5rem 0",
        borderTop: "1px solid rgba(0,0,0,0.06)",
      }}>
        {[
          { c: "#c9d1d9", l: "INFO" },
          { c: "#f0ad4e", l: "WARNING" },
          { c: "#f87171", l: "ERROR" },
          { c: "#ff6b6b", l: "BLOCKED" },
        ].map(({ c, l }) => (
          <div key={l} style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
            <div style={{ width: "8px", height: "8px", borderRadius: "2px", background: c }} />
            <span style={{ fontSize: "0.68rem", color: "#9a8878", fontWeight: 500 }}>{l}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
