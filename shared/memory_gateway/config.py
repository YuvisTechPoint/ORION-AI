"""Memory Gateway configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MemoryGatewayConfig:
    enabled: bool = True
    backend: str = "sqlite"
    sqlite_path: str = ".local/orion-memory.db"
    postgres_url: str = ""
    embedding_dims: int = 384
    min_confidence: float = 0.5
    quarantine_enabled: bool = True
    context_token_budget: int = 3000
    episodic_ttl_days: int = 365
