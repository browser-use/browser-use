"""Regression test: a failed step must tell the model why it actually failed.

When a step fails before the LLM returns usable output, `Agent._handle_step_error`
records the reason in `ActionResult.error` and clears `last_model_output`. The next
prompt is therefore built with `model_output=None`, and
`MessageManager._update_agent_history_description` used to render the recorded reason
(the old format was "No model output (parsing failed)" followed by the action results).

A history-formatting change (8c4dc394 "Improve history") dropped the action-results
interpolation from that branch, so every such failure was reported to the model as
"Agent failed to output in the right format." regardless of its real cause. An LLM
timeout, whose error text asks the model to shorten its output, was presented as a
schema violation instead, pushing the model to fix its JSON rather than shorten.
"""

import tempfile

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.views import ActionResult, AgentStepInfo
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm import SystemMessage

FORMAT_FALLBACK = 'Agent failed to output in the right format.'
LLM_TIMEOUT_ERROR = 'LLM call timed out after 60 seconds. Keep your thinking and output short.'


def _make_manager() -> MessageManager:
	return MessageManager(
		task='test task',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tempfile.mkdtemp()),
	)


def test_failed_step_reports_the_actual_error():
	"""The recorded error reaches the model instead of the generic format message."""
	mm = _make_manager()

	mm._update_agent_history_description(
		model_output=None,
		result=[ActionResult(error=LLM_TIMEOUT_ERROR)],
		step_info=AgentStepInfo(step_number=3, max_steps=10),
	)

	history = mm.agent_history_description
	assert LLM_TIMEOUT_ERROR in history
	assert FORMAT_FALLBACK not in history


def test_failed_step_without_a_recorded_error_keeps_the_format_message():
	"""With nothing to report, the original generic message is still the best guess."""
	mm = _make_manager()

	mm._update_agent_history_description(
		model_output=None,
		result=[],
		step_info=AgentStepInfo(step_number=3, max_steps=10),
	)

	assert FORMAT_FALLBACK in mm.agent_history_description


def test_long_step_error_is_elided_in_the_middle():
	"""A long error (e.g. a stack trace) is shortened so it cannot flood the prompt."""
	mm = _make_manager()
	long_error = 'HEAD' + 'x' * 500 + 'TAIL'

	mm._update_agent_history_description(
		model_output=None,
		result=[ActionResult(error=long_error)],
		step_info=AgentStepInfo(step_number=3, max_steps=10),
	)

	history = mm.agent_history_description
	assert long_error not in history
	assert 'HEAD' in history
	assert 'TAIL' in history
	assert '......' in history
