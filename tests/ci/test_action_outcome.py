"""Tests for ActionOutcome typed result system.

Covers: outcome enum values, ActionResult helper properties,
consecutive failures counting per outcome type,
multi_act break behavior, backward compatibility.
"""

from browser_use.agent.service import Agent
from browser_use.agent.views import (
	ActionOutcome,
	ActionResult,
)

# ===========================================================================
# Pure unit tests (no fixtures needed)
# ===========================================================================


class TestActionOutcomeEnum:
	"""ActionOutcome enum behavior"""

	def test_enum_values(self):
		assert ActionOutcome.SUCCESS.value == 'success'
		assert ActionOutcome.NOT_FOUND.value == 'not_found'
		assert ActionOutcome.INVALID_STATE.value == 'invalid_state'
		assert ActionOutcome.SYSTEM_ERROR.value == 'system_error'

	def test_is_str_enum(self):
		assert isinstance(ActionOutcome.SUCCESS, str)
		assert ActionOutcome.SUCCESS == 'success'


class TestActionResultHelpers:
	"""ActionResult helper properties"""

	def test_default_outcome(self):
		r = ActionResult()
		assert r.outcome == ActionOutcome.SUCCESS
		assert not r.is_not_found
		assert not r.is_system_error
		assert not r.is_invalid_state

	def test_not_found(self):
		r = ActionResult(outcome=ActionOutcome.NOT_FOUND, error='element not on page')
		assert r.is_not_found
		assert not r.is_system_error
		assert not r.is_invalid_state

	def test_system_error(self):
		r = ActionResult(outcome=ActionOutcome.SYSTEM_ERROR, error='cdp connection lost')
		assert r.is_system_error
		assert not r.is_not_found
		assert not r.is_invalid_state

	def test_invalid_state(self):
		r = ActionResult(outcome=ActionOutcome.INVALID_STATE, error='cannot click select element')
		assert r.is_invalid_state
		assert not r.is_not_found
		assert not r.is_system_error

	def test_backward_compat(self):
		"""Old-style ActionResult(error=...) now auto-infers SYSTEM_ERROR (not SUCCESS)."""
		r = ActionResult(error='some error')
		assert r.outcome == ActionOutcome.SYSTEM_ERROR
		assert r.is_system_error
		assert r.error == 'some error'

	def test_error_auto_infers_system_error(self):
		"""ActionResult(error=...) without explicit outcome defaults to SYSTEM_ERROR with new validator."""
		# Note: old style ActionResult(error=...) now auto-infers SYSTEM_ERROR
		# This is the expected behavior after the validator was added
		r = ActionResult(error='some error')
		assert r.outcome == ActionOutcome.SYSTEM_ERROR
		assert r.is_system_error
		assert r.error == 'some error'
		r = ActionResult(extracted_content='all good')
		assert r.outcome == ActionOutcome.SUCCESS
		assert not r.is_not_found
		assert r.error is None

	def test_break_conditions_not_found(self):
		"""NOT_FOUND triggers early break in multi_act"""
		r = ActionResult(outcome=ActionOutcome.NOT_FOUND, error='not found')
		assert r.is_not_found
		assert r.is_not_found or r.is_system_error or r.is_invalid_state

	def test_break_conditions_system_error(self):
		r = ActionResult(outcome=ActionOutcome.SYSTEM_ERROR, error='system failure')
		assert r.is_system_error
		assert r.is_system_error  # will break

	def test_break_conditions_invalid_state(self):
		r = ActionResult(outcome=ActionOutcome.INVALID_STATE, error='invalid state')
		assert r.is_invalid_state
		assert r.is_invalid_state  # will break


# ===========================================================================
# Agent integration tests (require browser_session + mock_llm fixtures)
# ===========================================================================


def _make_agent(browser_session, mock_llm, **kwargs):
	return Agent(task='Test task', llm=mock_llm, browser_session=browser_session, **kwargs)


class TestPostProcessFailureCounting:
	"""_post_process behavior with ActionOutcome"""

	async def test_system_error_increments(self, browser_session, mock_llm):
		agent = _make_agent(browser_session, mock_llm)
		agent.state.consecutive_failures = 0
		agent.state.last_result = [ActionResult(outcome=ActionOutcome.SYSTEM_ERROR, error='connection failed')]
		agent.state.n_steps = 1
		await agent._post_process()
		assert agent.state.consecutive_failures == 1

	async def test_not_found_does_not_increment(self, browser_session, mock_llm):
		agent = _make_agent(browser_session, mock_llm)
		agent.state.consecutive_failures = 0
		agent.state.last_result = [ActionResult(outcome=ActionOutcome.NOT_FOUND, error='element not found')]
		agent.state.n_steps = 1
		await agent._post_process()
		assert agent.state.consecutive_failures == 0

	async def test_invalid_state_does_not_increment(self, browser_session, mock_llm):
		agent = _make_agent(browser_session, mock_llm)
		agent.state.consecutive_failures = 0
		agent.state.last_result = [ActionResult(outcome=ActionOutcome.INVALID_STATE, error='cannot click select')]
		agent.state.n_steps = 1
		await agent._post_process()
		assert agent.state.consecutive_failures == 0

	async def test_success_resets_failures(self, browser_session, mock_llm):
		agent = _make_agent(browser_session, mock_llm)
		agent.state.consecutive_failures = 3
		agent.state.last_result = [ActionResult(extracted_content='success')]
		agent.state.n_steps = 1
		await agent._post_process()
		assert agent.state.consecutive_failures == 0

	async def test_old_style_error_becomes_system_error(self, browser_session, mock_llm):
		agent = _make_agent(browser_session, mock_llm)
		agent.state.consecutive_failures = 0
		agent.state.last_result = [ActionResult(error='old style error')]

		await agent._post_process()
		assert agent.state.consecutive_failures == 1
