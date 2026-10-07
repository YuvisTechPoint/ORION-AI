from core.heuristic_llm import heuristic_for_agent
from core.llm_client import LLMClient
from core.config import Settings


def test_monitoring_heuristic_extracts_anomalies() -> None:
    prompt = "Logs:\nERROR timeout connecting to database\nINFO ok\n"
    result = heuristic_for_agent("monitoring", prompt)
    assert "timeout" in " ".join(result["anomalies"]).lower()
    assert result["suggestions"]


def test_llm_client_mock_mode_uses_heuristic() -> None:
    client = LLMClient(Settings(LLM_MODE="mock"))
    result = client.generate("Logs:\nERROR payment webhook signature mismatch\n", agent_name="monitoring")
    assert result["anomalies"]
