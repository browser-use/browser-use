import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentBrain, AgentHistory, AgentOutput, ActionResult
from browser_use.browser import BrowserSession
from browser_use.controller.service import Controller

@pytest.mark.asyncio
async def test_get_next_action():
    """
    Unit test for the Agent's get_next_action method.

    This test focuses specifically on the agent's ability to correctly
    parse the LLM's response into a structured AgentOutput object.

    It ensures that:
    1. The agent can be initialized for a test setting.
    2. The 'get_next_action' method correctly processes a mocked LLM response.
    3. The resulting AgentOutput is correctly structured with the expected state and actions.
    """
    # 1. Arrange
    mock_llm = AsyncMock(spec=BaseChatModel)
    mock_controller = Controller()

    # We need a dummy Agent instance to call the method on.
    # We will still patch the __init__ methods that cause side effects.
    def mock_verify_and_setup(agent_instance):
        agent_instance.tool_calling_method = 'function_calling'

    with patch('browser_use.agent.llm_manager.LLMManager.verify_and_setup_llm', return_value='function_calling'):
        agent = Agent(
            task="test",
            llm=mock_llm,
            controller=mock_controller,
            use_vision=False,
            enable_memory=False
        )

    # Define the mock LLM's structured output
    action_model_instance = agent.ActionModel(**{"done": {"success": True, "text": "task complete"}})
    expected_brain = AgentBrain(
        page_summary="Analysis complete",
        evaluation_previous_goal="Satisfied",
        memory="N/A",
        next_goal="Complete the task"
    )
    mock_llm_response = {
        "parsed": AgentOutput(current_state=expected_brain, action=[action_model_instance]),
        "raw": "irrelevant raw response for this test"
    }

    # The structured_llm object inside get_next_action will call ainvoke
    structured_llm_mock = AsyncMock()
    structured_llm_mock.ainvoke.return_value = mock_llm_response

    # Mock the 'with_structured_output' call to return our mock
    agent.llm.with_structured_output = MagicMock(return_value=structured_llm_mock)

    input_messages = [MagicMock()] # The content of the messages doesn't matter for this test

    # 2. Act
    result_output = await agent.get_next_action(input_messages)

    # 3. Assert
    assert result_output.current_state == expected_brain
    assert len(result_output.action) == 1
    assert "done" in result_output.action[0].model_dump(exclude_unset=True)
    assert result_output.action[0].done.text == "task complete"

    # Ensure the mocks were called as expected
    agent.llm.with_structured_output.assert_called_with(agent.AgentOutput, include_raw=True, method='function_calling')
    structured_llm_mock.ainvoke.assert_called_once_with(input_messages) 