"""Test agent stops when browser is closed manually.

Verifies that when CDP/browser connection errors occur (e.g. user closes browser window),
the agent stops immediately instead of retrying until max_failures.
"""


class ConnectionClosedError(Exception):
	"""Simulates CDP connection closed - used only for error detection test."""


def test_is_browser_closed_error_detects_connection_errors(browser_session, mock_llm):
	"""Agent detects various browser-closed error patterns. Uses real browser_session per project guidelines."""
	from browser_use import Agent

	agent = Agent(task='test', llm=mock_llm, browser_session=browser_session)

	assert agent._is_browser_closed_error(ConnectionClosedError()) is True
	assert agent._is_browser_closed_error(RuntimeError('browser not connected')) is True
	assert agent._is_browser_closed_error(RuntimeError('Failed to open new tab - no browser is open')) is True
	assert (
		agent._is_browser_closed_error(
			RuntimeError('No valid agent focus available - target may have detached and recovery failed')
		)
		is True
	)

	# Normal errors should not trigger
	assert agent._is_browser_closed_error(ValueError('invalid input')) is False
	assert agent._is_browser_closed_error(RuntimeError('Element not found')) is False


async def test_handle_step_error_stops_agent_on_browser_closed(browser_session, mock_llm):
	"""When browser-closed error occurs, agent sets state.stopped and records result. Uses real browser_session."""
	from browser_use import Agent

	agent = Agent(task='test', llm=mock_llm, browser_session=browser_session)
	agent.state.stopped = False

	await agent._handle_step_error(RuntimeError('Cannot navigate - browser not connected'))

	assert agent.state.stopped is True
	assert agent.state.last_result is not None
	assert len(agent.state.last_result) == 1
	error_msg = agent.state.last_result[0].error
	assert error_msg is not None
	assert 'Browser closed' in error_msg
