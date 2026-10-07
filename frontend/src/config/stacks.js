/** Cross-stack URLs for ORION unified navigation (override via Vite env). */

export const STACKS = {
  hub: {
    id: "hub",
    label: "Command Hub",
    short: "Hub",
    ui: import.meta.env.VITE_HUB_URL || "http://127.0.0.1:5180",
    api: null,
  },
  canonical: {
    id: "canonical",
    label: "DevOps Console",
    short: "Console",
    ui: import.meta.env.VITE_CANONICAL_UI_URL || "http://127.0.0.1:5173",
    api: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
  },
  orion: {
    id: "orion",
    label: "ORION CI/CD",
    short: "ORION",
    ui: import.meta.env.VITE_ORION_UI_URL || "http://127.0.0.1:8001/ui/",
    api: import.meta.env.VITE_ORION_API_URL || "http://127.0.0.1:8001",
  },
  platform: {
    id: "platform",
    label: "DevOps Platform",
    short: "Platform",
    ui: import.meta.env.VITE_DEVOPS_UI_URL || "http://127.0.0.1:3000",
    api: import.meta.env.VITE_DEVOPS_API_URL || "http://127.0.0.1:8002",
  },
};

export const ACTIVE_STACK = "canonical";

export const VIEWS = [
  { id: "pipeline", label: "Pipeline" },
  { id: "intelligence", label: "Intelligence" },
  { id: "operations", label: "Operations" },
];
