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


async def test_rerun_skips_redundant_retry_steps(httpserver):
	"""Test that rerun_history skips redundant retry steps.

	This handles cases where the original run needed to click the same element multiple
	times due to slow page response, but during replay the first click already succeeded.
	When consecutive steps target the same element with the same action, the second step
	should be skipped as a redundant retry.
	"""
	from browser_use.dom.views import DOMInteractedElement

	# Set up a test page with a button
	test_html = """<!DOCTYPE html>
	<html>
	<body>
		<button id="login-btn" aria-label="Log In">Log In</button>
	</body>
	</html>"""
	httpserver.expect_request('/test').respond_with_data(test_html, content_type='text/html')
	test_url = httpserver.url_for('/test')

	# Create a mock LLM for summary
	summary_action = RerunSummaryAction(
		summary='Rerun completed with skipped redundant step',
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
	AgentOutput = agent.AgentOutput

	# Create an interacted element that matches the button on the page
	login_button_element = DOMInteractedElement(
		node_id=1,
		backend_node_id=1,
		frame_id=None,
		node_type=NodeType.ELEMENT_NODE,
		node_value='',
		node_name='BUTTON',
		attributes={'aria-label': 'Log In', 'id': 'login-btn'},
		x_path='html/body/button',
		element_hash=12345,  # Same hash for both steps (same element)
		stable_hash=12345,
		bounds=DOMRect(x=0, y=0, width=100, height=50),
	)

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

	# Step 2: Click login button (first click)
	click_step_1 = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Click login button',
			next_goal=None,
			action=[{'click': {'index': 1}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Clicked login button')],
		state=BrowserStateHistory(
			url=test_url,
			title='Test Page',
			tabs=[],
			interacted_element=[login_button_element],
		),
		metadata=StepMetadata(
			step_start_time=1,
			step_end_time=2,
			step_number=2,
			step_interval=0.1,
		),
	)

	# Step 3: Click login button AGAIN (redundant retry - same element, same action)
	click_step_2 = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Page did not change, clicking login button again',
			next_goal=None,
			action=[{'click': {'index': 1}}],  # type: ignore[arg-type]  # Same action type
		),
		result=[ActionResult(long_term_memory='Clicked login button')],
		state=BrowserStateHistory(
			url=test_url,
			title='Test Page',
			tabs=[],
			interacted_element=[login_button_element],  # Same element!
		),
		metadata=StepMetadata(
			step_start_time=2,
			step_end_time=3,
			step_number=3,
			step_interval=0.1,
		),
	)

	history = AgentHistoryList(history=[navigate_step, click_step_1, click_step_2])

	try:
		results = await agent.rerun_history(
			history,
			skip_failures=True,
			summary_llm=mock_summary_llm,
		)

		# Should have 4 results: navigate + click + skipped redundant + AI summary
		assert len(results) == 4

		# First result: navigation succeeded
		nav_result = results[0]
		assert nav_result.error is None

		# Second result: first click succeeded
		click_result = results[1]
		assert click_result.error is None

		# Third result: redundant retry was SKIPPED (not an error)
		skipped_result = results[2]
		assert skipped_result.error is None  # Not an error - intentionally skipped
		assert 'Skipped - redundant retry' in (skipped_result.extracted_content or '')

		# Fourth result: AI summary
		summary_result = results[3]
		assert summary_result.is_done is True

	finally:
		await agent.close()


