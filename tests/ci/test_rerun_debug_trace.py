"""Tests for rerun debug trace artifact generation."""

import json
from unittest.mock import AsyncMock

from browser_use.agent.service import Agent
from browser_use.agent.views import (
	ActionResult,
	AgentHistory,
	AgentHistoryList,
	RerunTrace,
	RerunTraceAttempt,
	RerunTraceStep,
	RerunSummaryAction,
	StepMetadata,
)
from browser_use.browser.views import BrowserStateHistory
from tests.ci.conftest import create_mock_llm


async def test_rerun_debug_trace_written_for_skipped_step(tmp_path):
	"""rerun_history should persist a structured debug trace when requested."""

	summary_action = RerunSummaryAction(
		summary='Rerun completed with skipped steps',
		success=True,
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
	trace_path = tmp_path / 'rerun-trace.json'
	report_path = tmp_path / 'rerun-trace.html'

	mock_state = BrowserStateHistory(
		url='https://example.com',
		title='Test Page',
		tabs=[],
		interacted_element=[None],
	)

	AgentOutput = agent.AgentOutput
	failed_step = AgentHistory(
		model_output=AgentOutput(
			evaluation_previous_goal=None,
			memory='Trying to navigate',
			next_goal='Open the destination page',
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

	history = AgentHistoryList(history=[failed_step])

	try:
		results = await agent.rerun_history(
			history,
			skip_failures=True,
			summary_llm=mock_summary_llm,
			debug_trace_path=trace_path,
			debug_report_path=report_path,
			source_history_path='fixtures/test-history.json',
		)

		assert len(results) == 2
		assert trace_path.exists()
		assert report_path.exists()

		trace = json.loads(trace_path.read_text(encoding='utf-8'))
		report_html = report_path.read_text(encoding='utf-8')
		assert trace['history_file_path'] == 'fixtures/test-history.json'
		assert trace['final_status'] == 'partial'
		assert trace['summary'] == 'Rerun completed with skipped steps'
		assert len(trace['steps']) == 1
		assert trace['steps'][0]['status'] == 'skipped'
		assert 'skip_failures=True' in trace['steps'][0]['skip_reason']
		assert trace['steps'][0]['original_url'] == 'https://example.com'
		assert trace['steps'][0]['goal'] == 'Open the destination page'
		assert 'Browser Use Rerun Trace Report' in report_html
		assert 'fixtures/test-history.json' in report_html
		assert 'Rerun completed with skipped steps' in report_html
	finally:
		await agent.close()


def test_rerun_trace_html_report_renders_match_metadata():
	"""HTML report should expose match-level and action match details."""

	trace = RerunTrace(
		task='Replay login flow',
		history_file_path='fixtures/login-history.json',
		final_status='partial',
		summary='Replay diverged on submit button matching.',
		steps=[
			RerunTraceStep(
				replay_step_index=0,
				original_step_number=3,
				status='failed',
				goal='Click submit',
				original_actions=[{'click': {'index': 7}}],
				original_interacted_elements=[{'node_name': 'button', 'attributes': {'aria-label': 'Submit'}}],
				original_url='https://example.com/form',
				original_title='Form',
				original_screenshot_path='screenshots/original-step-3.png',
				replay_url='https://example.com/form',
				replay_title='Form',
				replay_screenshot_path='screenshots/replay-step-3.png',
				retry_count=1,
				failure_reason='Could not find matching element after retries.',
				attempts=[
					RerunTraceAttempt(
						attempt_number=1,
						status='failed',
						match_level='AX_NAME',
						matched_element={'index': 11, 'node_name': 'button', 'ax_name': 'Submit'},
						replay_screenshot_path='screenshots/replay-step-3-attempt-1.png',
						action_match_details=[
							{
								'action': {'click': {'index': 7}},
								'match_level': 'AX_NAME',
								'resolved_index': 11,
							}
						],
						error='Could not find matching element after navigation changed the page.',
					)
				],
			)
		],
	)

	report_html = trace.to_html_report()
	assert 'Browser Use Rerun Trace Report' in report_html
	assert 'AX_NAME' in report_html
	assert 'resolved_index' in report_html
	assert 'fixtures/login-history.json' in report_html
	assert 'screenshots/replay-step-3-attempt-1.png' in report_html
