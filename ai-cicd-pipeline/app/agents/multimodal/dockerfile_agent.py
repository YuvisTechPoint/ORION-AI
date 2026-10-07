import re
from typing import Any

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent, as_text

DOCKERFILE_SYSTEM_PROMPT = (
    "You are a Docker expert and DevSecOps engineer. Analyze the Dockerfile, compose file, and build logs "
    "provided. Check for: base image vulnerabilities (outdated tags, EOL images), multi-stage build "
    "inefficiencies, secrets accidentally baked into layers (ENV or ARG with passwords/keys), missing "
    "`.dockerignore` entries causing large image sizes, incorrect USER directives (running as root), missing "
    "HEALTHCHECK instructions, improper COPY vs ADD usage, layer caching mistakes (COPY . . before pip "
    "install), and port exposure issues. Return ONLY valid JSON: `{\"dockerfile_issues\": [{\"line\": int, "
    '"issue_type": "security"|"performance"|"best_practice"|"error", "description": string, "current_code": '
    'string, "fixed_code": string, "severity": string}], "build_errors": [{"error_message": string, "cause": '
    'string, "fix": string}], "image_size_estimate_mb": int, "security_score": int, "optimized_dockerfile": '
    'string (the complete corrected Dockerfile), "summary": string, "estimated_size_reduction_mb": int}`'
)

AUTO_PR_SEVERITIES = {"critical", "high"}
_SEVERITY_PENALTY = {"critical": 30, "high": 15, "medium": 8, "low": 3}
_SECRET_RE = re.compile(r"^(ENV|ARG)\s+(\w*(PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|ACCESS_KEY)\w*)[\s=]+(\S+)", re.IGNORECASE)
_EOL_IMAGES = re.compile(
    r"^(python:(2|3\.[0-7])\b|node:(\d|1[0-5]|17|19)\b|ubuntu:(14|16|18)\.04|debian:(jessie|stretch|buster)|centos:)",
    re.IGNORECASE,
)
SUPPORTED_REPLACEMENTS = {
    "python": "python:3.11-slim",
    "node": "node:20-slim",
    "ubuntu": "ubuntu:22.04",
    "debian": "debian:bookworm-slim",
}
_BUILD_ERROR_HINTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"No matching distribution found for ([\w.\-]+)", re.I), "Package version not available", "Pin a version that exists on PyPI"),
    (re.compile(r"Unable to locate package ([\w.\-]+)", re.I), "apt package not found", "Run apt-get update in the same RUN layer"),
    (re.compile(r"COPY failed|failed to compute cache key|not found", re.I), "File missing from build context", "Check paths and .dockerignore"),
    (re.compile(r"returned a non-zero code|exit code: \d+", re.I), "A RUN step failed", "Run the failing command locally in the base image"),
    (re.compile(r"no space left on device", re.I), "Docker host out of disk", "docker system prune -af"),
]


