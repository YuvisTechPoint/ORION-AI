from app.agents.code_analysis_agent import CodeAnalysisAgent


def test_code_analysis_agent_class_exists() -> None:
    assert CodeAnalysisAgent.__name__ == "CodeAnalysisAgent"
