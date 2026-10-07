const vscode = require("vscode");
const https = require("https");
const http = require("http");

let statusBarItem;
let pollTimer;

function apiConfig() {
  const cfg = vscode.workspace.getConfiguration("orion");
  return {
    baseUrl: (cfg.get("apiUrl") || "http://127.0.0.1:8001").replace(/\/$/, ""),
    apiKey: cfg.get("apiKey") || "",
    pollSeconds: cfg.get("pollIntervalSeconds") || 30,
  };
}

function requestJson(path, options = {}) {
  const { baseUrl, apiKey } = apiConfig();
  const url = new URL(path, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  const lib = url.protocol === "https:" ? https : http;
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (apiKey) {
    headers["X-ORION-API-Key"] = apiKey;
  }
  return new Promise((resolve, reject) => {
    const req = lib.request(
      url,
      { method: options.method || "GET", headers },
      (res) => {
        let body = "";
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => {
          try {
            resolve({ status: res.statusCode, json: JSON.parse(body || "{}") });
          } catch (err) {
            reject(err);
          }
        });
      }
    );
    req.on("error", reject);
    if (options.body) {
      req.write(JSON.stringify(options.body));
    }
    req.end();
  });
}

async function refreshStatus() {
  if (!statusBarItem) return;
  try {
    const health = await requestJson("/health");
    const ready = await requestJson("/ready");
    const ok = health.status === 200 && (health.json.status === "ok" || health.json.api === "ok");
    const readyOk = ready.status === 200 && ready.json.ready;
    statusBarItem.text = ok
      ? readyOk
        ? "$(check) ORION ready"
        : "$(warning) ORION degraded"
      : "$(error) ORION down";
    statusBarItem.tooltip = `ORION ${apiConfig().baseUrl}`;
  } catch (err) {
    statusBarItem.text = "$(error) ORION unreachable";
    statusBarItem.tooltip = String(err);
  }
}

async function showRuns() {
  const resp = await requestJson("/api/v1/pipeline/runs?limit=15");
  if (resp.status !== 200) {
    vscode.window.showErrorMessage(`ORION runs failed: HTTP ${resp.status}`);
    return;
  }
  const runs = resp.json.runs || resp.json || [];
  const items = (Array.isArray(runs) ? runs : []).map((run) => ({
    label: `${run.status} · ${run.repo_full_name || run.repository || "repo"}`,
    description: (run.id || run.pipeline_run_id || "").slice(0, 8),
    detail: run.branch || "",
    run,
  }));
  const picked = await vscode.window.showQuickPick(items, {
    placeHolder: "Recent ORION pipeline runs",
  });
  if (picked) {
    const doc = await vscode.workspace.openTextDocument({
      content: JSON.stringify(picked.run, null, 2),
      language: "json",
    });
    await vscode.window.showTextDocument(doc);
  }
}

async function triggerScan() {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    vscode.window.showWarningMessage("Open a workspace folder to trigger a scan.");
    return;
  }
  const repo = await vscode.window.showInputBox({
    prompt: "Repository full name (owner/repo)",
    placeHolder: "acme/payments",
  });
  if (!repo) return;
  const branch = await vscode.window.showInputBox({
    prompt: "Branch",
    value: "main",
  });
  const commit = await vscode.window.showInputBox({
    prompt: "Commit SHA (optional — leave blank for HEAD)",
  });
  const body = { repo_full_name: repo, branch: branch || "main" };
  if (commit) body.commit_id = commit;
  const resp = await requestJson("/api/v1/pipeline/trigger", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  if (resp.status >= 200 && resp.status < 300) {
    vscode.window.showInformationMessage(
      `ORION pipeline queued: ${resp.json.pipeline_run_id || "ok"}`
    );
  } else {
    vscode.window.showErrorMessage(`Trigger failed: HTTP ${resp.status}`);
  }
}

function openUrl(path) {
  const { baseUrl } = apiConfig();
  vscode.env.openExternal(vscode.Uri.parse(`${baseUrl}${path}`));
}

function activate(context) {
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBarItem.command = "orion.refreshStatus";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  context.subscriptions.push(
    vscode.commands.registerCommand("orion.refreshStatus", refreshStatus),
    vscode.commands.registerCommand("orion.showRuns", showRuns),
    vscode.commands.registerCommand("orion.triggerScan", triggerScan),
    vscode.commands.registerCommand("orion.openDashboard", () => openUrl("/ui/")),
    vscode.commands.registerCommand("orion.openIntelligence", () =>
      openUrl("/api/v1/intelligence/dashboard")
    )
  );

  refreshStatus();
  const { pollSeconds } = apiConfig();
  pollTimer = setInterval(refreshStatus, pollSeconds * 1000);
  context.subscriptions.push({ dispose: () => clearInterval(pollTimer) });
}

function deactivate() {
  if (pollTimer) clearInterval(pollTimer);
}

module.exports = { activate, deactivate };
