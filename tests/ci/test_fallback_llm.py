"""
Tests for the fallback_llm feature in Agent.

Tests verify that when the primary LLM fails with rate limit (429) or server errors (503, 502, 500, 504),
the agent automatically switches to the fallback LLM and continues execution.
"""

from unittest.mock import AsyncMock

import pytest

from browser_use.agent.views import AgentOutput
from browser_use.llm import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.tools.service import Tools


def create_mock_llm(
	model_name: str = 'mock-llm',
	should_fail: bool = False,
	fail_with: type[Exception] | None = None,
	fail_status_code: int = 429,
	fail_message: str = 'Rate limit exceeded',
) -> BaseChatModel:
	"""Create a mock LLM for testing.

	Args:
		model_name: Name of the mock model
		should_fail: If True, the LLM will raise an exception
		fail_with: Exception type to raise (ModelRateLimitError or ModelProviderError)
		fail_status_code: HTTP status code for the error
		fail_message: Error message
	"""
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	AgentOutputWithActions = AgentOutput.type_with_custom_actions(ActionModel)

	llm = AsyncMock(spec=BaseChatModel)
	llm.model = model_name
	llm._verified_api_keys = True
	llm.provider = 'mock'
	llm.name = model_name
	llm.model_name = model_name

	default_done_action = """
	{
		"thinking": "null",
		"evaluation_previous_goal": "Successfully completed the task",
		"memory": "Task completed",
		"next_goal": "Task completed",
		"action": [
			{
				"done": {
					"text": "Task completed successfully",
					"success": true
				}
			}
		]
	}
	"""

	async def mock_ainvoke(*args, **kwargs):
		if should_fail:
			if fail_with == ModelRateLimitError:
				raise ModelRateLimitError(message=fail_message, status_code=fail_status_code, model=model_name)
			elif fail_with == ModelProviderError:
				raise ModelProviderError(message=fail_message, status_code=fail_status_code, model=model_name)
			else:
				raise Exception(fail_message)

		output_format = kwargs.get('output_format')
		if output_format is None:
			return ChatInvokeCompletion(completion=default_done_action, usage=None)
		else:
			parsed = output_format.model_validate_json(default_done_action)
			return ChatInvokeCompletion(completion=parsed, usage=None)

	llm.ainvoke.side_effect = mock_ainvoke

	return llm


