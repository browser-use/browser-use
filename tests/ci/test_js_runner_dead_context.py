"""A dead js lane must be loud, not empty (#5803).

`Page.evaluate` read the reply as `result.get('result', {}).get('value')` and
returned `''` when that was `None`. Two different things land there:

- an expression that genuinely returned nothing, where CDP answers with the
  RemoteObject `{"type": "undefined"}` and no `value` key;
- an evaluation that never ran, because the execution context it was addressed
  to is gone -- a detach, or a top-level navigation that replaced the context
  while the session id stayed valid -- where there is no RemoteObject at all.

The second answered `''` with no exception and no log, for the whole life of
the session, while `page_info()` and raw `cdp()` calls in the same session kept
working. An agent could not tell "the runner is dead" from "the page is
blocking me", and a report of a successful mutation could be fabricated from a
click that never happened.

These cells drive the two replies directly rather than through a browser: the
distinction under test is how one CDP reply is read, and a real detached
context is not reproducible on demand.
"""

import pytest

from browser_use.actor.element import Element
from browser_use.actor.page import Page
from browser_use.browser.views import BrowserError

ARROW = '() => 1 + 1'


class _FakeRuntime:
	def __init__(self, reply):
		self._reply = reply
		self.calls = []

	async def evaluate(self, params, session_id=None):
		self.calls.append((params, session_id))
		return self._reply

	async def callFunctionOn(self, params, session_id=None):
		self.calls.append((params, session_id))
		return self._reply


class _FakeSend:
	def __init__(self, reply):
		self.Runtime = _FakeRuntime(reply)


class _FakeClient:
	def __init__(self, reply):
		self.send = _FakeSend(reply)


def _page(reply) -> Page:
	page = Page.__new__(Page)
	page._client = _FakeClient(reply)
	page._ensure_session = _returns('session-abc')
	return page


def _element(reply) -> Element:
	element = Element.__new__(Element)
	element._client = _FakeClient(reply)
	element._session_id = 'session-abc'
	# The element's own resolution is not what is under test here; stub it so the
	# cell measures how the callFunctionOn reply is read.
	element._get_remote_object_id = _returns('object-1')
	return element


def _returns(value):
	async def _call(*args, **kwargs):
		return value

	return _call


# A RemoteObject is what CDP answers with on success; `undefined` is a real one.
UNDEFINED_REPLY = {'result': {'type': 'undefined'}}
NUMBER_REPLY = {'result': {'type': 'number', 'value': 2}}
STRING_REPLY = {'result': {'type': 'string', 'value': 'pong'}}
# What a dead context answers with: no RemoteObject at all.
NO_RESULT_REPLY: dict = {}
EMPTY_RESULT_REPLY = {'result': {}}


@pytest.mark.parametrize('reply', [NO_RESULT_REPLY, EMPTY_RESULT_REPLY], ids=['no result key', 'result without type'])
async def test_a_dead_execution_context_raises_instead_of_returning_empty(reply):
	with pytest.raises(BrowserError) as excinfo:
		await _page(reply).evaluate(ARROW)

	message = str(excinfo.value)
	assert 'never ran' in message
	# The session id is in the message because the report asks for the lane to be
	# identifiable from the traceback, not only from a reproduction.
	assert 'session-abc' in message


async def test_an_expression_that_really_returns_undefined_is_still_empty():
	"""The accept control, and the whole difficulty of the bug: `undefined` is a
	legitimate answer and must stay an empty string, or every void call starts
	raising."""
	assert await _page(UNDEFINED_REPLY).evaluate(ARROW) == ''


@pytest.mark.parametrize(('reply', 'expected'), [(NUMBER_REPLY, '2'), (STRING_REPLY, 'pong')], ids=['number', 'string'])
async def test_a_real_value_is_unchanged(reply, expected):
	assert await _page(reply).evaluate(ARROW) == expected


@pytest.mark.parametrize('reply', [NO_RESULT_REPLY, EMPTY_RESULT_REPLY], ids=['no result key', 'result without type'])
async def test_the_element_lane_is_guarded_too(reply):
	"""`Element.evaluate` reads `callFunctionOn` the same way, so a fix to only
	one of them leaves half the js surface silently dead."""
	with pytest.raises(BrowserError) as excinfo:
		await _element(reply).evaluate(ARROW)

	assert 'never ran' in str(excinfo.value)


async def test_the_element_lane_still_allows_a_real_undefined():
	assert await _element(UNDEFINED_REPLY).evaluate(ARROW) == ''


async def test_a_thrown_exception_still_reports_as_one():
	"""The pre-existing error path is untouched: a page that throws must keep
	saying so, rather than being re-reported as a dead context."""
	reply = {'exceptionDetails': {'text': 'ReferenceError: nope is not defined'}}

	with pytest.raises(RuntimeError) as excinfo:
		await _page(reply).evaluate(ARROW)

	assert 'evaluation failed' in str(excinfo.value)
	assert 'never ran' not in str(excinfo.value)
