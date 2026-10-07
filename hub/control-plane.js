/** Control plane panel — federated pipelines via Hub BFF */
(function () {
const CP_BASE = "/api/v1/control-plane";

async function cpFetch(path, params = {}) {
  const qs = new URLSearchParams(params);
  const url = `${CP_BASE}${path}${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

async function cpPost(path) {
  const res = await fetch(`${CP_BASE}${path}`, { method: "POST", cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail ? JSON.stringify(body.detail) : `${res.status} ${path}`);
  return body;
}

let activeEventSource = null;

function esc(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/"/g, "&quot;");
}

function statusClass(status) {
  const s = String(status || "").toLowerCase();
  if (s.includes("block") || s === "failed" || s === "rejected") return "cp-status--bad";
  if (s.includes("deploy") || s === "approved" || s === "monitoring" || s === "completed") return "cp-status--ok";
  if (s === "running" || s === "queued" || s.includes("ingest") || s.includes("analyzing")) return "cp-status--run";
  return "";
}

async function renderHealthMatrix() {
  const panel = document.getElementById("cp-health");
  if (!panel) return;
  panel.innerHTML = `<p class="cp-loading">Probing stack health…</p>`;
  try {
    const data = await cpFetch("/health");
    panel.innerHTML = (data.stacks || [])
      .map(
        (s) => `
      <div class="cp-health-card">
        <div class="cp-health-head"><span class="hub-dot ${s.health === "ok" ? "live" : "down"}"></span><strong>${esc(s.title)}</strong></div>
        <div class="cp-meta">health: ${esc(s.health)} · ready: ${esc(s.ready)} · ${s.latency_ms ?? "-"}ms</div>
        <div class="cp-meta cp-meta--mono">${esc(s.api_base)}</div>
      </div>`
      )
      .join("");
  } catch {
    panel.innerHTML = `<p class="cp-empty">Control plane API offline — restart hub with uvicorn.</p>`;
  }
}

async function loadPipelineExplorer() {
  const tbody = document.getElementById("cp-pipelines-body");
  const detail = document.getElementById("cp-detail");
  if (!tbody) return;

  const stack = document.getElementById("cp-filter-stack")?.value || "";
  const status = document.getElementById("cp-filter-status")?.value || "";
  const repo = document.getElementById("cp-filter-repo")?.value || "";

  tbody.innerHTML = `<tr><td colspan="7" class="cp-loading">Loading federated runs…</td></tr>`;
  try {
    const data = await cpFetch("/pipelines", {
      limit: 40,
      ...(stack ? { stack } : {}),
      ...(status ? { status } : {}),
      ...(repo ? { repo } : {}),
    });
    const items = data.items || [];
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="cp-empty">No pipeline runs (start stacks with run_all_stacks.ps1)</td></tr>`;
      return;
    }
    tbody.innerHTML = items
      .map(
        (r) => `
      <tr class="cp-row" data-run-id="${esc(r.id)}">
        <td><span class="cp-stack">${esc(r.stack)}</span></td>
        <td class="cp-mono">${esc(r.repository || r.project)}</td>
        <td>${esc(r.branch || "-")}</td>
        <td class="cp-mono">${esc(r.short_commit || (r.commit_sha || "").slice(0, 8) || "-")}</td>
        <td><span class="cp-status ${statusClass(r.status)}">${esc(r.status)}</span></td>
        <td class="cp-mono">${esc(r.correlation_id ? r.correlation_id.slice(0, 12) : "-")}</td>
        <td>${r.duration_seconds != null ? `${r.duration_seconds}s` : "-"}</td>
      </tr>`
      )
      .join("");

    tbody.querySelectorAll(".cp-row").forEach((row) => {
      row.addEventListener("click", () => showRunDetail(row.dataset.runId));
    });
    if (detail && !detail.dataset.loaded) {
      detail.dataset.loaded = "0";
      detail.innerHTML = `<p class="cp-hint">Select a run to inspect timeline and artifacts.</p>`;
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="cp-empty">Failed to load pipelines: ${esc(e.message)}</td></tr>`;
  }
}

async function showRunDetail(runId) {
  const detail = document.getElementById("cp-detail");
  if (!detail || !runId) return;
  detail.innerHTML = `<p class="cp-loading">Loading ${esc(runId)}…</p>`;
  try {
    const [run, timeline, artifacts, audit] = await Promise.all([
      cpFetch(`/pipelines/${encodeURIComponent(runId)}`),
      cpFetch(`/pipelines/${encodeURIComponent(runId)}/timeline`),
      cpFetch(`/pipelines/${encodeURIComponent(runId)}/artifacts`),
      cpFetch("/audit", { run_id: runId, limit: 10 }),
    ]);
    const stages = (timeline.stages || [])
      .map(
        (s) =>
          `<li class="cp-stage cp-stage--${esc(s.state)}"><span>${esc(s.label)}</span><em>${esc(s.state)}</em></li>`
      )
      .join("");
    const arts = (artifacts.artifacts || [])
      .slice(0, 12)
      .map((a) => `<li><code>${esc(a.artifact_type)}</code> ${esc(a.summary || a.verdict || "")}</li>`)
      .join("");
    const audits = (audit.events || [])
      .map((e) => `<li><code>${esc(e.action)}</code> · ${esc(e.actor || "system")} · ${esc(e.outcome || "")}</li>`)
      .join("");
    detail.innerHTML = `
      <div class="cp-detail-grid">
        <div>
          <h3>${esc(run.repository)} <span class="cp-status ${statusClass(run.status)}">${esc(run.status)}</span></h3>
          <p class="cp-meta">Stack <strong>${esc(run.stack)}</strong> · ID <code>${esc(run.native_id)}</code></p>
          <p class="cp-meta">Correlation <code>${esc(run.correlation_id || timeline.correlation_id || "-")}</code></p>
          <p class="cp-meta cp-live" id="cp-live-status">Live: connected</p>
          <div class="cp-actions">
            <button type="button" class="cp-btn cp-btn--ghost" data-action="retry" data-run-id="${esc(runId)}">Retry</button>
            <button type="button" class="cp-btn cp-btn--ghost" data-action="resume" data-run-id="${esc(runId)}">Resume</button>
            <button type="button" class="cp-btn cp-btn--ghost" data-action="cancel" data-run-id="${esc(runId)}">Cancel</button>
          </div>
          ${run.deep_link ? `<p><a href="${esc(run.deep_link)}" target="_blank" rel="noreferrer">Open in stack UI →</a></p>` : ""}
        </div>
        <div>
          <h4>Pipeline timeline</h4>
          <ol class="cp-timeline">${stages || "<li>No stages</li>"}</ol>
        </div>
        <div>
          <h4>Artifacts</h4>
          <ul class="cp-list">${arts || "<li>No artifacts indexed</li>"}</ul>
        </div>
        <div>
          <h4>Recent audit</h4>
          <ul class="cp-list">${audits || "<li>No audit events</li>"}</ul>
        </div>
      </div>`;
    detail.dataset.loaded = "1";
    detail.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const action = btn.dataset.action;
        const id = btn.dataset.runId;
        btn.disabled = true;
        try {
          await cpPost(`/pipelines/${encodeURIComponent(id)}/${action}`);
          await showRunDetail(id);
          await loadPipelineExplorer();
        } catch (e) {
          alert(e.message);
        } finally {
          btn.disabled = false;
        }
      });
    });
    subscribeRunEvents(runId);
  } catch (e) {
    detail.innerHTML = `<p class="cp-empty">${esc(e.message)}</p>`;
  }
}

function subscribeRunEvents(runId) {
  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
  }
  const live = document.getElementById("cp-live-status");
  const es = new EventSource(`${CP_BASE}/pipelines/${encodeURIComponent(runId)}/events`);
  activeEventSource = es;
  es.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data);
      if (data.status && live) {
        live.textContent = `Live: ${data.status}`;
      }
      if (data.kind === "complete") {
        es.close();
        if (live) live.textContent = "Live: complete";
        loadPipelineExplorer();
      }
    } catch {
      /* ignore */
    }
  };
  es.onerror = () => {
    if (live) live.textContent = "Live: disconnected";
    es.close();
  };
}

function wireControlPlane() {
  document.getElementById("cp-refresh")?.addEventListener("click", () => {
    renderHealthMatrix();
    loadPipelineExplorer();
  });
  ["cp-filter-stack", "cp-filter-status", "cp-filter-repo"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", loadPipelineExplorer);
    document.getElementById(id)?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") loadPipelineExplorer();
    });
  });
}

async function bootControlPlane() {
  wireControlPlane();
  await renderHealthMatrix();
  await loadPipelineExplorer();
  setInterval(() => {
    renderHealthMatrix();
    loadPipelineExplorer();
  }, 20000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootControlPlane);
} else {
  bootControlPlane();
}
})();
