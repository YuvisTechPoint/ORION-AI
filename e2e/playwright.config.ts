import { defineConfig } from "@playwright/test";
import path from "path";

const repoRoot = path.join(__dirname, "..");
const python =
  process.platform === "win32"
    ? path.join(repoRoot, ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, ".venv", "bin", "python");

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  fullyParallel: false,
  use: {
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "hub",
      use: { baseURL: "http://127.0.0.1:5180" },
    },
  ],
  webServer: {
    command: `"${python}" -m uvicorn hub.server:app --host 127.0.0.1 --port 5180`,
    cwd: repoRoot,
    url: "http://127.0.0.1:5180/health",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
