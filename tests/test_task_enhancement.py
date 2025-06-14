# run with `python -m pytest tests/test_task_enhancement.py -v`
# Test file for task enhancement functionality

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.views import BrowserStateSummary
from browser_use.controller.service import Controller


class TestTaskEnhancement:
	"""Test suite for task enhancement functionality during agent.run()"""

	@pytest.fixture
	def mock_llm(self):
		"""Mock LLM with proper spec for type safety"""
		mock = Mock(spec=BaseChatModel)
		mock.ainvoke = AsyncMock()
		# Add required attributes for LLM verification bypass
		mock._verified_api_keys = True
		mock._verified_tool_calling_method = 'function_calling'
		mock.model_name = 'gpt-4o'
		mock.with_structured_output = Mock(return_value=mock)
		mock.invoke = Mock()
		return mock

	@pytest.fixture
	def mock_controller(self):
		"""Mock controller with proper registry structure"""
		controller = Mock(spec=Controller)
		registry = Mock()
		registry.registry = MagicMock()
		registry.registry.actions = {}
		registry.get_prompt_description = Mock(return_value='Available actions')
		registry.create_action_model = Mock()
		controller.registry = registry
		return controller

	@pytest.fixture
	def mock_browser_session(self):
		"""Mock browser session with state summary"""
		browser_session = Mock(spec=BrowserSession)
		browser_session.get_state_summary = AsyncMock(
			return_value=BrowserStateSummary(
				url='https://example.com',
				title='Test Page',
				element_tree=MagicMock(),
				tabs=[],
				selector_map={},
				screenshot='',
			)
		)
		browser_session.get_current_page = AsyncMock()
		browser_session.stop = AsyncMock()
		return browser_session

	def test_agent_initialization_with_enhance_task_flag(self, mock_llm, mock_controller, mock_browser_session):
		"""
		Test that agent initialization stores the enhance_task flag correctly.

		This test ensures that:
		1. The enhance_task flag is stored during initialization
		2. Task enhancement does NOT happen during __init__
		3. Original task is preserved until run() is called
		"""
		# Arrange
		original_task = 'Go to Google and find OpenAI'

		# Mock the MessageManager and other dependencies
		with patch('browser_use.agent.service.MessageManager') as mock_message_manager:
			# Act
			agent = Agent(
				task=original_task,
				llm=mock_llm,
				controller=mock_controller,
				browser_session=mock_browser_session,
				enhance_task=True,
			)

			# Assert - task should still be original after initialization
			assert agent.task == original_task
			assert agent._should_enhance_task is True
			# LLM should NOT have been called during initialization
			mock_llm.ainvoke.assert_not_called()

	def test_agent_initialization_with_enhance_task_disabled(self, mock_llm, mock_controller, mock_browser_session):
		"""
		Test that agent initialization respects enhance_task=False.

		This test ensures that:
		1. The enhance_task flag is stored as False
		2. Task enhancement will be skipped during run()
		3. Original task is preserved
		"""
		# Arrange
		original_task = 'Go to Google and find OpenAI'

		# Mock the MessageManager and other dependencies
		with patch('browser_use.agent.service.MessageManager') as mock_message_manager:
			# Act
			agent = Agent(
				task=original_task,
				llm=mock_llm,
				controller=mock_controller,
				browser_session=mock_browser_session,
				enhance_task=False,
			)

			# Assert
			assert agent.task == original_task
			assert agent._should_enhance_task is False
			mock_llm.ainvoke.assert_not_called()

	@pytest.mark.asyncio
	async def test_enhance_task_async_method_directly(self, mock_llm, mock_controller, mock_browser_session):
		"""
		Test the _enhance_task_async method directly with various scenarios.

		This test ensures that:
		1. The method correctly processes enhancement requests
		2. LLM receives properly formatted prompts
		3. Enhanced content is returned correctly
		4. Method handles different task types appropriately
		"""
		# Arrange
		original_task = 'Buy iPhone'
		enhanced_content = 'Buy iPhone 15 Pro from Apple Store online, add to cart, and complete checkout with payment'

		mock_response = AIMessage(content=enhanced_content)
		mock_llm.ainvoke.return_value = mock_response

		# Mock the MessageManager and other dependencies
		with patch('browser_use.agent.service.MessageManager') as mock_message_manager:
			# Create agent
			agent = Agent(
				task='dummy task',
				llm=mock_llm,
				controller=mock_controller,
				browser_session=mock_browser_session,
			)

			# Act
			result = await agent._enhance_task_async(original_task)

			# Assert
			assert result == enhanced_content
			assert result != original_task
			mock_llm.ainvoke.assert_called_once()

			# Verify the LLM was called with correct enhancement prompt
			call_args = mock_llm.ainvoke.call_args[0][0]
			# call_args is a list of messages, get the content from the messages
			prompt_content = ''
			for msg in call_args:
				if hasattr(msg, 'content'):
					prompt_content += str(msg.content)
			assert 'task clarification specialist' in prompt_content.lower() or 'enhance' in prompt_content.lower()
			assert original_task in prompt_content

	@pytest.mark.asyncio
	async def test_enhance_task_async_failure_fallback(self, mock_llm, mock_controller, mock_browser_session):
		"""
		Test that _enhance_task_async handles failures gracefully.

		This test ensures that:
		1. When LLM enhancement fails, the original task is returned
		2. No exceptions are raised during enhancement
		3. Proper fallback behavior occurs
		"""
		# Arrange
		original_task = 'Go to Google and find OpenAI'
		mock_llm.ainvoke.side_effect = Exception('LLM enhancement failed')

		# Mock the MessageManager and other dependencies
		with patch('browser_use.agent.service.MessageManager') as mock_message_manager:
			# Create agent
			agent = Agent(
				task='dummy task',
				llm=mock_llm,
				controller=mock_controller,
				browser_session=mock_browser_session,
			)

			# Act
			result = await agent._enhance_task_async(original_task)

			# Assert - should fallback to original task
			assert result == original_task
			mock_llm.ainvoke.assert_called_once()

	@pytest.mark.asyncio
	async def test_task_enhancement_during_run_success(self, mock_llm, mock_controller, mock_browser_session):
		"""
		Test that task enhancement happens during agent.run() when enabled.

		This test ensures that:
		1. Enhancement happens at the start of run()
		2. Agent task is updated with enhanced version
		3. LLM is called for enhancement
		4. Run continues with enhanced task
		"""
		# Arrange
		original_task = 'Find Python tutorials'
		enhanced_content = 'Enhanced: Search for comprehensive Python tutorials on YouTube and return the top 3 results'

		mock_response = AIMessage(content=enhanced_content)
		mock_llm.ainvoke.return_value = mock_response

		# Mock the run method dependencies
		with (
			patch('browser_use.agent.service.MessageManager') as mock_message_manager,
			patch.object(Agent, 'step') as mock_step,
			patch.object(Agent, 'close') as mock_close,
			patch.object(Agent, '_log_agent_run') as mock_log_run,
		):
			# Mock step to return done immediately
			mock_step.side_effect = Exception('Stopping after enhancement')
			mock_close.return_value = AsyncMock()

			# Act
			agent = Agent(
				task=original_task,
				llm=mock_llm,
				controller=mock_controller,
				browser_session=mock_browser_session,
				enhance_task=True,
			)

			# Task should still be original before run
			assert agent.task == original_task

			# Start run() which should trigger enhancement
			try:
				await agent.run(max_steps=1)
			except Exception:
				pass  # Expected due to our mock

			# Assert enhancement happened
			assert agent.task == enhanced_content
			mock_llm.ainvoke.assert_called_once()

	@pytest.mark.asyncio
	async def test_task_enhancement_during_run_disabled(self, mock_llm, mock_controller, mock_browser_session):
		"""
		Test that task enhancement is skipped when enhance_task=False.

		This test ensures that:
		1. Enhancement is skipped when disabled
		2. Original task is preserved throughout run
		3. LLM is not called for enhancement
		"""
		# Arrange
		original_task = 'Find Python tutorials'

		# Mock the run method dependencies
		with (
			patch('browser_use.agent.service.MessageManager') as mock_message_manager,
			patch.object(Agent, 'step') as mock_step,
			patch.object(Agent, 'close') as mock_close,
			patch.object(Agent, '_log_agent_run') as mock_log_run,
		):
			# Mock step to return done immediately
			mock_step.side_effect = Exception('Stopping after check')
			mock_close.return_value = AsyncMock()

			# Act
			agent = Agent(
				task=original_task,
				llm=mock_llm,
				controller=mock_controller,
				browser_session=mock_browser_session,
				enhance_task=False,
			)

			# Start run() which should NOT trigger enhancement
			try:
				await agent.run(max_steps=1)
			except Exception:
				pass  # Expected due to our mock

			# Assert enhancement did NOT happen
			assert agent.task == original_task
			mock_llm.ainvoke.assert_not_called()

	@pytest.mark.asyncio
	async def test_task_enhancement_failure_during_run(self, mock_llm, mock_controller, mock_browser_session):
		"""
		Test graceful handling of enhancement failure during run().

		This test ensures that:
		1. When enhancement fails during run(), agent continues with original task
		2. No exceptions bubble up to break the run
		3. Warning is logged but execution continues
		"""
		# Arrange
		original_task = 'Navigate to shopping site'
		mock_llm.ainvoke.side_effect = Exception('Enhancement failed')

		# Mock the run method dependencies
		with (
			patch('browser_use.agent.service.MessageManager') as mock_message_manager,
			patch.object(Agent, 'step') as mock_step,
			patch.object(Agent, 'close') as mock_close,
			patch.object(Agent, '_log_agent_run') as mock_log_run,
		):
			# Mock step to return done immediately
			mock_step.side_effect = Exception('Stopping after enhancement failure')
			mock_close.return_value = AsyncMock()

			# Act
			agent = Agent(
				task=original_task,
				llm=mock_llm,
				controller=mock_controller,
				browser_session=mock_browser_session,
				enhance_task=True,
			)

			# Start run() - should handle enhancement failure gracefully
			try:
				await agent.run(max_steps=1)
			except Exception:
				pass  # Expected due to our mock

			# Assert fallback to original task after failure
			assert agent.task == original_task
			mock_llm.ainvoke.assert_called_once()

	def test_add_new_task_functionality(self, mock_llm, mock_controller, mock_browser_session):
		"""
		Test the add_new_task method functionality.

		This test ensures that:
		1. New tasks can be added to existing agent
		2. Task ID remains the same (continuous task)
		3. Message manager is updated with new task
		4. Agent state is properly updated
		"""
		# Arrange
		original_task = 'Original task'
		new_task = 'New additional task'

		# Mock the MessageManager and dependencies
		with patch('browser_use.agent.service.MessageManager') as mock_message_manager:
			# Mock the message manager instance
			mock_manager_instance = Mock()
			mock_manager_instance.add_new_task = Mock()
			mock_message_manager.return_value = mock_manager_instance

			agent = Agent(
				task=original_task,
				llm=mock_llm,
				controller=mock_controller,
				browser_session=mock_browser_session,
			)

			# Act
			agent.add_new_task(new_task)

			# Assert
			assert agent.task == new_task
			# Verify message manager received the new task
			mock_manager_instance.add_new_task.assert_called_once_with(new_task)


