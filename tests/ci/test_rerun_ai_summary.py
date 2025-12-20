"""Tests for AI summary generation during rerun"""

from unittest.mock import AsyncMock

from browser_use.agent.service import Agent
from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList, RerunSummaryAction, StepMetadata
from browser_use.browser.views import BrowserStateHistory
from browser_use.dom.views import DOMRect, NodeType
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


async def test_rerun_skips_steps_with_original_errors():
	"""Test that rerun_history skips steps that had errors in the original run when skip_failures=True"""

	# Create a mock LLM for summary
	summary_action = RerunSummaryAction(
		summary='Rerun completed with skipped steps',
		success=True,
		completion_status='complete',
	)

	async def custom_ainvoke(*args, **kwargs):
		output_format = args[1] if len(args) > 1 else kwargs.get('output_format')
		if output_format is RerunSummaryAction:
			from browser_use.llm.views import ChatInvokeCompletion

			return ChatInvokeCompletion(completion=summary_action, usage=None)
		raise ValueError('Unexpected output_format')

	mock_summary_llm = AsyncMock()
	mock_summary_llm.ainvoke.side_effect = custom_ainvoke

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)

	# Create mock history with a step that has an error
	mock_state = BrowserStateHistory(
		url='https://example.com',
		title='Test Page',
		tabs=[],
		interacted_element=[None],
	)

	# Get the dynamically created AgentOutput type from the agent
	AgentOutput = agent.AgentOutput

	# Create a step that originally had an error (using navigate action which doesn't require element matching)
	failed_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Trying to navigate',
			next_goal=None,
			action=[{'navigate': {'url': 'https://example.com/page'}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(error='Navigation failed - network error')],
		state=mock_state,
		metadata=StepMetadata(
			step_start_time=0,
			step_end_time=1,
			step_number=1,
			step_interval=1.0,
		),
	)

	# Create history with the failed step
	history = AgentHistoryList(history=[failed_step])

	try:
		# Run rerun with skip_failures=True - should skip the step with original error
		results = await agent.rerun_history(
			history,
			skip_failures=True,
			summary_llm=mock_summary_llm,
		)

		# The step should have been skipped (not retried) because it originally had an error
		# We should have 2 results: the skipped step result and the AI summary
		assert len(results) == 2

		# First result should indicate the step was skipped
		skipped_result = results[0]
		assert skipped_result.error is not None
		assert 'Skipped - original step had error' in skipped_result.error

		# Second result should be the AI summary
		summary_result = results[1]
		assert summary_result.is_done is True

	finally:
		await agent.close()


async def test_rerun_does_not_skip_originally_failed_when_skip_failures_false():
	"""Test that rerun_history does NOT skip steps with original errors when skip_failures=False.
	When skip_failures=False, the step should be attempted (and will succeed since navigate doesn't need element matching)."""

	# Create a mock LLM for summary (will be reached after the step succeeds)
	summary_action = RerunSummaryAction(
		summary='Rerun completed',
		success=True,
		completion_status='complete',
	)

	async def custom_ainvoke(*args, **kwargs):
		output_format = args[1] if len(args) > 1 else kwargs.get('output_format')
		if output_format is RerunSummaryAction:
			from browser_use.llm.views import ChatInvokeCompletion

			return ChatInvokeCompletion(completion=summary_action, usage=None)
		raise ValueError('Unexpected output_format')

	mock_summary_llm = AsyncMock()
	mock_summary_llm.ainvoke.side_effect = custom_ainvoke

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)

	# Create mock history with a step that has an error
	mock_state = BrowserStateHistory(
		url='https://example.com',
		title='Test Page',
		tabs=[],
		interacted_element=[None],
	)

	# Get the dynamically created AgentOutput type from the agent
	AgentOutput = agent.AgentOutput

	# Create a step that originally had an error but uses navigate (which will work on rerun)
	failed_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Trying to navigate',
			next_goal=None,
			action=[{'navigate': {'url': 'https://example.com/page'}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(error='Navigation failed - network error')],
		state=mock_state,
		metadata=StepMetadata(
			step_start_time=0,
			step_end_time=1,
			step_number=1,
			step_interval=1.0,
		),
	)

	# Create history with the failed step
	history = AgentHistoryList(history=[failed_step])

	try:
		# Run rerun with skip_failures=False - should attempt to replay (and succeed since navigate works)
		results = await agent.rerun_history(
			history,
			skip_failures=False,
			max_retries=1,
			summary_llm=mock_summary_llm,
		)

		# With skip_failures=False, the step should NOT be skipped even if original had error
		# The navigate action should succeed
		assert len(results) == 2

		# First result should be the successful navigation (not skipped)
		nav_result = results[0]
		# It should NOT contain "Skipped" since skip_failures=False
		if nav_result.error:
			assert 'Skipped' not in nav_result.error

	finally:
		await agent.close()


