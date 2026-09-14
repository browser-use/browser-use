import inspect
import json
import subprocess
from unittest.mock import AsyncMock, MagicMock

from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog


def test_clear_text_field_source_does_not_mention_change_event():
	"""Verify _clear_text_field source does not contain 'change' event dispatches."""
	source = inspect.getsource(DefaultActionWatchdog._clear_text_field)
	assert 'Event("change"' not in source
	assert "Event('change'" not in source
	assert 'Event("input"' in source


def test_clear_text_field_does_not_dispatch_premature_change_event():
	"""Invoke _clear_text_field against representative input and contenteditable elements and assert event emissions."""
	import asyncio

	from bubus import EventBus

	mock_cdp = MagicMock()
	mock_cdp.session_id = 'test-session-123'
	captured_params: dict[str, str] = {}

	async def mock_call_function_on(*args, **kwargs):
		params = kwargs.get('params') or (args[0] if args else {})
		captured_params.update(params)
		return {'result': {'value': {'cleared': True}}}

	mock_cdp.cdp_client.send.Runtime.callFunctionOn = AsyncMock(side_effect=mock_call_function_on)

	mock_session = MagicMock()
	watchdog = DefaultActionWatchdog.model_construct(event_bus=EventBus(), browser_session=mock_session)

	asyncio.run(watchdog._clear_text_field('elem-1', mock_cdp))

	js_code = captured_params['functionDeclaration']
	assert 'Event("change"' not in js_code
	assert 'Event("input"' in js_code

	node_runner = f"""
	const fn = {js_code};

	global.window = global;
	global.document = {{
		createRange: () => ({{
			setStart() {{}},
			setEnd() {{}},
		}}),
	}};
	global.window.getSelection = () => ({{
		removeAllRanges() {{}},
		addRange() {{}},
	}});

	const inputEvents = [];
	class MockHTMLInputElement {{
		constructor() {{
			this._val = "initial text";
		}}
		get value() {{
			return this._val;
		}}
		set value(v) {{
			this._val = v;
		}}
		getAttribute(name) {{
			return null;
		}}
		select() {{}}
		dispatchEvent(evt) {{
			inputEvents.push(evt.type);
		}}
	}}
	global.HTMLInputElement = MockHTMLInputElement;
	global.HTMLTextAreaElement = class {{}};
	global.Event = class Event {{
		constructor(type, opts) {{
			this.type = type;
			this.opts = opts;
		}}
	}};

	const inputElem = new MockHTMLInputElement();
	const inputResult = fn.call(inputElem);

	const ceEvents = [];
	const contentEditableElem = {{
		getAttribute(attr) {{
			return attr === 'contenteditable' ? 'true' : null;
		}},
		isContentEditable: true,
		firstChild: null,
		textContent: "initial rich text",
		innerHTML: "<p>initial rich text</p>",
		focus() {{}},
		dispatchEvent(evt) {{
			ceEvents.push(evt.type);
		}},
	}};

	const ceResult = fn.call(contentEditableElem);

	console.log(JSON.stringify({{
		inputEvents,
		inputResult,
		ceEvents,
		ceResult,
	}}));
	"""

	res = subprocess.run(['node', '-e', node_runner], capture_output=True, text=True)
	if res.returncode != 0:
		raise RuntimeError(f'Node script failed: {res.stderr}')
	out = json.loads(res.stdout)

	assert 'input' in out['inputEvents']
	assert 'change' not in out['inputEvents']
	assert out['inputResult']['cleared'] is True

	assert 'input' in out['ceEvents']
	assert 'change' not in out['ceEvents']
	assert out['ceResult']['cleared'] is True
