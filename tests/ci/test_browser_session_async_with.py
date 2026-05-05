"""
Tests for `BrowserSession` async context manager (`__aenter__` / `__aexit__`).

These tests verify the contract:

- `async with BrowserSession(...) as s` starts the session and exposes it
- Exiting the block cleanly stops the session (graceful, like calling `stop()`)
- A user exception inside the block does not prevent stop()
- `keep_alive=True` is honoured by the underlying lifecycle but the warning
  on entry tells the user that `async with` will still reset the session
- Resources (chromium subprocess) are released after the block exits
- An Agent can be constructed against a session that lives inside an
  `async with` block (existing API stays compatible)
- If `start()` raises during `__aenter__`, `__aexit__` is NOT called (per
  PEP 343), and the session does best-effort cleanup before re-raising

CLAUDE.md test rules followed:
- real `BrowserSession` + real headless chromium (no mocks)
- `pytest_httpserver` for HTTP, no remote URLs
- `mock_llm` only for the Agent compatibility test
- modern pytest-asyncio (plain async def, no decorator)
"""

from __future__ import annotations

import asyncio
import logging

import psutil
import pytest
from pytest_httpserver import HTTPServer

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession


def _make_session(**profile_overrides) -> BrowserSession:
	"""Build a headless BrowserSession with sane test defaults."""
	profile_kwargs = {
		'headless': True,
		'user_data_dir': None,  # ephemeral tmp dir
		'enable_default_extensions': False,  # speed up startup in tests
	}
	profile_kwargs.update(profile_overrides)
	return BrowserSession(browser_profile=BrowserProfile(**profile_kwargs))


# ---------------------------------------------------------------------------
# 1. fundamental: __aenter__ starts, __aexit__ stops
# ---------------------------------------------------------------------------
async def test_aenter_starts_and_aexit_stops():
	"""`async with BrowserSession()` starts the session on entry and stops it on exit."""
	session = _make_session()

	# Before entry: not connected
	assert not session.is_cdp_connected, 'session should not be connected before __aenter__'

	async with session as entered:
		# __aenter__ must return self so that `as entered` is the same session
		assert entered is session
		assert session.is_cdp_connected, 'session should be connected inside the block'

	# After exit: stop() ran, EventBus was reset
	assert not session.is_cdp_connected, 'session should not be connected after __aexit__'


# ---------------------------------------------------------------------------
# 2. PEP 343 contract: user exception still stops the session and propagates
# ---------------------------------------------------------------------------
async def test_user_exception_propagates_and_session_still_stops():
	"""A user exception inside the block must propagate, and the session must still stop."""
	session = _make_session()

	class _UserError(RuntimeError):
		pass

	with pytest.raises(_UserError, match='intentional user error'):
		async with session:
			assert session.is_cdp_connected
			raise _UserError('intentional user error')

	# stop() ran via __aexit__ even though the body raised
	assert not session.is_cdp_connected, 'session must be stopped after exit, even on exception'


# ---------------------------------------------------------------------------
# 3. keep_alive contract: warning on entry, session still resets on exit
# ---------------------------------------------------------------------------
async def test_keep_alive_emits_warning_on_aenter():
	"""Using `async with` on a keep_alive=True session must emit a warning at entry.

	This is intentional: `async with` semantically promises cleanup at exit,
	which contradicts keep_alive intent. We warn the user up front rather than
	silently resetting the session.

	Note: `browser_use` logger sets `propagate=False` (see logging_config.py),
	so we cannot rely on `caplog` (which attaches to the root logger). We attach
	a tiny capture handler directly to the `browser_use` namespace instead.
	"""
	session = _make_session(keep_alive=True)

	captured_messages: list[str] = []

	class _CaptureHandler(logging.Handler):
		def emit(self, record: logging.LogRecord) -> None:
			captured_messages.append(record.getMessage())

	handler = _CaptureHandler(level=logging.WARNING)
	bu_logger = logging.getLogger('browser_use')
	bu_logger.addHandler(handler)
	try:
		async with session:
			pass
	finally:
		bu_logger.removeHandler(handler)

	matching = [m for m in captured_messages if 'keep_alive' in m]
	assert len(matching) >= 1, f'expected a keep_alive warning, got messages: {captured_messages[:5]}'


