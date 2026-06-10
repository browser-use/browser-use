"""Tests for the LLM-driven stage orchestration loop in BrowserResearchAssistant.

These verify the alignment of research.py's orchestration with the core Agent's
observe->decide->act->replan philosophy: the orchestrator LLM picks the next stage
(or finishes early), budget is a dynamic shared pool, prior findings flow into the
next stage's prompt, and an unavailable orchestrator LLM degrades to a static drain.

No real browsers are launched: _run_stage is monkeypatched to return canned results,
and the orchestrator LLM is a small stub returning OrchestratorDecision objects.
"""

from __future__ import annotations

from browser_use.assistant.research import (
	AssistantMode,
	BrowserResearchAssistant,
	CandidateEvidence,
	GeneratedStageSpec,
	OrchestratorDecision,
	ResearchAssistantConfig,
	SourceType,
	StageResult,
	TaskPlan,
)
from browser_use.llm.views import ChatInvokeCompletion


class StubOrchestratorLLM:
	"""Returns a scripted sequence of OrchestratorDecision objects for output_format calls.

	If raise_always is set, ainvoke raises — used to exercise the static fallback path.
	"""

	def __init__(self, decisions: list[OrchestratorDecision] | None = None, raise_always: bool = False):
		self.model = 'stub-orchestrator'
		self._decisions = decisions or []
		self._index = 0
		self.raise_always = raise_always
		self.calls = 0

	async def ainvoke(self, messages, output_format=None):
		self.calls += 1
		if self.raise_always:
			raise RuntimeError('orchestrator LLM unavailable')
		if self._index < len(self._decisions):
			decision = self._decisions[self._index]
			self._index += 1
		else:
			decision = OrchestratorDecision(reasoning='exhausted', action='finish', finish_reason='no more decisions')
		return ChatInvokeCompletion(completion=decision, usage=None)


def _make_plan() -> TaskPlan:
	return TaskPlan(
		user_task='recommend over-ear headphones under 1000元',
		mode=AssistantMode.recommendation,
		locale='zh-CN',
		topic='headphones',
		budget='1000元',
		shopping_sources=['jd.com'],
		review_sources=['sspai.com'],
		web_sources=['bing.com'],
		shopping_queries=['耳机'],
		review_queries=['耳机 测评'],
		web_queries=['头戴耳机推荐'],
	)


def _make_config() -> ResearchAssistantConfig:
	return ResearchAssistantConfig(task='recommend over-ear headphones under 1000元', model='gpt-5.4', max_steps=18)


def _fake_stage_result(source_type: SourceType, steps_used: int, with_candidate: bool = True) -> StageResult:
	evidence = (
		[CandidateEvidence(title=f'{source_type.value} pick', source_type=source_type, source='x.com', evidence='ok')]
		if with_candidate
		else []
	)
	return StageResult(
		stage_name=f'{source_type.value}_collection',
		source_type=source_type,
		sources=['x.com'],
		prompt='stub-prompt',
		candidate_evidence=evidence,
		steps_used=steps_used,
	)


def _install_recording_run_stage(assistant: BrowserResearchAssistant, steps_per_stage: int = 4):
	"""Replace _run_stage with a recorder that returns canned results and captures prior_findings."""
	calls: list[dict] = []

	async def fake_run_stage(plan, source_type, sources, queries, max_steps, cdp_url, prior_findings=None):
		calls.append(
			{
				'source_type': source_type,
				'sources': list(sources),
				'max_steps': max_steps,
				'prior_findings': prior_findings,
			}
		)
		return _fake_stage_result(source_type, steps_used=steps_per_stage)

	assistant._run_stage = fake_run_stage  # type: ignore[method-assign]
	return calls


def _make_assistant(stub: StubOrchestratorLLM) -> BrowserResearchAssistant:
	assistant = BrowserResearchAssistant(_make_config(), llm=stub)  # type: ignore[arg-type]
	return assistant