class TestFallbackLLMParameter:
	"""Test fallback_llm parameter initialization."""

	def test_fallback_llm_none_by_default(self):
		"""Verify fallback_llm defaults to None."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		agent = Agent(task='Test task', llm=primary)

		assert agent._fallback_llm is None
		assert agent._using_fallback_llm is False
		assert agent._original_llm is primary

	def test_fallback_llm_single_model(self):
		"""Test passing a fallback LLM."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		fallback = create_mock_llm('fallback-model')

		agent = Agent(task='Test task', llm=primary, fallback_llm=fallback)

		assert agent._fallback_llm is fallback
		assert agent._using_fallback_llm is False

	def test_public_properties(self):
		"""Test the public properties for fallback status."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		fallback = create_mock_llm('fallback-model')

		agent = Agent(task='Test task', llm=primary, fallback_llm=fallback)

		# Before fallback
		assert agent.is_using_fallback_llm is False
		assert agent.current_llm_model == 'primary-model'

		# Trigger fallback
		error = ModelRateLimitError(message='Rate limit', status_code=429, model='primary')
		agent._try_switch_to_fallback_llm(error)

		# After fallback
		assert agent.is_using_fallback_llm is True
		assert agent.current_llm_model == 'fallback-model'


class TestFallbackLLMSwitching:
	"""Test the fallback switching logic in _try_switch_to_fallback_llm."""

	def test_switch_on_rate_limit_error(self):
		"""Test that agent switches to fallback on ModelRateLimitError."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		fallback = create_mock_llm('fallback-model')

		agent = Agent(task='Test task', llm=primary, fallback_llm=fallback)

		error = ModelRateLimitError(message='Rate limit exceeded', status_code=429, model='primary-model')
		result = agent._try_switch_to_fallback_llm(error)

		assert result is True
		assert agent.llm is fallback
		assert agent._using_fallback_llm is True

	def test_switch_on_503_error(self):
		"""Test that agent switches to fallback on 503 Service Unavailable."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		fallback = create_mock_llm('fallback-model')

		agent = Agent(task='Test task', llm=primary, fallback_llm=fallback)

		error = ModelProviderError(message='Service unavailable', status_code=503, model='primary-model')
		result = agent._try_switch_to_fallback_llm(error)

		assert result is True
		assert agent.llm is fallback
		assert agent._using_fallback_llm is True

	def test_switch_on_500_error(self):
		"""Test that agent switches to fallback on 500 Internal Server Error."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		fallback = create_mock_llm('fallback-model')

		agent = Agent(task='Test task', llm=primary, fallback_llm=fallback)

		error = ModelProviderError(message='Internal server error', status_code=500, model='primary-model')
		result = agent._try_switch_to_fallback_llm(error)

		assert result is True
		assert agent.llm is fallback

	def test_switch_on_502_error(self):
		"""Test that agent switches to fallback on 502 Bad Gateway."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		fallback = create_mock_llm('fallback-model')

		agent = Agent(task='Test task', llm=primary, fallback_llm=fallback)

		error = ModelProviderError(message='Bad gateway', status_code=502, model='primary-model')
		result = agent._try_switch_to_fallback_llm(error)

		assert result is True
		assert agent.llm is fallback

	def test_no_switch_on_400_error(self):
		"""Test that agent does NOT switch on 400 Bad Request (not retryable)."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		fallback = create_mock_llm('fallback-model')

		agent = Agent(task='Test task', llm=primary, fallback_llm=fallback)

		error = ModelProviderError(message='Bad request', status_code=400, model='primary-model')
		result = agent._try_switch_to_fallback_llm(error)

		assert result is False
		assert agent.llm is primary  # Still using primary
		assert agent._using_fallback_llm is False

	def test_switch_on_401_error(self):
		"""Test that agent switches to fallback on 401 Unauthorized (API key error)."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		fallback = create_mock_llm('fallback-model')

		agent = Agent(task='Test task', llm=primary, fallback_llm=fallback)

		error = ModelProviderError(message='Invalid API key', status_code=401, model='primary-model')
		result = agent._try_switch_to_fallback_llm(error)

		assert result is True
		assert agent.llm is fallback
		assert agent._using_fallback_llm is True

	def test_switch_on_402_error(self):
		"""Test that agent switches to fallback on 402 Payment Required (insufficient credits)."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		fallback = create_mock_llm('fallback-model')

		agent = Agent(task='Test task', llm=primary, fallback_llm=fallback)

		error = ModelProviderError(message='Insufficient credits', status_code=402, model='primary-model')
		result = agent._try_switch_to_fallback_llm(error)

		assert result is True
		assert agent.llm is fallback
		assert agent._using_fallback_llm is True

	def test_no_switch_when_no_fallback_configured(self):
		"""Test that agent returns False when no fallback is configured."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		agent = Agent(task='Test task', llm=primary)

		error = ModelRateLimitError(message='Rate limit exceeded', status_code=429, model='primary-model')
		result = agent._try_switch_to_fallback_llm(error)

		assert result is False
		assert agent.llm is primary

	def test_no_switch_when_already_using_fallback(self):
		"""Test that agent doesn't switch again when already using fallback."""
		from browser_use import Agent

		primary = create_mock_llm('primary-model')
		fallback = create_mock_llm('fallback-model')

		agent = Agent(task='Test task', llm=primary, fallback_llm=fallback)

		# First switch succeeds
		error = ModelRateLimitError(message='Rate limit', status_code=429, model='primary')
		result = agent._try_switch_to_fallback_llm(error)
		assert result is True
		assert agent.llm is fallback

		# Second switch fails - already using fallback
		result = agent._try_switch_to_fallback_llm(error)
		assert result is False
		assert agent.llm is fallback  # Still on fallback


