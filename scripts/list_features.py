"""Enumerate confirmed feature file paths in this workspace.
Run: python scripts/list_features.py
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FEATURES = {
    "OAuth (GitHub)": [
        "backend/api/auth.py",
        "backend/main.py",
        "backend/.env",
        "OAUTH_INTEGRATION_GUIDE.md",
    ],
    "Multimodal Agents": [
        "backend/app/agents/multimodal/base_multimodal_agent.py",
        "backend/app/agents/multimodal/payment_agent.py",
        "backend/app/agents/multimodal/github_log_agent.py",
        "backend/app/api/routes/multimodal.py",
        "backend/tests/test_multimodal_api.py",
    ],
    "User Model + Migration": [
        "backend/models/db_models.py",
        "backend/scripts/create_user_table.py",
        "backend/services/auth.py",
    ],
    "Reverse Proxy (nginx)": [
        "nginx/nginx.conf",
        "nginx/conf.d/",
    ],
    "systemd Services": [
        "systemd/orion-api.service",
        "systemd/orion-monitor.service",
        "systemd/orion-worker.service",
    ],
    "CI / Workflows": [
        ".github/workflows/auto-delete-branches.yml",
    ],
    "Frontend Auth UI": [
        "frontend/src/App.jsx",
        "frontend/index.html",
    ],
}


def exists(path: str) -> bool:
    return (ROOT / path).exists()


def main():
    print("Confirmed feature file paths (workspace root: %s)" % ROOT)
    for feat, paths in FEATURES.items():
        print(f"\n- {feat}:")
        for p in paths:
            full = ROOT / p
            status = "OK" if full.exists() else "MISSING"
            print(f"  - {p} -> {status}")

    print("\nNote: run this script from the repo root to validate locally.")


if __name__ == '__main__':
    main()
