"""Stack adapters — normalize native APIs into control-plane models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hub.federation.catalog import stack_by_id, stack_entries
from hub.federation.client import fetch_json
from hub.federation.models import (
    FederatedPipelineList,
    StackHealth,
    UnifiedArtifact,
    UnifiedAuditEvent,
    UnifiedHealthMatrix,
    UnifiedPipelineRun,
)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _duration(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return round((b - a).total_seconds(), 2)
    except ValueError:
        return None


def _composite_id(stack: str, native_id: str) -> str:
    return f"{stack}:{native_id}"


def _parse_composite(run_id: str) -> tuple[str, str]:
    if ":" not in run_id:
        raise ValueError(f"Invalid federated run id '{run_id}'; expected stack:native_id")
    stack, native = run_id.split(":", 1)
    return stack, native


async def list_orion_runs(
    stack: dict[str, Any],
    *,
    limit: int,
    correlation_id: str | None,
    status: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> list[UnifiedPipelineRun]:
    api = (stack.get("api") or "").rstrip("/")
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    if repo:
        params["repo"] = repo
    if branch:
        params["branch"] = branch
    code, body = await fetch_json(f"{api}/api/v1/pipeline/runs", correlation_id=correlation_id, params=params)
    if code != 200 or not isinstance(body, dict):
        return []
    items = body.get("items") or body.get("runs") or []
    ui = stack.get("ui") or api
    out: list[UnifiedPipelineRun] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        native = str(row.get("id", ""))
        repo_name = str(row.get("repo_full_name") or "")
        started = _iso(row.get("created_at"))
        completed = _iso(row.get("completed_at"))
        st = str(row.get("status") or "unknown")
        failed_stage = st if st.startswith("blocked_") or st in {"failed", "rejected"} else None
        out.append(
            UnifiedPipelineRun(
                id=_composite_id("orion", native),
                stack="orion",
                native_id=native,
                project=repo_name.split("/")[-1] if repo_name else "",
                repository=repo_name,
                branch=row.get("branch"),
                commit_sha=row.get("commit_id"),
                short_commit=row.get("short_commit_id"),
                status=st,
                correlation_id=row.get("correlation_id"),
                trace_id=row.get("trace_id"),
                started_at=started,
                updated_at=_iso(row.get("updated_at")),
                completed_at=completed,
                duration_seconds=_duration(started, completed),
                failed_stage=failed_stage,
                pusher=row.get("pusher"),
                error_message=row.get("error_message"),
                deep_link=f"{ui.rstrip('/')}/#run-{native}",
            )
        )
    return out


async def list_canonical_runs(
    stack: dict[str, Any],
    *,
    limit: int,
    correlation_id: str | None,
) -> list[UnifiedPipelineRun]:
    api = (stack.get("api") or "").rstrip("/")
    code, body = await fetch_json(f"{api}/pipelines", correlation_id=correlation_id, params={"limit": limit})
    if code != 200 or not isinstance(body, list):
        return []
    ui = stack.get("ui") or api
    out: list[UnifiedPipelineRun] = []
    for row in body:
        if not isinstance(row, dict):
            continue
        native = str(row.get("pipeline_id", ""))
        repo = str(row.get("repo_name") or "")
        st = str(row.get("status") or "unknown")
        stage = str(row.get("current_stage") or "")
        started = _iso(row.get("created_at"))
        updated = _iso(row.get("updated_at"))
        out.append(
            UnifiedPipelineRun(
                id=_composite_id("canonical", native),
                stack="canonical",
                native_id=native,
                project=repo,
                repository=repo,
                status=st,
                failed_stage=stage if st.startswith("blocked") or st == "failed" else None,
                started_at=started,
                updated_at=updated,
                duration_seconds=_duration(started, updated),
                correlation_id=row.get("correlation_id"),
                deep_link=ui,
            )
        )
    return out


async def list_platform_runs(
    stack: dict[str, Any],
    *,
    limit: int,
    correlation_id: str | None,
) -> list[UnifiedPipelineRun]:
    api = (stack.get("api") or "").rstrip("/")
    code, body = await fetch_json(f"{api}/api/pipelines", correlation_id=correlation_id)
    if code != 200 or not isinstance(body, list):
        return []
    ui = stack.get("ui") or api
    out: list[UnifiedPipelineRun] = []
    for row in body[:limit]:
        if not isinstance(row, dict):
            continue
        native = str(row.get("id", ""))
        repo = str(row.get("repo_url") or "")
        st = str(row.get("status") or "unknown")
        started = _iso(row.get("created_at"))
        out.append(
            UnifiedPipelineRun(
                id=_composite_id("platform", native),
                stack="platform",
                native_id=native,
                project=repo.rstrip("/").split("/")[-1] if repo else "",
                repository=repo,
                status=st,
                failed_stage=st if st in {"blocked", "failed"} else None,
                started_at=started,
                correlation_id=row.get("correlation_id"),
                deep_link=ui,
            )
        )
    return out


async def federated_list_pipelines(
    *,
    limit: int = 30,
    stack_filter: str | None = None,
    status: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
    correlation_id: str | None = None,
) -> FederatedPipelineList:
    per_stack = max(5, limit // 3 + 1)
    items: list[UnifiedPipelineRun] = []
    for stack in stack_entries():
        sid = stack.get("id")
        if stack_filter and sid != stack_filter:
            continue
        if sid == "orion":
            rows = await list_orion_runs(
                stack, limit=per_stack, correlation_id=correlation_id, status=status, repo=repo, branch=branch
            )
        elif sid == "canonical":
            rows = await list_canonical_runs(stack, limit=per_stack, correlation_id=correlation_id)
        elif sid == "platform":
            rows = await list_platform_runs(stack, limit=per_stack, correlation_id=correlation_id)
        else:
            rows = []
        if repo:
            needle = repo.lower()
            rows = [r for r in rows if needle in (r.repository or "").lower()]
        if status:
            rows = [r for r in rows if r.status == status]
        items.extend(rows)

    items.sort(key=lambda r: r.started_at or "", reverse=True)
    items = items[:limit]
    return FederatedPipelineList(
        total=len(items),
        items=items,
        filters={"stack": stack_filter, "status": status, "repo": repo, "branch": branch, "limit": limit},
        correlation_id=correlation_id,
    )


async def get_run(stack: str, native_id: str, *, correlation_id: str | None) -> UnifiedPipelineRun | None:
    entry = stack_by_id(stack)
    if not entry:
        return None
    if stack == "orion":
        api = entry["api"].rstrip("/")
        code, body = await fetch_json(f"{api}/api/v1/pipeline/runs/{native_id}", correlation_id=correlation_id)
        if code != 200 or not isinstance(body, dict):
            return None
        ui = entry.get("ui") or api
        started = _iso(body.get("created_at"))
        completed = _iso(body.get("completed_at"))
        st = str(body.get("status") or "unknown")
        repo_name = str(body.get("repo_full_name") or "")
        return UnifiedPipelineRun(
            id=_composite_id("orion", native_id),
            stack="orion",
            native_id=native_id,
            project=repo_name.split("/")[-1] if repo_name else "",
            repository=repo_name,
            branch=body.get("branch"),
            commit_sha=body.get("commit_id"),
            short_commit=body.get("short_commit_id"),
            status=st,
            correlation_id=body.get("correlation_id"),
            trace_id=body.get("trace_id"),
            started_at=started,
            updated_at=_iso(body.get("updated_at")),
            completed_at=completed,
            duration_seconds=_duration(started, completed),
            failed_stage=st if st.startswith("blocked_") or st in {"failed", "rejected"} else None,
            pusher=body.get("pusher"),
            error_message=body.get("error_message"),
            deep_link=f"{ui.rstrip('/')}/#run-{native_id}",
        )
    if stack == "canonical":
        api = entry["api"].rstrip("/")
        code, body = await fetch_json(f"{api}/pipeline-status/{native_id}", correlation_id=correlation_id)
        if code != 200 or not isinstance(body, dict):
            return None
        repo = str(body.get("repo_name") or "")
        st = str(body.get("status") or "unknown")
        stage = str(body.get("current_stage") or "")
        return UnifiedPipelineRun(
            id=_composite_id("canonical", native_id),
            stack="canonical",
            native_id=native_id,
            project=repo,
            repository=repo,
            status=st,
            correlation_id=body.get("correlation_id"),
            trace_id=body.get("trace_id"),
            failed_stage=stage if st.startswith("blocked") or st == "failed" else None,
            deep_link=entry.get("ui"),
        )
    if stack == "platform":
        api = entry["api"].rstrip("/")
        code, body = await fetch_json(f"{api}/api/pipeline/{native_id}", correlation_id=correlation_id)
        if code != 200 or not isinstance(body, dict):
            return None
        repo = str(body.get("repo_url") or "")
        st = str(body.get("status") or "unknown")
        meta = body.get("metadata_json") if isinstance(body.get("metadata_json"), dict) else {}
        return UnifiedPipelineRun(
            id=_composite_id("platform", native_id),
            stack="platform",
            native_id=native_id,
            project=repo.rstrip("/").split("/")[-1] if repo else "",
            repository=repo,
            commit_sha=body.get("commit_sha"),
            status=st,
            correlation_id=meta.get("correlation_id"),
            trace_id=meta.get("trace_id"),
            started_at=_iso(body.get("created_at")),
            failed_stage=st if st in {"blocked", "failed"} else None,
            deep_link=entry.get("ui"),
        )
    return None


async def list_artifacts(
    run_id: str,
    *,
    correlation_id: str | None,
) -> list[UnifiedArtifact]:
    stack, native = _parse_composite(run_id)
    entry = stack_by_id(stack)
    if not entry:
        return []
    api = entry["api"].rstrip("/")
    if stack == "orion":
        code, body = await fetch_json(f"{api}/api/v1/pipeline/runs/{native}/artifacts", correlation_id=correlation_id)
        if code != 200 or not isinstance(body, dict):
            return []
        artifacts = body.get("artifacts") or body.get("items") or []
    elif stack == "platform":
        code, body = await fetch_json(f"{api}/api/pipeline/{native}", correlation_id=correlation_id)
        if code != 200 or not isinstance(body, dict):
            return []
        artifacts = []
        for sr in body.get("stage_results") or []:
            if isinstance(sr, dict):
                artifacts.append(
                    {
                        "artifact_type": sr.get("stage_name") or "stage_result",
                        "summary": sr.get("status"),
                        "verdict": sr.get("status"),
                        "created_at": sr.get("finished_at"),
                    }
                )
    else:
        code, body = await fetch_json(f"{api}/pipeline-status/{native}", correlation_id=correlation_id)
        if code != 200 or not isinstance(body, dict):
            return []
        raw = body.get("artifacts") if isinstance(body.get("artifacts"), dict) else {}
        artifacts = [{"artifact_type": k, "content": v} for k, v in raw.items()]

    out: list[UnifiedArtifact] = []
    for idx, art in enumerate(artifacts):
        if not isinstance(art, dict):
            continue
        atype = str(art.get("artifact_type") or art.get("type") or f"artifact_{idx}")
        out.append(
            UnifiedArtifact(
                id=f"{run_id}:{atype}",
                stack=stack,  # type: ignore[arg-type]
                run_id=run_id,
                native_run_id=native,
                artifact_type=atype,
                summary=str(art.get("summary") or "") or None,
                verdict=str(art.get("verdict") or "") or None,
                created_at=_iso(art.get("created_at")),
                correlation_id=correlation_id,
            )
        )
    return out


async def get_artifact(run_id: str, artifact_type: str, *, correlation_id: str | None) -> dict[str, Any]:
    stack, native = _parse_composite(run_id)
    entry = stack_by_id(stack)
    if not entry:
        return {}
    api = entry["api"].rstrip("/")
    if stack == "orion":
        code, body = await fetch_json(
            f"{api}/api/v1/pipeline/runs/{native}/artifacts/{artifact_type}",
            correlation_id=correlation_id,
        )
        return body if code == 200 and isinstance(body, dict) else {}
    if stack == "canonical":
        code, body = await fetch_json(f"{api}/pipeline-status/{native}", correlation_id=correlation_id)
        if code == 200 and isinstance(body, dict):
            arts = body.get("artifacts") or {}
            if isinstance(arts, dict) and artifact_type in arts:
                return {"artifact_type": artifact_type, "content": arts[artifact_type]}
    return {}


async def list_audit(
    *,
    run_id: str | None = None,
    stack_filter: str | None = None,
    action: str | None = None,
    correlation_id: str | None = None,
    limit: int = 50,
) -> list[UnifiedAuditEvent]:
    events: list[UnifiedAuditEvent] = []
    if run_id:
        stack, native = _parse_composite(run_id)
        stacks = [stack_by_id(stack)] if stack_by_id(stack) else []
    else:
        stacks = [s for s in stack_entries() if not stack_filter or s.get("id") == stack_filter]

    for stack in stacks:
        if not stack:
            continue
        sid = stack.get("id")
        api = (stack.get("api") or "").rstrip("/")
        native = run_id.split(":", 1)[1] if run_id and run_id.startswith(f"{sid}:") else None
        if sid == "orion" and native:
            code, body = await fetch_json(f"{api}/api/v1/pipeline/runs/{native}/audit", correlation_id=correlation_id)
            if code == 200 and isinstance(body, dict):
                for ev in body.get("events") or []:
                    if not isinstance(ev, dict):
                        continue
                    if action and ev.get("action") != action:
                        continue
                    events.append(
                        UnifiedAuditEvent(
                            id=f"orion:{ev.get('id') or ev.get('timestamp')}",
                            stack="orion",
                            run_id=_composite_id("orion", native),
                            native_run_id=native,
                            action=str(ev.get("action") or ""),
                            actor=ev.get("actor") or ev.get("user"),
                            outcome=ev.get("outcome"),
                            timestamp=_iso(ev.get("timestamp") or ev.get("ts") or ev.get("created_at")),
                            correlation_id=(
                                (ev.get("details") or {}).get("correlation_id")
                                if isinstance(ev.get("details"), dict)
                                else ev.get("correlation_id")
                            )
                            or correlation_id,
                            details=ev.get("details") if isinstance(ev.get("details"), dict) else {},
                        )
                    )
        elif sid == "orion" and not native:
            code, body = await fetch_json(
                f"{api}/api/v1/intelligence/audit-explorer",
                correlation_id=correlation_id,
                params={"limit": limit, "action": action or None},
            )
            if code == 200 and isinstance(body, dict):
                for ev in body.get("events") or body.get("items") or []:
                    if not isinstance(ev, dict):
                        continue
                    rid = str(ev.get("run_id") or ev.get("pipeline_run_id") or "")
                    events.append(
                        UnifiedAuditEvent(
                            id=f"orion:{ev.get('id') or rid}:{ev.get('action')}",
                            stack="orion",
                            run_id=_composite_id("orion", rid) if rid else "orion:unknown",
                            native_run_id=rid or "unknown",
                            action=str(ev.get("action") or ""),
                            actor=ev.get("actor"),
                            outcome=ev.get("outcome"),
                            timestamp=_iso(ev.get("timestamp")),
                            correlation_id=ev.get("correlation_id"),
                            details=ev.get("details") if isinstance(ev.get("details"), dict) else {},
                        )
                    )
        elif sid == "canonical" and native:
            code, body = await fetch_json(f"{api}/pipelines/{native}/audit", correlation_id=correlation_id)
            if code == 200 and isinstance(body, dict):
                for ev in body.get("events") or []:
                    if isinstance(ev, dict):
                        events.append(
                            UnifiedAuditEvent(
                                id=f"canonical:{ev.get('timestamp')}:{ev.get('action')}",
                                stack="canonical",
                                run_id=_composite_id("canonical", native),
                                native_run_id=native,
                                action=str(ev.get("action") or ""),
                                actor=ev.get("actor"),
                                outcome=ev.get("outcome"),
                                timestamp=_iso(ev.get("timestamp")),
                                details=ev.get("details") if isinstance(ev.get("details"), dict) else {},
                            )
                        )
        elif sid == "platform" and native:
            code, body = await fetch_json(f"{api}/api/pipeline/{native}/audit", correlation_id=correlation_id)
            if code == 200 and isinstance(body, dict):
                for ev in body.get("events") or []:
                    if isinstance(ev, dict):
                        events.append(
                            UnifiedAuditEvent(
                                id=f"platform:{ev.get('timestamp')}:{ev.get('action')}",
                                stack="platform",
                                run_id=_composite_id("platform", native),
                                native_run_id=native,
                                action=str(ev.get("action") or ""),
                                actor=ev.get("actor"),
                                outcome=ev.get("outcome"),
                                timestamp=_iso(ev.get("timestamp")),
                                details=ev.get("details") if isinstance(ev.get("details"), dict) else {},
                            )
                        )
    events.sort(key=lambda e: e.timestamp or "", reverse=True)
    return events[:limit]


async def _probe_stack_health(
    entry: dict[str, Any],
    *,
    correlation_id: str | None,
    probe_timeout: float,
) -> StackHealth:
    import asyncio
    import time

    sid = entry.get("id")
    if sid == "hub":
        return StackHealth(
            stack="hub",
            title=str(entry.get("title") or "Command Hub"),
            api_base=(entry.get("api") or "").rstrip("/"),
            health="ok",
            ready="ok",
            health_payload={"status": "ok", "service": "orion-command-hub"},
            ready_payload={"ready": True},
            latency_ms=0.0,
        )

    api = (entry.get("api") or "").rstrip("/")
    health_url = entry.get("health") or f"{api}/health"
    ready_url = entry.get("ready") or f"{api}/ready"
    t0 = time.perf_counter()
    (h_code, h_body), (r_code, r_body) = await asyncio.gather(
        fetch_json(health_url, correlation_id=correlation_id, timeout=probe_timeout),
        fetch_json(ready_url, correlation_id=correlation_id, timeout=probe_timeout),
    )
    latency = round((time.perf_counter() - t0) * 1000, 1)
    return StackHealth(
        stack=sid,  # type: ignore[arg-type]
        title=str(entry.get("title") or sid),
        api_base=api,
        health="ok" if h_code == 200 else "down",
        ready="ok" if r_code == 200 and isinstance(r_body, dict) and r_body.get("ready", True) else "degraded",
        health_payload=h_body if isinstance(h_body, dict) else {},
        ready_payload=r_body if isinstance(r_body, dict) else {},
        latency_ms=latency,
    )


async def health_matrix(*, correlation_id: str | None) -> UnifiedHealthMatrix:
    import asyncio

    probe_timeout = 3.0
    entries = stack_entries()
    stacks = await asyncio.gather(
        *[_probe_stack_health(entry, correlation_id=correlation_id, probe_timeout=probe_timeout) for entry in entries]
    )
    return UnifiedHealthMatrix(
        generated_at=datetime.now(timezone.utc).isoformat(),
        hub_status="ok",
        stacks=list(stacks),
    )


TERMINAL_STATUSES = frozenset(
    {
        "deployed",
        "approved",
        "monitoring",
        "completed",
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
        "blocked_governance",
        "blocked_mesh",
        "blocked_finops",
        "blocked_release",
        "blocked_iam",
        "blocked_reliability",
        "blocked_dr",
        "blocked_knowledge",
        "blocked_autopilot",
        "blocked_unified_risk",
        "blocked_catalog",
        "blocked_cloud",
        "blocked_with_prs_sent",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "BLOCKED",
    }
)


def _write_url(stack: str, native_id: str, action: str) -> str | None:
    entry = stack_by_id(stack)
    if not entry:
        return None
    api = (entry.get("api") or "").rstrip("/")
    if stack == "orion":
        return f"{api}/api/v1/pipeline/runs/{native_id}/{action}"
    if stack == "canonical":
        return f"{api}/pipelines/{native_id}/{action}"
    if stack == "platform":
        return f"{api}/api/pipeline/{native_id}/{action}"
    return None


async def control_action(
    run_id: str,
    action: str,
    *,
    correlation_id: str | None,
) -> tuple[int, Any]:
    from hub.federation.client import post_json

    stack, native = _parse_composite(run_id)
    if action not in {"retry", "resume", "cancel"}:
        return 400, {"error": f"unsupported action {action}"}
    url = _write_url(stack, native, action)
    if not url:
        return 404, {"error": "unknown stack"}
    return await post_json(url, correlation_id=correlation_id)
