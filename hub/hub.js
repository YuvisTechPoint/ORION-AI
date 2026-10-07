const ORION_NAV_URL = "http://127.0.0.1:8001/api/v1/runtime/navigation";

let NAV_STACKS = [];
let STACKS = [
  {
    id: "canonical",
    title: "DevOps Console",
    desc: "Submit code, archives, and GitHub repos with OAuth, Auto-PR, and multimodal intelligence.",
    ui: "http://127.0.0.1:5173",
    health: "http://127.0.0.1:8000/health",
    ready: "http://127.0.0.1:8000/ready",
    intelligence: "http://127.0.0.1:8000/api/v1/intelligence/dashboard",
    metaKeys: ["qa_mode", "llm_mode", "queue_backend"],
  },
  {
    id: "orion",
    title: "ORION CI/CD",
    desc: "Nine-stage webhook pipeline with parallel full scan, simulated deploy, and live WebSocket telemetry.",
    ui: "http://127.0.0.1:8001/ui/",
    health: "http://127.0.0.1:8001/health",
    ready: "http://127.0.0.1:8001/ready",
    intelligence: "http://127.0.0.1:8001/api/v1/intelligence/dashboard",
    metaKeys: ["deploy_mode", "executor", "llm_mode"],
  },
  {
    id: "platform",
    title: "DevOps Platform",
    desc: "Celery-backed agents with inline fallback, stress testing, and production deployment modes.",
    ui: "http://127.0.0.1:3000",
    health: "http://127.0.0.1:8002/health",
    ready: "http://127.0.0.1:8002/ready",
    intelligence: "http://127.0.0.1:8002/api/intelligence/dashboard",
    metaKeys: ["deploy_mode", "executor", "redis"],
  },
];

function mapCatalogStack(s) {
  return {
    id: s.id,
    title: s.title,
    desc: s.description || s.desc || "",
    ui: s.ui,
    health: s.health,
    ready: s.ready,
    intelligence: s.intelligence,
    metaKeys: s.metaKeys || [],
  };
}

async function loadStacks() {
  const sources = [
    async () => {
      const res = await fetch("/api/v1/control-plane/catalog", { cache: "no-store" });
      if (!res.ok) return null;
      return await res.json();
    },
    async () => {
      const res = await fetch(ORION_NAV_URL, { mode: "cors", cache: "no-store" });
      if (!res.ok) return null;
      return await res.json();
    },
    async () => {
      const res = await fetch("./stacks.json", { cache: "no-store" });
      if (!res.ok) return null;
      const data = await res.json();
      if (Array.isArray(data)) {
        return {
          stacks: [
            { id: "hub", short: "Hub", title: "Command Hub", ui: "http://127.0.0.1:5180" },
            ...data.map(mapCatalogStack),
          ],
        };
      }
      return null;
    },
  ];
  for (const load of sources) {
    try {
      const catalog = await load();
      if (!catalog || !Array.isArray(catalog.stacks)) continue;
      NAV_STACKS = catalog.stacks.filter((s) => s.ui);
      const probeStacks = catalog.stacks.filter((s) => s.id !== "hub" && s.health);
      if (probeStacks.length) STACKS = probeStacks.map(mapCatalogStack);
      return;
    } catch {
      /* try next source */
    }
  }
}

function renderHubNav() {
  const nav = document.getElementById("hub-nav");
  if (!nav || !NAV_STACKS.length) return;
  nav.innerHTML =
    `<span class="hub-nav__label">Stacks</span>` +
    NAV_STACKS.map((s) => {
      const active = s.id === "hub";
      if (active) {
        return `<span class="hub-nav-pill hub-nav-pill--active" aria-current="page">${s.short || s.title}</span>`;
      }
      return `<a class="hub-nav-pill" href="${s.ui}" target="_blank" rel="noopener noreferrer" title="${s.title || s.short}">${s.short || s.title}</a>`;
    }).join("");
}

async function probe(url) {
  try {
    const res = await fetch(url, { mode: "cors", cache: "no-store" });
    if (!res.ok) return { state: "down", data: {} };
    const data = await res.json().catch(() => ({}));
    if (data.status === "ok" || data.api === "ok") return { state: "live", data };
    return { state: "live", data };
  } catch {
    return { state: "down", data: {} };
  }
}