class TestFallbackLLMIntegration:
	"""Integration tests for fallback LLM behavior in get_model_output."""

	def _create_failing_mock_llm(
		self,
		model_name: str,
		fail_with: type[Exception],
		fail_status_code: int = 429,
		fail_message: str = 'Rate limit exceeded',
	) -> BaseChatModel:
		"""Create a mock LLM that always fails with the specified error."""
		llm = AsyncMock(spec=BaseChatModel)
		llm.model = model_name
		llm._verified_api_keys = True
		llm.provider = 'mock'
		llm.name = model_name
		llm.model_name = model_name

		async def mock_ainvoke(*args, **kwargs):
			if fail_with == ModelRateLimitError:
				raise ModelRateLimitError(message=fail_message, status_code=fail_status_code, model=model_name)
			elif fail_with == ModelProviderError:
				raise ModelProviderError(message=fail_message, status_code=fail_status_code, model=model_name)
			else:
				raise Exception(fail_message)

		llm.ainvoke.side_effect = mock_ainvoke
		return llm

	def _create_succeeding_mock_llm(self, model_name: str, agent) -> BaseChatModel:
		"""Create a mock LLM that succeeds and returns a valid AgentOutput."""
		llm = AsyncMock(spec=BaseChatModel)
		llm.model = model_name
		llm._verified_api_keys = True
		llm.provider = 'mock'
		llm.name = model_name
		llm.model_name = model_name

		default_done_action = """
		{
			"thinking": "null",
			"evaluation_previous_goal": "Successfully completed the task",
			"memory": "Task completed",
			"next_goal": "Task completed",
			"action": [
				{
					"done": {
						"text": "Task completed successfully",
						"success": true
					}
				}
			]
		}
		"""

		# Capture the agent reference for use in the closure
		captured_agent = agent

		async def mock_ainvoke(*args, **kwargs):
			# Get the output format from kwargs and use it to parse
			output_format = kwargs.get('output_format')
			if output_format is not None:
				parsed = output_format.model_validate_json(default_done_action)
				return ChatInvokeCompletion(completion=parsed, usage=None)
			# Fallback: use the agent's AgentOutput type
			parsed = captured_agent.AgentOutput.model_validate_json(default_done_action)
			return ChatInvokeCompletion(completion=parsed, usage=None)

		llm.ainvoke.side_effect = mock_ainvoke
		return llm

	@pytest.mark.asyncio
	async def test_get_model_output_switches_to_fallback_on_rate_limit(self, browser_session):
		"""Test that get_model_output automatically switches to fallback on rate limit."""
		from browser_use import Agent

		# Create agent first with a working mock LLM
		placeholder = create_mock_llm('placeholder')
		agent = Agent(task='Test task', llm=placeholder, browser_session=browser_session)

		# Create a failing primary and succeeding fallback
		primary = self._create_failing_mock_llm(
			'primary-model',
			fail_with=ModelRateLimitError,
			fail_status_code=429,
			fail_message='Rate limit exceeded',
		)
		fallback = self._create_succeeding_mock_llm('fallback-model', agent)

		# Replace the LLM and set up fallback
		agent.llm = primary
		agent._original_llm = primary
		agent._fallback_llm = fallback

		from browser_use.llm.messages import BaseMessage, UserMessage

		messages: list[BaseMessage] = [UserMessage(content='Test message')]

		# This should switch to fallback and succeed
		result = await agent.get_model_output(messages)

		assert result is not None
		assert agent.llm is fallback
		assert agent._using_fallback_llm is True

	@pytest.mark.asyncio
	async def test_get_model_output_raises_when_no_fallback(self, browser_session):
		"""Test that get_model_output raises error when no fallback is configured."""
		from browser_use import Agent

		# Create agent first with a working mock LLM
		placeholder = create_mock_llm('placeholder')
		agent = Agent(task='Test task', llm=placeholder, browser_session=browser_session)

		# Replace with failing LLM
		primary = self._create_failing_mock_llm(
			'primary-model',
			fail_with=ModelRateLimitError,
			fail_status_code=429,
			fail_message='Rate limit exceeded',
		)
		agent.llm = primary
		agent._original_llm = primary
		agent._fallback_llm = None  # No fallback

		from browser_use.llm.messages import BaseMessage, UserMessage

		messages: list[BaseMessage] = [UserMessage(content='Test message')]

		# This should raise since no fallback is configured
		with pytest.raises(ModelRateLimitError):
			await agent.get_model_output(messages)

	@pytest.mark.asyncio
	async def test_get_model_output_raises_when_fallback_also_fails(self, browser_session):
		"""Test that error is raised when fallback also fails."""
		from browser_use import Agent

		# Create agent first with a working mock LLM
		placeholder = create_mock_llm('placeholder')
		agent = Agent(task='Test task', llm=placeholder, browser_session=browser_session)

		# Both models fail
		primary = self._create_failing_mock_llm('primary', fail_with=ModelRateLimitError, fail_status_code=429)
		fallback = self._create_failing_mock_llm('fallback', fail_with=ModelProviderError, fail_status_code=503)

		agent.llm = primary
		agent._original_llm = primary
		agent._fallback_llm = fallback

		from browser_use.llm.messages import BaseMessage, UserMessage

		messages: list[BaseMessage] = [UserMessage(content='Test message')]

		# Should fail after fallback also fails
		with pytest.raises((ModelRateLimitError, ModelProviderError)):
			await agent.get_model_output(messages)


if __name__ == '__main__':
	pytest.main([__file__, '-v'])
