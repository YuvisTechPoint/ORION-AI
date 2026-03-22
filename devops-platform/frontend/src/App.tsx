import axios from "axios";
import { useCallback, useMemo, useState } from "react";
import { analyzeLogs, getPipeline, getPipelineStatus, triggerDeploy, triggerPipeline } from "./api/client";
import AgentArtifacts from "./components/AgentArtifacts";
import AgentLogs from "./components/AgentLogs";
import Monitoring from "./components/Monitoring";
import PipelineControl from "./components/PipelineControl";
import PipelineInput from "./components/PipelineInput";
import StageChart from "./components/StageChart";
import { usePipelineWS, WsEvent } from "./hooks/usePipelineWS";

function resolveRepoUrl(repo: string, repoUrl: string): string {
  const trimmedUrl = repoUrl.trim();
  if (trimmedUrl) return trimmedUrl;
  const r = repo.trim();
  if (!r) return "";
  if (r.startsWith("http://") || r.startsWith("https://")) return r;
  if (r.includes("/")) return `https://github.com/${r.replace(/^\/+/, "")}`;
  return `https://github.com/example/${r}`;
}

export type LogLine = { ts: string; level: string; message: string; stage?: string };

export default function App() {
  const [repo, setRepo] = useState("payment-service");
  const [repoUrl, setRepoUrl] = useState("");
  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [deployKey, setDeployKey] = useState("");
  const [status, setStatus] = useState("PENDING");
  const [currentStage, setCurrentStage] = useState("PENDING");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logLines, setLogLines] = useState<LogLine[]>([]);
  const [monLogs, setMonLogs] = useState("");
  const [monResult, setMonResult] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<Record<string, unknown>>({});
  const [wsConnected, setWsConnected] = useState(false);
  const [stageChart, setStageChart] = useState<{ labels: string[]; values: number[] }>({
    labels: ["DEV", "QA", "STRESS", "APPROVAL", "DEPLOYMENT", "MONITORING"],
    values: [0, 0, 0, 0, 0, 0],
  });

  const onWs = useCallback((ev: WsEvent) => {
    if (ev.type === "log" && ev.message) {
      setLogLines((prev) => [
        ...prev,
        {
          ts: (ev.timestamp as string) || new Date().toISOString(),
          level: (ev.level as string) || "INFO",
          message: String(ev.message),
          stage: (ev.stage as string) || "",
        },
      ]);
    }
    if (ev.type === "status_change" && ev.new_status) {
      setStatus(String(ev.new_status));
      setCurrentStage(String(ev.new_status));
    }
    if (ev.type === "artifact" && ev.stage && ev.data) {
      setArtifacts((prev) => ({
        ...prev,
        [(ev.stage as string).toLowerCase()]: ev.data,
      }));
    }
  }, []);

  const { connected } = usePipelineWS(pipelineId, onWs);

  // keep connection state in sync
  useMemo(() => {
    setWsConnected(connected);
  }, [connected]);

  const running = useMemo(() => {
    return !["COMPLETED", "FAILED", "BLOCKED"].includes(status);
  }, [status]);

  const handleTrigger = async () => {
    setError(null);
    setLoading(true);
    setLogLines([]);
    setArtifacts({});
    setMonResult(null);
    try {
      const url = resolveRepoUrl(repo, repoUrl);
      if (!url) {
        setError("Enter a GitHub URL or repository name.");
        return;
      }
      const data = await triggerPipeline(url, deployKey || undefined);
      setPipelineId(data.pipeline_id);
      setStatus(data.status || "PENDING");
      setCurrentStage("PENDING");
    } catch (e: unknown) {
      if (axios.isAxiosError(e)) {
        const detail = e.response?.data;
        const msg =
          typeof detail === "object" && detail && "detail" in detail
            ? String((detail as { detail: unknown }).detail)
            : e.message;
        setError(msg);
      } else {
        setError(e instanceof Error ? e.message : "Request failed");
      }
    } finally {
      setLoading(false);
    }
  };

  const refresh = async () => {
    if (!pipelineId) return;
    setLoading(true);
    try {
      const s = await getPipelineStatus(pipelineId);
      setStatus(s.status);
      setCurrentStage(s.current_stage || s.status);
      const full = await getPipeline(pipelineId);
      const art: Record<string, unknown> = {};
      const mapOrder = ["DEV", "QA", "STRESS", "APPROVAL", "DEPLOYMENT", "MONITORING"];
      const vals = [0, 0, 0, 0, 0, 0];
      for (const sr of full.stage_results || []) {
        if (sr.stage && sr.output_json) art[sr.stage] = sr.output_json;
        if (sr.stage === "code_analysis") vals[0] = sr.passed ? 1 : 0.3;
        if (sr.stage === "security") vals[0] = Math.min(vals[0], sr.passed ? vals[0] : 0.2);
        if (sr.stage === "qa") vals[1] = sr.passed ? 1 : 0.3;
        if (sr.stage === "stress") vals[2] = sr.passed ? 1 : 0.3;
        if (sr.stage === "deployment") vals[4] = sr.passed ? 1 : 0.3;
        if (sr.stage === "monitoring") vals[5] = sr.passed ? 1 : 0.3;
      }
      if (full.status === "COMPLETED") vals[3] = 1;
      setStageChart({ labels: mapOrder, values: vals });
      setArtifacts(art);

      // Also pull logs
      for (const log of full.logs || []) {
        setLogLines((prev) => {
          const exists = prev.some(
            (l) => l.ts === log.timestamp && l.message === log.message
          );
          if (exists) return prev;
          return [
            ...prev,
            {
              ts: log.timestamp || "",
              level: log.level || "INFO",
              message: log.message || "",
              stage: log.stage || "",
            },
          ];
        });
      }
    } catch (e: unknown) {
      const err = e as { message?: string };
      setError(err.message || "Refresh failed");
    } finally {
      setLoading(false);
    }
  };

  const deploy = async () => {
    if (!pipelineId || !deployKey) return;
    setLoading(true);
    try {
      await triggerDeploy(pipelineId, deployKey);
    } catch (e: unknown) {
      const err = e as { message?: string };
      setError(err.message || "Deploy failed");
    } finally {
      setLoading(false);
    }
  };

  const runAnalyze = async () => {
    if (!pipelineId || !monLogs.trim()) return;
    setLoading(true);
    setMonResult(null);
    try {
      const data = await analyzeLogs(pipelineId, monLogs);
      setMonResult(JSON.stringify(data, null, 2));
    } catch (e: unknown) {
      if (axios.isAxiosError(e)) {
        const detail = e.response?.data;
        const msg =
          typeof detail === "object" && detail && "detail" in detail
            ? String((detail as { detail: unknown }).detail)
            : e.message;
        setError(msg);
      } else {
        setError(e instanceof Error ? e.message : "Analyze failed");
      }
    } finally {
      setLoading(false);
    }
  };

  const statusProgress = useMemo(() => {
    const stageOrder = ["PENDING", "DEV", "QA", "STRESS", "APPROVAL", "DEPLOYMENT", "MONITORING", "COMPLETED"];
    const idx = stageOrder.indexOf(status);
    if (status === "FAILED" || status === "BLOCKED") return 100;
    return Math.round(((idx < 0 ? 0 : idx) / (stageOrder.length - 1)) * 100);
  }, [status]);

  return (
    <div style={{ minHeight: "100vh" }}>
      {/* ── Top navigation bar ── */}
      <header className="platform-header">
        <div style={{ maxWidth: "1280px", margin: "0 auto", padding: "0 1.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", height: "60px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <div style={{
                width: "36px", height: "36px", borderRadius: "10px",
                background: "linear-gradient(135deg, #E8832A, #C96E1A)",
                display: "flex", alignItems: "center", justifyContent: "center",
                boxShadow: "0 2px 8px rgba(232,131,42,0.4)",
              }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="12" cy="12" r="10" stroke="white" strokeWidth="2"/>
                  <circle cx="12" cy="12" r="4" fill="white"/>
                  <path d="M12 2 L12 6 M12 18 L12 22 M2 12 L6 12 M18 12 L22 12" stroke="white" strokeWidth="2" strokeLinecap="round"/>
                </svg>
              </div>
              <div>
                <span style={{ fontWeight: 800, fontSize: "1rem", color: "#1a1208", letterSpacing: "-0.02em" }}>ORION</span>
                <span style={{ fontWeight: 400, fontSize: "0.8rem", color: "#9a8878", marginLeft: "0.5rem" }}>DevOps Platform</span>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
              {pipelineId && (
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.75rem", color: "#9a8878" }}>
                  <div className={`ws-dot ${wsConnected || connected ? "ws-dot-connected" : "ws-dot-disconnected"}`} />
                  <span>{wsConnected || connected ? "Live" : "Connecting…"}</span>
                </div>
              )}
              <a
                href="http://localhost:8000/docs"
                target="_blank"
                rel="noreferrer"
                style={{
                  fontSize: "0.8rem", fontWeight: 500, color: "#7a6b5a",
                  textDecoration: "none", padding: "0.375rem 0.75rem",
                  borderRadius: "8px", border: "1px solid rgba(0,0,0,0.08)",
                  transition: "all 150ms",
                  display: "inline-flex", alignItems: "center", gap: "0.375rem",
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                API Docs
              </a>
            </div>
          </div>
        </div>
      </header>

      {/* ── Main content ── */}
      <main style={{ maxWidth: "1280px", margin: "0 auto", padding: "2rem 1.5rem 4rem" }}>
        {/* Hero title */}
        <div style={{ marginBottom: "2rem" }} className="animate-fade-in">
          <h1 style={{
            fontSize: "1.75rem", fontWeight: 800, color: "#1a1208",
            letterSpacing: "-0.03em", marginBottom: "0.375rem",
          }}>
            Multi-Agent DevOps Console
          </h1>
          <p style={{ fontSize: "0.9rem", color: "#7a6b5a", fontWeight: 400 }}>
            AI-powered pipeline automation • Code analysis → Security → QA → Stress → Deployment
          </p>
        </div>

        {/* Status progress bar (when a pipeline is active) */}
        {pipelineId && (
          <div className="animate-fade-in" style={{ marginBottom: "1.5rem" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.5rem" }}>
              <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "#7a6b5a", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Pipeline Progress
              </span>
              <span style={{ fontSize: "0.75rem", fontWeight: 700, color: "#E8832A" }}>
                {status === "FAILED" || status === "BLOCKED" ? status : `${statusProgress}%`}
              </span>
            </div>
            <div className="status-bar">
              <div
                className="status-bar-fill"
                style={{
                  width: `${statusProgress}%`,
                  background: status === "BLOCKED" || status === "FAILED"
                    ? "linear-gradient(90deg, #ef5350, #ff7043)"
                    : status === "COMPLETED"
                    ? "linear-gradient(90deg, #66bb6a, #43a047)"
                    : "linear-gradient(90deg, #E8832A, #f5a65b)",
                }}
              />
            </div>
          </div>
        )}

        {/* Error toast */}
        {error && (
          <div className="toast-error animate-slide-in" style={{ marginBottom: "1.25rem", display: "flex", gap: "0.75rem", alignItems: "flex-start" }}>
            <svg style={{ color: "#ef5350", flexShrink: 0, marginTop: "1px" }} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, marginBottom: "0.125rem" }}>Error</div>
              <div style={{ opacity: 0.85 }}>{error}</div>
            </div>
            <button
              onClick={() => setError(null)}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#c62828", padding: 0 }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        )}

        {/* ── Grid layout ── */}
        <div style={{ display: "grid", gap: "1.25rem", gridTemplateColumns: "1fr 1fr" }}>
          {/* Pipeline Input */}
          <div className="animate-fade-in" style={{ animationDelay: "0.05s" }}>
            <PipelineInput
              repo={repo}
              repoUrl={repoUrl}
              loading={loading || (running && !!pipelineId)}
              onRepoChange={setRepo}
              onRepoUrlChange={setRepoUrl}
              onSubmit={handleTrigger}
            />
          </div>

          {/* Pipeline Control */}
          <div className="animate-fade-in" style={{ animationDelay: "0.1s" }}>
            <PipelineControl
              pipelineId={pipelineId}
              deployKey={deployKey}
              status={status}
              currentStage={currentStage}
              loading={loading}
              wsConnected={wsConnected || connected}
              onDeployKey={setDeployKey}
              onRefresh={refresh}
              onDeploy={deploy}
            />
          </div>

          {/* Stage Chart — full width */}
          <div style={{ gridColumn: "1 / -1" }} className="animate-fade-in" style={{ animationDelay: "0.15s" }}>
            <StageChart labels={stageChart.labels} values={stageChart.values} status={status} />
          </div>

          {/* Agent Logs — full width */}
          {pipelineId && (
            <div style={{ gridColumn: "1 / -1" }} className="animate-scale-in">
              <AgentLogs lines={logLines} connected={wsConnected || connected} />
            </div>
          )}

          {/* Monitoring */}
          {pipelineId && (
            <div className="animate-fade-in" style={{ animationDelay: "0.2s" }}>
              <Monitoring
                logs={monLogs}
                onLogs={setMonLogs}
                onAnalyze={runAnalyze}
                loading={loading}
                result={monResult}
                pipelineId={pipelineId}
              />
            </div>
          )}

          {/* Agent Artifacts */}
          {pipelineId && (
            <div className="animate-fade-in" style={{ animationDelay: "0.25s" }}>
              <AgentArtifacts artifacts={artifacts} />
            </div>
          )}
        </div>
      </main>

      {/* ── Footer ── */}
      <footer style={{
        borderTop: "1px solid rgba(0,0,0,0.06)",
        padding: "1.25rem 1.5rem",
        textAlign: "center",
        fontSize: "0.75rem",
        color: "#b0a090",
        background: "rgba(255,255,255,0.5)",
      }}>
        ORION Multi-Agent DevOps Platform · Powered by Anthropic Claude Sonnet
      </footer>
    </div>
  );
}
