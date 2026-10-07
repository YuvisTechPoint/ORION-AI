"""Map stack-native pipeline statuses to a unified delivery timeline."""

from __future__ import annotations

from hub.federation.models import TimelineStage, UnifiedTimeline

ORION_STAGES: list[tuple[str, str]] = [
    ("ingesting", "Webhook / ingestion"),
    ("analyzing_code", "Code analysis"),
    ("analyzing_security", "Security scan"),
    ("running_qa", "QA / tests"),
    ("running_stress", "Stress test"),
    ("awaiting_approval", "Approval"),
    ("deploying", "Deployment"),
    ("deployed", "Verification"),
    ("monitoring", "Monitoring"),
]

CANONICAL_STAGES: list[tuple[str, str]] = [
    ("dev", "Ingestion / code analysis"),
    ("qa", "QA"),
    ("stress", "Stress"),
    ("approval", "Approval"),
    ("deployment", "Deployment"),
    ("monitoring", "Monitoring"),
    ("completed", "Complete"),
]

PLATFORM_STAGES: list[tuple[str, str]] = [
    ("pending", "Queued"),
    ("running", "Running agents"),
    ("deploying", "Deploying"),
    ("deployed", "Deployed"),
    ("monitoring", "Monitoring"),
    ("completed", "Complete"),
]

TERMINAL_FAIL = frozenset(
    {
        "failed",
        "rejected",
        "cancelled",
        "rolled_back",
        "auto_rolled_back",
        "blocked",
        "blocked_code",
        "blocked_security",
        "blocked_tests",
        "blocked_stress",
        "blocked_secrets",
        "blocked_policy",
        "blocked_injection",
        "blocked_agent_eval",
        "blocked_with_prs_sent",
    }
)


def _stage_state(stage_key: str, current: str, failed: bool) -> str:
    if current == stage_key:
        return "failed" if failed else "active"
    order_map = {k: i for i, (k, _) in enumerate(_stage_list_for(current))}
    if stage_key not in order_map or current not in order_map:
        return "pending"
    if order_map[stage_key] < order_map[current]:
        return "completed"
    if failed and order_map[stage_key] > order_map[current]:
        return "skipped"
    return "pending"


def _stage_list_for(status: str) -> list[tuple[str, str]]:
    if status.startswith("blocked_") or status in ORION_STAGES or status in {"queued", "ingesting", "approved"}:
        return ORION_STAGES
    return ORION_STAGES


def build_timeline(
    *,
    stack: str,
    run_id: str,
    native_run_id: str,
    status: str,
    current_stage: str | None = None,
    correlation_id: str | None = None,
) -> UnifiedTimeline:
    failed = status in TERMINAL_FAIL or str(status).startswith("blocked")
    if stack == "canonical":
        stages_def = CANONICAL_STAGES
        current = current_stage or status
    elif stack == "platform":
        stages_def = PLATFORM_STAGES
        current = status.lower() if isinstance(status, str) else str(status)
    else:
        stages_def = ORION_STAGES
        current = status

    stages: list[TimelineStage] = []
    passed_current = False
    for key, label in stages_def:
        if key == current:
            state = "failed" if failed else "active"
            passed_current = True
        elif not passed_current:
            state = "completed"
        else:
            state = "skipped" if failed else "pending"
        stages.append(TimelineStage(key=key, label=label, state=state))

    return UnifiedTimeline(
        stack=stack,  # type: ignore[arg-type]
        run_id=run_id,
        native_run_id=native_run_id,
        correlation_id=correlation_id,
        current_status=str(status),
        stages=stages,
    )
