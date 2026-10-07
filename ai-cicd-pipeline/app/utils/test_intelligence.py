"""Test selection, flaky detection, coverage gates, and mutation target heuristics."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from app.config import settings
from app.utils.tools import repo_env, tool_cmd

_MODULE_TO_TEST = re.compile(r"^tests?/(?:test_)?(.+?)(?:_test)?\.py$", re.I)


def select_relevant_tests(changed_files: list[str], repo_path: str) -> dict[str, Any]:
    """Map changed source files to likely pytest targets."""
    root = Path(repo_path)
    tests_dir = root / "tests"
    alt_tests = root / "test"
    base = tests_dir if tests_dir.is_dir() else alt_tests if alt_tests.is_dir() else None

    if not base or not changed_files:
        return {
            "mode": "full_suite",
            "selected_tests": [],
            "reason": "no tests directory or no changed files",
            "estimated_reduction": 0,
        }

    selected: set[str] = set()
    modules: set[str] = set()

    for rel in changed_files:
        norm = rel.replace("\\", "/")
        if norm.startswith("tests/") or norm.startswith("test/"):
            selected.add(norm)
            continue
        stem = Path(norm).stem.replace(".", "_")
        modules.add(stem)
        if "/" in norm:
            modules.add(Path(norm).parent.name)

    for test_file in base.rglob("test_*.py"):
        rel = test_file.relative_to(root).as_posix()
        name = test_file.stem.lower()
        for mod in modules:
            if mod.lower() in name or mod.lower() in rel.lower():
                selected.add(rel)

    for test_file in base.rglob("*_test.py"):
        rel = test_file.relative_to(root).as_posix()
        for mod in modules:
            if mod.lower() in test_file.stem.lower():
                selected.add(rel)

    if not selected:
        return {
            "mode": "full_suite",
            "selected_tests": [],
            "reason": "no mapped tests for changed modules",
            "changed_modules": sorted(modules),
            "estimated_reduction": 0,
        }

    total_tests = len(list(base.rglob("test_*.py"))) + len(list(base.rglob("*_test.py")))
    reduction = max(0, round(100 * (1 - len(selected) / max(total_tests, 1))))

    return {
        "mode": "selected",
        "selected_tests": sorted(selected)[:80],
        "changed_modules": sorted(modules),
        "total_tests_in_repo": total_tests,
        "estimated_reduction_percent": min(95, reduction),
        "reason": f"Running {len(selected)} mapped test file(s) for {len(changed_files)} changed file(s).",
    }


def analyze_flaky_tests(
    current_report: dict[str, Any],
    historical_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify tests using historical qa_report artifacts from the same repo."""
    stats: dict[str, dict[str, int]] = {}

    def _accumulate(report: dict[str, Any]) -> None:
        for test in report.get("tests", []) if isinstance(report.get("tests"), list) else []:
            nodeid = str(test.get("nodeid", ""))
            if not nodeid:
                continue
            bucket = stats.setdefault(nodeid, {"runs": 0, "pass": 0, "fail": 0})
            bucket["runs"] += 1
            outcome = str(test.get("outcome", "")).lower()
            if outcome == "passed":
                bucket["pass"] += 1
            elif outcome in {"failed", "error"}:
                bucket["fail"] += 1

    for hist in historical_reports:
        _accumulate(hist)
    _accumulate(current_report)

    classifications: list[dict[str, Any]] = []
    for nodeid, bucket in stats.items():
        runs = bucket["runs"]
        if runs < 2:
            continue
        fail_rate = bucket["fail"] / runs
        if fail_rate == 0:
            cls = "stable"
        elif 0 < fail_rate < 0.08:
            cls = "flaky"
        elif fail_rate >= 0.5:
            cls = "consistently_failing"
        else:
            cls = "newly_failing"
        classifications.append(
            {
                "test": nodeid,
                "runs": runs,
                "pass": bucket["pass"],
                "fail": bucket["fail"],
                "flakiness_percent": round(fail_rate * 100, 2),
                "classification": cls,
                "confidence": "low" if runs < 5 else "medium" if runs < 20 else "high",
            }
        )

    flaky = [c for c in classifications if c["classification"] == "flaky"]
    return {
        "tests_tracked": len(classifications),
        "flaky_count": len(flaky),
        "flaky_tests": flaky[:20],
        "classifications": classifications[:50],
        "summary": f"Tracked {len(classifications)} test(s); {len(flaky)} flaky.",
    }


