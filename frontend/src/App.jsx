import { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const STAGE_ORDER = ["dev", "qa", "stress", "approval", "deployment", "completed"];

function StageTimeline({ currentStage }) {
  return (
    <div className="timeline">
      {STAGE_ORDER.map((stage) => {
        const currentIndex = STAGE_ORDER.indexOf(currentStage);
        const stageIndex = STAGE_ORDER.indexOf(stage);
        const active = stageIndex <= currentIndex;
        return (
          <div key={stage} className={`stage-chip ${active ? "active" : ""}`}>
            {stage.toUpperCase()}
          </div>
        );
      })}
    </div>
  );
}

function formatMessage(entry) {
  return `${entry.ts} | ${entry.stage.toUpperCase()} | ${entry.message}`;
}

export default function App() {
  const [pipelineId, setPipelineId] = useState("");
  const [repoName, setRepoName] = useState("payment-service");
  const [repoUrl, setRepoUrl] = useState("");
  const [codeText, setCodeText] = useState("");
  const [diffText, setDiffText] = useState("- insecure_call()\n+ secure_call()");
  const [logsText, setLogsText] = useState("2026-03-21T10:12:06Z ERROR timeout connecting to db");
  const [deploymentApiKey, setDeploymentApiKey] = useState("");

  const [state, setState] = useState(null);
  const [monitoring, setMonitoring] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [wsStatus, setWsStatus] = useState("idle");
  const [apiHealth, setApiHealth] = useState(null);

  const agentArtifacts = useMemo(() => {
    if (!state?.artifacts) {
      return [];
    }
    return Object.entries(state.artifacts);
  }, [state]);

  // file upload and archive UI removed — GitHub-only flow

  async function submitGithub() {
    setError("");
    if (!repoUrl) {
      setError("Enter a GitHub repository URL first.");
      return;
    }

    // Client-side validation: only allow GitHub repo links
    const githubRe = /^(?:https?:\/\/)?(?:www\.)?github\.com[:\/]+[^\/\s]+\/[\w.\-]+(?:\.git)?(?:\/.*)?$/i;
    if (!githubRe.test(repoUrl.trim())) {
      setError("Please enter a valid GitHub repository URL (github.com/owner/repo)");
      return;
    }

    // normalize: ensure scheme exists for backend comfort
    let normalized = repoUrl.trim();
    if (!normalized.startsWith("http://") && !normalized.startsWith("https://")) {
      normalized = "https://" + normalized;
    }
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("repo_url", normalized);
      fd.append("branch", "main");
      const resp = await fetch(`${API_BASE}/submit-github?force_real=true`, {
        method: "POST",
        body: fd,
      });
      const data = await (resp.headers.get("content-type")?.includes("application/json") ? resp.json() : resp.text());
      if (!resp.ok) {
        const message = typeof data === "string" ? data : data.detail || JSON.stringify(data);
        throw new Error(`Submit failed: ${message}`);
      }
      setPipelineId(data.pipeline_id);
      await fetchStatus(data.pipeline_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function submitCode() {
    setError("");
    const hasUploadedFiles = Object.keys(repoFiles).length > 0;
    const effectiveCode = codeText || Object.values(repoFiles)[0] || "";
    if (!effectiveCode) {
      setError("Upload at least one code file before submitting.");
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/submit-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_name: repoName,
          code: effectiveCode,
          diff: diffText,
          config_text: configText,
          repo_files: hasUploadedFiles ? repoFiles : undefined,
        }),
      });
      if (!response.ok) {
        throw new Error(`Submit failed with ${response.status}`);
      }
      const data = await response.json();
      setPipelineId(data.pipeline_id);
      await fetchStatus(data.pipeline_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function fetchStatus(id = pipelineId, background = false) {
    if (!id) {
      setError("Provide a pipeline id first.");
      return;
    }
    setError("");
    if (!background) {
      setLoading(true);
    }
    try {
      const response = await fetch(`${API_BASE}/pipeline-status/${id}`);
      if (!response.ok) {
        throw new Error(`Status failed with ${response.status}`);
      }
      const data = await response.json();
      setState(data);
    } catch (err) {
      setError(err.message);
    } finally {
      if (!background) {
        setLoading(false);
      }
    }
  }

  async function fetchHealth(background = false) {
    if (!background) {
      setLoading(true);
    }
    try {
      const response = await fetch(`${API_BASE}/health`);
      if (!response.ok) {
        throw new Error(`Health check failed with ${response.status}`);
      }
      const data = await response.json();
      setApiHealth(data);
    } catch (err) {
      setError(err.message);
    } finally {
      if (!background) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    fetchHealth(true);
    const intervalId = window.setInterval(() => {
      fetchHealth(true);
    }, 15000);
    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    if (!pipelineId) {
      return undefined;
    }
    const intervalId = window.setInterval(() => {
      fetchStatus(pipelineId, true);
    }, 5000);
    return () => window.clearInterval(intervalId);
  }, [pipelineId]);

  useEffect(() => {
    if (!pipelineId) {
      setWsStatus("idle");
      return undefined;
    }

    const wsBase = API_BASE.replace(/^http/, "ws");
    const socket = new WebSocket(`${wsBase}/ws/pipeline-status/${pipelineId}`);
    setWsStatus("connecting");

    socket.onopen = () => setWsStatus("connected");
    socket.onclose = () => setWsStatus("disconnected");
    socket.onerror = () => setWsStatus("error");
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "snapshot") {
          setState((prev) => {
            if (!prev) {
              return {
                pipeline_id: payload.pipeline_id,
                current_stage: payload.stage,
                status: payload.status,
                history: payload.history || [],
                artifacts: {},
              };
            }
            return {
              ...prev,
              current_stage: payload.stage,
              status: payload.status,
              history: payload.history || prev.history,
            };
          });
          return;
        }

        if (payload.type === "pipeline_stage") {
          fetchStatus(pipelineId, true);
        }
      } catch {
        setWsStatus("error");
      }
    };

    return () => socket.close();
  }, [pipelineId]);

  async function triggerDeployment() {
    if (!pipelineId) {
      setError("Provide a pipeline id first.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/trigger-deployment`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(deploymentApiKey ? { "X-API-Key": deploymentApiKey } : {}),
        },
        body: JSON.stringify({ pipeline_id: pipelineId, approved_by: "dashboard" }),
      });
      if (!response.ok) {
        throw new Error(`Trigger deployment failed with ${response.status}`);
      }
      const data = await response.json();
      setState(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function analyzeLogs() {
    if (!pipelineId) {
      setError("Provide a pipeline id first.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/analyze-logs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pipeline_id: pipelineId, logs: logsText }),
      });
      if (!response.ok) {
        throw new Error(`Analyze logs failed with ${response.status}`);
      }
      const data = await response.json();
      setMonitoring(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="shell">
      <header className="hero">
        <h1>DevOps Agent Console</h1>
        <p>Pipeline status, stage timeline, and agent outputs in one place.</p>
        <div className="meta-row">
          <span className={`health-badge ${apiHealth?.status === "ok" ? "ok" : "bad"}`}>
            API: {apiHealth?.status || "unknown"}
          </span>
          <span className="ws-badge">WS: {wsStatus}</span>
        </div>
      </header>

      <section className="grid">
        <article className="panel">
          <h2>Pipeline Input</h2>
          <label>Repository</label>
          <input value={repoName} onChange={(e) => setRepoName(e.target.value)} />
          <label>Fetch from public GitHub</label>
          <input value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/owner/repo" />
          <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
            <button onClick={submitGithub} disabled={loading || !repoUrl}>
              Fetch GitHub Repo & Run
            </button>
          </div>
        </article>

        <article className="panel">
          <h2>Pipeline Control</h2>
          <label>Pipeline ID</label>
          <input value={pipelineId} onChange={(e) => setPipelineId(e.target.value)} />
          <label>Deployment API Key</label>
          <input
            value={deploymentApiKey}
            onChange={(e) => setDeploymentApiKey(e.target.value)}
            placeholder="devops-approver-key"
          />
          <div className="button-row">
            <button onClick={() => fetchStatus()} disabled={loading}>
              Refresh Status
            </button>
            <button onClick={triggerDeployment} disabled={loading}>
              Trigger Deployment
            </button>
          </div>
          {state && (
            <>
              <div className="status-row">
                <span className={`badge ${state.status}`}>{state.status.toUpperCase()}</span>
                <span>Current stage: {state.current_stage.toUpperCase()}</span>
              </div>
              <StageTimeline currentStage={state.current_stage} />
            </>
          )}
        </article>

        <article className="panel wide">
          <h2>Agent Logs</h2>
          <div className="logs-box">
            {state?.history?.length
              ? state.history.map((entry, idx) => <div key={idx}>{formatMessage(entry)}</div>)
              : "No logs yet."}
          </div>
        </article>

        <article className="panel">
          <h2>Monitoring</h2>
          <label>Runtime Logs</label>
          <textarea rows={6} value={logsText} onChange={(e) => setLogsText(e.target.value)} />
          <button onClick={analyzeLogs} disabled={loading}>
            Analyze Logs
          </button>
          {monitoring && (
            <div className="result-block">
              <strong>{monitoring.summary}</strong>
              <p>Anomalies: {monitoring.anomalies.join(" | ") || "none"}</p>
              <p>Suggestions: {monitoring.suggestions.join(" | ") || "none"}</p>
            </div>
          )}
        </article>

        <article className="panel">
          <h2>Agent Artifacts</h2>
          <div className="artifact-list">
            {agentArtifacts.length
              ? agentArtifacts.map(([name, value]) => (
                  <details key={name}>
                    <summary>{name}</summary>
                    <pre>{JSON.stringify(value, null, 2)}</pre>
                  </details>
                ))
              : "No artifacts yet."}
          </div>
        </article>
      </section>

      {error && <div className="error">{error}</div>}
    </main>
  );
}
