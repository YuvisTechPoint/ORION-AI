import { useEffect, useState } from "react";
import { ACTIVE_STACK, STACKS, VIEWS } from "../config/stacks.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

function fallbackStacks() {
  return Object.values(STACKS).filter((s) => s.ui);
}

export default function NavHub({ activeView, onViewChange }) {
  const [stacks, setStacks] = useState(fallbackStacks());
  const [views, setViews] = useState(VIEWS);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/runtime/navigation`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((nav) => {
        if (!nav || !Array.isArray(nav.stacks)) return;
        setStacks(nav.stacks.filter((s) => s.ui));
        if (Array.isArray(nav.views) && nav.views.length) {
          setViews(
            nav.views.map((v) => ({
              id: v.id,
              label: v.label,
            }))
          );
        }
      })
      .catch(() => {
        /* keep static fallback */
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
            onClick={() => onViewChange(view.id)}
          >
            {view.label}
          </button>
        ))}
      </div>
    </nav>
  );
}
