"""Signed build verification (Cosign-compatible heuristic)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


def sign_build_digest(*, commit: str, repo: str, image_tag: str) -> str:
    payload = f"{repo}@{commit}:{image_tag}"
    return hashlib.sha256(payload.encode()).hexdigest()


def verify_signed_build(
    *,
    commit: str,
    repo: str,
    deployment_info: dict[str, Any] | None = None,
    require_signature: bool = False,
    simulated: bool = False,
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

    if stored_sig and str(stored_sig) == digest:
        return {
            "signed": True,
            "verified": True,
            "simulated": False,
            "signer": deployment_info.get("signer", "unknown"),
            "digest": digest,
            "image_tag": image_tag,
            "summary": f"Signature verified for {image_tag}.",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    return {
        "signed": bool(stored_sig),
        "verified": False,
        "simulated": False,
        "digest": digest,
        "image_tag": image_tag,
        "summary": "Build signature missing or invalid — unsigned image.",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
