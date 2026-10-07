export const STACKS = {
  hub: {
    id: "hub",
    short: "Hub",
    ui: import.meta.env.VITE_HUB_URL || "http://127.0.0.1:5180",
  },
  canonical: {
    id: "canonical",
    short: "Console",
    ui: import.meta.env.VITE_CANONICAL_UI_URL || "http://127.0.0.1:5173",
  },
  orion: {
    id: "orion",
    short: "ORION",
    ui: import.meta.env.VITE_ORION_UI_URL || "http://127.0.0.1:8001/ui/",
  },
  platform: {
    id: "platform",
    short: "Platform",
    ui: import.meta.env.VITE_DEVOPS_UI_URL || "http://127.0.0.1:3000",
  },
} as const;

export const ACTIVE_STACK = "platform";

export const VIEWS = [
  { id: "pipeline", label: "Pipeline" },
  { id: "intelligence", label: "Intelligence" },
  { id: "operations", label: "Operations" },
] as const;

export type ViewId = (typeof VIEWS)[number]["id"];
