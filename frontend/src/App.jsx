import { useEffect, useMemo, useRef, useState } from "react";
import AnalyzerModals from "./AnalyzerModals";
import NavHub from "./components/NavHub.jsx";
import { VIEWS } from "./config/stacks.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const STAGE_KEYS = ["dev", "qa", "stress", "approval", "deployment", "monitoring", "completed"];
const STAGE_LABELS = ["DEV", "QA", "STRESS", "APPROVAL", "DEPLOYMENT", "MONITORING", "COMPLETED"];

function buildStageStates(history, currentStage, status) {
  const states = Object.fromEntries(STAGE_KEYS.map((k) => [k, "pending"]));
  const failRe = /(failed|fail|blocked|denied|error|skipped)/i;

  (history || []).forEach((entry) => {
    const stage = (entry?.stage || "").toLowerCase();
    if (!Object.prototype.hasOwnProperty.call(states, stage)) {
      return;
    }
    const msg = String(entry?.message || "");
    if (failRe.test(msg)) {
      states[stage] = "failed";
      return;
    }
    if (states[stage] !== "failed") {
      states[stage] = "passed";
    }
  });

  const cur = (currentStage || "").toLowerCase();
  if (Object.prototype.hasOwnProperty.call(states, cur) && states[cur] === "pending") {
    states[cur] = status === "running" ? "running" : "pending";
  }
  if ((status || "").toLowerCase() === "completed") {
    states.completed = "passed";
  }

  return states;
}