# ---------------------------------------------------------------------------
# 4. resource leak: chromium process is terminated after normal exit
# ---------------------------------------------------------------------------
async def test_chromium_process_terminated_after_normal_aexit():
	"""After `async with` exits normally, the spawned chromium subprocess must be gone.

	Catches the regression where stop() leaves a zombie chromium process.
	"""
	session = _make_session()

	chromium_pid: int | None = None
	async with session:
		# Find the launched chromium PID by walking children of the current process.
		# BrowserSession launches chromium as a child (or grandchild) — accept either.
		current = psutil.Process()
		for child in current.children(recursive=True):
			# heuristic: chromium-family executables
			try:
				name = (child.name() or '').lower()
				if 'chrom' in name or 'headless_shell' in name:
					chromium_pid = child.pid
					break
			except (psutil.NoSuchProcess, psutil.AccessDenied):
				continue

		# If we can't find one, the test environment doesn't actually launch a child
		# process (e.g. CDP-attached). Skip rather than false-positive.
		if chromium_pid is None:
			pytest.skip('no child chromium process found; skipping resource-leak check')

		assert psutil.pid_exists(chromium_pid), 'chromium pid should exist while inside async with'

	# After exit: give the OS a brief moment to reap the child, then assert it is gone
	for _ in range(20):  # up to ~2s
		if not psutil.pid_exists(chromium_pid):
			break
		await asyncio.sleep(0.1)
	else:
		# Final check, fail if still alive
		assert not psutil.pid_exists(chromium_pid), f'chromium pid {chromium_pid} should be gone after __aexit__'


# ---------------------------------------------------------------------------
# 5. Agent compatibility: existing Agent(browser_session=s) pattern still works
# ---------------------------------------------------------------------------
async def test_agent_can_use_session_inside_async_with(httpserver: HTTPServer, mock_llm):
	"""`async with BrowserSession() as s: Agent(..., browser_session=s)` round-trips."""
	httpserver.expect_request('/').respond_with_data(
		'<html><body><h1>browser-use async-with test</h1></body></html>',
		content_type='text/html',
	)

	async with _make_session() as session:
		agent = Agent(
			task=f'visit {httpserver.url_for("/")} and report title',
			llm=mock_llm,
			browser_session=session,
		)
		# We don't need to fully run the agent here — we just need to assert that
		# constructing it against a context-managed session works and that the
		# session is healthy enough for the agent to talk to it.
		assert agent.browser_session is session
		assert session.is_cdp_connected

	# After exit, session is no longer connected
	assert not session.is_cdp_connected


# ---------------------------------------------------------------------------
# 6. start() failure during __aenter__ does NOT leak partial state
# ---------------------------------------------------------------------------
async def test_start_failure_in_aenter_does_not_leak_state():
	"""If `start()` raises during `__aenter__`, the session must not be left half-initialized.

	Per PEP 343, Python does NOT call `__aexit__` when `__aenter__` raises, so
	BrowserSession must do its own best-effort cleanup before re-raising.

	We subclass instead of monkeypatch because BrowserSession is a Pydantic v2
	BaseModel with `validate_assignment=True`, which rejects setattr on
	instance methods.
	"""

	class _StartBoom(RuntimeError):
		pass

	class _FailingSession(BrowserSession):
		async def start(self) -> None:
			raise _StartBoom('simulated start() failure')

	session = _FailingSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, enable_default_extensions=False))

	with pytest.raises(_StartBoom, match='simulated start'):
		async with session:
			pytest.fail('block body must not run when __aenter__ raises')

	# After failed enter: session must report not-connected (the cleanup branch
	# called kill()/stop() and reset internal state).
	assert not session.is_cdp_connected, 'session must not appear connected after a failed __aenter__'


