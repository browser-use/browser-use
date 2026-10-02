"""Forced completion must request a status the selected done schema can express."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from browser_use import Agent
from browser_use.agent.views import AgentStepInfo
from browser_use.beta import Agent as BetaAgent
from tests.ci.conftest import create_mock_llm


class OutputWithStatus(BaseModel):
	success: bool
	rows: list[str]


@pytest.mark.parametrize('structured', [False, True])
@pytest.mark.parametrize('limit', ['steps', 'failures'])
@pytest.mark.parametrize('agent_class', [Agent, BetaAgent], ids=['native', 'beta'])
async def test_forced_completion_uses_available_status_field(tmp_path: Path, structured: bool, limit: str, agent_class):
	"""Both stopping paths preserve failure reporting for structured and ordinary output."""
	agent = agent_class(
		task='Collect two records',
		llm=create_mock_llm(),
		output_model_schema=OutputWithStatus if structured else None,
		file_system_path=str(tmp_path / 'agent-files'),
	)
	if limit == 'steps':
		await agent._force_done_after_last_step(AgentStepInfo(step_number=0, max_steps=1))
	else:
		agent.state.consecutive_failures = agent.settings.max_failures
		await agent._force_done_after_failure()

	status_field = 'task_success' if structured else 'success'
	message = agent._message_manager.state.history.context_messages[-1]
	assert isinstance(message.content, str)
	assert f'set {status_field} in "done" to false' in message.content
	assert agent.AgentOutput is agent.DoneAgentOutput
	params = agent.tools.registry.registry.actions['done'].param_model
	assert status_field in params.model_json_schema()['properties']
	if structured:
		assert status_field in params.model_json_schema()['required']
	payload = (
		{'task_success': False, 'data': {'success': False, 'rows': []}}
		if structured
		else {
			'success': False,
			'text': 'The requested records are unavailable',
		}
	)
	assert params.model_validate(payload).model_dump()['success'] is False
