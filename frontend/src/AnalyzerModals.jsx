import { useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const TITLES = {
  git: "Git Log Analyzer",
  pay: "Payment Analyzer",
  log: "Log Analyzer",
  docker: "Dockerfile Analyzer",
  triage: "Production Triage",
  github: "GitHub Actions Log",
};

function FileDrop({ files, setFiles, accept, hint }) {
  const inputRef = useRef(null);
  return (
    <div>
      <button
        type="button"
        className="dropzone"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          setFiles(Array.from(e.dataTransfer.files || []));
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 4 }}>{hint}</div>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{accept}</div>
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={accept}
        style={{ display: "none" }}
        onChange={(e) => setFiles(Array.from(e.target.files || []))}
      />
      <div className="file-list">
        {files.map((file) => (
          <div key={file.name} className="file-item">
            {file.name}
          </div>
        ))}
      </div>
    </div>
  );
}

function appendTextAsFile(fd, text) {
  if (!text.trim()) return;
  fd.append("files", new Blob([text], { type: "text/plain" }), "pasted.txt");
}

export default function AnalyzerModals({ open, onClose }) {
  const [gitText, setGitText] = useState("");
  const [gitFiles, setGitFiles] = useState([]);
  const [useGh, setUseGh] = useState(false);
  const [repo, setRepo] = useState("");
  const [branch, setBranch] = useState("main");
  const [prNumber, setPrNumber] = useState("");
  const [commitSha, setCommitSha] = useState("");
  const [logLimit, setLogLimit] = useState("30");
  const [payText, setPayText] = useState("");
  const [payFiles, setPayFiles] = useState([]);
  const [genericText, setGenericText] = useState("");
  const [genericFiles, setGenericFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  if (!open) return null;

  async function run() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const fd = new FormData();
      let path = "";

      if (open === "git") {
        fd.append("text_input", gitText);
        fd.append("use_gh_cli", useGh ? "true" : "false");
        fd.append("repo_full_name", repo);
        fd.append("branch", branch);
        fd.append("commit_sha", commitSha);
        fd.append("log_limit", logLimit);
        if (prNumber) fd.append("pr_number", prNumber);
        gitFiles.forEach((file) => fd.append("files", file));
        path = "/api/v1/multimodal/git-logs";
      } else if (open === "pay") {
        fd.append("text_input", payText);
        payFiles.forEach((file) => fd.append("files", file));
        path = "/api/v1/multimodal/payment";
      } else if (open === "log") {
        let logType = "server_timeout";
        if (genericText.trim()) {
          const pre = await fetch(`${API_BASE}/api/v1/tools/text-analyze`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ text: genericText, operations: ["classify_log"] }),
          });
          if (pre.ok) {
            const body = await pre.json();
            if (body.log_type) logType = body.log_type;
          }
        }
        fd.append("agent_type", "log_analysis");
        fd.append("log_type", logType);
        genericFiles.forEach((file) => fd.append("files", file));
        appendTextAsFile(fd, genericText);
        path = "/api/v1/multimodal/analyze";
      } else if (open === "docker") {
        fd.append("agent_type", "dockerfile");
        genericFiles.forEach((file) => fd.append("files", file));
        appendTextAsFile(fd, genericText);
        path = "/api/v1/multimodal/analyze";
      } else if (open === "triage") {
        genericFiles.forEach((file) => fd.append("files", file));
        appendTextAsFile(fd, genericText);
        path = "/api/v1/multimodal/triage";
      } else if (open === "github") {
        fd.append("agent_type", "github_actions");
        genericFiles.forEach((file) => fd.append("files", file));
        appendTextAsFile(fd, genericText);
        path = "/api/v1/multimodal/analyze";
      } else {
        throw new Error("Unknown analyzer");
      }

      const resp = await fetch(`${API_BASE}${path}`, { method: "POST", body: fd, credentials: "include" });
      const data = await (resp.headers.get("content-type")?.includes("application/json") ? resp.json() : resp.text());
      if (!resp.ok) {
        throw new Error(typeof data === "string" ? data : data.detail || JSON.stringify(data));
      }
      setResult(data);
    } catch (err) {
      setError(err.message || "Analysis failed");
    } finally {
      setBusy(false);
    }
  }

  const isGeneric = open === "log" || open === "docker" || open === "triage" || open === "github";

  return (
    <div className="modal-overlay" style={{ display: "flex" }} role="dialog">
      <div className="modal-container">
        <div className="modal-header">
          <div className="issue-title">{TITLES[open] || "Analyzer"}</div>
          <button className="modal-close" type="button" onClick={onClose}>
            x
          </button>
        </div>
        <div className="modal-body">
          {open === "git" ? (
            <>
              <FileDrop files={gitFiles} setFiles={setGitFiles} accept=".log,.txt,.zip,.png,.jpg,.jpeg,.csv" hint="Drop logs, screenshots, or ZIP files" />
              <textarea className="log-textarea" rows={8} value={gitText} onChange={(e) => setGitText(e.target.value)} placeholder="Paste logs here" />
              <label className="label-inline">
                <input type="checkbox" checked={useGh} onChange={(e) => setUseGh(e.target.checked)} />
                Fetch logs with GH CLI
              </label>
              {useGh && (
                <div className="field-group">
                  <input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="owner/repo" />
                  <input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="branch" />
                  <input value={prNumber} onChange={(e) => setPrNumber(e.target.value)} placeholder="PR #" />
                  <input value={commitSha} onChange={(e) => setCommitSha(e.target.value)} placeholder="commit sha" />
                  <input value={logLimit} onChange={(e) => setLogLimit(e.target.value)} placeholder="limit" />
                </div>
              )}
            </>
          ) : open === "pay" ? (
            <>
              <FileDrop files={payFiles} setFiles={setPayFiles} accept=".csv,.png,.jpg,.jpeg,.pdf,.json" hint="Drop CSVs, dashboards, or webhook JSON" />
              <textarea className="log-textarea" rows={8} value={payText} onChange={(e) => setPayText(e.target.value)} placeholder="Paste payment logs or webhook JSON" />
            </>
          ) : (
            <>
              <FileDrop
                files={genericFiles}
                setFiles={setGenericFiles}
                accept={open === "docker" ? ".dockerfile,Dockerfile,.txt,.log" : ".log,.txt,.png,.jpg,.jpeg,.zip,.csv"}
                hint={open === "docker" ? "Drop Dockerfile or build logs" : "Drop logs, screenshots, or incident artifacts"}
              />
              <textarea
                className="log-textarea"
                rows={8}
                value={genericText}
                onChange={(e) => setGenericText(e.target.value)}
                placeholder={open === "triage" ? "Paste incident timeline, alerts, or error output" : "Paste text to analyze"}
              />
            </>
          )}
          {error && <div className="modal-error">{error}</div>}
          {result && <pre className="results-container">{JSON.stringify(result, null, 2)}</pre>}
        </div>
        <div className="modal-footer">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Close
          </button>
          <button type="button" className="btn-primary" disabled={busy} onClick={run}>
            {busy ? "Analyzing..." : "Analyze with AI"}
          </button>
        </div>
      </div>
    </div>
  );
}