def _logical_lines(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    buf, start = "", 0
    for idx, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not buf:
            start = idx
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        if buf.strip() and not buf.strip().startswith("#"):
            out.append((start, buf.strip()))
        buf = ""
    if buf.strip():
        out.append((start, buf.strip()))
    return out


def _issue(line: int, itype: str, desc: str, current: str, fixed: str, severity: str) -> dict[str, Any]:
    return {
        "line": line,
        "issue_type": itype,
        "description": desc,
        "current_code": current,
        "fixed_code": fixed,
        "severity": severity,
    }


def analyze_dockerfile(text: str, has_dockerignore: bool = True) -> list[dict[str, Any]]:
    lines = _logical_lines(text)
    issues: list[dict[str, Any]] = []
    instrs = [(n, l.split(None, 1)[0].upper(), l) for n, l in lines]
    copy_all_line = None
    first_copy_all = None
    users = [l for _, i, l in instrs if i == "USER"]

    for n, instr, line in instrs:
        arg = line.split(None, 1)[1] if " " in line else ""
        if instr in ("COPY", "ADD") and re.match(r"^(--\S+\s+)*\.\s+\S+", arg) and first_copy_all is None:
            copy_all_line = first_copy_all = n
        if instr == "FROM":
            image = arg.split()[0] if arg else ""
            if image.lower() != "scratch" and not image.startswith("$"):
                if _EOL_IMAGES.match(image):
                    fixed = SUPPORTED_REPLACEMENTS.get(image.split(":")[0].lower(), "<supported-image>")
                    issues.append(_issue(n, "security", f"End-of-life base image {image}", line, f"FROM {fixed}", "high"))
                elif ":" not in image.split("/")[-1] or image.endswith(":latest"):
                    issues.append(_issue(n, "security", f"Unpinned base image tag ({image})", line, f"FROM {image.split(':')[0]}:<pinned-version>", "medium"))
        elif instr in ("ENV", "ARG") and (m := _SECRET_RE.match(line)):
            issues.append(_issue(n, "security", f"Secret {m.group(2)} baked into image layer", line, f"# pass {m.group(2)} at runtime", "critical"))
        elif instr == "ADD" and not re.search(r"https?://|\.tar(\.gz)?\b|\.tgz\b", arg):
            issues.append(_issue(n, "best_practice", "Use COPY instead of ADD for local files", line, "COPY " + arg, "low"))
        elif instr == "RUN":
            if re.search(r"\b(pip|pip3) install\b|\bnpm (ci|install)\b|\byarn install\b", arg) and copy_all_line is not None:
                issues.append(
                    _issue(copy_all_line, "performance", "COPY . . before dependency install breaks layer caching", "COPY . .",
                           "COPY requirements.txt .  (install deps)  then COPY . .", "medium")
                )
                copy_all_line = None
            if "apt-get install" in arg and "--no-install-recommends" not in arg:
                issues.append(_issue(n, "performance", "apt-get install without --no-install-recommends", line,
                                     line.replace("apt-get install", "apt-get install --no-install-recommends"), "low"))
            if "apt-get install" in arg and "rm -rf /var/lib/apt/lists" not in arg:
                issues.append(_issue(n, "performance", "apt lists not cleaned in the same layer", line,
                                     line + " && rm -rf /var/lib/apt/lists/*", "low"))
            if re.search(r"\bpip3? install\b", arg) and "--no-cache-dir" not in arg:
                issues.append(_issue(n, "performance", "pip install without --no-cache-dir", line,
                                     re.sub(r"\b(pip3?) install\b", r"\1 install --no-cache-dir", line), "low"))
        elif instr == "EXPOSE" and re.search(r"\b22\b", arg):
            issues.append(_issue(n, "security", "SSH port 22 exposed", line, "# remove EXPOSE 22", "high"))

    if lines and (not users or users[-1].split(None, 1)[1].strip() in ("root", "0")):
        issues.append(_issue(lines[-1][0], "security", "Container runs as root", users[-1] if users else "",
                             "USER appuser", "high"))
    if lines and not any(i == "HEALTHCHECK" for _, i, _ in instrs):
        issues.append(_issue(lines[-1][0], "best_practice", "Missing HEALTHCHECK instruction", "",
                             "HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1", "medium"))
    if first_copy_all is not None and not has_dockerignore:
        issues.append(_issue(first_copy_all, "performance",
                             "COPY . . without a .dockerignore sends .git, venvs and caches into the image",
                             "COPY . .", ".dockerignore with .git, .venv, __pycache__, node_modules", "medium"))
    return issues


def _healthcheck(base_image: str, port: str) -> str:
    opts = "HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD"
    if base_image.startswith("python"):
        # slim Python images ship without curl
        return (
            f"{opts} python -c \"import urllib.request; "
            f"urllib.request.urlopen('http://localhost:{port}/health', timeout=4)\" || exit 1"
        )
    return f"{opts} curl -f http://localhost:{port}/health || exit 1"


def optimize_dockerfile(text: str) -> str:
    out: list[str] = []
    has_user = has_health = False
    port = "8000"
    base = ""
    for raw in text.splitlines():
        line = raw
        stripped = line.strip()
        upper = stripped.upper()
        if _SECRET_RE.match(stripped):
            name = _SECRET_RE.match(stripped).group(2)
            out.append(f"# {name} must be supplied at runtime (removed from image layer)")
            continue
        if upper.startswith("FROM ") and len(stripped.split()) > 1:
            image = stripped.split()[1]
            replacement = SUPPORTED_REPLACEMENTS.get(image.split(":")[0].lower()) if _EOL_IMAGES.match(image) else None
            if replacement:
                line = line.replace(image, replacement, 1)
            base = (replacement or image).lower()
        if upper.startswith("ADD ") and not re.search(r"https?://|\.tar(\.gz)?\b|\.tgz\b", stripped):
            line = re.sub(r"^(\s*)ADD\b", r"\1COPY", line, flags=re.IGNORECASE)
        if "apt-get install" in line and "--no-install-recommends" not in line:
            line = line.replace("apt-get install", "apt-get install --no-install-recommends")
        if re.search(r"\bpip3? install\b", line) and "--no-cache-dir" not in line:
            line = re.sub(r"\b(pip3?) install\b", r"\1 install --no-cache-dir", line)
        if upper.startswith("EXPOSE "):
            ports = [p for p in stripped.split()[1:] if p.split("/")[0] != "22"]
            if not ports:
                continue
            port = ports[0].split("/")[0]
            line = "EXPOSE " + " ".join(ports)
        if upper.startswith("USER ") and stripped.split()[1] not in ("root", "0"):
            has_user = True
        if upper.startswith("HEALTHCHECK"):
            has_health = True
        if upper.startswith(("CMD", "ENTRYPOINT")) and (not has_user or not has_health):
            if not has_health:
                out.append(_healthcheck(base, port))
                has_health = True
            if not has_user:
                out.append("RUN useradd --create-home --uid 1001 appuser")
                out.append("USER appuser")
                has_user = True
        out.append(line)
    if not has_health:
        out.append(_healthcheck(base, port))
    if not has_user:
        out.extend(["RUN useradd --create-home --uid 1001 appuser", "USER appuser"])
    return "\n".join(out) + "\n"


def estimate_image_size_mb(text: str) -> int:
    m = re.search(r"^\s*FROM\s+(\S+)", text, re.IGNORECASE | re.MULTILINE)
    image = (m.group(1) if m else "").lower()
    if "alpine" in image:
        return 80
    if "slim" in image or "distroless" in image:
        return 200
    if image.startswith(("python", "node", "golang", "openjdk")):
        return 1000
    return 400


class DockerfileAgent(BaseMultimodalAgent):
    artifact_type = "dockerfile_analysis"

    def __init__(
        self,
        *args: Any,
        repo_full_name: str | None = None,
        clone_url: str | None = None,
        branch: str = "main",
        github_token: str | None = None,
        dockerfile_path: str = "Dockerfile",
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.repo_full_name = repo_full_name
        self.clone_url = clone_url or (f"https://github.com/{repo_full_name}.git" if repo_full_name else "")
        self.branch = branch or "main"
        self.github_token = github_token
        self.dockerfile_path = dockerfile_path or "Dockerfile"

    def _split_artifacts(self) -> tuple[str, list[str], bool]:
        dockerfile, logs, has_ignore = "", [], False
        for art in self.text_artifacts():
            name = str(art.get("filename", "")).lower()
            content = as_text(art.get("content", ""))
            if name.endswith(".dockerignore"):
                has_ignore = True
            elif not dockerfile and ("dockerfile" in name or re.match(r"\s*(#.*\n\s*)*FROM\s", content, re.IGNORECASE)):
                dockerfile = content
            elif "compose" not in name:
                logs.append(content)
        return dockerfile, logs, has_ignore

    def _heuristic(self) -> dict[str, Any]:
        dockerfile, logs, has_ignore = self._split_artifacts()
        issues = analyze_dockerfile(dockerfile, has_dockerignore=has_ignore) if dockerfile else []
        build_errors = []
        for log in logs:
            for line in log.splitlines():
                for pattern, cause, fix in _BUILD_ERROR_HINTS:
                    if pattern.search(line) and ("error" in line.lower() or "failed" in line.lower()):
                        build_errors.append({"error_message": line.strip()[:300], "cause": cause, "fix": fix})
                        break
        score = max(0, 100 - sum(_SEVERITY_PENALTY.get(i["severity"], 0) for i in issues if i["issue_type"] == "security"))
        size = estimate_image_size_mb(dockerfile) if dockerfile else 0
        reduction = sum(30 for i in issues if i["issue_type"] == "performance")
        return {
            "dockerfile_issues": issues,
            "build_errors": build_errors[:50],
            "image_size_estimate_mb": size,
            "security_score": score,
            "optimized_dockerfile": optimize_dockerfile(dockerfile) if dockerfile else "",
            "summary": f"{len(issues)} Dockerfile issue(s), {len(build_errors)} build error(s); security score {score}/100.",
            "estimated_size_reduction_mb": min(reduction, size),
        }

    async def _maybe_open_pr(self, result: dict[str, Any]) -> dict[str, Any]:
        blocking = [
            i for i in result.get("dockerfile_issues", []) if str(i.get("severity", "")).lower() in AUTO_PR_SEVERITIES
        ]
        if not blocking:
            return {"triggered": False, "reason": "no high/critical Dockerfile issues"}
        if not self.repo_full_name or not result.get("optimized_dockerfile"):
            return {"triggered": False, "reason": "repo_full_name or optimized_dockerfile missing"}

        from app.services.auto_pr_service import AutoPRService

        try:
            service = AutoPRService(self.github_token, self.repo_full_name, self.clone_url, self.branch)
        except ValueError as exc:
            return {"triggered": False, "reason": str(exc)}
        try:
            bundle = await service.open_dockerfile_remediation_pr(
                self.dockerfile_path, result["optimized_dockerfile"], blocking, self.pipeline_run_id
            )
            if self.db is not None and self.pipeline_run_id is not None:
                async with self._db_lock():
                    await service.save_pr_registry(self.db, self.pipeline_run_id, [bundle])
            return {
                "triggered": True,
                "pr_url": bundle.pr_url,
                "pr_number": bundle.pr_number,
                "branch_name": bundle.branch_name,
                "error": bundle.error,
            }
        except Exception as exc:  # noqa: BLE001 - PR creation is best-effort
            self.logger.warning("Dockerfile auto-PR failed: %s", exc)
            return {"triggered": False, "reason": f"auto-PR failed: {exc}"}
        finally:
            await service.close()

    async def execute(self) -> dict[str, Any]:
        result = await self._analyze_json(
            DOCKERFILE_SYSTEM_PROMPT,
            "Analyze the provided Docker artifacts and return the JSON report.",
            self._heuristic(),
            required_key="dockerfile_issues",
            max_tokens=6000,
        )
        result["auto_pr"] = await self._maybe_open_pr(result)
        return await self._persist(result)
