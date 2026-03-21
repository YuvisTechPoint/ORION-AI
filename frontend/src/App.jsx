import { useEffect, useMemo, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001";

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
  const [logsText, setLogsText] = useState("");
  const [deploymentApiKey, setDeploymentApiKey] = useState("");

  const [state, setState] = useState(null);
  const [monitoring, setMonitoring] = useState(null);
  const [realtimeMonitoring, setRealtimeMonitoring] = useState(true);
  const [lastMonitoringAt, setLastMonitoringAt] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [wsStatus, setWsStatus] = useState("idle");
  const [monitoringWsStatus, setMonitoringWsStatus] = useState("idle");
  const [apiHealth, setApiHealth] = useState(null);
  const monitoringSocketRef = useRef(null);
  const [authStatus, setAuthStatus] = useState({
    authenticated: false,
    username: null,
    has_github_token: false,
    token_valid: false,
  });
  const [userProfile, setUserProfile] = useState(null);

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

  async function checkAuthStatus() {
    try {
      const response = await fetch(`${API_BASE}/auth/status`, { credentials: "include" });
      if (!response.ok) {
        throw new Error(`Auth status failed with ${response.status}`);
      }
      const data = await response.json();
      setAuthStatus(data);

      if (data.authenticated) {
        const meResp = await fetch(`${API_BASE}/auth/me`, { credentials: "include" });
        if (meResp.ok) {
          const profile = await meResp.json();
          setUserProfile(profile);
        }
      } else {
        setUserProfile(null);
      }
    } catch (err) {
      setAuthStatus({ authenticated: false, username: null, has_github_token: false, token_valid: false });
      setUserProfile(null);
      setError((prev) => prev || err.message);
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
    checkAuthStatus();
    const intervalId = window.setInterval(() => {
      checkAuthStatus();
    }, 30000);
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

  async function analyzeLogs(background = false) {
    setError("");
    if (!background) {
      setLoading(true);
    }
    try {
      const payload = { logs: logsText };
      if (pipelineId) {
        payload.pipeline_id = pipelineId;
      }
      const response = await fetch(`${API_BASE}/analyze-logs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(`Analyze logs failed with ${response.status}`);
      }
      const data = await response.json();
      setMonitoring(data);
      setLastMonitoringAt(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err.message);
    } finally {
      if (!background) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    if (!realtimeMonitoring || !logsText.trim()) {
      if (monitoringSocketRef.current) {
        monitoringSocketRef.current.close();
        monitoringSocketRef.current = null;
      }
      setMonitoringWsStatus("idle");
      return undefined;
    }

    const wsBase = API_BASE.replace(/^http/, "ws");
    const socket = new WebSocket(`${wsBase}/ws/analyze-logs`);
    monitoringSocketRef.current = socket;
    setMonitoringWsStatus("connecting");

    socket.onopen = () => {
      setMonitoringWsStatus("connected");
      socket.send(
        JSON.stringify({
          pipeline_id: pipelineId || null,
          logs: logsText,
          multimodal_inputs: [],
        })
      );
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "monitoring_result") {
          setMonitoring(payload.result);
          setLastMonitoringAt(new Date().toLocaleTimeString());
        }
        if (payload.type === "error") {
          setError(payload.message || "Monitoring websocket error");
        }
      } catch {
        setMonitoringWsStatus("error");
      }
    };

    socket.onerror = () => setMonitoringWsStatus("error");
    socket.onclose = () => setMonitoringWsStatus("disconnected");

    return () => {
      socket.close();
      if (monitoringSocketRef.current === socket) {
        monitoringSocketRef.current = null;
      }
    };
  }, [realtimeMonitoring]);

  useEffect(() => {
    const socket = monitoringSocketRef.current;
    if (!realtimeMonitoring || !socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    if (!logsText.trim()) {
      return;
    }

    socket.send(
      JSON.stringify({
        pipeline_id: pipelineId || null,
        logs: logsText,
        multimodal_inputs: [],
      })
    );
  }, [logsText, pipelineId, realtimeMonitoring]);

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
          <span className="ws-badge">MON: {monitoringWsStatus}</span>
        </div>
        <div className="auth-row">
          {authStatus.authenticated ? (
            <div className="auth-in">
              <img
                src={userProfile?.avatar || "https://avatars.githubusercontent.com/u/9919?v=4"}
                alt="avatar"
                className="user-avatar"
                width={34}
                height={34}
              />
              <div className="auth-text">
                <span className="auth-name">@{authStatus.username || userProfile?.username}</span>
                <span className="auth-subtext">GitHub token ready</span>
              </div>
              <a className="btn-logout" href={`${API_BASE}/auth/logout`}>
                Logout
              </a>
            </div>
          ) : (
            <a className="btn-github-login" href={`${API_BASE}/auth/github`}>
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                width="16"
                height="16"
                fill="currentColor"
              >
                <path d="M12 .5C5.648.5.5 5.648.5 12c0 5.088 3.292 9.388 7.865 10.905.575.1.785-.245.785-.547 0-.27-.01-.985-.015-1.934-3.2.695-3.88-1.543-3.88-1.543-.523-1.33-1.277-1.685-1.277-1.685-1.044-.714.08-.7.08-.7 1.155.08 1.764 1.186 1.764 1.186 1.027 1.76 2.695 1.252 3.353.958.103-.744.402-1.252.73-1.54-2.554-.29-5.238-1.277-5.238-5.683 0-1.256.45-2.284 1.186-3.09-.12-.29-.515-1.46.11-3.04 0 0 .965-.31 3.164 1.18a11.02 11.02 0 0 1 2.88-.39c.975.005 1.955.132 2.873.39 2.198-1.49 3.162-1.18 3.162-1.18.626 1.58.232 2.75.114 3.04.74.806 1.185 1.834 1.185 3.09 0 4.416-2.688 5.39-5.252 5.673.413.355.78 1.055.78 2.13 0 1.54-.014 2.78-.014 3.156 0 .306.208.654.79.542C20.212 21.384 23.5 17.084 23.5 12 23.5 5.648 18.352.5 12 .5Z" />
              </svg>
              Login with GitHub
            </a>
          )}
        </div>
      </header>

      {!authStatus.authenticated && (
        <div className="auth-banner">
          <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
            <path d="M11.001 3.003a2 2 0 0 1 1.998 0l8.485 4.9a2 2 0 0 1 .998 1.732v9.8a2 2 0 0 1-1 1.732l-8.485 4.9a2 2 0 0 1-2 0l-8.5-4.9a2 2 0 0 1-1-1.732v-9.8a2 2 0 0 1 1-1.732zM12 5.135 4 9.7v8.6l8 4.565 8-4.565V9.7L12 5.135Zm-1 4.365h2v5h-2zm0 6h2v2h-2z" />
          </svg>
          <span>
            You are not logged in with GitHub. Auto-PR features require GitHub authentication. <a href={`${API_BASE}/auth/github`}>Login now →</a>
          </span>
        </div>
      )}

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
          <textarea
            rows={6}
            value={logsText}
            onChange={(e) => setLogsText(e.target.value)}
            placeholder="Paste runtime logs here for analysis..."
          />
          <label style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <input
              type="checkbox"
              checked={realtimeMonitoring}
              onChange={(e) => setRealtimeMonitoring(e.target.checked)}
            />
            Real-time analysis (5s)
          </label>
          <button onClick={analyzeLogs} disabled={loading}>
            Analyze Logs
          </button>
          {monitoring && (
            <div className="result-block">
              <strong>{monitoring.summary}</strong>
              <p>Anomalies: {monitoring.anomalies.join(" | ") || "none"}</p>
              <p>Suggestions: {monitoring.suggestions.join(" | ") || "none"}</p>
              <p>Last analyzed: {lastMonitoringAt || "just now"}</p>
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
