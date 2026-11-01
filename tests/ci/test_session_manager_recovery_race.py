"""Regression tests for the SessionManager._recover_agent_focus race condition.

Bug: a concurrent waiter that gave up inside _recover_agent_focus() (5s timeout
while waiting for the ongoing recovery) unconditionally reset the recovery
state in its finally block - it set _recovery_complete_event, cleared
_recovery_in_progress and dropped the _recovery_task reference - even though
the recovery owner was still running outside the lock. Consequences:

1. Third parties waiting on the event (e.g. ensure_valid_focus) were signalled
   that recovery had completed while it was still in flight.
2. The cleared _recovery_in_progress flag allowed yet another concurrent
   recovery to start, which could create a second emergency tab.

Fix: only the task that created the recovery state (the owner) may reset it.
"""


import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

from browser_use.browser.session_manager import SessionManager


def _make_session_manager() -> tuple[SessionManager, MagicMock]:
	logger = logging.getLogger('test_recovery_race')
	browser_session = MagicMock()
	browser_session.logger = logger
	# Non-None CDP client so the recovery owner proceeds past the shutdown check
	browser_session._cdp_client_root = MagicMock()
	# Focus points at the crashed target so the owner does not bail out early
	browser_session.agent_focus_target_id = 'crashed-target'
	return SessionManager(browser_session), browser_session


class TimedOutEventStub:
	"""Stub for _recovery_complete_event whose wait() raises TimeoutError.

	Mimics what asyncio.wait_for(..., timeout=5.0) delivers to a concurrent
	waiter when the ongoing recovery takes longer than 5s, without waiting 5s.
	"""

	def __init__(self) -> None:
		self._set = False

	async def wait(self) -> None:
		await asyncio.sleep(0.05)
		if not self._set:
			raise TimeoutError

	def set(self) -> None:
		self._set = True

	def is_set(self) -> bool:
		return self._set


async def test_timed_out_waiter_does_not_reset_owner_recovery_state() -> None:
	"""While slow recovery owner A is still recovering, a concurrent waiter B
	that gives up (timeout path) must NOT reset A's recovery state."""
	sm, browser_session = _make_session_manager()

	release_owner = asyncio.Event()

	# First poll after creating the new page finds the session, so A succeeds
	mock_session = MagicMock()
	sm._get_session_for_target = MagicMock(return_value=mock_session)

	# Owner A blocks in _cdp_create_new_page until the test releases it
	async def slow_create_page(url: str) -> str:
		await release_owner.wait()
		return 'new-target-A'

	browser_session._cdp_create_new_page = AsyncMock(side_effect=slow_create_page)

	# Start the slow recovery owner A
	task_a = asyncio.create_task(sm._recover_agent_focus('crashed-target'))
	await asyncio.sleep(0.05)
	# A has acquired the lock, created the recovery state, released the lock and
	# is now blocked in _cdp_create_new_page (still recovering outside the lock)
	assert sm._recovery_in_progress is True
	assert sm._recovery_complete_event is not None
	# Simulate the _handle_target_detached bookkeeping pointing at A's task
	sm._recovery_task = task_a

	# Swap in a stub event so concurrent waiter B times out quickly (the stub's
	# wait() raises TimeoutError, i.e. the 5s wait_for timeout fires early)
	stub_event = TimedOutEventStub()
	sm._recovery_complete_event = stub_event

	# Start concurrent waiter B: it sees recovery in progress and waits for it
	task_b = asyncio.create_task(sm._recover_agent_focus('other-crashed-target'))
	await asyncio.wait_for(task_b, timeout=2.0)  # B gives up via the timeout path

	# THE REGRESSION: B's exit must not touch A's in-flight recovery state
	assert sm._recovery_in_progress is True, 'waiter B reset _recovery_in_progress while owner A is still recovering'
	assert sm._recovery_complete_event is stub_event
	assert stub_event.is_set() is False, 'waiter B signalled recovery completion while owner A is still recovering'
	assert sm._recovery_task is task_a, 'waiter B dropped the owner recovery task reference'

	# Owner A finishes and resets its own recovery state
	release_owner.set()
	await asyncio.wait_for(task_a, timeout=5.0)

	assert sm._recovery_in_progress is False
	assert stub_event.is_set() is True
	assert sm._recovery_task is None
	assert browser_session.agent_focus_target_id == 'new-target-A'