async def test_rerun_cleanup_on_failure(httpserver):
	"""Test that rerun_history properly cleans up resources (closes browser/connections) even when it fails.

	This test verifies the try/finally cleanup logic by creating a step that will fail
	(element matching fails) and checking that the browser session is properly closed afterward.
	"""
	from browser_use.dom.views import DOMInteractedElement

	# Set up a test page with a button that has DIFFERENT attributes than our historical element
	test_html = """<!DOCTYPE html>
	<html>
	<body>
		<button id="real-button" aria-label="real-button">Click me</button>
	</body>
	</html>"""
	httpserver.expect_request('/test').respond_with_data(test_html, content_type='text/html')
	test_url = httpserver.url_for('/test')

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)
	AgentOutput = agent.AgentOutput

	# Step 1: Navigate to test page
	navigate_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Navigate to test page',
			next_goal=None,
			action=[{'navigate': {'url': test_url}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Navigated')],
		state=BrowserStateHistory(
			url=test_url,
			title='Test Page',
			tabs=[],
			interacted_element=[None],
		),
		metadata=StepMetadata(
			step_start_time=0,
			step_end_time=1,
			step_number=1,
			step_interval=0.1,
		),
	)

	# Step 2: Click on element that won't be found (different identifiers)
	failing_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Trying to click non-existent button',
			next_goal=None,
			action=[{'click': {'index': 100}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Clicked button')],  # Original succeeded
		state=BrowserStateHistory(
			url=test_url,
			title='Test Page',
			tabs=[],
			interacted_element=[
				DOMInteractedElement(
					node_id=1,
					backend_node_id=9999,
					frame_id=None,
					node_type=NodeType.ELEMENT_NODE,
					node_value='',
					node_name='BUTTON',
					attributes={'aria-label': 'non-existent-button', 'id': 'fake-id'},
					x_path='html/body/button[999]',
					element_hash=123456789,
					stable_hash=987654321,
					bounds=DOMRect(x=0, y=0, width=100, height=50),
					ax_name='non-existent',
				)
			],
		),
		metadata=StepMetadata(
			step_start_time=0,
			step_end_time=1,
			step_number=2,
			step_interval=0.1,
		),
	)

	history = AgentHistoryList(history=[navigate_step, failing_step])

	# Run rerun with skip_failures=False - should fail and raise RuntimeError
	# but the try/finally should ensure cleanup happens
	try:
		await agent.rerun_history(
			history,
			skip_failures=False,
			max_retries=1,  # Fail quickly
		)
		assert False, 'Expected RuntimeError to be raised'
	except RuntimeError as e:
		# Expected - the step should fail on element matching
		assert 'failed after 1 attempts' in str(e)

	# If we get here without hanging, the cleanup worked
	# The browser session should be closed by the finally block in rerun_history
	# We can verify by checking that calling close again doesn't cause issues
	# (close() is idempotent - calling it multiple times should be safe)
	await agent.close()  # Should not hang or error since already closed


async def test_rerun_records_errors_when_skip_failures_true(httpserver):
	"""Test that rerun_history records errors in results even when skip_failures=True.

	This ensures the AI summary correctly counts failures. Previously, when skip_failures=True
	and a step failed after all retries, no error result was appended, causing the AI summary
	to incorrectly report success=True even with multiple failures.
	"""
	from browser_use.dom.views import DOMInteractedElement

	# Set up a test page with a button that has DIFFERENT attributes than our historical element
	# This ensures element matching will fail (the historical element won't be found)
	test_html = """<!DOCTYPE html>
	<html>
	<body>
		<button id="real-button" aria-label="real-button">Click me</button>
	</body>
	</html>"""
	httpserver.expect_request('/test').respond_with_data(test_html, content_type='text/html')
	test_url = httpserver.url_for('/test')

	# Create a mock LLM for summary that returns partial success
	summary_action = RerunSummaryAction(
		summary='Some steps failed',
		success=False,
		completion_status='partial',
	)

	async def custom_ainvoke(*args, **kwargs):
		output_format = args[1] if len(args) > 1 else kwargs.get('output_format')
		if output_format is RerunSummaryAction:
			from browser_use.llm.views import ChatInvokeCompletion

			return ChatInvokeCompletion(completion=summary_action, usage=None)
		raise ValueError('Unexpected output_format')

	mock_summary_llm = AsyncMock()
	mock_summary_llm.ainvoke.side_effect = custom_ainvoke

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)

	# Create history with:
	# 1. First step navigates to test page (will succeed)
	# 2. Second step tries to click a non-existent element (will fail on element matching)
	AgentOutput = agent.AgentOutput

	# Step 1: Navigate to test page
	navigate_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Navigate to test page',
			next_goal=None,
			action=[{'navigate': {'url': test_url}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Navigated')],
		state=BrowserStateHistory(
			url=test_url,
			title='Test Page',
			tabs=[],
			interacted_element=[None],
		),
		metadata=StepMetadata(
			step_start_time=0,
			step_end_time=1,
			step_number=1,
			step_interval=0.1,
		),
	)

	# Step 2: Click on element that won't exist on current page (different hash/attributes)
	failing_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Trying to click non-existent button',
			next_goal=None,
			action=[{'click': {'index': 100}}],  # type: ignore[arg-type]  # Original index doesn't matter, matching will fail
		),
		result=[ActionResult(long_term_memory='Clicked button')],  # Original succeeded
		state=BrowserStateHistory(
			url=test_url,
			title='Test Page',
			tabs=[],
			interacted_element=[
				DOMInteractedElement(
					node_id=1,
					backend_node_id=9999,
					frame_id=None,
					node_type=NodeType.ELEMENT_NODE,
					node_value='',
					node_name='BUTTON',
					# This element has completely different identifiers than the real button
					attributes={'aria-label': 'non-existent-button', 'id': 'fake-id'},
					x_path='html/body/button[999]',  # XPath that doesn't exist
					element_hash=123456789,  # Hash that won't match
					stable_hash=987654321,  # Stable hash that won't match
					bounds=DOMRect(x=0, y=0, width=100, height=50),
					ax_name='non-existent',
				)
			],
		),
		metadata=StepMetadata(
			step_start_time=0,
			step_end_time=1,
			step_number=2,
			step_interval=0.1,
		),
	)

	history = AgentHistoryList(history=[navigate_step, failing_step])

	try:
		# Run rerun with skip_failures=True - should NOT raise but should record the error
		results = await agent.rerun_history(
			history,
			skip_failures=True,
			max_retries=1,  # Fail quickly
			summary_llm=mock_summary_llm,
		)

		# Should have 3 results: navigation success + error from failed step + AI summary
		assert len(results) == 3

		# First result should be successful navigation
		nav_result = results[0]
		assert nav_result.error is None

		# Second result should be the error (element matching failed)
		error_result = results[1]
		assert error_result.error is not None
		assert 'failed after 1 attempts' in error_result.error

		# Third result should be the AI summary
		summary_result = results[2]
		assert summary_result.is_done is True

	finally:
		await agent.close()
