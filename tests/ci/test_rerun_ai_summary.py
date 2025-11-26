"""Tests for AI summary generation during rerun"""

from unittest.mock import AsyncMock

from browser_use.agent.service import Agent
from browser_use.agent.views import ActionResult, RerunSummaryAction
from tests.ci.conftest import create_mock_llm


async def test_generate_rerun_summary_success():
	"""Test that _generate_rerun_summary generates an AI summary for successful rerun"""
	# Create mock LLM that returns RerunSummaryAction
	summary_action = RerunSummaryAction(
		summary='Form filled successfully',
		success=True,
		completion_status='complete',
	)

	async def custom_ainvoke(*args, **kwargs):
		# Get output_format from second positional arg or kwargs
		output_format = args[1] if len(args) > 1 else kwargs.get('output_format')
		assert output_format is RerunSummaryAction
		from browser_use.llm.views import ChatInvokeCompletion

		return ChatInvokeCompletion(completion=summary_action, usage=None)

	# Mock ChatOpenAI class
	mock_openai = AsyncMock()
	mock_openai.ainvoke.side_effect = custom_ainvoke

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)
	await agent.browser_session.start()

	try:
		# Create some successful results
		results = [
			ActionResult(long_term_memory='Step 1 completed'),
			ActionResult(long_term_memory='Step 2 completed'),
		]

		# Pass the mock LLM directly as summary_llm
		summary = await agent._generate_rerun_summary('Test task', results, summary_llm=mock_openai)

		# Check that result is the AI summary
		assert summary.is_done is True
		assert summary.success is True
		assert summary.extracted_content == 'Form filled successfully'
		assert 'Rerun completed' in (summary.long_term_memory or '')

	finally:
		await agent.close()


async def test_generate_rerun_summary_with_errors():
	"""Test that AI summary correctly reflects errors in execution"""
	# Create mock LLM for summary
	summary_action = RerunSummaryAction(
		summary='Rerun had errors',
		success=False,
		completion_status='failed',
	)

	async def custom_ainvoke(*args, **kwargs):
		output_format = args[1] if len(args) > 1 else kwargs.get('output_format')
		assert output_format is RerunSummaryAction
		from browser_use.llm.views import ChatInvokeCompletion

		return ChatInvokeCompletion(completion=summary_action, usage=None)

	mock_openai = AsyncMock()
	mock_openai.ainvoke.side_effect = custom_ainvoke

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)
	await agent.browser_session.start()

	try:
		# Create results with errors
		results_with_errors = [
			ActionResult(error='Failed to find element'),
			ActionResult(error='Timeout'),
		]

		# Pass the mock LLM directly as summary_llm
		summary = await agent._generate_rerun_summary('Test task', results_with_errors, summary_llm=mock_openai)

		# Verify summary reflects errors
		assert summary.is_done is True
		assert summary.success is False
		assert summary.extracted_content == 'Rerun had errors'

	finally:
		await agent.close()


async def test_generate_rerun_summary_fallback_on_error():
	"""Test that a fallback summary is generated if LLM fails"""
	# Mock ChatOpenAI to throw an error
	mock_openai = AsyncMock()
	mock_openai.ainvoke.side_effect = Exception('LLM service unavailable')

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)
	await agent.browser_session.start()

	try:
		# Create some results
		results = [
			ActionResult(long_term_memory='Step 1 completed'),
			ActionResult(long_term_memory='Step 2 completed'),
		]

		# Pass the mock LLM directly as summary_llm
		summary = await agent._generate_rerun_summary('Test task', results, summary_llm=mock_openai)

		# Verify fallback summary
		assert summary.is_done is True
		assert summary.success is True  # No errors, so success=True
		assert 'Rerun completed' in (summary.extracted_content or '')
		assert '2/2' in (summary.extracted_content or '')  # Should show stats

	finally:
		await agent.close()


async def test_generate_rerun_summary_statistics():
	"""Test that summary includes execution statistics in the prompt"""
	# Create mock LLM
	summary_action = RerunSummaryAction(
		summary='3 of 5 steps succeeded',
		success=False,
		completion_status='partial',
	)

	async def custom_ainvoke(*args, **kwargs):
		output_format = args[1] if len(args) > 1 else kwargs.get('output_format')
		assert output_format is RerunSummaryAction
		from browser_use.llm.views import ChatInvokeCompletion

		return ChatInvokeCompletion(completion=summary_action, usage=None)

	mock_openai = AsyncMock()
	mock_openai.ainvoke.side_effect = custom_ainvoke

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)
	await agent.browser_session.start()

	try:
		# Create results with mix of success and errors
		results = [
			ActionResult(long_term_memory='Step 1 completed'),
			ActionResult(error='Step 2 failed'),
			ActionResult(long_term_memory='Step 3 completed'),
			ActionResult(error='Step 4 failed'),
			ActionResult(long_term_memory='Step 5 completed'),
		]

		# Pass the mock LLM directly as summary_llm
		summary = await agent._generate_rerun_summary('Test task', results, summary_llm=mock_openai)

		# Verify summary
		assert summary.is_done is True
		assert summary.success is False  # partial completion
		assert '3 of 5' in (summary.extracted_content or '')

	finally:
		await agent.close()
