"""Heuristic routing — recommend multimodal agents from uploads and pasted text."""

from __future__ import annotations

import re
from typing import Any

from app.utils.multimodal_registry import MULTIMODAL_AGENT_CATALOG, normalize_agent_id
from app.utils.text_analysis import classify_log_type

_DOCKERFILE_RE = re.compile(r"^\s*(FROM|ARG|RUN|CMD|ENTRYPOINT|WORKDIR|ENV|EXPOSE)\b", re.MULTILINE | re.IGNORECASE)
_PAYMENT_RE = re.compile(r"\b(transaction_id|stripe|paypal|charge_id|payment_status|refund)\b", re.IGNORECASE)
_GIT_LOG_RE = re.compile(r"^(commit|Author:|Date:|Merge:|    [a-f0-9]{7,40}\b)", re.MULTILINE)
_JENKINS_RE = re.compile(r"\b(Jenkins|Finished: (FAILURE|UNSTABLE)|\[Pipeline\]|hudson\.)\b", re.IGNORECASE)
_GITLAB_CI_RE = re.compile(r"\b(gitlab-runner|GitLab CI|ERROR: Job failed)\b", re.IGNORECASE)
_CIRCLECI_RE = re.compile(r"\b(CircleCI|cicleci|circle ci)\b", re.IGNORECASE)
_GITHUB_ACTIONS_RE = re.compile(r"(##\[error\]|##\[warning\]|actions/runner|workflow run)", re.IGNORECASE)
_PROMETHEUS_RE = re.compile(r"^#\s*(HELP|TYPE)\s+", re.MULTILINE)
_GRAFANA_JSON_RE = re.compile(r'"dashboard"\s*:\s*\{|"panels"\s*:\s*\[|"targets"\s*:\s*\[', re.IGNORECASE)
_K8S_DOC_RE = re.compile(r"^\s*apiVersion:\s*", re.MULTILINE)
_IMAGE_HINTS = re.compile(r"\b(outage|incident|error rate|503|500|p1|sev-?1)\b", re.IGNORECASE)


def _artifact_text(artifact: dict[str, Any]) -> str:
    content = artifact.get("content", "")
    if isinstance(content, (bytes, bytearray)):
        return bytes(content).decode("utf-8", errors="replace")
    return str(content or "")


def _filename(artifact: dict[str, Any]) -> str:
    return str(artifact.get("filename") or "").lower()


def _score(agent_id: str, points: int, reason: str, scores: dict[str, dict[str, Any]]) -> None:
    bucket = scores.setdefault(agent_id, {"agent_id": agent_id, "score": 0, "reasons": []})
    bucket["score"] += points
    if reason not in bucket["reasons"]:
        bucket["reasons"].append(reason)


def _score_text_content(
    text: str,
    *,
    fname: str,
    art_type: str,
    scores: dict[str, dict[str, Any]],
) -> None:
    if art_type == "image" or fname.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        _score("production_triage", 8, "image upload detected", scores)
        if _IMAGE_HINTS.search(text):
            _score("production_triage", 4, "incident language near image context", scores)

    if fname == "dockerfile" or "dockerfile" in fname:
        _score("dockerfile", 10, f"filename {fname}", scores)
    if _DOCKERFILE_RE.search(text[:4000]):
        _score("dockerfile", 6, "Dockerfile directives in text", scores)

    if fname.endswith(".csv") or art_type == "csv":
        _score("payment", 7, "CSV upload", scores)
    if fname.endswith(".pdf") or art_type == "pdf":
        _score("payment", 5, "PDF upload (payment or docs)", scores)
    if _PAYMENT_RE.search(text[:5000]):
        _score("payment", 8, "payment field names detected", scores)

    if _GIT_LOG_RE.search(text[:6000]):
        _score("git_logs", 8, "git log format detected", scores)

    if _PROMETHEUS_RE.search(text) or fname.endswith((".prom", ".metrics")):
        _score("metrics_snapshot", 10, "Prometheus exposition format", scores)
    if _GRAFANA_JSON_RE.search(text) or fname.endswith(".json"):
        if "panel" in text.lower() or "grafana" in text.lower():
            _score("metrics_snapshot", 8, "Grafana/dashboard JSON shape", scores)
    if _K8S_DOC_RE.search(text) or fname.endswith((".yaml", ".yml")) and "kind:" in text:
        if _K8S_DOC_RE.search(text):
            _score("kubernetes", 10, "Kubernetes manifest detected", scores)

    if _GITHUB_ACTIONS_RE.search(text):
        _score("github_actions", 9, "GitHub Actions log markers", scores)
    elif _JENKINS_RE.search(text) or _GITLAB_CI_RE.search(text) or _CIRCLECI_RE.search(text):
        _score("ci_build_log", 9, "CI platform markers in log", scores)
    elif classify_log_type(text) in {"build_error", "deployment_crash", "server_timeout"}:
        _score("log_analysis", 6, f"classified log type {classify_log_type(text)}", scores)
    elif text.strip():
        _score("log_analysis", 3, "generic log/text content", scores)


def route_multimodal_inputs(
    *,
    artifacts: list[dict[str, Any]] | None = None,
    text_input: str = "",
    preferred_agent: str | None = None,
) -> dict[str, Any]:
    artifacts = list(artifacts or [])
    combined_parts: list[str] = []
    scores: dict[str, dict[str, Any]] = {}

    if preferred_agent:
        agent_id = normalize_agent_id(preferred_agent)
        if agent_id:
            _score(agent_id, 100, f"explicit agent_type={preferred_agent}", scores)

    pasted = text_input.strip()
    if pasted:
        combined_parts.append(pasted)
        _score_text_content(pasted, fname="pasted.txt", art_type="text", scores=scores)

    for art in artifacts:
        fname = _filename(art)
        text = _artifact_text(art)
        if text:
            combined_parts.append(text[:8000])
            _score_text_content(text, fname=fname, art_type=str(art.get("type") or ""), scores=scores)

    combined = "\n".join(p for p in combined_parts if p).strip()
    if combined and not scores:
        log_kind = classify_log_type(combined)
        if log_kind == "build_error":
            _score("log_analysis", 5, "build_error classification", scores)
        elif log_kind in {"deployment_crash", "server_timeout", "memory_leak"}:
            _score("log_analysis", 5, f"{log_kind} classification", scores)
            _score("production_triage", 2, "operational incident candidate", scores)

    ranked = sorted(scores.values(), key=lambda r: (-r["score"], r["agent_id"]))
    primary = ranked[0]["agent_id"] if ranked else "log_analysis"
    secondary = [r["agent_id"] for r in ranked[1:3] if r["score"] >= 3]

    catalog_ids = {e["id"] for e in MULTIMODAL_AGENT_CATALOG}
    if primary not in catalog_ids:
        primary = "log_analysis"

    return {
        "primary_agent": primary,
        "recommended_agents": [primary, *secondary],
        "rankings": ranked,
        "combined_text_chars": len(combined),
        "summary": (
            f"Route to {primary}"
            + (f" (+ {', '.join(secondary)})" if secondary else "")
            + f" from {len(artifacts)} file(s) and {len(text_input)} pasted char(s)."
        ),
    }
