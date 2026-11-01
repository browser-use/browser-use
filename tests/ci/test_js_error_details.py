"""Tests for JavaScript error formatting in the evaluate / search_page / find_elements actions.

The payloads below were captured from a real `Runtime.evaluate` CDP response (headless Edge 154),
so the formatter is exercised against the shapes Chromium actually produces:
`text` is only "Uncaught" while the reason lives in `exception.description`.
"""

from types import SimpleNamespace
from typing import Any

from browser_use.tools.service import Tools
from browser_use.tools.utils import format_js_exception

# --- Real CDP payloads ---

SYNTAX_ERROR_PAYLOAD: dict[str, Any] = {
	'exceptionId': 5,
	'text': 'Uncaught',
	'lineNumber': 0,
	'columnNumber': 0,
	'scriptId': '8',
	'exception': {
		'type': 'object',
		'subtype': 'error',
		'className': 'SyntaxError',
		'description': 'SyntaxError: Illegal return statement',
		'objectId': '6542120185813589313.1.8',
	},
}

TYPE_ERROR_PAYLOAD: dict[str, Any] = {
	'exceptionId': 6,
	'text': 'Uncaught',
	'lineNumber': 0,
	'columnNumber': 5,
	'scriptId': '4',
	'exception': {
		'type': 'object',
		'subtype': 'error',
		'className': 'TypeError',
		'description': "TypeError: Cannot read properties of null (reading 'x')\n    at <anonymous>:1:6",
		'objectId': '6542120185813589313.1.10',
	},
}

THROWN_ERROR_PAYLOAD: dict[str, Any] = {
	'exceptionId': 7,
	'text': 'Uncaught',
	'lineNumber': 0,
	'columnNumber': 0,
	'scriptId': '5',
	'exception': {
		'type': 'object',
		'subtype': 'error',
		'className': 'Error',
		'description': 'Error: boom\n    at <anonymous>:1:7',
		'objectId': '6542120185813589313.1.12',
	},
}

# `throw 'plain string'` carries no description and no className.
THROWN_PRIMITIVE_PAYLOAD: dict[str, Any] = {
	'exceptionId': 8,
	'text': 'Uncaught',
	'lineNumber': 0,
	'columnNumber': 0,
	'scriptId': '6',
	'exception': {'type': 'string', 'value': 'plain string'},
}

OK_PAYLOAD: dict[str, Any] = {'result': {'type': 'number', 'value': 2}}


# --- Test doubles ---


class _FakeBrowserSession:
	"""Stand-in for BrowserSession that replays one canned `Runtime.evaluate` response, so no browser is needed."""

	def __init__(self, evaluate_result: dict[str, Any], session_id: str = 'fake-session'):
		self._evaluate_result = evaluate_result
		self._session_id = session_id
		# `Tools.__getattr__` -> Registry.execute_action inspects these before calling the action.
		self.agent_focus_target_id: str | None = None
		self.session_manager = SimpleNamespace(get_target=lambda *args, **kwargs: None)
		self.cdp_client = SimpleNamespace(send=SimpleNamespace(Runtime=SimpleNamespace(evaluate=self._evaluate)))

	async def _evaluate(self, params: dict[str, Any] | None = None, session_id: str | None = None) -> dict[str, Any]:
		del params, session_id
		return self._evaluate_result

	async def get_current_page_url(self) -> str:
		return 'about:blank'

	async def get_or_create_cdp_session(self) -> SimpleNamespace:
		return SimpleNamespace(
			session_id=self._session_id,
			cdp_client=self.cdp_client,
		)


# --- format_js_exception: happy path ---


def test_syntax_error_reports_reason_and_position():
	message = format_js_exception(SYNTAX_ERROR_PAYLOAD)

	assert 'SyntaxError' in message
	assert 'Illegal return statement' in message
	assert 'line 1, col 1' in message
	assert '\n' not in message


