import re
from typing import Any


def run_quality_rules(code: str, diff: str, config_text: str) -> list[dict[str, Any]]:
    text = "\n".join([code or "", diff or "", config_text or ""])
    findings: list[dict[str, Any]] = []

    if re.search(r"\bTODO\b", text, flags=re.IGNORECASE):
        findings.append(
            {
                "type": "todo_left_in_code",
                "severity": "low",
                "line": "n/a",
                "fix": "Resolve TODO items or convert to tracked task references.",
                "snippet": "TODO",
            }
        )

    if re.search(r"except\s*:\s*", text):
        findings.append(
            {
                "type": "broad_exception_handler",
                "severity": "medium",
                "line": "n/a",
                "fix": "Catch specific exception types and log structured context.",
                "snippet": "except:",
            }
        )

    if re.search(r"\bprint\s*\(", text):
        findings.append(
            {
                "type": "debug_print_in_runtime_path",
                "severity": "low",
                "line": "n/a",
                "fix": "Replace print statements with structured logging.",
                "snippet": "print(...)",
            }
        )

    return findings


def run_security_rules(code: str, diff: str, config_text: str, repo_files: dict[str, str] | None = None) -> list[dict[str, Any]]:
    text = "\n".join([code or "", diff or "", config_text or ""])
    if repo_files:
        text += "\n" + "\n".join(repo_files.values())

    findings: list[dict[str, Any]] = []

    if re.search(r"SELECT\s+\*\s+FROM.+\{.+\}", text, flags=re.IGNORECASE):
        findings.append(
            {
                "type": "possible_sql_injection",
                "severity": "high",
                "line": "n/a",
                "fix": "Use parameterized queries and avoid string interpolation for SQL.",
                "snippet": "SELECT ... {user_input}",
            }
        )

    if re.search(r"\beval\s*\(", text):
        findings.append(
            {
                "type": "unsafe_eval_usage",
                "severity": "high",
                "line": "n/a",
                "fix": "Remove eval usage and parse input with safe parsers.",
                "snippet": "eval(...)",
            }
        )

    if re.search(r"\b(secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"]+['\"]", text, flags=re.IGNORECASE):
        findings.append(
            {
                "type": "hardcoded_secret",
                "severity": "high",
                "line": "n/a",
                "fix": "Move secrets to environment variables or secret manager.",
                "snippet": "secret='...'",
            }
        )

    if re.search(r"debug\s*:\s*true", text, flags=re.IGNORECASE):
        findings.append(
            {
                "type": "debug_mode_enabled",
                "severity": "medium",
                "line": "n/a",
                "fix": "Disable debug mode in deployed environments.",
                "snippet": "debug: true",
            }
        )

    return findings
