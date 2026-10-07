"""Fetch public GitHub repository file tree and contents for agent context."""

from __future__ import annotations

import base64
import io
import os
import re
import zipfile
from typing import Any

import requests

from app.config import get_settings

EXTS = {".py", ".js", ".ts", ".go", ".java", ".sol"}
MAX_FILES = 20
MAX_CHARS_PER_FILE = 3000
MAX_TOTAL_CHARS = 50000


def parse_github_url(url: str) -> tuple[str, str, str]:
    """Return owner, repo, branch (default main)."""
    url = url.strip().rstrip("/")
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)", url)
    if not m:
        raise ValueError("Invalid GitHub URL")
    owner, repo = m.group(1), m.group(2).replace(".git", "")
    branch = "main"
    if "/tree/" in url:
        tail = url.split("/tree/", 1)[1]
        branch = tail.split("/")[0] if tail else branch
    return owner, repo, branch


def fetch_repo_snapshot(repo_url: str) -> dict[str, Any]:
    settings = get_settings()
    owner, repo, branch = parse_github_url(repo_url)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    api = f"https://api.github.com/repos/{owner}/{repo}"
    r = requests.get(api, headers=headers, timeout=60)
    r.raise_for_status()
    repo_data = r.json()
    default_branch = repo_data.get("default_branch") or branch

    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
    tr = requests.get(tree_url, headers=headers, timeout=60)
    tr.raise_for_status()
    tree = tr.json().get("tree") or []

    files_meta = [x for x in tree if x.get("type") == "blob"]
    candidates: list[str] = []
    for item in files_meta:
        path = item.get("path") or ""
        if any(path.endswith(ext) for ext in EXTS):
            candidates.append(path)

    snapshot_files: list[dict[str, str]] = []
    total = 0
    for path in candidates:
        if len(snapshot_files) >= MAX_FILES:
            break
        content_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        cr = requests.get(content_url, headers=headers, params={"ref": default_branch}, timeout=30)
        if cr.status_code != 200:
            continue
        cj = cr.json()
        if cj.get("encoding") != "base64":
            continue
        raw = base64.b64decode(cj.get("content", "")).decode("utf-8", errors="replace")
        chunk = raw[:MAX_CHARS_PER_FILE]
        if total + len(chunk) > MAX_TOTAL_CHARS:
            break
        snapshot_files.append({"path": path, "content": chunk})
        total += len(chunk)

    return {
        "repo": f"{owner}/{repo}",
        "default_branch": default_branch,
        "files": snapshot_files,
        "total_chars": total,
    }


def fetch_zipball_to_temp(repo_url: str, temp_dir: str) -> tuple[str, str]:
    """Download zipball, extract to temp_dir. Returns (short_sha, inner_project_path)."""
    settings = get_settings()
    owner, repo, branch = parse_github_url(repo_url)
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    zip_url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{branch}"
    zr = requests.get(zip_url, headers=headers, timeout=180, stream=True)
    zr.raise_for_status()

    buf = io.BytesIO()
    for chunk in zr.iter_content(65536):
        buf.write(chunk)
    buf.seek(0)

    short_sha = "unknown"
    inner = temp_dir
    with zipfile.ZipFile(buf) as zf:
        zf.extractall(temp_dir)
        names = zf.namelist()
        if names:
            root = names[0].split("/")[0]
            inner = os.path.join(temp_dir, root)
            # org-repo-12abcdef
            m = re.search(r"-([a-f0-9]{7,})$", root)
            if m:
                short_sha = m.group(1)[:8]

    return short_sha, inner
