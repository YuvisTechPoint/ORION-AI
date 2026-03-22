import { useEffect, useMemo, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const STAGE_KEYS = ["dev", "qa", "stress", "approval", "deployment", "monitoring", "completed"];
const STAGE_LABELS = ["DEV", "QA", "STRESS", "APPROVAL", "DEPLOYMENT", "MONITORING", "COMPLETED"];

function StageTimeline({ currentStage, status }) {
  const norm = (s) => (s || "").toLowerCase();
  const cur = STAGE_KEYS.indexOf(norm(currentStage));
  const currentIdx = cur >= 0 ? cur : -1;
  const lastIdx = STAGE_KEYS.length - 1;
  const st = (status || "").toLowerCase();

  return (
    <div className="stage-timeline">
      {STAGE_KEYS.map((key, i) => {
        let nodeState = "pending";
        if (currentIdx >= 0 && st) {
          if (i < currentIdx) {
            nodeState = "passed";
          } else if (i > currentIdx) {
            nodeState = "pending";
          } else {
            if (st === "failed") nodeState = "failed";
            else if (st === "blocked") nodeState = "blocked";
            else if (st === "running") nodeState = "running";
            else if (st === "completed") nodeState = "passed";
            else nodeState = "running";
          }
        }

        const chip =
          nodeState === "passed"
            ? "OK"
            : nodeState === "running"
              ? "RUN"
              : nodeState === "failed"
                ? "FAIL"
                : nodeState === "blocked"
                  ? "HOLD"
                  : "—";

        const chipClass =
          nodeState === "passed"
            ? "stage-chip stage-chip--ok"
            : nodeState === "running"
              ? "stage-chip stage-chip--run"
              : nodeState === "failed"
                ? "stage-chip stage-chip--fail"
                : nodeState === "blocked"
                  ? "stage-chip stage-chip--hold"
                  : "stage-chip stage-chip--idle";

        const isLast = i === lastIdx;

        return (
          <div key={key} className={`stage-row${isLast ? " stage-row--last" : ""}`}>
            <div className={`stage-node node-${nodeState}`} aria-hidden="true">
              {nodeState === "passed" && (
                <svg width="8" height="8" viewBox="0 0 8 8" fill="none" aria-hidden="true">
                  <path d="M1.5 4L3.2 5.7 6.5 1.5" stroke="white" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
              {nodeState === "failed" && (
                <svg width="8" height="8" viewBox="0 0 8 8" fill="none" aria-hidden="true">
                  <path d="M1.5 1.5L6.5 6.5M6.5 1.5L1.5 6.5" stroke="white" strokeWidth="1.4" strokeLinecap="round" />
                </svg>
              )}
            </div>
            <span className="stage-label">{STAGE_LABELS[i]}</span>
            <span className={chipClass}>{chip}</span>
          </div>
        );
      })}
    </div>
  );
}

function inferLogLevel(message) {
  const m = (message || "").toUpperCase();
  if (m.includes("BLOCKED")) return "BLOCKED";
  if (m.includes("ERROR") || m.includes("FATAL")) return "ERROR";
  if (m.includes("WARN")) return "WARN";
  return "INFO";
}

function LogLine({ entry }) {
  const level = inferLogLevel(entry.message);
  return (
    <div className="log-line">
      <span className="log-ts">{entry.ts}</span>
      <span className={`log-badge log-badge--${level.toLowerCase()}`}>{level}</span>
      <span className="log-msg">
        <span className="log-stage">{entry.stage?.toUpperCase()}</span> {entry.message}
      </span>
    </div>
  );
}

function BrandHexLogo() {
  return (
    <svg className="brand-hex" width="36" height="36" viewBox="0 0 36 36" aria-hidden="true">
      <g transform="translate(18 18)">
        <polygon points="0,-15 13,-7.5 13,7.5 0,15 -13,7.5 -13,-7.5" fill="none" />
        <path d="M0 0L0-15L13-7.5Z" fill="var(--orange-primary)" />
        <path d="M0 0L13-7.5L13 7.5Z" fill="var(--orange-deep)" />
        <path d="M0 0L13 7.5L0 15Z" fill="var(--orange-primary)" />
        <path d="M0 0L0 15L-13 7.5Z" fill="var(--orange-deep)" />
        <path d="M0 0L-13 7.5L-13-7.5Z" fill="var(--orange-primary)" />
        <path d="M0 0L-13-7.5L0-15Z" fill="var(--orange-deep)" />
      </g>
    </svg>
  );
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
      fd.append("enable_auto_pr", "false");
      const resp = await fetch(`${API_BASE}/submit-github?force_real=true`, {
        method: "POST",
        body: fd,
        credentials: "include",
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
        credentials: "include",
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
      const response = await fetch(`${API_BASE}/api/v1/auth/status`, { credentials: "include" });
      if (!response.ok) {
        throw new Error(`Auth status failed with ${response.status}`);
      }
      const data = await response.json();
      setAuthStatus(data);

      if (data.authenticated) {
        const meResp = await fetch(`${API_BASE}/api/v1/auth/me`, { credentials: "include" });
        if (meResp.ok) {
          const profile = await meResp.json();
          setUserProfile(profile);
        }
      } else {
        setUserProfile(null);
      }
    } catch {
      // Silently fail — backend may be unavailable; don't pollute the main error state
      setAuthStatus({ authenticated: false, username: null, has_github_token: false, token_valid: false });
      setUserProfile(null);
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
        credentials: "include",
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
        credentials: "include",
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
    <div className="app-wrap">
      <main className="shell">
        <header className="hero">
          <div className="hero-grid">
            <div className="hero-brand">
              <BrandHexLogo />
              <h1>DevOps Agent Console</h1>
            </div>
            <div className="hero-center">
              <div className="status-pill-group">
                <span className={`status-pill ${apiHealth?.status === "ok" ? "status-pill--ok" : "status-pill--bad"}`}>
                  <span
                    className={`pill-dot ${apiHealth?.status === "ok" ? "pill-dot--pulse-green" : "pill-dot--pulse-muted"}`}
                  />
                  API: {apiHealth?.status || "unknown"}
                </span>
                <span className={`status-pill ${wsStatus === "connected" ? "status-pill--ws-live" : ""}`}>
                  <span
                    className={`pill-dot ${wsStatus === "connected" ? "pill-dot--pulse-orange" : "pill-dot--pulse-muted"}`}
                  />
                  WS: {wsStatus}
                </span>
                <span className="status-pill">
                  <span
                    className={`pill-dot ${
                      monitoringWsStatus === "connected" ? "pill-dot--pulse-orange" : "pill-dot--pulse-muted"
                    }`}
                  />
                  MON: {monitoringWsStatus}
                </span>
              </div>
              <div className="header-sep" role="presentation" aria-hidden="true" />
              <div className="modal-triggers">
                <button
                  type="button"
                  className="btn-modal-trigger"
                  onClick={() => window.openModal && window.openModal("modal-git-logs")}
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                    <path d="M4 4h16a2 2 0 0 1 2 2v3H2V6a2 2 0 0 1 2-2Zm-2 7h20v7a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2Zm5.5 2.5a1.5 1.5 0 1 0 0 3h5a1.5 1.5 0 0 0 0-3Z" />
                  </svg>
                  <span>Git Log Analyzer</span>
                </button>
                <button
                  type="button"
                  className="btn-modal-trigger btn-modal-payment"
                  onClick={() => window.openModal && window.openModal("modal-payment")}
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                    <path d="M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2H3Zm0 4h18v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Zm3 5a1 1 0 0 0 0 2h4a1 1 0 0 0 0-2Z" />
                  </svg>
                  <span>Payment Analyzer</span>
                </button>
              </div>
            </div>
            <div className="hero-auth">
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
                  <a className="btn-logout" href={`${API_BASE}/api/v1/auth/logout`}>
                    Logout
                  </a>
                </div>
              ) : (
                <a className="btn-github-login" href={`${API_BASE}/api/v1/auth/github`}>
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
          </div>
          <p className="hero-tagline">Pipeline status, stage timeline, and agent outputs in one place.</p>
        </header>

        <section className="grid">
          <article className="panel panel-card">
            <h2 className="panel-title">
              <svg className="panel-title-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true">
                <path
                  d="M4 12h4l2-6 4 12 2-6h4"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span>Pipeline Input</span>
            </h2>
            <div className="field-group">
              <label>Repository</label>
              <input value={repoName} onChange={(e) => setRepoName(e.target.value)} />
            </div>
            <div className="field-group">
              <label>Fetch from public GitHub</label>
              <input
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/owner/repo"
              />
            </div>
            <div className="field-group field-group--actions">
              <button type="button" className="btn-primary" onClick={submitGithub} disabled={loading || !repoUrl}>
                Fetch GitHub Repo &amp; Run
              </button>
            </div>
          </article>

          <article className="panel panel-card panel-has-timeline">
            <h2 className="panel-title">
              <svg className="panel-title-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true">
                <path
                  d="M5 8h2M5 12h2M5 16h2M11 8h8M11 12h5M11 16h8"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
                <circle cx="8" cy="8" r="1.5" fill="currentColor" />
                <circle cx="8" cy="12" r="1.5" fill="currentColor" />
                <circle cx="8" cy="16" r="1.5" fill="currentColor" />
              </svg>
              <span>Pipeline Control</span>
            </h2>
            <div className="field-group">
              <label>Pipeline ID</label>
              <input value={pipelineId} onChange={(e) => setPipelineId(e.target.value)} />
            </div>
            <div className="field-group">
              <label>Deployment API Key</label>
              <input
                value={deploymentApiKey}
                onChange={(e) => setDeploymentApiKey(e.target.value)}
                placeholder="devops-approver-key"
              />
            </div>
            <div className="button-row field-group field-group--actions">
              <button type="button" className="btn-secondary" onClick={() => fetchStatus()} disabled={loading}>
                Refresh Status
              </button>
              <button type="button" className="btn-primary" onClick={triggerDeployment} disabled={loading}>
                Trigger Deployment
              </button>
            </div>
            {state && (
              <>
                <div className="status-row">
                  <span className={`badge ${state.status}`}>{state.status.toUpperCase()}</span>
                  <span>Current stage: {state.current_stage.toUpperCase()}</span>
                </div>
              </>
            )}
            <StageTimeline currentStage={state?.current_stage} status={state?.status} />
          </article>

          <article className="panel panel-card wide">
            <h2 className="panel-title">
              <svg className="panel-title-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true">
                <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="1.5" />
                <path d="M3 8h18" stroke="currentColor" strokeWidth="1.5" />
                <path d="M6 12h6M6 15h10" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              </svg>
              <span>Agent Logs</span>
            </h2>
            <div className="terminal-window">
              <div className="terminal-bar">
                <span style={{ width: "11px", height: "11px", borderRadius: "50%", background: "#FF5F56" }} />
                <span style={{ width: "11px", height: "11px", borderRadius: "50%", background: "#FFBD2E" }} />
                <span style={{ width: "11px", height: "11px", borderRadius: "50%", background: "#27C93F" }} />
                <span
                  style={{
                    fontFamily: "monospace",
                    fontSize: "10px",
                    letterSpacing: "0.1em",
                    color: "rgba(255,255,255,0.3)",
                    flex: 1,
                    textAlign: "center",
                  }}
                >
                  AGENT LOGS
                </span>
              </div>
              <div className="terminal-body">
                {state?.history?.length ? (
                  state.history.map((entry, idx) => <LogLine key={idx} entry={entry} />)
                ) : (
                  <>
                    <span className="term-prompt">$</span>{" "}
                    <span className="term-idle">waiting for pipeline events...</span>
                  </>
                )}
              </div>
            </div>
          </article>

          <article className="panel panel-card">
            <h2 className="panel-title">
              <svg className="panel-title-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true">
                <path
                  d="M4 12a8 8 0 0 1 16 0M4 12v4a2 2 0 0 0 2 2h2M20 12v4a2 2 0 0 1-2 2h-2"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
                <circle cx="12" cy="12" r="2" fill="currentColor" />
              </svg>
              <span>Monitoring</span>
            </h2>
            <div className="field-group">
              <label>Runtime Logs</label>
              <textarea
                rows={6}
                value={logsText}
                onChange={(e) => setLogsText(e.target.value)}
                placeholder="Paste runtime logs here for analysis..."
              />
            </div>
            <div className="field-group field-group--checkbox">
              <label className="label-inline">
                <input
                  type="checkbox"
                  checked={realtimeMonitoring}
                  onChange={(e) => setRealtimeMonitoring(e.target.checked)}
                />
                Real-time analysis (5s)
              </label>
            </div>
            <div className="field-group field-group--actions">
              <button type="button" className="btn-primary" onClick={analyzeLogs} disabled={loading}>
                Analyze Logs
              </button>
            </div>
            {monitoring && (
              <div className="result-block">
                <strong>{monitoring.summary}</strong>
                <p>Anomalies: {monitoring.anomalies.join(" | ") || "none"}</p>
                <p>Suggestions: {monitoring.suggestions.join(" | ") || "none"}</p>
                <p>Last analyzed: {lastMonitoringAt || "just now"}</p>
              </div>
            )}
          </article>

          <article className="panel panel-card">
            <h2 className="panel-title">
              <svg className="panel-title-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true">
                <path
                  d="M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7Z"
                  stroke="currentColor"
                  strokeWidth="1.5"
                />
                <path d="M8 11h8M8 14h5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              </svg>
              <span>Agent Artifacts</span>
            </h2>
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
    </div>
  );
}
