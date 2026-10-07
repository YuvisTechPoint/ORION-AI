"""Input validation and SSRF guards for pipeline APIs."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

from fastapi import HTTPException

from app.config import settings

_REMOTE_PREFIXES = ("https://", "http://", "ssh://", "git@")
_GIT_HOST_RE = re.compile(r"^git@([^:/]+)")
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "metadata.google.internal",
        "169.254.169.254",
    }
)


def _hostname_from_git_url(url: str) -> str | None:
    if url.startswith("git@"):
        match = _GIT_HOST_RE.match(url)
        return match.group(1).lower() if match else None
    if url.startswith(_REMOTE_PREFIXES[:2]):
        parsed = urlparse(url)
        return (parsed.hostname or "").lower() or None
    return None


def _is_blocked_host(hostname: str) -> bool:
    host = hostname.lower().strip(".")
    if not host or host in _BLOCKED_HOSTNAMES:
        return True
    if host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def validate_remote_clone_url(url: str) -> None:
    """Reject clone URLs that target private or metadata endpoints in production."""
    if not settings.is_production:
        return
    if not url.startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail="Production only accepts https:// git clone URLs for remote repositories.",
        )
    hostname = _hostname_from_git_url(url)
    if hostname and _is_blocked_host(hostname):
        raise HTTPException(status_code=400, detail="Clone URL targets a blocked host.")


def validate_branch_name(branch: str) -> None:
    if not branch or branch.startswith("-") or ".." in branch:
        raise HTTPException(status_code=400, detail="Invalid branch name.")
