"""Regression tests for #5361: failed scroll/input/find_text must set ActionResult.error.

The agent loop keys off ActionResult.error:
- multi_act() aborts the remaining action queue when results[-1].error is set
- _post_process() increments consecutive_failures only when error is set

If tools report total failure as success (error=None), the LLM is fed a false
premise and max_failures never trips.
"""

from __future__ import annotations

from typing import Any

from browser_use.browser.views import BrowserError
from browser_use.tools.service import Tools
from browser_use.tools.views import InputTextAction, ScrollAction


class _BoomEvent:
	"""Event whose event_result always raises — models a broken CDP dispatch."""

	def __init__(self, message: str = 'CDP scroll dispatch failed'):
		self._message = message

	def __await__(self):
		async def _complete():
			return self

		return _complete().__await__()

	async def event_result(self, **_kwargs: Any) -> None:
		raise RuntimeError(self._message)


class _SuccessEvent:
	"""Event that resolves cleanly (no error)."""

	def __await__(self):
		async def _complete():
			return self

		return _complete().__await__()

	async def event_result(self, **_kwargs: Any) -> None:
		return None


class _BoomBus:
	def dispatch(self, _ev: Any) -> _BoomEvent:
		return _BoomEvent()


class _ConfigurableBus:
	"""Bus that can return boom or BrowserError / success results per call."""

	def __init__(self, factory):
		self._factory = factory

	def dispatch(self, _ev: Any):
		return self._factory()


class _FakeSession:
	"""Minimal browser_session stub for action-handler unit tests."""

	def __init__(self, event_bus: Any | None = None, element: Any | None = object()):
		self.event_bus = event_bus if event_bus is not None else _BoomBus()
		self._element = element

	async def get_element_by_index(self, _index: int) -> Any | None:
		return self._element

	async def get_or_create_cdp_session(self) -> Any:
		raise RuntimeError('no cdp')


def _action_fn(tools: Tools, name: str):
	return tools.registry.registry.actions[name].function


async def test_scroll_default_pages_reports_error_when_all_scrolls_fail():
	"""pages=1.0 (default) used to claim success after every scroll attempt failed."""
	tools = Tools()
	scroll = _action_fn(tools, 'scroll')
	session = _FakeSession(event_bus=_BoomBus())

	# Avoid slow asyncio.sleep(0.15) between multi-page iterations: pages=1.0 loops once.
	result = await scroll(params=ScrollAction(down=True, pages=1.0), browser_session=session)

	assert result.error is not None, f'expected error, got memory={result.long_term_memory!r}'
	assert 'scroll' in result.error.lower()
	assert result.long_term_memory is None or 'Scrolled' not in (result.long_term_memory or '')


async def test_scroll_multi_page_total_failure_reports_error():
	"""pages=3.0 with zero completed scrolls must set error= (not 'Scrolled 0.0 pages')."""
	tools = Tools()
	scroll = _action_fn(tools, 'scroll')
	result = await scroll(
		params=ScrollAction(down=True, pages=3.0),
		browser_session=_FakeSession(event_bus=_BoomBus()),
	)

	assert result.error is not None
	assert '0.0 pages' not in (result.extracted_content or '')
	assert '0.0 pages' not in (result.long_term_memory or '')


async def test_scroll_fractional_page_failure_reports_error():
	"""pages<1.0 already went through the outer except; keep that contract."""
	tools = Tools()
	scroll = _action_fn(tools, 'scroll')
	result = await scroll(
		params=ScrollAction(down=True, pages=0.5),
		browser_session=_FakeSession(event_bus=_BoomBus()),
	)

	assert result.error is not None
	assert 'scroll' in result.error.lower()


async def test_input_missing_index_reports_error():
	"""Stale element index must set error= so a queued submit click is aborted."""
	tools = Tools()
	input_fn = _action_fn(tools, 'input')
	session = _FakeSession(element=None)

	result = await input_fn(
		params=InputTextAction(index=42, text='hello'),
		browser_session=session,
	)

	assert result.error is not None
	assert '42' in result.error
	assert result.extracted_content is None or result.error


async def test_find_text_cdp_failure_reports_error():
	"""CDP/transport failures during scroll-to-text must set error=."""
	tools = Tools()
	find_text = _action_fn(tools, 'find_text')
	session = _FakeSession(event_bus=_BoomBus())

	result = await find_text(text='needle', browser_session=session)

	assert result.error is not None
	assert 'needle' in result.error
	assert 'not found or not visible' not in (result.extracted_content or '')


async def test_find_text_not_found_is_non_error_negative_result():
	"""Genuine 'text not on page' stays a non-error result for LLM planning."""

	class _NotFoundEvent:
		def __await__(self):
			async def _complete():
				return self

			return _complete().__await__()

		async def event_result(self, **_kwargs: Any) -> None:
			raise BrowserError('Text not found: "needle"', details={'text': 'needle'})

	tools = Tools()
	find_text = _action_fn(tools, 'find_text')
	session = _FakeSession(event_bus=_ConfigurableBus(lambda: _NotFoundEvent()))

	result = await find_text(text='needle', browser_session=session)

	assert result.error is None
	assert result.extracted_content is not None
	assert 'not found' in result.extracted_content.lower()
