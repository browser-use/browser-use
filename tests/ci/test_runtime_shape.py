from pathlib import Path

import pytest
from pydantic import ValidationError

from browser_use.agent.runtime import (
	ArtifactStore,
	BrowserAgentSession,
	BrowserEventStream,
	BrowserRunConfig,
	ModelCapabilities,
	ToolContext,
)
from browser_use.llm.openai.chat import ChatOpenAI


class ExperimentalLLM:
	provider = 'browser-use'
	model = 'brand-new-browser-model-2026-05-30'
	supports_native_tool_calling = True
	supports_structured_output = True
	supports_vision = True


def test_model_capabilities_preserve_unknown_model_name() -> None:
	capabilities = ModelCapabilities.from_llm(ExperimentalLLM())

	assert capabilities.provider == 'browser-use'
	assert capabilities.model_name == 'brand-new-browser-model-2026-05-30'
	assert capabilities.native_tool_calling is True
	assert capabilities.structured_output is True
	assert capabilities.vision is True
	assert capabilities.prefers_flash_mode is True
	assert capabilities.uses_browser_use_prompt is False


def test_openai_wrapper_advertises_native_tool_capabilities_without_model_rewrites() -> None:
	llm = ChatOpenAI(model='gpt-5.4-mini')
	capabilities = ModelCapabilities.from_llm(llm)

	assert capabilities.provider == 'openai'
	assert capabilities.model_name == 'gpt-5.4-mini'
	assert capabilities.native_tool_calling is True
	assert capabilities.structured_output is True
	assert capabilities.parallel_tool_calls is True


class ClaudeSonnetLLM:
	provider = 'anthropic'
	model = 'claude-sonnet-4-20260101'


class ClaudeOpus45LLM:
	provider = 'anthropic'
	model = 'claude-opus-4-5-20260101'


class GeminiLLM:
	provider = 'google'
	model = 'gemini-3-pro-preview'


class GrokLLM:
	provider = 'xai'
	model = 'grok-3-fast'


def test_model_capabilities_centralize_agent_setup_heuristics() -> None:
	claude = ModelCapabilities.from_llm(ClaudeSonnetLLM())
	opus = ModelCapabilities.from_llm(ClaudeOpus45LLM())
	gemini = ModelCapabilities.from_llm(GeminiLLM())
	grok = ModelCapabilities.from_llm(GrokLLM())

	assert claude.is_anthropic is True
	assert claude.recommended_screenshot_size == (1400, 850)
	assert claude.default_timeout_s == 90
	assert claude.supports_coordinate_clicking is True
	assert opus.is_anthropic_4_5 is True
	assert gemini.default_timeout_s == 90
	assert gemini.supports_coordinate_clicking is True
	assert grok.default_timeout_s == 75
	assert grok.unsupported_vision_reason == 'This XAI model does not support use_vision=True yet.'


def test_browser_agent_session_represents_run_and_turn() -> None:
	config = BrowserRunConfig(max_steps=12, max_actions_per_step=4)
	session = BrowserAgentSession.create(task='Find the install command', llm=ExperimentalLLM(), config=config)

	turn = session.start_turn(step_index=0, browser_state={'url': 'about:blank', 'elements': []})
	finished_event = session.finish_turn(turn, metadata={'actions': 1})

	assert session.run_id == config.run_id
	assert session.config.runtime_mode == 'legacy'
	assert session.model_capabilities.model_name == ExperimentalLLM.model
	assert len(session.turns) == 1
	assert turn.status == 'completed'
	assert session.event_stream.events[0].event_type == 'turn.started'
	assert finished_event.event_type == 'turn.completed'
	assert [event.sequence for event in session.event_stream.events] == [1, 2]


def test_tool_context_shares_event_stream_and_artifacts() -> None:
	session = BrowserAgentSession.create(task='Download a file')
	turn = session.start_turn(step_index=2)
	tool_context = session.tool_context(turn, metadata={'source': 'test'})

	artifact = tool_context.artifact_store.add(kind='download', name='report.csv', path=Path('/tmp/report.csv'))
	event = tool_context.emit_tool_event('tool.completed', {'tool_name': 'browser.download'})

	assert session.artifact_store.get(artifact.artifact_id) == artifact
	assert event.run_id == session.run_id
	assert event.turn_id == turn.turn_id
	assert event.sequence == 2
	assert event.payload == {'tool_name': 'browser.download'}


def test_event_stream_can_reset_sequence() -> None:
	stream = BrowserEventStream()
	stream.emit(run_id='run-1', event_type='run.started')
	stream.clear()
	event = stream.emit(run_id='run-1', event_type='run.started')

	assert event.sequence == 1
	assert len(stream.events) == 1


def test_runtime_models_validate_basic_invariants() -> None:
	with pytest.raises(ValidationError):
		BrowserRunConfig(max_steps=0)

	with pytest.raises(ValidationError):
		BrowserAgentSession.create(task='   ')


def test_tool_context_can_be_constructed_directly() -> None:
	store = ArtifactStore()
	stream = BrowserEventStream()
	context = ToolContext(run_id='run-1', turn_id='turn-1', artifact_store=store, event_stream=stream)

	context.artifact_store.add(kind='screenshot', uri='memory://step-1.png', media_type='image/png')
	context.emit_tool_event('tool.started', {'tool_name': 'browser.screenshot'})

	assert context.artifact_store is store
	assert context.event_stream is stream
	assert stream.events[0].event_type == 'tool.started'
