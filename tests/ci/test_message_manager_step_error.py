"""Regression test for the error text of steps that produced no model output.

`_update_agent_history_description` used to hardcode "Agent failed to output in the right
format." for every step whose `model_output` was None. `model_output is None` only means the
step never produced model output — a dropped CDP websocket, an LLM timeout or a `step_timeout`
cancellation all take that branch too, so the model was told to fix its JSON for failures that
had nothing to do with its output. The step's real error text is already formatted into
`action_results` a few lines above; it just has to reach the history item.
"""

import tempfile

import pytest
from pydantic import BaseModel, ValidationError

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.views import ActionResult, AgentError, AgentStepInfo
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm import SystemMessage


class _ExpectedSchema(BaseModel):
	"""Stand-in for AgentOutput, so a real pydantic ValidationError can be produced."""

	action: str


def _make_manager() -> MessageManager:
	return MessageManager(
		task='task',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tempfile.mkdtemp()),
	)


def _model_output_format_error() -> str:
	"""The exact text Agent._handle_step_error stores when model output validation fails."""
	with pytest.raises(ValidationError) as exc_info:
		_ExpectedSchema(action=object())
	return AgentError.format_error(exc_info.value)


def _run_failed_step(error: str, step_number: int) -> MessageManager:
	"""Record a step that produced no model output and only an error, like Agent.step does."""
	mm = _make_manager()
	mm._update_agent_history_description(
		model_output=None,
		result=[ActionResult(error=error)],
		step_info=AgentStepInfo(step_number=step_number, max_steps=10),
	)
	return mm


def test_non_format_step_error_reports_its_own_text():
	"""A step that failed for a non-format reason must say what actually went wrong."""
	step_error = 'WebSocket connection closed: browser disconnected'

	mm = _run_failed_step(step_error, step_number=3)

	item = mm.state.agent_history_items[-1]
	assert step_error in (item.error or '')
	assert AgentError.VALIDATION_ERROR not in (item.error or '')
	# HistoryItem.to_string() returns `error` verbatim, so this is what the model reads.
	assert step_error in item.to_string()


def test_output_format_failure_still_reports_the_format_problem():
	"""The real model-output ValidationError must keep telling the model its schema was wrong."""
	format_error = _model_output_format_error()
	assert AgentError.VALIDATION_ERROR in format_error

	mm = _run_failed_step(format_error, step_number=4)

	assert AgentError.VALIDATION_ERROR in (mm.state.agent_history_items[-1].error or '')


def test_step_without_any_error_text_keeps_the_format_hint():
	"""No error text at all means nothing better than the format hint can be said."""
	mm = _make_manager()
	mm._update_agent_history_description(
		model_output=None,
		result=[],
		step_info=AgentStepInfo(step_number=5, max_steps=10),
	)

	assert AgentError.VALIDATION_ERROR in (mm.state.agent_history_items[-1].error or '')