def discover_test_layout(repo_path: str) -> dict[str, Any]:
    root = Path(repo_path)
    tests_dir = root / "tests"
    alt = root / "test"
    base = tests_dir if tests_dir.is_dir() else alt if alt.is_dir() else None
    framework = "pytest" if base else "unknown"
    test_files = 0
    if base:
        test_files = len(list(base.rglob("test_*.py"))) + len(list(base.rglob("*_test.py")))
    return {
        "has_tests": base is not None,
        "tests_directory": base.name if base else None,
        "framework": framework,
        "test_file_count": test_files,
    }


def _public_functions(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    return [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")]


def identify_mutation_targets(changed_files: list[str], repo_path: str) -> dict[str, Any]:
    """Heuristic mutation-testing targets — changed code with weak test mapping."""
    root = Path(repo_path)
    selection = select_relevant_tests(changed_files, repo_path)
    selected = {t.lower() for t in selection.get("selected_tests") or []}
    targets: list[dict[str, Any]] = []

    for rel in changed_files:
        norm = rel.replace("\\", "/")
        if not norm.endswith(".py") or norm.startswith(("tests/", "test/")):
            continue
        path = root / norm
        if not path.is_file():
            continue
        stem = Path(norm).stem
        likely_tests = {f"tests/test_{stem}.py", f"test/test_{stem}.py", f"tests/{stem}_test.py"}
        has_direct_test = any(t in selected or t.lower() in selected for t in likely_tests)
        funcs = _public_functions(path)
        if not has_direct_test or len(funcs) >= 3:
            targets.append(
                {
                    "file": norm,
                    "public_functions": funcs[:12],
                    "has_direct_test_file": has_direct_test,
                    "priority": "high" if not has_direct_test else "medium",
                    "recommended_tool": "mutmut",
                }
            )

    return {
        "target_count": len(targets),
        "targets": targets[:25],
        "tools_recommended": ["mutmut", "cosmic-ray"],
        "summary": f"{len(targets)} mutation target(s) identified from changed Python modules.",
        "analysis_mode": "heuristic",
    }


def estimate_coverage_proxy(changed_files: list[str], repo_path: str) -> dict[str, Any]:
    """Proxy coverage: share of changed source modules with mapped pytest files."""
    source_files = [
        f.replace("\\", "/")
        for f in changed_files
        if f.endswith(".py") and not f.startswith(("tests/", "test/"))
    ]
    if not source_files:
        return {"percent": None, "mapped_modules": 0, "changed_modules": 0, "mode": "proxy"}

    selection = select_relevant_tests(changed_files, repo_path)
    selected = selection.get("selected_tests") or []
    mapped = 0
    for rel in source_files:
        stem = Path(rel).stem
        if any(stem.lower() in t.lower() for t in selected):
            mapped += 1
    percent = round(100 * mapped / len(source_files), 2)
    return {
        "percent": percent,
        "mapped_modules": mapped,
        "changed_modules": len(source_files),
        "mode": "proxy",
    }


def _coverage_from_qa(qa_report: dict[str, Any] | None) -> float | None:
    if not qa_report:
        return None
    cov = qa_report.get("coverage")
    if isinstance(cov, dict) and cov.get("percent") is not None:
        return float(cov["percent"])
    return None


def analyze_coverage_regression(
    *,
    current_qa: dict[str, Any] | None,
    historical_qa: list[dict[str, Any]],
    proxy: dict[str, Any] | None = None,
    min_percent: float | None = None,
    max_regression: float | None = None,
) -> dict[str, Any]:
    min_percent = settings.test_coverage_min_percent if min_percent is None else min_percent
    max_regression = settings.test_coverage_max_regression_percent if max_regression is None else max_regression

    current = _coverage_from_qa(current_qa)
    if current is None and proxy:
        current = proxy.get("percent")

    baselines = [v for v in (_coverage_from_qa(h) for h in historical_qa) if v is not None]
    baseline = round(sum(baselines) / len(baselines), 2) if baselines else None

    regression = None
    if current is not None and baseline is not None:
        regression = round(baseline - current, 2)

    violations: list[str] = []
    if current is not None and current < min_percent:
        violations.append(f"coverage {current}% below minimum {min_percent}%")
    if regression is not None and regression > max_regression:
        violations.append(f"coverage regressed {regression}% vs baseline {baseline}%")

    verdict = "fail" if violations else "pass"
    if current is None and not violations:
        verdict = "warn"

    return {
        "current_percent": current,
        "baseline_percent": baseline,
        "regression_percent": regression,
        "min_percent": min_percent,
        "max_regression_percent": max_regression,
        "violations": violations,
        "verdict": verdict,
        "summary": (
            f"Coverage {current}% (baseline {baseline}%, regression {regression}%)."
            if current is not None
            else "Coverage baseline unavailable — proxy metrics only."
        ),
    }


def probe_pytest_coverage(repo_path: str, test_targets: list[str] | None = None) -> dict[str, Any]:
    """Optional live coverage via pytest-cov when installed."""
    if not settings.test_coverage_probe_enabled:
        return {"status": "skipped", "reason": "disabled"}
    if importlib.util.find_spec("pytest_cov") is None:
        return {"status": "skipped", "reason": "pytest-cov not installed"}

    root = Path(repo_path)
    report_path = root / ".orion_coverage.json"
    targets = test_targets or [str(root / "tests")] if (root / "tests").is_dir() else [repo_path]
    cmd = tool_cmd(
        "pytest",
        *targets,
        "--cov=.",
        f"--cov-report=json:{report_path}",
        "-q",
        "--maxfail=1",
        "--tb=no",
    )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.test_coverage_probe_timeout_seconds,
            cwd=repo_path,
            env=repo_env(repo_path),
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"status": "failed", "reason": str(exc)}

    percent = None
    if report_path.is_file():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            totals = data.get("totals") or {}
            percent = round(float(totals.get("percent_covered", 0)), 2)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        finally:
            report_path.unlink(missing_ok=True)

    return {
        "status": "ok" if percent is not None else "failed",
        "percent": percent,
        "exit_code": proc.returncode,
        "reason": None if percent is not None else (proc.stderr or proc.stdout)[:300],
    }


def evaluate_test_gates(report: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = []
    flaky = (report.get("flaky_analysis") or {}).get("flaky_count", 0)
    if flaky and settings.test_flaky_gate_enabled:
        violations.append(f"{flaky} flaky test indicator(s)")

    coverage = report.get("coverage_regression") or {}
    if settings.test_coverage_gate_enabled and coverage.get("verdict") == "fail":
        violations.extend(coverage.get("violations") or [])

    contract = report.get("contract_testing") or {}
    if contract.get("verdict") == "fail":
        violations.append("contract testing failed")

    mutation = report.get("mutation_targets") or {}
    high = sum(1 for t in mutation.get("targets") or [] if t.get("priority") == "high")
    if high >= settings.test_mutation_warn_threshold:
        violations.append(f"{high} changed module(s) lack direct test files")

    if violations and settings.test_coverage_gate_enabled and any("coverage" in v for v in violations):
        gate = "fail"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"

    return {"gate_verdict": gate, "violations": violations}


def build_test_intelligence_report(
    repo_path: str,
    *,
    changed_files: list[str] | None = None,
    qa_current: dict[str, Any] | None = None,
    historical_qa: list[dict[str, Any]] | None = None,
    contract_report: dict[str, Any] | None = None,
    test_generation: dict[str, Any] | None = None,
    run_live_coverage: bool = False,
) -> dict[str, Any]:
    files = changed_files or []
    selection = select_relevant_tests(files, repo_path)
    layout = discover_test_layout(repo_path)
    flaky = analyze_flaky_tests(qa_current or {}, historical_qa or []) if qa_current else {"flaky_count": 0, "summary": "no qa report yet"}
    proxy = estimate_coverage_proxy(files, repo_path)
    coverage_live = probe_pytest_coverage(repo_path, selection.get("selected_tests")) if run_live_coverage else {"status": "skipped"}
    if coverage_live.get("status") == "ok" and qa_current is not None:
        qa_current = {**qa_current, "coverage": {"percent": coverage_live.get("percent"), "mode": "pytest-cov"}}
    coverage_reg = analyze_coverage_regression(
        current_qa=qa_current,
        historical_qa=historical_qa or [],
        proxy=proxy,
    )
    mutation = identify_mutation_targets(files, repo_path)

    report: dict[str, Any] = {
        **selection,
        "test_layout": layout,
        "flaky_analysis": flaky,
        "coverage_proxy": proxy,
        "coverage_probe": coverage_live,
        "coverage_regression": coverage_reg,
        "mutation_targets": mutation,
        "contract_testing": contract_report or {},
        "test_generation": test_generation or {},
        "analysis_mode": "heuristic",
    }
    report["gates"] = evaluate_test_gates(report)
    report["gate_verdict"] = report["gates"]["gate_verdict"]
    report["summary"] = (
        f"Test intel {report['gate_verdict']}: mode={selection.get('mode')}, "
        f"flaky={flaky.get('flaky_count', 0)}, "
        f"coverage={coverage_reg.get('current_percent') or proxy.get('percent')}%."
    )
    return report
