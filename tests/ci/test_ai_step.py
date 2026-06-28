"""Tests for AI step private method used during rerun"""

from unittest.mock import AsyncMock

from browser_use.agent.service import Agent
from browser_use.agent.views import ActionResult
from tests.ci.conftest import create_mock_llm


async def test_execute_ai_step_basic():
	"""Test that _execute_ai_step extracts content with AI"""

	# Create mock LLM that returns text response
	async def custom_ainvoke(*args, **kwargs):
		from browser_use.llm.views import ChatInvokeCompletion

		return ChatInvokeCompletion(completion='Extracted: Test content from page', usage=None)

	mock_llm = AsyncMock()
	mock_llm.ainvoke.side_effect = custom_ainvoke
	mock_llm.model = 'mock-model'

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)
	await agent.browser_session.start()

	try:
		# Execute _execute_ai_step with mock LLM
		result = await agent._execute_ai_step(
			query='Extract the main heading',
			include_screenshot=False,
			extract_links=False,
			ai_step_llm=mock_llm,
		)

		# Verify result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Extracted: Test content from page' in result.extracted_content
		assert result.long_term_memory is not None

	finally:
		await agent.close()


async def test_execute_ai_step_with_screenshot():
	"""Test that _execute_ai_step includes screenshot when requested"""

	# Create mock LLM
	async def custom_ainvoke(*args, **kwargs):
		from browser_use.llm.views import ChatInvokeCompletion

		# Verify that we received a message with image content
		messages = args[0] if args else []
		assert len(messages) >= 1, 'Should have at least one message'

		# Check if any message has image content
		has_image = False
		for msg in messages:
			if hasattr(msg, 'content') and isinstance(msg.content, list):
				for part in msg.content:
					if hasattr(part, 'type') and part.type == 'image_url':
						has_image = True
						break

		assert has_image, 'Should include screenshot in message'
		return ChatInvokeCompletion(completion='Extracted content with screenshot analysis', usage=None)

	mock_llm = AsyncMock()
	mock_llm.ainvoke.side_effect = custom_ainvoke
	mock_llm.model = 'mock-model'

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)
	await agent.browser_session.start()

	try:
		# Execute _execute_ai_step with screenshot
		result = await agent._execute_ai_step(
			query='Analyze this page',
			include_screenshot=True,
			extract_links=False,
			ai_step_llm=mock_llm,
		)

		# Verify result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Extracted content with screenshot analysis' in result.extracted_content

	finally:
		await agent.close()


async def test_execute_ai_step_error_handling():
	"""Test that _execute_ai_step handles errors gracefully"""
	# Create mock LLM that raises an error
	mock_llm = AsyncMock()
	mock_llm.ainvoke.side_effect = Exception('LLM service unavailable')
	mock_llm.model = 'mock-model'

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)
	await agent.browser_session.start()

	try:
		# Execute _execute_ai_step - should return ActionResult with error
		result = await agent._execute_ai_step(
			query='Extract data',
			include_screenshot=False,
			ai_step_llm=mock_llm,
		)

		# Verify error is in result (not raised)
		assert isinstance(result, ActionResult)
		assert result.error is not None
		assert 'AI step failed' in result.error

	finally:
		await agent.close()
