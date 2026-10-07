import httpx

API_BASE = "http://localhost:8000"

with httpx.Client(base_url=API_BASE, timeout=120.0) as client:
    data = {
        "repo_url": "https://github.com/octocat/Hello-World",
        "branch": "main",
        "enable_auto_pr": "false",
    }
    resp = client.post("/submit-github?force_real=true", data=data)
    print("status:", resp.status_code)
    print("text:", resp.text)
