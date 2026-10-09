/** Operations Center — federated SLO, fleet, incidents, and blockers */
(function () {
const CP_BASE = "/api/v1/control-plane";
let platformEventSource = null;

async function opsFetch(path) {
  const res = await fetch(`${CP_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

function esc(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/"/g, "&quot;");
}

async function renderOperationsCenter() {
  const panel = document.getElementById("ops-center");
  if (!panel) return;
  panel.innerHTML = `<p class="cp-loading">Loading operations center…</p>`;
  try {
    const data = await opsFetch("/operations");
    const slo = data.slo_summary || {};
    const fleet = data.fleet || {};
    const blockers = data.top_blockers || [];
    const alerts = data.alerts || [];
    const grid = data.service_grid || [];
    const policy = data.policy_panel || {};
    const security = data.security_panel || {};
    const performance = data.performance_panel || {};
    const memory = data.memory_panel || {};
    const platformEvents = data.platform_events || {};
    const events = platformEvents.events || [];

    panel.innerHTML = `
      <div class="ops-kpis">
        <div class="ops-kpi"><span class="ops-kpi-val">${data.active_pipelines ?? 0}</span><span class="ops-kpi-label">Active</span></div>
        <div class="ops-kpi"><span class="ops-kpi-val">${data.blocked_pipelines ?? 0}</span><span class="ops-kpi-label">Blocked</span></div>
        <div class="ops-kpi"><span class="ops-kpi-val">${data.incidents_open ?? 0}</span><span class="ops-kpi-label">Incidents</span></div>
        <div class="ops-kpi"><span class="ops-kpi-val">${slo.avg_pass_rate != null ? Math.round(slo.avg_pass_rate * 100) + "%" : "—"}</span><span class="ops-kpi-label">Avg pass rate</span></div>
        <div class="ops-kpi"><span class="ops-kpi-val">${esc(fleet.highest_risk_repo || "—")}</span><span class="ops-kpi-label">Highest risk</span></div>
      </div>
      <p class="ops-summary">${esc(data.summary)}</p>
      <div class="ops-grid">
        ${grid
          .map(
            (s) => `
          <div class="ops-card">
            <div class="ops-card-head"><span class="hub-dot ${s.health === "ok" ? "live" : "down"}"></span><strong>${esc(s.title)}</strong></div>
            <div class="cp-meta">health ${esc(s.health)} · ready ${esc(s.ready)} · ${s.latency_ms ?? "-"}ms</div>
            <div class="cp-meta">pass ${s.pass_rate != null ? Math.round(s.pass_rate * 100) + "%" : "—"} · alerts ${s.alert_count ?? 0}</div>
          </div>`
          )
          .join("")}
      </div>
      <div class="ops-columns ops-columns-3">
        <div class="ops-col">
          <h3>Policy</h3>
          <p class="cp-meta">engine ${esc(policy.policy_engine || "heuristic")} · OPA ${policy.opa_enabled ? "on" : "off"}</p>
          ${(policy.stacks || []).map((s) => `<div class="cp-meta">[${esc(s.stack)}] ${esc(s.policy_engine)}${s.opa ? " + OPA" : ""}</div>`).join("") || `<p class="cp-empty">No policy telemetry.</p>`}
        </div>
        <div class="ops-col">
          <h3>Security scanners</h3>
          <p class="cp-meta">SAST ${security.real_sast ? "bandit" : "heuristic"} · SCA ${security.real_sca ? "pip-audit" : "heuristic"}</p>
          ${(security.stacks || []).map((s) => `<div class="cp-meta">[${esc(s.stack)}] bandit=${s.bandit ? "✓" : "—"} pip-audit=${s.pip_audit ? "✓" : "—"}</div>`).join("") || `<p class="cp-empty">No scanner telemetry.</p>`}
        </div>
        <div class="ops-col">
          <h3>Performance</h3>
          <p class="cp-meta">baseline persist ${performance.baseline_persist ? "on" : "off"} · gate ${performance.baseline_gate ? "on" : "off"}</p>
          <p class="cp-meta">fleet risk ${esc(performance.fleet_highest_risk || "—")}${performance.fleet_avg_risk != null ? ` · avg ${performance.fleet_avg_risk}` : ""}</p>
        </div>
      </div>
      <div class="ops-columns ops-columns-3">
        <div class="ops-col">
          <h3>Memory & events</h3>
          <p class="cp-meta">gateway ${memory.gateway_enabled ? "on" : "off"} · event bus ${memory.event_bus_enabled ? "on" : "off"}</p>
          ${(memory.stacks || []).map((s) => `<div class="cp-meta">[${esc(s.stack)}] mem=${s.memory_gateway ? "✓" : "—"} events=${s.platform_event_bus ? "✓" : "—"}</div>`).join("") || `<p class="cp-empty">No memory telemetry.</p>`}
        </div>
        <div class="ops-col">
          <h3>Platform events</h3>
          <ul class="ops-list" id="ops-platform-events-list">
            ${events.length ? events.slice(0, 8).map((e) => `<li>${esc(e.event_type)} · ${esc(e.correlation_id || "")}</li>`).join("") : `<li class="cp-empty">No recent platform events.</li>`}
          </ul>
        </div>
        <div class="ops-col">
          <h3>Event feed status</h3>
          <p class="cp-meta">source ${esc(platformEvents.source || "—")} · count ${platformEvents.count ?? 0}</p>
          <p class="cp-meta" id="ops-platform-events-live">${platformEvents.available ? "Live SSE: connecting…" : esc(platformEvents.error || "unavailable")}</p>
        </div>
      </div>
      <div class="ops-columns">
        <div class="ops-col">
          <h3>Top blockers</h3>
          ${blockers.length ? `<ul class="ops-list">${blockers.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : `<p class="cp-empty">No blockers reported.</p>`}
        </div>
        <div class="ops-col">
          <h3>Alerts</h3>
          ${alerts.length ? `<ul class="ops-list">${alerts.map((a) => `<li>[${esc(a.stack)}] ${esc(a.code || a.message || JSON.stringify(a))}</li>`).join("")}</ul>` : `<p class="cp-empty">No active alerts.</p>`}
        </div>
      </div>`;
    wirePlatformEventStream(platformEvents.available);
  } catch {
    panel.innerHTML = `<p class="cp-empty">Operations center unavailable — start hub BFF and stacks.</p>`;
    wirePlatformEventStream(false);
  }
}

function wirePlatformEventStream(available) {
  if (platformEventSource) {
    platformEventSource.close();
    platformEventSource = null;
  }
  const statusEl = document.getElementById("ops-platform-events-live");
  const listEl = document.getElementById("ops-platform-events-list");
  if (!available || !statusEl) return;
  const es = new EventSource(`${CP_BASE}/platform-events/stream`);
  platformEventSource = es;
  es.onopen = () => {
    statusEl.textContent = "Live SSE: connected (ORION platform events)";
  };
  es.onmessage = (msg) => {
    try {
      const payload = JSON.parse(msg.data);
      if (payload.kind === "platform_event" && payload.event && listEl) {
        const e = payload.event;
        const li = document.createElement("li");
        li.textContent = `${e.event_type || "event"} · ${e.correlation_id || ""}`;
        const empty = listEl.querySelector(".cp-empty");
        if (empty) empty.remove();
        listEl.prepend(li);
        while (listEl.children.length > 12) listEl.removeChild(listEl.lastChild);
      }
      if (payload.kind === "error") {
        statusEl.textContent = `Live SSE: ${payload.message || "error"}`;
      }
    } catch {
      /* ignore malformed SSE payloads */
    }
  };
  es.onerror = () => {
    statusEl.textContent = "Live SSE: disconnected (retrying…)";
  };
}

function wireOperationsCenter() {
  document.getElementById("ops-refresh")?.addEventListener("click", renderOperationsCenter);
}

async function bootOperationsCenter() {
  wireOperationsCenter();
  await renderOperationsCenter();
  setInterval(renderOperationsCenter, 20000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootOperationsCenter);
} else {
  bootOperationsCenter();
}
})();