async def test_orchestrator_finishes_early():
	"""Orchestrator can stop after one stage even though more remain in the queue."""
	plan = _make_plan()
	assistant = _make_assistant(
		StubOrchestratorLLM(
			decisions=[
				OrchestratorDecision(reasoning='run first', action='run_stage'),
				OrchestratorDecision(reasoning='enough evidence', action='finish', finish_reason='done'),
			]
		)
	)
	calls = _install_recording_run_stage(assistant)

	results = await assistant._run_stages(plan, cdp_url=None)

	# Only one stage ran despite web+shopping+review all being queued.
	assert len(results) == 1
	assert len(calls) == 1


async def test_dynamic_budget_pool_drains_and_reclaims():
	"""Each stage draws max(MIN, steps_used) from the shared pool; cheap stages leave more for later ones."""
	plan = _make_plan()
	# Run every stage (no early finish) so we exhaust the queue.
	decisions = [OrchestratorDecision(reasoning=f'run {i}', action='run_stage') for i in range(5)]
	assistant = _make_assistant(StubOrchestratorLLM(decisions=decisions))
	calls = _install_recording_run_stage(assistant, steps_per_stage=4)

	results = await assistant._run_stages(plan, cdp_url=None)

	# Queue has web+shopping+review = 3 stages; all run, none exceeds the per-stage cap.
	assert len(results) == 3
	assert all(call['max_steps'] >= 2 for call in calls)
	# The first stage gets a full base allocation; later stages still get >= MIN_STAGE_STEPS.
	assert calls[0]['max_steps'] >= calls[-1]['max_steps']


async def test_prior_findings_injected_into_later_stages():
	"""Stage N+1 receives a non-empty prior_findings snapshot; the first stage receives none."""
	plan = _make_plan()
	decisions = [OrchestratorDecision(reasoning=f'run {i}', action='run_stage') for i in range(5)]
	assistant = _make_assistant(StubOrchestratorLLM(decisions=decisions))
	calls = _install_recording_run_stage(assistant)

	await assistant._run_stages(plan, cdp_url=None)

	assert len(calls) >= 2
	# First stage has no prior context.
	assert not calls[0]['prior_findings']
	# Subsequent stages see prior findings referencing the earlier stage.
	assert calls[1]['prior_findings']
	assert 'Prior findings' in calls[1]['prior_findings']


async def test_synthesized_next_stage_overrides_queue():
	"""When the orchestrator returns next_stage, that spec runs instead of the queue head."""
	plan = _make_plan()
	custom = GeneratedStageSpec(source_type=SourceType.official, source='sony.com', queries=['wh-1000xm5'])
	assistant = _make_assistant(
		StubOrchestratorLLM(
			decisions=[
				OrchestratorDecision(reasoning='go official first', action='run_stage', next_stage=custom),
				OrchestratorDecision(reasoning='done', action='finish'),
			]
		)
	)
	calls = _install_recording_run_stage(assistant)

	await assistant._run_stages(plan, cdp_url=None)

	assert len(calls) == 1
	assert calls[0]['source_type'] == SourceType.official
	assert calls[0]['sources'] == ['sony.com']


async def test_falls_back_to_static_drain_when_orchestrator_llm_fails():
	"""If the orchestrator LLM (and fallback) error, the loop drains the queue deterministically."""
	plan = _make_plan()
	assistant = _make_assistant(StubOrchestratorLLM(raise_always=True))
	assistant.fallback_llm = None
	calls = _install_recording_run_stage(assistant)

	results = await assistant._run_stages(plan, cdp_url=None)

	# All three queued stages ran via the static fallback, in priority order (web first).
	assert len(results) == 3
	assert calls[0]['source_type'] == SourceType.web


async def test_empty_queue_returns_no_stages():
	"""A plan with no sources yields an empty queue and no orchestration calls."""
	plan = TaskPlan(user_task='x', mode=AssistantMode.generic, locale='en-US', topic='x')
	llm = StubOrchestratorLLM()
	assistant = _make_assistant(llm)
	_install_recording_run_stage(assistant)

	results = await assistant._run_stages(plan, cdp_url=None)

	assert results == []
	assert llm.calls == 0
