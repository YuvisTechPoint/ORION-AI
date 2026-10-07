import { useEffect, useState } from "react";
import { ACTIVE_STACK, STACKS, ViewId, VIEWS } from "../config/stacks";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8002";

type StackLink = { id: string; short?: string; title?: string; ui: string };
type ViewLink = { id: ViewId | string; label: string };

type Props = {
  activeView: ViewId;
  onViewChange: (view: ViewId) => void;
};

function fallbackStacks(): StackLink[] {
  return Object.values(STACKS);
}

export default function NavHub({ activeView, onViewChange }: Props) {
  const [stacks, setStacks] = useState<StackLink[]>(fallbackStacks());
  const [views, setViews] = useState<ViewLink[]>([...VIEWS]);

  useEffect(() => {
    fetch(`${API_BASE}/api/runtime/navigation`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((nav) => {
        if (!nav || !Array.isArray(nav.stacks)) return;
        setStacks(nav.stacks.filter((s: StackLink) => s.ui));
        if (Array.isArray(nav.views) && nav.views.length) {
          setViews(nav.views.map((v: { id: string; label: string }) => ({ id: v.id, label: v.label })));
        }
      })
      .catch(() => {
        /* static fallback */
      });
  }, []);

  return (
    <nav className="orion-nav-hub" aria-label="ORION platform navigation">
      <div className="orion-nav-hub__stacks">
        <span className="orion-nav-hub__label">Stacks</span>
        {stacks.map((stack) => {
          const active = stack.id === ACTIVE_STACK;
          const label = stack.short || stack.title;
          if (active) {
            return (
              <span
                key={stack.id}
                className="orion-nav-pill orion-nav-pill--active"
                aria-current="page"
              >
                <span className="orion-nav-pill__dot" />
                {label}
              </span>
            );
          }
          return (
            <a
              key={stack.id}
              href={stack.ui}
              className="orion-nav-pill"
              target="_blank"
              rel="noopener noreferrer"
              title={stack.title || label}
            >
              <span className="orion-nav-pill__dot" />
              {label}
            </a>
          );
        })}
      </div>
      <div className="orion-nav-hub__views">
        <span className="orion-nav-hub__label">Views</span>
        {views.map((view) => (
          <button
            key={view.id}
            type="button"
            className={`orion-nav-pill ${activeView === view.id ? "orion-nav-pill--active" : ""}`}
            onClick={() => onViewChange(view.id as ViewId)}
          >
            {view.label}
          </button>
        ))}
      </div>
    </nav>
  );
}
