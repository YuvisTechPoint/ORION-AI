import argparse

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Git Log Analyzer using backend GH CLI mode")
    parser.add_argument("--api-base", default="http://localhost:8000", help="Backend API base URL")
    parser.add_argument("--repo", required=True, help="Repository in owner/repo format")
    parser.add_argument("--pr", type=int, default=None, help="Optional pull request number")
    parser.add_argument("--commit", default="", help="Optional commit SHA")
    parser.add_argument("--branch", default="main", help="Branch for recent commit log fetch")
    parser.add_argument("--limit", type=int, default=30, help="Recent commit count (1-100)")
    parser.add_argument("--cookie", default="", help="Optional session cookie value for authenticated endpoint")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = {
        "use_gh_cli": "true",
        "repo_full_name": args.repo,
        "branch": args.branch,
        "log_limit": str(max(1, min(args.limit, 100))),
    }
    if args.pr is not None:
        payload["pr_number"] = str(args.pr)
    if args.commit.strip():
        payload["commit_sha"] = args.commit.strip()

    cookies = None
    if args.cookie.strip():
        cookies = {"session": args.cookie.strip()}

    with httpx.Client(base_url=args.api_base, timeout=120.0, cookies=cookies) as client:
        resp = client.post("/api/v1/multimodal/git-logs", data=payload)

    print("status:", resp.status_code)
    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type:
        print(resp.json())
    else:
        print(resp.text)


if __name__ == "__main__":
    main()
