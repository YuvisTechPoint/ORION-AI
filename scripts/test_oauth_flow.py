"""
Programmatic smoke test for GitHub OAuth flow.

For full end-to-end OAuth test, open http://localhost:8000 in a browser and click "Login with GitHub".
"""

import sys

import httpx

API_BASE = "http://localhost:8000"


def report(name: str, ok: bool, detail: str) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: {detail}")


def main() -> int:
    with httpx.Client(base_url=API_BASE, follow_redirects=False) as client:
        # 1. auth status should be unauthenticated without a session
        resp = client.get("/api/v1/auth/status")
        try:
            data = resp.json()
        except Exception:
            data = {}
        report("auth status (no session)", resp.status_code == 200 and not data.get("authenticated", False), str(data))

        # 2. /auth/me should be protected
        resp_me = client.get("/api/v1/auth/me")
        report("auth me protected", resp_me.status_code == 401, f"status={resp_me.status_code}")

        # 3. OAuth redirect should point to GitHub authorize
        resp_login = client.get("/api/v1/auth/github")
        location = resp_login.headers.get("location", "")
        expected_redirect = "github.com/login/oauth/authorize" in location
        report(
            "oauth login redirect",
            resp_login.status_code in {302, 307} and expected_redirect,
            f"status={resp_login.status_code}, location={location}",
        )

        # 4. Pipeline health should still be reachable
        resp_health = client.get("/api/v1/pipeline/health")
        report("pipeline health", resp_health.status_code == 200, f"status={resp_health.status_code}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
