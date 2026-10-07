/** Operations Center — federated SLO, fleet, incidents, and blockers */
(function () {
const CP_BASE = "/api/v1/control-plane";

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
  } catch {
    panel.innerHTML = `<p class="cp-empty">Operations center unavailable — start hub BFF and stacks.</p>`;
  }
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