# ---------------------------------------------------------------------------
# 6b. cloud / externally-attached sessions: __aenter__ rollback must NOT
#     tear down the caller's externally-managed browser (Codex review on PR
#     #4784). stop() flows into BrowserStopEvent which derives a cloud
#     session ID from cdp_url and terminates it; kill() obviously does the
#     same with force=True. Both must be skipped for non-local sessions.
# ---------------------------------------------------------------------------
async def test_aenter_failure_skips_cleanup_for_non_local_sessions():
	"""On a non-local session, a failing `start()` must not call `kill()` or
	`stop()` — those would terminate the externally-managed browser.

	Verified by spying on both methods through a subclass that reports
	``is_local == False``.
	"""
	cleanup_calls: list[str] = []

	class _StartBoom(RuntimeError):
		pass

	class _NonLocalFailingSession(BrowserSession):
		@property
		def is_local(self) -> bool:
			# Pretend this session was attached to an externally-managed browser.
			return False

		async def start(self) -> None:
			raise _StartBoom('simulated start() failure on non-local')

		async def kill(self) -> None:
			cleanup_calls.append('kill')

		async def stop(self) -> None:
			cleanup_calls.append('stop')

	session = _NonLocalFailingSession(
		browser_profile=BrowserProfile(headless=True, user_data_dir=None, enable_default_extensions=False)
	)

	with pytest.raises(_StartBoom, match='simulated start'):
		async with session:
			pytest.fail('block body must not run')

	# Critical: cleanup must be skipped for non-local sessions, otherwise we
	# would tear down a browser the caller asked us only to attach to.
	assert cleanup_calls == [], f'cleanup must be skipped for non-local sessions, got: {cleanup_calls}'


# ---------------------------------------------------------------------------
# 7. CancelledError contract: task cancel inside the block must still stop()
# ---------------------------------------------------------------------------
async def test_cancelled_error_in_block_still_stops_session():
	"""asyncio.CancelledError mid-block must propagate AND trigger cleanup.

	Cancel is a BaseException (not Exception), so any cleanup that catches
	`Exception` would silently miss it. `__aexit__` must run on cancellation.
	"""
	session = _make_session()

	async def _run_with_cancel() -> None:
		async with session:
			assert session.is_cdp_connected
			# Self-cancel from inside the block.
			task = asyncio.current_task()
			assert task is not None
			task.cancel()
			# Yield so the cancellation actually fires here, not later.
			await asyncio.sleep(0)

	with pytest.raises(asyncio.CancelledError):
		await _run_with_cancel()

	# stop() must have run via __aexit__ even on cancellation
	assert not session.is_cdp_connected, 'session must be stopped after CancelledError, not leaked'


# ---------------------------------------------------------------------------
# Note: a `test_reentry_same_instance` style test is intentionally NOT
# included here. The current BrowserSession lifecycle does not support
# reusing the same instance across multiple `async with` blocks because
# `stop()` rebuilds the internal EventBus while the handlers registered in
# `model_post_init` stay on the original bus. The docstring of
# `BrowserSession.__aenter__` documents this limitation. Lifting it is a
# separate change to the lifecycle code and is out of scope for this PR.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 8. minimal: empty block completes without errors
# ---------------------------------------------------------------------------
async def test_no_op_empty_block_completes():
	"""`async with BrowserSession(): pass` must complete a full start/stop cycle.

	Catches the regression where an unused context manager raises (e.g. due
	to lazy initialization that only runs on the first action).
	"""
	async with _make_session():
		pass  # no actions, just enter and exit


# ---------------------------------------------------------------------------
# 10. real navigate inside the block must work
# ---------------------------------------------------------------------------
async def test_navigate_inside_async_with_block(httpserver: HTTPServer):
	"""Inside `async with`, the session must be capable of real CDP work."""
	httpserver.expect_request('/').respond_with_data(
		'<html><body><h1>browser-use sanity</h1></body></html>',
		content_type='text/html',
	)
	url = httpserver.url_for('/')

	async with _make_session() as session:
		assert session.is_cdp_connected
		# A real CDP-driven navigate should resolve without error inside the block
		await session.navigate_to(url)
		current = await session.get_current_page_url()
		assert url.split('?')[0] in current, f'expected to be at {url}, got {current}'


# ---------------------------------------------------------------------------
# 11. two independent sessions running side-by-side (sequential, not nested)
# ---------------------------------------------------------------------------
async def test_two_independent_sessions_run_sequentially():
	"""Two independent BrowserSession objects must each manage their own
	chromium subprocess without interfering with each other when used in
	sequence."""
	async with _make_session() as s1:
		assert s1.is_cdp_connected

	async with _make_session() as s2:
		assert s2.is_cdp_connected

	assert not s1.is_cdp_connected
	assert not s2.is_cdp_connected


