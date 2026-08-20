from types import SimpleNamespace
from typing import Any

from browser_use.agent.service import Agent
from browser_use.agent.views import RerunSummaryAction
from browser_use.llm.views import ChatInvokeCompletion


class _SessionModel:
	def __init__(self) -> None:
		self.closed_sessions: list[str] = []
		self.model = 'session-model'

	async def close_session(self, session_id: str) -> None:
		self.closed_sessions.append(session_id)

	async def ainvoke(self, messages, output_format=None, **kwargs):
		return ChatInvokeCompletion(
			completion=RerunSummaryAction(summary='done', success=True, completion_status='complete'),
			usage=None,
		)


class _BrowserSession:
	id = 'browser-session'
	agent_focus_target_id = None

	async def take_screenshot(self, **kwargs):
		return None


async def test_agent_closes_only_its_session_on_each_distinct_model():
	shared = _SessionModel()
	compaction = _SessionModel()
	ai_step = _SessionModel()
	agent: Any = object.__new__(Agent)
	agent.session_id = 'agent-one'
	agent.llm = shared
	agent.judge_llm = shared
	agent._original_llm = shared
	agent._fallback_llm = None
	agent.settings = SimpleNamespace(
		page_extraction_llm=shared,
		message_compaction=SimpleNamespace(compaction_llm=compaction),
	)
	agent._additional_session_llms = {id(ai_step): ai_step}

	await agent._close_llm_sessions()

	assert shared.closed_sessions == ['agent-one']
	assert compaction.closed_sessions == ['agent-one']
	assert ai_step.closed_sessions == ['agent-one']


async def test_rerun_summary_tracks_custom_llm_for_session_cleanup():
	custom_summary_llm = _SessionModel()
	agent: Any = object.__new__(Agent)
	agent.session_id = 'agent-one'
	agent.llm = _SessionModel()
	agent.browser_session = _BrowserSession()
	agent._additional_session_llms = {}

	result = await agent._generate_rerun_summary('task', [], custom_summary_llm)

	assert result.error is None
	assert agent._additional_session_llms[id(custom_summary_llm)] is custom_summary_llm