async function probeIntelligence(url) {
  try {
    const res = await fetch(url, { mode: "cors", cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function formatMeta(stack, data) {
  if (!data || typeof data !== "object") return "";
  const parts = (stack.metaKeys || [])
    .map((key) => {
      const value = data[key];
      if (value === undefined || value === null || value === "") return null;
      return `${key}=${value}`;
    })
    .filter(Boolean);
  return parts.join(" · ");
}

function render(states) {
  const grid = document.getElementById("hub-grid");
  grid.innerHTML = STACKS.map((s, i) => {
    const { state, data } = states[i];
    const meta = formatMeta(s, data);
    return `
      <a class="hub-card" href="${s.ui}" rel="noreferrer" title="${s.title}">
        <div class="hub-card__badge"><span class="hub-dot ${state}"></span>${state === "live" ? "Online" : "Offline"}</div>
        <h2>${s.title}</h2>
        <p>${s.desc}</p>
        <div class="hub-meta">${s.ui}</div>
        ${meta ? `<div class="hub-meta hub-meta--detail">${meta}</div>` : ""}
      </a>`;
  }).join("");
}

function renderIntelligence(rows) {
  const panel = document.getElementById("hub-intel");
  if (!panel) return;
  const live = rows.filter((r) => r.data);
  if (!live.length) {
    panel.innerHTML = `<p class="hub-intel__empty">Intelligence APIs offline — start stacks with <code>.\\run_all_stacks.ps1</code></p>`;
    return;
  }

  const blockers = live.flatMap((r) => (r.data.pipelines?.top_blockers || []).slice(0, 2));
  const alerts = live.flatMap((r) =>
    (r.data.alerts || []).map((a) => ({ stack: r.stack, ...a }))
  );
  const passRates = live.map(
    (r) => `${r.stack}: ${Math.round((r.data.pipelines?.pass_rate || 0) * 100)}%`
  );

  panel.innerHTML = `
    <div class="hub-intel__grid">
      ${live
        .map(
          (r) => `
        <div class="hub-intel__card">
          <div class="hub-intel__head">
            <span class="hub-dot ${r.ready?.ready === false ? "down" : "live"}"></span>
            <strong>${r.stack}</strong>
          </div>
          <div class="hub-intel__stat">${r.data.pipelines?.total_recent || 0} recent runs</div>
          <div class="hub-intel__stat">Pass rate ${Math.round((r.data.pipelines?.pass_rate || 0) * 100)}%</div>
          <div class="hub-intel__stat">SLO success ${Math.round((r.data.slo?.success_rate || 0) * 100)}%</div>
          ${
            r.data.capabilities?.gate_fusion
              ? `<div class="hub-intel__tag">gate fusion</div>`
              : ""
          }
          ${
            r.ready?.ready === false
              ? `<div class="hub-intel__tag hub-intel__tag--warn">not ready</div>`
              : `<div class="hub-intel__tag">production ready</div>`
          }
        </div>`
        )
        .join("")}
    </div>
    ${
      alerts.length
        ? `<div class="hub-intel__alerts"><strong>SLO alerts</strong><ul>${alerts
            .slice(0, 5)
            .map((a) => `<li class="hub-intel__alert hub-intel__alert--${a.severity}"><em>${a.stack}</em> — ${a.message}</li>`)
            .join("")}</ul></div>`
        : ""
    }
    ${
      blockers.length
        ? `<div class="hub-intel__blockers"><strong>Top blockers</strong><ul>${blockers
            .slice(0, 4)
            .map((b) => `<li>${b}</li>`)
            .join("")}</ul></div>`
        : `<div class="hub-intel__blockers hub-intel__blockers--ok">No active gate violations across recent runs.</div>`
    }
    <div class="hub-intel__footer">Aggregate pass rates: ${passRates.join(" · ")}</div>
  `;
}

async function refreshIntelligence() {
  const rows = await Promise.all(
    STACKS.map(async (s) => {
      const [data, ready] = await Promise.all([
        probeIntelligence(s.intelligence),
        probeIntelligence(s.ready),
      ]);
      return { stack: s.title, data, ready };
    })
  );
  renderIntelligence(rows);
}

async function refresh() {
  const states = await Promise.all(STACKS.map((s) => probe(s.health)));
  render(states);
  await refreshIntelligence();
}

async function boot() {
  await loadStacks();
  renderHubNav();
  await refresh();
  setInterval(refresh, 15000);
}

boot();