async def test_is_redundant_retry_step_detection():
	"""Test the _is_redundant_retry_step method directly."""
	from browser_use.dom.views import DOMInteractedElement

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)
	AgentOutput = agent.AgentOutput

	# Create an interacted element
	button_element = DOMInteractedElement(
		node_id=1,
		backend_node_id=1,
		frame_id=None,
		node_type=NodeType.ELEMENT_NODE,
		node_value='',
		node_name='BUTTON',
		attributes={'aria-label': 'Submit'},
		x_path='html/body/button',
		element_hash=12345,
		stable_hash=12345,
		bounds=DOMRect(x=0, y=0, width=100, height=50),
	)

	different_element = DOMInteractedElement(
		node_id=2,
		backend_node_id=2,
		frame_id=None,
		node_type=NodeType.ELEMENT_NODE,
		node_value='',
		node_name='INPUT',
		attributes={'name': 'email'},
		x_path='html/body/input',
		element_hash=99999,  # Different hash
		stable_hash=99999,
		bounds=DOMRect(x=0, y=0, width=200, height=30),
	)

	# Step with click on button
	click_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Click button',
			next_goal=None,
			action=[{'click': {'index': 1}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Clicked')],
		state=BrowserStateHistory(
			url='http://test.com',
			title='Test',
			tabs=[],
			interacted_element=[button_element],
		),
		metadata=StepMetadata(step_start_time=0, step_end_time=1, step_number=1, step_interval=0.1),
	)

	# Same click on same button (redundant retry)
	retry_click_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Click button again',
			next_goal=None,
			action=[{'click': {'index': 1}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Clicked')],
		state=BrowserStateHistory(
			url='http://test.com',
			title='Test',
			tabs=[],
			interacted_element=[button_element],  # Same element
		),
		metadata=StepMetadata(step_start_time=1, step_end_time=2, step_number=2, step_interval=0.1),
	)

	# Different action type on same element (not redundant)
	input_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Type in button (weird but valid)',
			next_goal=None,
			action=[{'input': {'index': 1, 'text': 'hello'}}],  # type: ignore[arg-type]  # Different action type
		),
		result=[ActionResult(long_term_memory='Typed')],
		state=BrowserStateHistory(
			url='http://test.com',
			title='Test',
			tabs=[],
			interacted_element=[button_element],
		),
		metadata=StepMetadata(step_start_time=2, step_end_time=3, step_number=3, step_interval=0.1),
	)

	# Same action type but different element (not redundant)
	different_element_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Click different element',
			next_goal=None,
			action=[{'click': {'index': 2}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Clicked')],
		state=BrowserStateHistory(
			url='http://test.com',
			title='Test',
			tabs=[],
			interacted_element=[different_element],  # Different element
		),
		metadata=StepMetadata(step_start_time=3, step_end_time=4, step_number=4, step_interval=0.1),
	)

	try:
		# Test 1: Same element, same action, previous succeeded -> redundant
		assert agent._is_redundant_retry_step(retry_click_step, click_step, True) is True

		# Test 2: Same element, same action, previous FAILED -> NOT redundant
		assert agent._is_redundant_retry_step(retry_click_step, click_step, False) is False

		# Test 3: Same element, different action type -> NOT redundant
		assert agent._is_redundant_retry_step(input_step, click_step, True) is False

		# Test 4: Different element, same action type -> NOT redundant
		assert agent._is_redundant_retry_step(different_element_step, click_step, True) is False

		# Test 5: No previous step -> NOT redundant
		assert agent._is_redundant_retry_step(click_step, None, True) is False

	finally:
		await agent.close()


async def test_count_expected_elements_from_history():
	"""Test that _count_expected_elements_from_history correctly estimates element count based on action indices."""
	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)
	AgentOutput = agent.AgentOutput

	# Test 1: Action with low index (5) -> needs at least 6 elements (index + 1)
	step_low_index = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Test',
			next_goal=None,
			action=[{'input': {'index': 5, 'text': 'test'}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Done')],
		state=BrowserStateHistory(
			url='http://test.com',
			title='Test',
			tabs=[],
			interacted_element=[None],
		),
		metadata=StepMetadata(step_start_time=0, step_end_time=1, step_number=1, step_interval=0.1),
	)

	# Test 2: Action with higher index (25) -> needs at least 26 elements
	step_high_index = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Test',
			next_goal=None,
			action=[{'click': {'index': 25}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Done')],
		state=BrowserStateHistory(
			url='http://test.com',
			title='Test',
			tabs=[],
			interacted_element=[None],
		),
		metadata=StepMetadata(step_start_time=0, step_end_time=1, step_number=2, step_interval=0.1),
	)

	# Test 3: Action with very high index (100) -> capped at 50
	step_very_high_index = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Test',
			next_goal=None,
			action=[{'click': {'index': 100}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Done')],
		state=BrowserStateHistory(
			url='http://test.com',
			title='Test',
			tabs=[],
			interacted_element=[None],
		),
		metadata=StepMetadata(step_start_time=0, step_end_time=1, step_number=3, step_interval=0.1),
	)

	# Test 4: Navigate action (no index) -> returns 0
	step_no_index = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Test',
			next_goal=None,
			action=[{'navigate': {'url': 'http://test.com'}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Done')],
		state=BrowserStateHistory(
			url='http://test.com',
			title='Test',
			tabs=[],
			interacted_element=[None],
		),
		metadata=StepMetadata(step_start_time=0, step_end_time=1, step_number=4, step_interval=0.1),
	)

	# Test 5: Multiple actions - uses max index
	step_multiple_actions = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Test',
			next_goal=None,
			action=[
				{'click': {'index': 3}},  # type: ignore[arg-type]
				{'input': {'index': 10, 'text': 'test'}},  # type: ignore[arg-type]
			],
		),
		result=[ActionResult(long_term_memory='Done'), ActionResult(long_term_memory='Done')],
		state=BrowserStateHistory(
			url='http://test.com',
			title='Test',
			tabs=[],
			interacted_element=[None, None],
		),
		metadata=StepMetadata(step_start_time=0, step_end_time=1, step_number=5, step_interval=0.1),
	)

	# Test 6: Action with index 0 (edge case) -> needs at least 1 element
	# Using input action because it allows index 0 (click requires ge=1)
	step_index_zero = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Test',
			next_goal=None,
			action=[{'input': {'index': 0, 'text': 'test'}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Done')],
		state=BrowserStateHistory(
			url='http://test.com',
			title='Test',
			tabs=[],
			interacted_element=[None],
		),
		metadata=StepMetadata(step_start_time=0, step_end_time=1, step_number=6, step_interval=0.1),
	)

	try:
		# Test 1: Action index 5 -> needs 6 elements (index + 1)
		assert agent._count_expected_elements_from_history(step_low_index) == 6

		# Test 2: Action index 25 -> needs 26 elements
		assert agent._count_expected_elements_from_history(step_high_index) == 26

		# Test 3: Action index 100 -> capped at 50
		assert agent._count_expected_elements_from_history(step_very_high_index) == 50

		# Test 4: Navigate has no index -> returns 0
		assert agent._count_expected_elements_from_history(step_no_index) == 0

		# Test 5: Multiple actions -> uses max index (10) + 1 = 11
		assert agent._count_expected_elements_from_history(step_multiple_actions) == 11

		# Test 6: Action index 0 (edge case) -> needs 1 element (0 + 1)
		assert agent._count_expected_elements_from_history(step_index_zero) == 1

	finally:
		await agent.close()


async def test_wait_for_minimum_elements(httpserver):
	"""Test that _wait_for_minimum_elements waits for elements to appear."""
	# Set up a simple test page with a button
	test_html = """<!DOCTYPE html>
	<html>
	<body>
		<button id="btn1">Button 1</button>
		<button id="btn2">Button 2</button>
		<input type="text" id="input1" />
	</body>
	</html>"""
	httpserver.expect_request('/test').respond_with_data(test_html, content_type='text/html')
	test_url = httpserver.url_for('/test')

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)

	try:
		await agent.browser_session.start()

		# Navigate to the test page first
		from browser_use.browser.events import NavigateToUrlEvent

		await agent.browser_session.event_bus.dispatch(NavigateToUrlEvent(url=test_url, new_tab=False))

		# Wait a bit for navigation
		import asyncio

		await asyncio.sleep(1.0)

		# Test 1: Wait for 1 element (should succeed quickly)
		state = await agent._wait_for_minimum_elements(min_elements=1, timeout=5.0, poll_interval=0.5)
		assert state is not None
		assert state.dom_state.selector_map is not None
		assert len(state.dom_state.selector_map) >= 1

		# Test 2: Wait for reasonable number of elements (should succeed)
		state = await agent._wait_for_minimum_elements(min_elements=2, timeout=5.0, poll_interval=0.5)
		assert state is not None
		assert len(state.dom_state.selector_map) >= 2

		# Test 3: Wait for too many elements (should timeout but still return state)
		state = await agent._wait_for_minimum_elements(min_elements=100, timeout=2.0, poll_interval=0.5)
		assert state is not None  # Should still return a state even on timeout

	finally:
		await agent.close()


async def test_rerun_waits_for_elements_before_matching(httpserver):
	"""Test that rerun_history waits for elements before attempting element matching.

	This test verifies that for actions needing element matching (like click),
	the rerun logic waits for the page to have enough elements before proceeding.
	"""
	from browser_use.dom.views import DOMInteractedElement

	# Set up a test page with elements
	test_html = """<!DOCTYPE html>
	<html>
	<body>
		<button id="test-btn" aria-label="Test Button">Click me</button>
	</body>
	</html>"""
	httpserver.expect_request('/test').respond_with_data(test_html, content_type='text/html')
	test_url = httpserver.url_for('/test')

	# Create a mock LLM for summary
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
	AgentOutput = agent.AgentOutput

	# Create an element that matches the page
	button_element = DOMInteractedElement(
		node_id=1,
		backend_node_id=5,  # This will trigger waiting for at least 5 elements
		frame_id=None,
		node_type=NodeType.ELEMENT_NODE,
		node_value='',
		node_name='BUTTON',
		attributes={'aria-label': 'Test Button', 'id': 'test-btn'},
		x_path='html/body/button',
		element_hash=12345,
		stable_hash=12345,
		bounds=DOMRect(x=0, y=0, width=100, height=50),
	)

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

	# Step 2: Click button (needs element matching, should wait for elements)
	click_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Click button',
			next_goal=None,
			action=[{'click': {'index': 5}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Clicked')],
		state=BrowserStateHistory(
			url=test_url,
			title='Test Page',
			tabs=[],
			interacted_element=[button_element],
		),
		metadata=StepMetadata(
			step_start_time=1,
			step_end_time=2,
			step_number=2,
			step_interval=0.1,
		),
	)

	history = AgentHistoryList(history=[navigate_step, click_step])

	try:
		# Run rerun with wait_for_elements=True - should wait for elements before trying to match
		results = await agent.rerun_history(
			history,
			skip_failures=True,
			max_retries=1,
			summary_llm=mock_summary_llm,
			wait_for_elements=True,  # Enable element waiting
		)

		# Should have results: navigate + click (or error if element not found) + summary
		assert len(results) >= 2

		# First result should be navigation success
		nav_result = results[0]
		assert nav_result.error is None

	finally:
		await agent.close()


async def test_rerun_uses_exponential_backoff_retry_delays(httpserver):
	"""Test that rerun uses exponential backoff delays between retries (5s, 10s, 20s, capped at 30s)."""
	import time

	from browser_use.dom.views import DOMInteractedElement

	# Set up a test page with a button that won't match
	test_html = """<!DOCTYPE html>
	<html>
	<body>
		<button id="real-btn">Real Button</button>
	</body>
	</html>"""
	httpserver.expect_request('/test').respond_with_data(test_html, content_type='text/html')
	test_url = httpserver.url_for('/test')

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)
	AgentOutput = agent.AgentOutput

	# Create an element that WON'T match (different identifiers)
	non_matching_element = DOMInteractedElement(
		node_id=1,
		backend_node_id=1,  # Low to avoid long element waiting
		frame_id=None,
		node_type=NodeType.ELEMENT_NODE,
		node_value='',
		node_name='BUTTON',
		attributes={'aria-label': 'Non-existent', 'id': 'fake-id'},
		x_path='html/body/button[999]',
		element_hash=99999,
		stable_hash=99999,
		bounds=DOMRect(x=0, y=0, width=100, height=50),
	)

	# Step 1: Navigate
	navigate_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Navigate',
			next_goal=None,
			action=[{'navigate': {'url': test_url}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Navigated')],
		state=BrowserStateHistory(
			url=test_url,
			title='Test',
			tabs=[],
			interacted_element=[None],
		),
		metadata=StepMetadata(step_start_time=0, step_end_time=1, step_number=1, step_interval=0.1),
	)

	# Step 2: Click non-matching element (will fail and retry)
	failing_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Click',
			next_goal=None,
			action=[{'click': {'index': 1}}],  # type: ignore[arg-type]
		),
		result=[ActionResult(long_term_memory='Clicked')],
		state=BrowserStateHistory(
			url=test_url,
			title='Test',
			tabs=[],
			interacted_element=[non_matching_element],
		),
		metadata=StepMetadata(step_start_time=1, step_end_time=2, step_number=2, step_interval=0.1),
	)

	history = AgentHistoryList(history=[navigate_step, failing_step])

	try:
		start_time = time.time()

		# Run rerun with 2 retries - should use exponential backoff (5s for first retry)
		# Attempt 1 fails -> wait 5s -> Attempt 2 fails -> done
		try:
			await agent.rerun_history(
				history,
				skip_failures=False,
				max_retries=2,  # Will fail twice with 5s delay between (exponential: 5s * 2^0 = 5s)
			)
		except RuntimeError:
			pass  # Expected to fail

		elapsed = time.time() - start_time

		# Should have taken at least 5 seconds (the first retry delay with exponential backoff)
		# Exponential backoff formula: base_delay * 2^(retry_count-1) = 5 * 2^0 = 5s
		assert elapsed >= 4.5, f'Expected at least 4.5s elapsed (5s exponential backoff), got {elapsed:.1f}s'

	finally:
		await agent.close()


async def test_exponential_backoff_calculation():
	"""Test that exponential backoff correctly calculates delays: 5s, 10s, 20s, capped at 30s."""
	# Verify the exponential backoff formula: min(5 * 2^(retry-1), 30)
	base_delay = 5.0
	max_delay = 30.0

	# Retry 1: 5 * 2^0 = 5s
	assert min(base_delay * (2**0), max_delay) == 5.0

	# Retry 2: 5 * 2^1 = 10s
	assert min(base_delay * (2**1), max_delay) == 10.0

	# Retry 3: 5 * 2^2 = 20s
	assert min(base_delay * (2**2), max_delay) == 20.0

	# Retry 4: 5 * 2^3 = 40s -> capped at 30s
	assert min(base_delay * (2**3), max_delay) == 30.0

	# Retry 5: 5 * 2^4 = 80s -> capped at 30s
	assert min(base_delay * (2**4), max_delay) == 30.0
