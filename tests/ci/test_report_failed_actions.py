"""Regression tests for #5361: scroll/input/scroll_to_text report failed actions as successes.

Three actions in browser_use/tools/service.py returned a non-error ActionResult when the
underlying operation failed. Because the agent loop keys off ActionResult.error:

- Agent.multi_act() keeps executing queued follow-up actions on a page that never changed
- Agent._post_process() never increments consecutive_failures, so max_failures is never hit
- the LLM is told the action succeeded and reasons from a false premise next step

Sites under test:
1. scroll (pages >= 1.0): total scroll failure reports success; the pages == 1.0 branch
   never consults completed_scrolls.
2. input: a stale element index returns extracted_content instead of error, unlike scroll.
3. scroll_to_text (find_text): one except Exception conflates "text not found" (legitimate
   negative) with a real CDP/transport failure and returns non-error for both.
"""

from browser_use.agent.views import ActionResult
from browser_use.browser.views import BrowserError
from browser_use.tools.service import Tools
from browser_use.tools.views import InputTextAction, ScrollAction


class FakeEvent:
	"""Awaitable stand-in for the object returned by event_bus.dispatch."""

	def __init__(self, exc: Exception | None = None):
		self._exc = exc

	def __await__(self):
		return self._go().__await__()

	async def _go(self):
		return None

	async def event_result(self, raise_if_any: bool = True, raise_if_none: bool = False):
		if self._exc is not None:
			raise self._exc
		return None


def _make_session(dispatch_exc: Exception | None = None, element_lookup=None, fail_after: int | None = None):
	"""Fake BrowserSession.

	dispatch_exc: exception every event dispatch raises (None = always succeed).
	fail_after: only the first N dispatches succeed, then dispatch_exc raises.
	element_lookup: value get_element_by_index returns.
	"""

	class EventBus:
		def __init__(self):
			self.calls = 0

		def dispatch(self, event):
			self.calls += 1
			if dispatch_exc is not None and (fail_after is None or self.calls > fail_after):
				return FakeEvent(dispatch_exc)
			return FakeEvent(None)

	class FakeSession:
		event_bus = EventBus()

		async def get_or_create_cdp_session(self):
			raise RuntimeError('no cdp session available')

		async def get_element_by_index(self, index):
			return element_lookup

	return FakeSession()


def _run(name: str, **kwargs):
	fn = Tools().registry.registry.actions[name].function
	return __import__('asyncio').run(fn(**kwargs))


class TestScrollReportsFailure:
	def test_default_single_page_scroll_total_failure_is_error(self):
		"""pages=1.0 (the default) with every scroll failing must be an error, not 'Scrolled down 1000px'."""
		session = _make_session(dispatch_exc=RuntimeError('CDP scroll dispatch failed'))

		result: ActionResult = _run('scroll', params=ScrollAction(), browser_session=session)

		assert result.error is not None, f'total scroll failure reported as success: {result.extracted_content!r}'

	def test_multi_page_scroll_total_failure_is_error(self):
		"""pages=3.0 with 0/3 scrolls completing must be an error, not 'Scrolled down 0.0 pages'."""
		session = _make_session(dispatch_exc=RuntimeError('CDP scroll dispatch failed'))

		result: ActionResult = _run('scroll', params=ScrollAction(pages=3.0), browser_session=session)

		assert result.error is not None, f'total multi-page scroll failure reported as success: {result.extracted_content!r}'

	def test_partial_scroll_still_reports_success_with_honest_count(self):
		"""Best-effort partial scrolls stay successes, but the memory reflects what actually completed."""
		session = _make_session(dispatch_exc=RuntimeError('CDP scroll dispatch failed'), fail_after=1)

		result: ActionResult = _run('scroll', params=ScrollAction(pages=3.0), browser_session=session)

		assert result.error is None
		assert result.long_term_memory == 'Scrolled down 1.0 pages'


class TestInputReportsFailure:
	def test_stale_element_index_is_error(self):
		"""input on a vanished element index must be an error so queued follow-ups abort."""
		session = _make_session(element_lookup=None)

		result: ActionResult = _run('input', params=InputTextAction(index=5, text='hello'), browser_session=session)

		assert result.error is not None, f'input into a stale index reported as success: {result.extracted_content!r}'


class TestScrollToTextReportsFailure:
	def test_cdp_failure_is_error(self):
		"""A real CDP/transport failure must be an error, not 'text not found'."""
		session = _make_session(dispatch_exc=RuntimeError('websocket connection closed'))

		result: ActionResult = _run('find_text', text='needle', browser_session=session)

		assert result.error is not None, f'CDP failure reported as text-not-found: {result.extracted_content!r}'
		assert 'not found' not in (result.error or '').lower()

	def test_text_not_found_remains_legitimate_negative(self):
		"""BrowserError (text genuinely absent) stays a non-error negative result."""
		session = _make_session(dispatch_exc=BrowserError('Text not found: needle', details={'text': 'needle'}))

		result: ActionResult = _run('find_text', text='needle', browser_session=session)

		assert result.error is None
		assert result.extracted_content is not None
		assert 'not found' in result.extracted_content
