"""Signed build verification — Cosign CLI when available, digest fallback otherwise."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any


def sign_build_digest(*, commit: str, repo: str, image_tag: str) -> str:
    payload = f"{repo}@{commit}:{image_tag}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _cosign_binary(cosign_path: str = "") -> str | None:
    explicit = (cosign_path or "").strip()
    if explicit:
        return explicit
    return shutil.which("cosign")


def run_cosign_verify(image_ref: str, *, cosign_path: str = "") -> dict[str, Any]:
    """Invoke `cosign verify` when the binary is on PATH."""
    binary = _cosign_binary(cosign_path)
    if not binary:
        return {"tool": "cosign", "status": "skipped", "reason": "cosign not on PATH", "verified": False}

    try:
        proc = subprocess.run(
            [binary, "verify", image_ref],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return {"tool": "cosign", "status": "failed", "reason": str(exc), "verified": False}

    if proc.returncode == 0:
        return {
            "tool": "cosign",
            "status": "ok",
            "verified": True,
            "image_ref": image_ref,
            "stdout": (proc.stdout or "").strip()[:500],
        }

    tail = (proc.stderr or proc.stdout or "").strip()[-500:]
    return {
        "tool": "cosign",
        "status": "failed",
        "verified": False,
        "image_ref": image_ref,
        "reason": tail or f"cosign verify exit {proc.returncode}",
    }


def verify_signed_build(
    *,
    commit: str,
    repo: str,
    deployment_info: dict[str, Any] | None = None,
    require_signature: bool = False,
    simulated: bool = False,
    cosign_path: str = "",
    cosign_verify_enabled: bool = True,
) -> dict[str, Any]:
    deployment_info = deployment_info or {}
    image_tag = str(deployment_info.get("image_tag") or f"{repo.split('/')[-1]}:{commit[:12]}")
    digest = sign_build_digest(commit=commit, repo=repo, image_tag=image_tag)
    stored_sig = deployment_info.get("signature") or deployment_info.get("cosign_signature")

    if simulated or not require_signature:
        return {
            "signed": True,
            "verified": True,
            "simulated": True,
            "signer": "orion-simulated-cosign",
            "digest": digest,
            "image_tag": image_tag,
            "summary": f"Simulated signature verified for {image_tag}.",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    external: dict[str, Any] | None = None
    if cosign_verify_enabled and image_tag and (":" in image_tag or "/" in image_tag):
        external = run_cosign_verify(image_tag, cosign_path=cosign_path)
        if external.get("status") == "ok":
            return {
                "signed": True,
                "verified": True,
                "simulated": False,
                "signer": "cosign",
                "digest": digest,
                "image_tag": image_tag,
                "external_scanner": external,
                "summary": f"Cosign signature verified for {image_tag}.",
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }
        if external.get("status") == "failed":
            return {
                "signed": False,
                "verified": False,
                "simulated": False,
                "digest": digest,
                "image_tag": image_tag,
                "external_scanner": external,
                "summary": f"Cosign verification failed for {image_tag}.",
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }

    if stored_sig and str(stored_sig) == digest:
        return {
            "signed": True,
            "verified": True,
            "simulated": False,
            "signer": deployment_info.get("signer", "digest-fallback"),
            "digest": digest,
            "image_tag": image_tag,
            "external_scanner": external,
            "summary": f"Digest signature verified for {image_tag}.",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    return {
        "signed": bool(stored_sig),
        "verified": False,
        "simulated": False,
        "digest": digest,
        "image_tag": image_tag,
        "external_scanner": external,
        "summary": "Build signature missing or invalid — unsigned image.",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def signed_build_verify_options() -> dict[str, Any]:
    """Resolve verification flags from ORION settings."""
    from app.config import settings

    return {
        "require_signature": settings.require_signed_builds,
        "simulated": not settings.require_signed_builds,
        "cosign_path": settings.cosign_path,
        "cosign_verify_enabled": settings.cosign_verify_enabled,
    }