function StageTimeline({ currentStage, status, history }) {
  const states = buildStageStates(history, currentStage, status);
  const norm = (s) => (s || "").toLowerCase();
  const lastIdx = STAGE_KEYS.length - 1;

  return (
    <div className="stage-timeline">
      {STAGE_KEYS.map((key, i) => {
        const nodeState = states[key] || "pending";

        const chip =
          nodeState === "passed"
            ? "\u2713"
            : nodeState === "running"
              ? "RUN"
              : nodeState === "failed"
                ? "\u2717"
                : nodeState === "blocked"
                  ? "\u2717"
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

function StageChart({ history, currentStage, status }) {
  const states = buildStageStates(history, currentStage, status);
  return (
    <div className="stage-chart" aria-label="stage chart">
      {STAGE_KEYS.map((key, i) => {
        const nodeState = states[key] || "pending";
        const height =
          nodeState === "passed" || nodeState === "failed" || nodeState === "blocked"
            ? 100
            : nodeState === "running"
              ? 60
              : 18;
        return (
          <div key={key} className="stage-chart-col">
            <div className="stage-chart-track">
              <div
                className={`stage-chart-bar stage-chart-bar--${nodeState}`}
                style={{ height: `${height}%` }}
              />
            </div>
            <span>{STAGE_LABELS[i]}</span>
          </div>
        );
      })}
    </div>
  );
}

function AgentProgress({ active }) {
  const AGENT_SEQUENCE = [
    "Code Analysis Agent",
    "Security Agent",
    "QA Runner",
    "Stress Tester",
    "Pipeline Control Agent",
    "Deployment Agent",
    "Monitoring Agent",
  ];
  const [idx, setIdx] = useState(0);
  useEffect(() => {
    if (!active) {
      setIdx(0);
      return undefined;
    }
    const t = setInterval(() => setIdx((i) => (i + 1) % AGENT_SEQUENCE.length), 1100);
    return () => clearInterval(t);
  }, [active]);
  if (!active) return null;
  return (
    <div className="agent-progress" aria-live="polite">
      <div className="agent-progress-line">
        <span className="agent-dot" />
        <span className="agent-text">{AGENT_SEQUENCE[idx]} is running...</span>
      </div>
    </div>
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
  const [submitMultimodalModes, setSubmitMultimodalModes] = useState([]);
  const [submitMultimodalText, setSubmitMultimodalText] = useState("");
  const [enableAutoPr, setEnableAutoPr] = useState(false);
  const [archiveFile, setArchiveFile] = useState(null);

  function toggleSubmitMode(mode) {
    setSubmitMultimodalModes((prev) => {
      if (prev.includes(mode)) {
        return prev.filter((x) => x !== mode);
      }
      return [...prev, mode];
    });
  }

  const [state, setState] = useState(null);
  const [monitoring, setMonitoring] = useState(null);
  const [realtimeMonitoring, setRealtimeMonitoring] = useState(true);
  const [lastMonitoringAt, setLastMonitoringAt] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showAgentAnim, setShowAgentAnim] = useState(false);
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
  const [runtimeConfig, setRuntimeConfig] = useState(null);
  const [pipelineHistory, setPipelineHistory] = useState([]);
  const [analyzerOpen, setAnalyzerOpen] = useState(null);
  const [userProfile, setUserProfile] = useState(null);
  const [activeView, setActiveView] = useState(() => {
    const hash = window.location.hash.replace(/^#\/?/, "");
    return VIEWS.some((v) => v.id === hash) ? hash : "pipeline";
  });

  function setActiveViewAndHash(viewId) {
    setActiveView(viewId);
    window.location.hash = `#/${viewId}`;
  }

  const agentArtifacts = useMemo(() => {
    if (!state?.artifacts) {
      return [];
    }
    return Object.entries(state.artifacts);
  }, [state]);

  // GitHub is the primary flow; submit-code and submit-archive are also supported below.

  async function afterPipelineSubmit(data) {
    setPipelineId(data.pipeline_id);
    const params = new URLSearchParams(window.location.search);
    params.set("pipeline", data.pipeline_id);
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
    await fetchStatus(data.pipeline_id);
    await fetchPipelines();
  }

  async function submitCode() {
    setError("");
    if (!repoName.trim() || !codeText.trim()) {
      setError("Repo name and code snippet are required for submit-code.");
      return;
    }
    setLoading(true);
    setShowAgentAnim(true);
    try {
      const response = await fetch(`${API_BASE}/submit-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          repo_name: repoName.trim(),
          code: codeText,
          diff: diffText || "",
          enable_auto_pr: enableAutoPr,
          clone_url: repoUrl.trim() || undefined,
        }),
      });
      const data = await (response.headers.get("content-type")?.includes("application/json") ? response.json() : response.text());
      if (!response.ok) {
        throw new Error(typeof data === "string" ? data : data.detail || JSON.stringify(data));
      }
      await afterPipelineSubmit(data);
    } catch (err) {
      setError(err.message);
      setShowAgentAnim(false);
    } finally {
      setLoading(false);
    }
  }

  async function submitArchive() {
    setError("");
    if (!archiveFile) {
      setError("Choose a .zip archive first.");
      return;
    }
    setLoading(true);
    setShowAgentAnim(true);
    try {
      const fd = new FormData();
      fd.append("repo_name", repoName.trim() || "uploaded-archive");
      fd.append("archive", archiveFile);
      const response = await fetch(`${API_BASE}/submit-archive?force_real=false`, {
        method: "POST",
        body: fd,
        credentials: "include",
      });
      const data = await (response.headers.get("content-type")?.includes("application/json") ? response.json() : response.text());
      if (!response.ok) {
        throw new Error(typeof data === "string" ? data : data.detail || JSON.stringify(data));
      }
      await afterPipelineSubmit(data);
    } catch (err) {
      setError(err.message);
      setShowAgentAnim(false);
    } finally {
      setLoading(false);
    }
  }

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
    setShowAgentAnim(true);
    try {
      const fd = new FormData();
      fd.append("repo_url", normalized);
      fd.append("branch", "main");
      fd.append("enable_auto_pr", enableAutoPr ? "true" : "false");
      fd.append("multimodal_modes", submitMultimodalModes.join(","));
      if (submitMultimodalModes.length > 0 && submitMultimodalText.trim()) {
        fd.append("multimodal_text", submitMultimodalText.trim());
      }
      const resp = await fetch(`${API_BASE}/submit-github?force_real=false&wait=false`, {
        method: "POST",
        body: fd,
        credentials: "include",
      });
      const data = await (resp.headers.get("content-type")?.includes("application/json") ? resp.json() : resp.text());
      if (!resp.ok) {
        const message = typeof data === "string" ? data : data.detail || JSON.stringify(data);
        throw new Error(`Submit failed: ${message}`);
      }
      await afterPipelineSubmit(data);
    } catch (err) {
      setError(err.message);
      setShowAgentAnim(false);
    } finally {
      setLoading(false);
    }
  }

  async function fetchPipelines() {
    try {
      const response = await fetch(`${API_BASE}/pipelines`);
      if (!response.ok) return;
      const data = await response.json();
      setPipelineHistory(Array.isArray(data) ? data : []);
    } catch {
      setPipelineHistory([]);
    }
  }

  async function fetchRuntimeConfig() {
    try {
      const response = await fetch(`${API_BASE}/runtime-config`);
      if (!response.ok) return;
      setRuntimeConfig(await response.json());
    } catch {
      setRuntimeConfig(null);
    }
  }

  async function cancelPipeline() {
    if (!pipelineId) return;
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/pipelines/${pipelineId}/cancel`, { method: "POST" });
      if (!response.ok) throw new Error(`Cancel failed with ${response.status}`);
      setState(await response.json());
      await fetchPipelines();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function retryPipeline() {
    if (!pipelineId) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/pipelines/${pipelineId}/retry`, {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `Retry failed with ${response.status}`);
      }
      setState(await response.json());
      await fetchPipelines();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const retryableStatus = ["blocked", "blocked_with_prs_sent", "failed", "cancelled"].includes(state?.status);

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
    const onHash = () => {
      const hash = window.location.hash.replace(/^#\/?/, "");
      if (VIEWS.some((v) => v.id === hash)) setActiveView(hash);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    fetchHealth(true);
    fetchRuntimeConfig();
    fetchPipelines();
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("pipeline");
    if (fromUrl) {
      setPipelineId(fromUrl);
      fetchStatus(fromUrl, true);
    }
    const intervalId = window.setInterval(() => {
      fetchHealth(true);
      fetchPipelines();
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
      let detectedLogType = null;
      if (logsText.trim()) {
        try {
          const pre = await fetch(`${API_BASE}/api/v1/tools/text-analyze`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ text: logsText, operations: ["classify_log", "sanitize"] }),
          });
          if (pre.ok) {
            const preBody = await pre.json();
            detectedLogType = preBody.log_type || null;
          }
        } catch {
          /* keep default analyze-logs path */
        }
      }
      const payload = { logs: logsText };
      if (pipelineId) {
        payload.pipeline_id = pipelineId;
      }
      if (detectedLogType) {
        payload.detected_log_type = detectedLogType;
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
              <div>
                <h1>DevOps Agent Console</h1>
                <a
                  className="hero-hub-link"
                  href={import.meta.env.VITE_HUB_URL || "http://127.0.0.1:5180"}
                  target="_blank"
                  rel="noreferrer"
                >
                  ORION Command Hub →
                </a>
              </div>
            </div>
            <div className="hero-center">
              <div className="status-pill-group">
                <span className={`status-pill ${apiHealth?.status === "ok" ? "status-pill--ok" : "status-pill--bad"}`}>
                  <span
                    className={`pill-dot ${apiHealth?.status === "ok" ? "pill-dot--pulse-green" : "pill-dot--pulse-muted"}`}
                  />
                  API: {apiHealth?.status || "unknown"}
                </span>
                <span className="status-pill">
                  QA: {runtimeConfig?.qa_mode || apiHealth?.qa_mode || "n/a"}
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
                  onClick={() => setAnalyzerOpen("git")}
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                    <path d="M4 4h16a2 2 0 0 1 2 2v3H2V6a2 2 0 0 1 2-2Zm-2 7h20v7a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2Zm5.5 2.5a1.5 1.5 0 1 0 0 3h5a1.5 1.5 0 0 0 0-3Z" />
                  </svg>
                  <span>Git Log Analyzer</span>
                </button>
                <button
                  type="button"
                  className="btn-modal-trigger btn-modal-payment"
                  onClick={() => setAnalyzerOpen("pay")}
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                    <path d="M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2H3Zm0 4h18v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Zm3 5a1 1 0 0 0 0 2h4a1 1 0 0 0 0-2Z" />
                  </svg>
                  <span>Payment Analyzer</span>
                </button>
                <button type="button" className="btn-modal-trigger" onClick={() => setAnalyzerOpen("log")}>
                  Log Analyzer
                </button>
                <button type="button" className="btn-modal-trigger" onClick={() => setAnalyzerOpen("docker")}>
                  Dockerfile
                </button>
                <button type="button" className="btn-modal-trigger" onClick={() => setAnalyzerOpen("triage")}>
                  Production Triage
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

        <NavHub activeView={activeView} onViewChange={setActiveViewAndHash} />

        {activeView === "operations" && (
          <section className="grid">
            <article className="panel panel-card wide">
              <h2 className="panel-title"><span>System Operations</span></h2>
              <div className="status-pill-group" style={{ marginBottom: "1rem" }}>
                <span className="status-pill">API: {apiHealth?.status || "unknown"}</span>
                <span className="status-pill">QA: {runtimeConfig?.qa_mode || "n/a"}</span>
                <span className="status-pill">WS: {wsStatus}</span>
                <span className="status-pill">MON: {monitoringWsStatus}</span>
              </div>
              <pre className="results-container">{JSON.stringify(runtimeConfig || apiHealth || {}, null, 2)}</pre>
            </article>
            <article className="panel panel-card wide">
              <h2 className="panel-title"><span>Recent Pipeline Runs</span></h2>
              <div className="runs-table">
                {pipelineHistory.length === 0 ? (
                  <p className="hint">No runs yet — trigger a pipeline from the Pipeline view.</p>
                ) : (
                  pipelineHistory.map((run) => (
                    <button
                      key={run.pipeline_id}
                      type="button"
                      className="runs-table__row btn-secondary"
                      onClick={() => {
                        setPipelineId(run.pipeline_id);
                        setActiveViewAndHash("pipeline");
                        fetchStatus(run.pipeline_id);
                      }}
                    >
                      <span>{run.repo_name}</span>
                      <span className="badge">{run.status}</span>
                      <span className="mono">{run.pipeline_id}</span>
                    </button>
                  ))
                )}
              </div>
            </article>
          </section>
        )}

        {activeView === "intelligence" && (
          <section className="grid">
            <article className="panel panel-card wide">
              <h2 className="panel-title"><span>Intelligence Suite</span></h2>
              <p className="hint">Launch multimodal agents for logs, payments, Dockerfiles, and incident triage.</p>
              <div className="modal-triggers modal-triggers--grid">
                {[
                  ["git", "Git Log Analyzer"],
                  ["pay", "Payment Analyzer"],
                  ["log", "Log Analyzer"],
                  ["docker", "Dockerfile Hardening"],
                  ["triage", "Production Triage"],
                  ["github", "GitHub Actions Log"],
                ].map(([id, label]) => (
                  <button key={id} type="button" className="btn-modal-trigger" onClick={() => setAnalyzerOpen(id)}>
                    {label}
                  </button>
                ))}
              </div>
            </article>
            <article className="panel panel-card">
              <h2 className="panel-title"><span>Log Monitoring</span></h2>
              <textarea rows={6} value={logsText} onChange={(e) => setLogsText(e.target.value)} placeholder="Paste runtime logs…" />
              <button type="button" className="btn-primary" onClick={analyzeLogs} disabled={loading} style={{ marginTop: "0.75rem" }}>
                Analyze Logs
              </button>
              {monitoring && (
                <div className="result-block" style={{ marginTop: "1rem" }}>
                  <strong>{monitoring.summary}</strong>
                </div>
              )}
            </article>
          </section>
        )}

        {activeView === "pipeline" && (
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
              <label>Local label (optional)</label>
              <input value={repoName} onChange={(e) => setRepoName(e.target.value)} placeholder="my-service" />
            </div>
            <div className="field-group">
              <label>Fetch from public GitHub</label>
              <input
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/owner/repo"
              />
            </div>
            <div className="field-group">
              <label>Select multimodal analyzers to run (optional)</label>
              <div className="field-group field-group--checkbox">
                <label className="label-inline">
                  <input
                    type="checkbox"
                    checked={submitMultimodalModes.includes("git_logs")}
                    onChange={() => toggleSubmitMode("git_logs")}
                  />
                  Git Log Analyzer
                </label>
                <label className="label-inline">
                  <input
                    type="checkbox"
                    checked={submitMultimodalModes.includes("payment")}
                    onChange={() => toggleSubmitMode("payment")}
                  />
                  Payment Analyzer
                </label>
              </div>
            </div>
            {submitMultimodalModes.length > 0 && (
              <div className="field-group">
                <label>Multimodal context (logs/notes)</label>
                <textarea
                  rows={4}
                  value={submitMultimodalText}
                  onChange={(e) => setSubmitMultimodalText(e.target.value)}
                  placeholder="Paste runtime logs or context to analyze alongside pipeline checks"
                />
              </div>
            )}
            <div className="field-group field-group--checkbox">
              <label className="label-inline">
                <input type="checkbox" checked={enableAutoPr} onChange={(e) => setEnableAutoPr(e.target.checked)} />
                Enable Auto-PR on pipeline block
              </label>
            </div>
            <div className="field-group">
              <label>Code snippet (submit-code)</label>
              <textarea rows={5} value={codeText} onChange={(e) => setCodeText(e.target.value)} placeholder="Paste Python or other source" />
            </div>
            <div className="field-group">
              <label>Diff (optional)</label>
              <textarea rows={3} value={diffText} onChange={(e) => setDiffText(e.target.value)} />
            </div>
            <div className="field-group field-group--actions">
              <button type="button" className="btn-secondary" onClick={submitCode} disabled={loading}>
                Submit Code Snippet
              </button>
            </div>
            <div className="field-group">
              <label>Upload zip archive (submit-archive)</label>
              <input type="file" accept=".zip,application/zip" onChange={(e) => setArchiveFile(e.target.files?.[0] || null)} />
            </div>
            <div className="field-group field-group--actions">
              <button type="button" className="btn-secondary" onClick={submitArchive} disabled={loading || !archiveFile}>
                Upload Archive &amp; Run
              </button>
            </div>
            <div className="field-group field-group--actions">
              <button type="button" className="btn-primary" onClick={submitGithub} disabled={loading || !repoUrl}>
                Fetch GitHub Repo &amp; Run
              </button>
            </div>
            <AgentProgress active={loading || showAgentAnim} />
            {pipelineHistory.length > 0 && (
              <div className="field-group">
                <label>Recent runs</label>
                <div className="artifact-list">
                  {pipelineHistory.slice(0, 8).map((run) => (
                    <button
                      key={run.pipeline_id}
                      type="button"
                      className="btn-secondary"
                      onClick={() => {
                        setPipelineId(run.pipeline_id);
                        fetchStatus(run.pipeline_id);
                        const params = new URLSearchParams(window.location.search);
                        params.set("pipeline", run.pipeline_id);
                        window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
                      }}
                    >
                      {run.repo_name} · {run.status}
                    </button>
                  ))}
                </div>
              </div>
            )}
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
              <button type="button" className="btn-secondary" onClick={cancelPipeline} disabled={loading || !pipelineId}>
                Cancel run
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={retryPipeline}
                disabled={loading || !pipelineId || !retryableStatus}
              >
                Retry run
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
            <StageTimeline currentStage={state?.current_stage} status={state?.status} history={state?.history} />
            <StageChart history={state?.history} currentStage={state?.current_stage} status={state?.status} />
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
              {state?.artifacts?.auto_pr_registry?.branches?.length ? (
                <div className="result-block">
                  <strong>Auto-fix PRs</strong>
                  {(state.artifacts.auto_pr_registry.branches || []).map((branch) => (
                    <p key={branch.branch_name || branch.pr_number}>
                      {branch.pr_url ? (
                        <a href={branch.pr_url} target="_blank" rel="noreferrer">
                          {branch.pr_url}
                        </a>
                      ) : (
                        `${branch.category || "fix"} #${branch.pr_number || "n/a"}`
                      )}
                    </p>
                  ))}
                </div>
              ) : null}
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
        )}

        {error && <div className="error">{error}</div>}
      </main>
      <AnalyzerModals open={analyzerOpen} onClose={() => setAnalyzerOpen(null)} />
    </div>
  );
}
