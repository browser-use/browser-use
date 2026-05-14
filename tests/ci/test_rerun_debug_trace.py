"""Tests for rerun debug trace artifact generation."""

import json
from unittest.mock import AsyncMock

from browser_use.agent.service import Agent
from browser_use.agent.views import (
	ActionResult,
	AgentHistory,
	AgentHistoryList,
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
			source_history_path='fixtures/test-history.json',
		)

		assert len(results) == 2
		assert trace_path.exists()

		trace = json.loads(trace_path.read_text(encoding='utf-8'))
		assert trace['history_file_path'] == 'fixtures/test-history.json'
		assert trace['final_status'] == 'partial'
		assert trace['summary'] == 'Rerun completed with skipped steps'
		assert len(trace['steps']) == 1
		assert trace['steps'][0]['status'] == 'skipped'
		assert 'skip_failures=True' in trace['steps'][0]['skip_reason']
		assert trace['steps'][0]['original_url'] == 'https://example.com'
		assert trace['steps'][0]['goal'] == 'Open the destination page'
	finally:
		await agent.close()
