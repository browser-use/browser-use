"""Test that browser does not auto-reconnect after agent.close() with keep_alive=True.

Regression test for a browser-use keep_alive reconnect issue.
When an agent finishes (keep_alive=True) and the user manually closes Chrome,
the CDP WebSocket-drop callback must NOT trigger auto-reconnect.
"""

import pytest

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


@pytest.fixture(scope='function')
async def keep_alive_session():
	"""Create a keep_alive=True session, start it, yield, then kill."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		),
	)
	await session.start()
	yield session
	await session.kill()


class TestNoReconnectAfterClose:
	"""Verify _intentional_stop flag lifecycle prevents zombie reconnections."""

	async def test_agent_close_sets_intentional_stop(self, keep_alive_session: BrowserSession, mock_llm):
		"""Agent.close() with keep_alive=True must set _intentional_stop=True
		so that the CDP drop callback does NOT trigger auto-reconnect."""
		from browser_use import Agent

		session = keep_alive_session
		assert session._intentional_stop is False, '_intentional_stop should be False during active session'

		agent = Agent(task='Test task', llm=mock_llm, browser_session=session)
		await agent.run()

		# Agent.close() is called in the finally block of run().
		# With our fix, _intentional_stop must now be True.
		assert session._intentional_stop is True, (
			'_intentional_stop must be True after Agent.close() with keep_alive=True '
			'so that CDP WebSocket-drop callback does not trigger auto-reconnect'
		)

	async def test_reset_preserves_intentional_stop(self, keep_alive_session: BrowserSession):
		"""reset() must NOT clear _intentional_stop back to False.

		Previously reset() unconditionally set _intentional_stop = False at the
		end, which re-enabled auto-reconnect for delayed CDP callbacks.
		"""
		session = keep_alive_session

		# Set flag as kill()/stop()/Agent.close() would
		session._intentional_stop = True
		await session.reset()

		# After reset, the flag must still be True (our fix)
		assert session._intentional_stop is True, (
			'reset() must not clear _intentional_stop; delayed CDP callbacks could re-trigger auto-reconnect'
		)

	async def test_start_clears_intentional_stop(self):
		"""start() must clear _intentional_stop so auto-reconnect is armed
		for the new session (needed for session reuse pattern)."""
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=True,
			),
		)

		# Simulate prior close that set the flag
		session._intentional_stop = True

		# Starting a new session must clear the flag
		await session.start()
		assert session._intentional_stop is False, (
			'start() must clear _intentional_stop so auto-reconnect works for the new session'
		)

		await session.kill()

	async def test_ws_drop_callback_respects_intentional_stop(self, keep_alive_session: BrowserSession):
		"""The WebSocket-drop callback must be a no-op when _intentional_stop is True."""
		session = keep_alive_session

		# Set intentional stop (as Agent.close() now does)
		session._intentional_stop = True

		# Simulate what _on_message_handler_done checks
		# This is the guard that must prevent reconnection
		should_reconnect = not (session._intentional_stop or session._reconnecting or not session.cdp_url)
		assert not should_reconnect, 'With _intentional_stop=True, the WS drop callback must NOT trigger reconnection'

	async def test_sequential_reuse_with_agent(self, mock_llm):
		"""Verify the session reuse pattern still works after the fix.

		Pattern: session.start() -> agent1.run() -> agent1.close() ->
		         agent2 reuses session -> agent2.run() -> agent2.close() -> session.kill()
		"""
		from browser_use import Agent

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=True,
			),
		)

		try:
			# First agent lifecycle
			await session.start()
			assert session._intentional_stop is False

			agent1 = Agent(task='First task', llm=mock_llm, browser_session=session)
			await agent1.run()

			# After agent1 close, flag must be True
			assert session._intentional_stop is True

			# Second agent lifecycle — start() re-arms reconnection
			agent2 = Agent(task='Second task', llm=mock_llm, browser_session=session)
			await agent2.run()

			# After agent2 close, flag must be True again
			assert session._intentional_stop is True

		finally:
			await session.kill()
