"""Test agent stops when browser is closed manually.

Verifies that when CDP/browser connection errors occur (e.g. user closes browser window),
the agent stops immediately instead of retrying until max_failures.
"""

from unittest.mock import MagicMock

from browser_use import Agent
from tests.ci.conftest import create_mock_llm


class TestAgentBrowserClosed:
	"""Test agent behavior when browser is closed."""

	def test_is_browser_closed_error_detects_connection_errors(self):
		"""Agent detects various browser-closed error patterns."""
		mock_session = MagicMock()
		agent = Agent(task='test', llm=create_mock_llm(), browser_session=mock_session)

		# Connection errors
		class ConnectionClosedError(Exception):
			pass

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

	async def test_handle_step_error_stops_agent_on_browser_closed(self):
		"""When browser-closed error occurs, agent sets state.stopped and records result."""
		mock_session = MagicMock()
		agent = Agent(task='test', llm=create_mock_llm(), browser_session=mock_session)
		agent.state.stopped = False

		await agent._handle_step_error(RuntimeError('Cannot navigate - browser not connected'))

		assert agent.state.stopped is True
		assert agent.state.last_result is not None
		assert len(agent.state.last_result) == 1
		error_msg = agent.state.last_result[0].error
		assert error_msg is not None
		assert 'Browser closed' in error_msg
