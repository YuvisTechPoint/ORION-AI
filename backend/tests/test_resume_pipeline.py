import pytest

from models.schemas import PipelineState, SubmitCodeRequest
from services.orchestrator import Orchestrator
from core.config import Settings


@pytest.mark.asyncio
async def test_resume_pipeline_requires_checkpoint(monkeypatch) -> None:
    settings = Settings(qa_mode="simulated", llm_mode="mock")
    orchestrator = Orchestrator(settings)
    state = PipelineState(repo_name="demo")
    state.artifacts["submit_request"] = SubmitCodeRequest(repo_name="demo", code="print('hi')").model_dump()
    orchestrator.state_store.upsert(state)

    with pytest.raises(ValueError, match="No checkpoint"):
        await orchestrator.resume_pipeline(state.pipeline_id)
