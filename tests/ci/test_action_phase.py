"""Regression tests for the LLM action phase."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.agent.pipeline import ActionPhase


@pytest.mark.asyncio
async def test_llm_timeout_keeps_original_message():
	agent = MagicMock()
	agent.settings.llm_timeout = 12
	agent.message_manager.get_messages.return_value = []
	agent.state.n_steps = 1
	agent.llm.model = 'test-model'
	agent._llm_service.get_model_output_with_retry = AsyncMock(side_effect=TimeoutError)

	phase = ActionPhase(agent, MagicMock())

	with pytest.raises(TimeoutError, match='Keep your thinking and output short'):
		await phase._get_next_action(MagicMock())
