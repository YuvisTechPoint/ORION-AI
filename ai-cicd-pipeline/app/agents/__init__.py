"""AI agents for the ORION pipeline.

Exports are resolved lazily so importing a single agent module never drags in the
orchestrator (which imports services that import agents) and creates an import cycle.
"""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ApprovalAgent": "app.agents.approval_agent",
    "BaseAgent": "app.agents.base_agent",
    "CodeAnalysisAgent": "app.agents.code_analysis_agent",
    "DeploymentAgent": "app.agents.deployment_agent",
    "FullScanOrchestrator": "app.agents.full_scan_orchestrator",
    "MonitoringAgent": "app.agents.monitoring_agent",
    "PipelineOrchestrator": "app.agents.orchestrator",
    "QAAgent": "app.agents.qa_agent",
    "SecurityAgent": "app.agents.security_agent",
    "StressTestAgent": "app.agents.stress_test_agent",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        return getattr(import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module 'app.agents' has no attribute {name!r}")