class TestTaskValidation:
	"""Test suite for task validation and processing"""

	@pytest.fixture
	def mock_llm(self):
		mock = Mock(spec=BaseChatModel)
		mock.ainvoke = AsyncMock()
		# Add required attributes for LLM verification bypass
		mock._verified_api_keys = True
		mock._verified_tool_calling_method = 'function_calling'
		mock.model_name = 'gpt-4o'
		mock.with_structured_output = Mock(return_value=mock)
		mock.invoke = Mock()
		return mock

	@pytest.fixture
	def mock_controller(self):
		controller = Mock(spec=Controller)
		registry = Mock()
		registry.registry = MagicMock()
		registry.registry.actions = {}
		registry.get_prompt_description = Mock(return_value='Available actions')
		registry.create_action_model = Mock()
		controller.registry = registry
		return controller

	@pytest.fixture
	def mock_browser_session(self):
		browser_session = Mock(spec=BrowserSession)
		browser_session.get_state_summary = AsyncMock()
		browser_session.get_current_page = AsyncMock()
		browser_session.stop = AsyncMock()
		return browser_session

	@pytest.mark.asyncio
	async def test_task_validation_empty_task(self, mock_llm, mock_controller, mock_browser_session):
		"""
		Test that empty tasks are handled appropriately.

		This test ensures that:
		1. Empty tasks don't break agent initialization
		2. Agent accepts empty tasks (they can get enhanced)
		3. Agent remains in valid state
		"""
		# Arrange
		mock_response = AIMessage(content='Enhanced empty task')
		mock_llm.ainvoke.return_value = mock_response

		# Mock the MessageManager and other dependencies
		with patch('browser_use.agent.service.MessageManager') as mock_message_manager:
			# Act - empty tasks should work, they can get enhanced during run
			agent = Agent(
				task='', llm=mock_llm, controller=mock_controller, browser_session=mock_browser_session, enhance_task=True
			)

			# Test the enhancement method directly
			result = await agent._enhance_task_async('')

			# Assert
			assert result == 'Enhanced empty task'

	def test_task_validation_very_long_task(self, mock_llm, mock_controller, mock_browser_session):
		"""
		Test handling of very long task descriptions.

		This test ensures that:
		1. Long tasks are handled properly
		2. No truncation occurs unexpectedly
		3. Agent processes full task content
		"""
		# Arrange
		long_task = 'Very long task ' * 1000  # Create a very long task

		# Mock the MessageManager and other dependencies
		with patch('browser_use.agent.service.MessageManager') as mock_message_manager:
			# Act - disable enhancement for this test to check original task handling
			agent = Agent(
				task=long_task, llm=mock_llm, controller=mock_controller, browser_session=mock_browser_session, enhance_task=False
			)

			# Assert
			assert agent.task == long_task
			assert len(agent.task) == len(long_task)

	def test_task_enhancement_flag_default_value(self, mock_llm, mock_controller, mock_browser_session):
		"""
		Test that the enhance_task parameter has the correct default value.

		This test ensures that:
		1. Default value for enhance_task is True
		2. Enhancement is enabled by default
		"""
		# Mock the MessageManager and other dependencies
		with patch('browser_use.agent.service.MessageManager') as mock_message_manager:
			# Act - don't specify enhance_task to test default
			agent = Agent(
				task='test task',
				llm=mock_llm,
				controller=mock_controller,
				browser_session=mock_browser_session,
			)

			# Assert - default should be True
			assert agent._should_enhance_task is True
