import { useState } from "react";
import { api } from "../api/client";
import { STACKS } from "../config/stacks";

const TOOLS = [
  { id: "log_analysis", label: "Log Analysis", agent: "log_analysis" },
  { id: "github_actions", label: "GitHub Actions", agent: "github_actions" },
  { id: "dockerfile", label: "Dockerfile", agent: "dockerfile" },
  { id: "production_triage", label: "Production Triage", agent: "production_triage" },
] as const;

export default function MultimodalTools() {
  const [tool, setTool] = useState<(typeof TOOLS)[number]["id"]>("log_analysis");
  const [text, setText] = useState("");
  const [files, setFiles] = useState<FileList | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  async function analyze() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("agent_type", tool);
      if (text.trim()) fd.append("text_input", text);
      if (files) {
        Array.from(files).forEach((f) => fd.append("files", f));
      }
      if (!text.trim() && (!files || files.length === 0)) {
        throw new Error("Paste text or attach at least one file.");
      }
      const res = await api.post("/api/multimodal/analyze", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(JSON.stringify(res.data.result || res.data, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ padding: "1.5rem" }}>
      <div className="card-header">
        <div className="card-header-icon">🧠</div>
        <div>
          <h2 className="card-title">Intelligence Suite</h2>
          <p style={{ fontSize: "0.7rem", color: "#9a8878" }}>
            Multimodal agents via local ORION proxy ·{" "}
            <a href={STACKS.orion.ui} style={{ color: "#E8832A" }}>
              open full ORION dashboard
            </a>
          </p>
        </div>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "1rem" }}>
        {TOOLS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={tool === t.id ? "btn-primary" : "btn-secondary"}
            onClick={() => setTool(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <textarea
        className="input-field"
        rows={8}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Paste logs, Dockerfile, incident timeline…"
        style={{ fontFamily: "JetBrains Mono, monospace", fontSize: "0.72rem", marginBottom: "0.75rem" }}
      />
      <input type="file" multiple onChange={(e) => setFiles(e.target.files)} style={{ marginBottom: "0.75rem" }} />
      <button type="button" className="btn-primary" disabled={busy} onClick={() => void analyze()} style={{ width: "100%" }}>
        {busy ? "Analyzing…" : "Run agent analysis"}
      </button>
      {error && <div className="toast-error animate-slide-in" style={{ marginTop: "0.75rem" }}>{error}</div>}
      {result && (
        <pre style={{ marginTop: "1rem", padding: "0.875rem", background: "#f8f6f2", fontSize: "0.7rem", overflow: "auto", maxHeight: 320 }}>
          {result}
        </pre>
      )}
    </div>
  );
}