# ---------------------------------------------------------------------------
# 12. nested usage of two independent sessions (concurrent lifetimes)
# ---------------------------------------------------------------------------
async def test_two_independent_sessions_nested():
	"""Two independent sessions used in nested `async with` blocks must each
	stay healthy until their own block exits."""
	async with _make_session() as outer:
		assert outer.is_cdp_connected
		async with _make_session() as inner:
			assert inner.is_cdp_connected
			# both connected at the same time
			assert outer.is_cdp_connected
			assert inner is not outer
		# inner exited; outer must remain connected
		assert not inner.is_cdp_connected
		assert outer.is_cdp_connected
	assert not outer.is_cdp_connected


# ---------------------------------------------------------------------------
# 13. user calls start() inside the block — must be idempotent (no-op)
# ---------------------------------------------------------------------------
async def test_user_calling_start_inside_block_is_idempotent():
	"""If user code calls `await session.start()` inside an `async with`
	block, the second call must be a no-op — start() is documented as
	idempotent (browser/session.py docstring at on_BrowserStartEvent)."""
	async with _make_session() as session:
		assert session.is_cdp_connected
		# Second start() call should be a no-op
		await session.start()
		assert session.is_cdp_connected, 'second start() inside block must not break connection'


# ---------------------------------------------------------------------------
# 14. calling stop() before exiting also works (cooperative early teardown)
# ---------------------------------------------------------------------------
async def test_user_calling_stop_inside_block_then_exit():
	"""User can `await session.stop()` early; `__aexit__` then runs against
	an already-stopped session and must not crash."""
	session = _make_session()
	async with session:
		assert session.is_cdp_connected
		await session.stop()
		assert not session.is_cdp_connected
	# __aexit__ ran on already-stopped session; must complete cleanly
	assert not session.is_cdp_connected


# ---------------------------------------------------------------------------
# 15. resource leak: no orphan asyncio tasks survive the block
# ---------------------------------------------------------------------------
async def test_no_orphan_asyncio_tasks_after_aexit():
	"""After exiting `async with`, the number of asyncio tasks belonging to
	BrowserSession internals must return to baseline.

	Catches event-bus or watchdog tasks that aren't cancelled on stop().
	"""
	loop = asyncio.get_event_loop()
	# Snapshot the baseline of tasks owned by this loop before the block.
	# We only count tasks NOT belonging to the current test coroutine.
	current = asyncio.current_task()
	baseline = {t for t in asyncio.all_tasks(loop) if t is not current and not t.done()}

	async with _make_session():
		pass

	# After exit, give the loop a couple of ticks to retire transient tasks
	for _ in range(20):
		leaked = {t for t in asyncio.all_tasks(loop) if t is not current and not t.done()} - baseline
		if not leaked:
			break
		await asyncio.sleep(0.1)
	else:
		# Build a readable failure message listing the leaked tasks
		names = sorted(t.get_name() for t in leaked)
		pytest.fail(f'leaked asyncio tasks after __aexit__: {names}')


# ---------------------------------------------------------------------------
# 15. exit-side cleanup error must not mask a user exception in flight
# ---------------------------------------------------------------------------
async def test_aexit_stop_failure_does_not_mask_user_exception():
	"""If `stop()` itself raises during `__aexit__` while a user exception is
	already in flight, the user's exception must surface, not the cleanup error.

	Conversely, if the block exited normally, the cleanup error must propagate
	(otherwise it would be silently swallowed). Both directions of the
	asymmetric contract are covered.

	We override `start()` and `stop()` so this test exercises only the
	`__aexit__` exception-masking branch — no real chromium is spawned.
	"""

	class _StopBoom(RuntimeError):
		pass

	class _UserError(RuntimeError):
		pass

	class _StopFailingSession(BrowserSession):
		async def start(self) -> None:
			# Skip real chromium spawn — test focuses on __aexit__ behavior.
			pass

		async def stop(self) -> None:
			raise _StopBoom('simulated stop() failure')

	# Direction 1: user error in flight + stop() fails → user error wins
	session1 = _StopFailingSession(
		browser_profile=BrowserProfile(headless=True, user_data_dir=None, enable_default_extensions=False)
	)
	with pytest.raises(_UserError, match='user exception wins'):
		async with session1:
			raise _UserError('user exception wins')

	# Direction 2: block exited normally + stop() fails → cleanup error propagates
	session2 = _StopFailingSession(
		browser_profile=BrowserProfile(headless=True, user_data_dir=None, enable_default_extensions=False)
	)
	with pytest.raises(_StopBoom, match='simulated stop'):
		async with session2:
			pass