def test_runtime_error_keeps_reason_and_drops_stack():
	message = format_js_exception(TYPE_ERROR_PAYLOAD)

	assert message.startswith('TypeError: Cannot read properties of null')
	assert 'line 1, col 6' in message
	# The JS stack trace stays out of the one-liner.
	assert 'at <anonymous>' not in message


def test_thrown_error_object_reports_message():
	message = format_js_exception(THROWN_ERROR_PAYLOAD)

	assert message == 'Error: boom (line 1, col 1)'


def test_thrown_primitive_falls_back_to_value():
	message = format_js_exception(THROWN_PRIMITIVE_PAYLOAD)

	assert 'plain string' in message
	assert 'line 1, col 1' in message


# --- format_js_exception: boundaries ---


def test_generic_text_is_used_when_no_exception_object():
	assert format_js_exception({'text': 'Uncaught'}) == 'Uncaught'
	assert format_js_exception({'text': 'Illegal return statement'}) == 'Illegal return statement'


def test_missing_or_malformed_payload_never_raises():
	for payload in (None, {}, [], 'boom', 42):
		assert format_js_exception(payload) == 'Unknown JavaScript error'  # type: ignore[arg-type]


def test_repeated_uncaught_prefix_is_not_duplicated():
	payload = {
		'text': 'Uncaught',
		'exception': {'className': 'Error', 'description': 'Uncaught: boom'},
	}

	assert format_js_exception(payload) == 'boom'


def test_location_falls_back_to_stack_trace():
	payload = {
		'text': 'Uncaught',
		'exception': {'className': 'Error', 'description': 'Error: nope'},
		'stackTrace': {
			'callFrames': [{'functionName': 'go', 'url': 'https://example.com/a.js', 'lineNumber': 41, 'columnNumber': 2}]
		},
	}

	assert format_js_exception(payload) == 'Error: nope (at https://example.com/a.js:42:3)'


def test_long_description_is_truncated():
	payload = {
		'text': 'Uncaught',
		'lineNumber': 0,
		'columnNumber': 0,
		'exception': {'className': 'Error', 'description': 'Error: ' + 'x' * 5000},
	}

	message = format_js_exception(payload)

	assert len(message) <= 1000
	assert message.endswith('... [truncated]')
	assert message.startswith('Error: xxx')


# --- Wiring: the tool actions use the formatter ---


async def test_evaluate_returns_readable_error():
	tools = Tools()
	session = _FakeBrowserSession({'exceptionDetails': SYNTAX_ERROR_PAYLOAD})
	result = await tools.evaluate(code='return 42;', browser_session=session)

	assert result.error is not None
	# New detail...
	assert 'SyntaxError' in result.error
	assert 'Illegal return statement' in result.error
	assert 'line 1, col 1' in result.error
	# ...without losing the existing wrapper text.
	assert 'JavaScript Execution Failed:' in result.error
	assert 'JavaScript execution error:' in result.error
	assert 'Validated Code (after quote fixing):' in result.error


async def test_evaluate_success_path_unchanged():
	tools = Tools()
	result = await tools.evaluate(code='1 + 1', browser_session=_FakeBrowserSession(OK_PAYLOAD))

	assert result.error is None
	assert result.extracted_content == '2'


async def test_search_page_error_keeps_prefix():
	tools = Tools()
	session = _FakeBrowserSession({'exceptionDetails': SYNTAX_ERROR_PAYLOAD})
	result = await tools.search_page(pattern='Widget', browser_session=session)

	assert result.error is not None
	assert result.error.startswith('search_page failed: ')
	assert 'SyntaxError' in result.error


async def test_find_elements_error_keeps_prefix():
	tools = Tools()
	session = _FakeBrowserSession({'exceptionDetails': TYPE_ERROR_PAYLOAD})
	result = await tools.find_elements(selector='div', browser_session=session)

	assert result.error is not None
	assert result.error.startswith('find_elements failed: ')
	assert 'TypeError' in result.error
