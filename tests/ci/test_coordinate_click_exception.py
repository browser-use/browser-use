"""Tests for #5365: _click_by_coordinate() diagnosability.

Two deviations from the conventions used elsewhere in tools/service.py:

1. The generic exception handler in _click_by_coordinate() binds `e` but discards
   it, so the LLM never learns *why* a coordinate click failed (its sibling
   _click_by_index() includes the cause).
2. The fire-and-forget coordinate highlight uses a bare asyncio.create_task
   instead of the project's create_task_with_error_handling() helper, so a
   highlight failure surfaces as an unretrieved-task warning instead of being
   logged in context.

These tests drive the real registered click action with a lightweight
BrowserSession stand-in (no browser is launched).
"""

import asyncio

from browser_use.tools.service import Tools
from browser_use.tools.views import ClickElementAction


class _FakeEvent:
	"""Minimal event-bus event: awaitable, plus event_result()."""

	def __init__(self, result=None):
		self._result = result

	def __await__(self):
		async def _done():
			return None

		return _done().__await__()

	async def event_result(self, raise_if_any=True, raise_if_none=False):
		if raise_if_any and isinstance(self._result, Exception):
			raise self._result
		if raise_if_none and self._result is None:
			raise RuntimeError('No event result was produced')
		return self._result


class _FakeEventBus:
	def dispatch(self, event):
		return _FakeEvent()


class _FakeBrowserSession:
	"""BrowserSession stand-in exposing only what _click_by_coordinate touches."""

	def __init__(self, tabs_error=None):
		self.llm_screenshot_size = None
		self._original_viewport_size = None
		self.tabs_error = tabs_error
		self.event_bus = _FakeEventBus()
		self.highlight_coordinate_click_calls = []

	async def get_tabs(self):
		if self.tabs_error is not None:
			raise self.tabs_error
		return []

	async def highlight_coordinate_click(self, x, y):
		self.highlight_coordinate_click_calls.append((x, y))
		return None


async def _run_coordinate_click(session, x=100, y=200):
	tools = Tools()
	tools.set_coordinate_clicking(True)
	action = tools.registry.registry.actions['click']
	params = ClickElementAction(coordinate_x=x, coordinate_y=y)
	return await action.function(params=params, browser_session=session)


async def test_coordinate_click_error_includes_exception_detail():
	"""The failure cause must reach the ActionResult instead of being discarded."""
	session = _FakeBrowserSession(tabs_error=RuntimeError('boom-marker'))

	result = await _run_coordinate_click(session)

	assert result is not None
	assert result.error is not None
	assert 'Failed to click at coordinates (100, 200)' in result.error
	assert 'boom-marker' in result.error


async def test_coordinate_click_highlight_uses_error_handling_helper(monkeypatch):
	"""The highlight task must go through create_task_with_error_handling, not a bare asyncio.create_task."""
	original_create_task = asyncio.create_task
	helper_calls = []
	helper_tasks = []
	raw_task_coroutines = []

	def fake_create_task(coro, *args, **kwargs):
		raw_task_coroutines.append(coro)
		return original_create_task(coro, *args, **kwargs)

	def fake_helper(coro, *, name=None, logger_instance=None, suppress_exceptions=False):
		helper_calls.append((name, suppress_exceptions))
		task = original_create_task(coro)
		helper_tasks.append(task)
		return task

	monkeypatch.setattr('asyncio.create_task', fake_create_task)
	monkeypatch.setattr('browser_use.tools.service.create_task_with_error_handling', fake_helper)

	session = _FakeBrowserSession()
	result = await _run_coordinate_click(session)

	# Let the fire-and-forget highlight task run to completion so the call is recorded.
	for task in helper_tasks:
		await task

	# The click itself succeeds and the highlight coroutine is created.
	assert result is not None
	assert result.error is None
	assert session.highlight_coordinate_click_calls == [(100, 200)]

	# The helper (not raw asyncio.create_task) must own the highlight task.
	assert any(name == 'highlight_coordinate_click' and suppress is True for name, suppress in helper_calls)
	raw_names = [c.cr_code.co_name for c in raw_task_coroutines]
	assert 'highlight_coordinate_click' not in raw_names
