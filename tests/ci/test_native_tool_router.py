import json

import pytest

from browser_use.agent.runtime import (
	BrowserAgentSession,
	BrowserRuntimeEventTypes,
	ClickCoordinatesInput,
	NativeToolCall,
	NativeToolRouter,
	click_coordinates_as_click_arguments,
)
from browser_use.tools.service import Tools


def test_native_tool_router_exposes_api_safe_names() -> None:
	router = NativeToolRouter.from_tools(Tools())

	navigate = router.resolve('browser.navigate')
	click = router.resolve('browser_click')

	assert navigate.api_name == 'browser_navigate'
	assert click.name == 'browser.click'
	assert 'browser.get_state' in router.definitions
	assert 'browser.cdp' in router.definitions
	assert 'browser.html' in router.definitions
	assert 'browser.markdown' in router.definitions
	assert 'browser.accessibility' in router.definitions
	assert 'browser.inspect_element' in router.definitions
	assert 'browser.network' in router.definitions
	assert 'browser.http_fetch' in router.definitions
	assert any(tool['function']['name'] == 'browser_navigate' for tool in router.tool_schemas())
	assert 'browser.cdp only when lower-level CDP handles' in router.guidance()


def test_native_tool_router_validates_with_existing_pydantic_models() -> None:
	router = NativeToolRouter.from_tools(Tools())
	call = NativeToolCall(tool_name='browser_navigate', arguments={'url': 'https://example.com', 'new_tab': False})

	params = router.validate_call(call)

	assert params.model_dump() == {'url': 'https://example.com', 'new_tab': False}

	with pytest.raises(ValueError):
		router.validate_call(NativeToolCall(tool_name='browser.navigate', arguments={'new_tab': False}))


def test_native_tool_router_filters_page_specific_actions() -> None:
	tools = Tools()

	@tools.action('Only available on example.com', domains=['example.com'])
	async def example_only() -> str:
		return 'ok'

	assert 'browser.example_only' not in NativeToolRouter.from_tools(tools).definitions
	assert 'browser.example_only' in NativeToolRouter.from_tools(tools, page_url='https://example.com').definitions


@pytest.mark.asyncio
async def test_native_tool_router_executes_existing_action_without_fake_action_model() -> None:
	tools = Tools()
	session = BrowserAgentSession.create(task='Wait briefly')
	turn = session.start_turn(step_index=0)
	context = session.tool_context(turn, tools=tools, action_timeout=5)
	router = NativeToolRouter.from_tools(tools)

	result = await router.execute(NativeToolCall(tool_name='browser.wait', arguments={'seconds': 1}, call_id='call-1'), context)

	assert result.call_id == 'call-1'
	assert result.is_error is False
	assert result.structured_content['extracted_content'] == 'Waited for 1 seconds'
	assert result.to_context_item().render().startswith('<tool_result name="browser.wait" id="call-1">')
	assert [event.event_type for event in session.event_stream.events] == ['turn.started', 'tool.started', 'tool.completed']


@pytest.mark.asyncio
async def test_native_tool_router_can_drive_simple_browser_task(browser_session, httpserver) -> None:
	httpserver.expect_request('/native-tool').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<button id="reveal" onclick="document.getElementById('answer').textContent = 'native-tool-ok'">Reveal</button>
		<p id="answer">hidden</p>
	</body>
</html>""",
		content_type='text/html',
	)

	tools = Tools()
	router = NativeToolRouter.from_tools(tools)
	session = BrowserAgentSession.create(task='Reveal the answer')
	turn = session.start_turn(step_index=0)
	context = session.tool_context(turn, tools=tools, browser_session=browser_session, action_timeout=30)

	navigate_result = await router.execute(
		NativeToolCall(tool_name='browser.navigate', arguments={'url': httpserver.url_for('/native-tool')}), context
	)
	assert navigate_result.is_error is False

	state = await browser_session.get_browser_state_summary(include_screenshot=False)
	button_index = next(
		idx
		for idx, element in state.dom_state.selector_map.items()
		if getattr(element, 'tag_name', None) == 'button' and getattr(element, 'attributes', {}).get('id') == 'reveal'
	)

	click_result = await router.execute(NativeToolCall(tool_name='browser.click', arguments={'index': button_index}), context)
	assert click_result.is_error is False

	cdp_session = await browser_session.get_or_create_cdp_session()
	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('answer').textContent", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	assert readback.get('result', {}).get('value') == 'native-tool-ok'


@pytest.mark.asyncio
async def test_native_tool_router_executes_get_state_and_raw_cdp(browser_session, httpserver) -> None:
	httpserver.expect_request('/native-state').respond_with_data(
		"""<!doctype html>
<html>
	<head><title>Native State</title></head>
	<body>
		<button id="state-button">State Button</button>
	</body>
</html>""",
		content_type='text/html',
	)

	tools = Tools()
	session = BrowserAgentSession.create(task='Inspect state')
	turn = session.start_turn(step_index=0)
	context = session.tool_context(turn, tools=tools, browser_session=browser_session, action_timeout=30)
	router = NativeToolRouter.from_tools(tools)

	navigate_result = await router.execute(
		NativeToolCall(tool_name='browser.navigate', arguments={'url': httpserver.url_for('/native-state')}), context
	)
	assert navigate_result.is_error is False

	state_result = await router.execute(
		NativeToolCall(
			tool_name='browser.get_state',
			arguments={'include_screenshot': False, 'include_dom': True},
			call_id='state-call',
		),
		context,
	)
	assert state_result.is_error is False
	assert state_result.call_id == 'state-call'
	assert state_result.structured_content['url'].endswith('/native-state')
	assert 'State Button' in state_result.structured_content['dom']
	assert len(state_result.structured_content['runtime_handles']['current_target_id']) > 4
	assert len(state_result.structured_content['runtime_handles']['current_session_id']) > 4
	assert len(state_result.structured_content['tabs'][0]['target_id']) > 4

	cdp_result = await router.execute(
		NativeToolCall(
			tool_name='browser.cdp',
			arguments={
				'method': 'Runtime.evaluate',
				'params': {'expression': 'document.title', 'returnByValue': True},
			},
			call_id='cdp-call',
		),
		context,
	)
	assert cdp_result.is_error is False
	assert cdp_result.call_id == 'cdp-call'
	assert cdp_result.structured_content['response']['result']['value'] == 'Native State'
	assert len(cdp_result.structured_content['target_id']) > 4
	assert len(cdp_result.structured_content['session_id']) > 4

	assert BrowserRuntimeEventTypes.BROWSER_STATE_REFRESHED in [event.event_type for event in session.event_stream.events]


@pytest.mark.asyncio
async def test_native_tool_router_executes_coordinate_click(browser_session, httpserver) -> None:
	httpserver.expect_request('/native-coordinate').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<button id="reveal" style="margin: 40px; width: 160px; height: 60px;"
			onclick="document.getElementById('answer').textContent = 'coordinate-ok'">
			Reveal
		</button>
		<p id="answer">hidden</p>
	</body>
</html>""",
		content_type='text/html',
	)

	tools = Tools()
	router = NativeToolRouter.from_tools(tools)
	session = BrowserAgentSession.create(task='Click by coordinates')
	turn = session.start_turn(step_index=0)
	context = session.tool_context(turn, tools=tools, browser_session=browser_session, action_timeout=30)

	navigate_result = await router.execute(
		NativeToolCall(tool_name='browser.navigate', arguments={'url': httpserver.url_for('/native-coordinate')}), context
	)
	assert navigate_result.is_error is False

	rect_result = await router.execute(
		NativeToolCall(
			tool_name='browser.cdp',
			arguments={
				'method': 'Runtime.evaluate',
				'params': {
					'expression': """
const rect = document.getElementById('reveal').getBoundingClientRect();
JSON.stringify({ x: Math.floor(rect.left + rect.width / 2), y: Math.floor(rect.top + rect.height / 2) });
""",
					'returnByValue': True,
				},
			},
		),
		context,
	)
	assert rect_result.is_error is False

	coords = json.loads(rect_result.structured_content['response']['result']['value'])
	click_result = await router.execute(
		NativeToolCall(
			tool_name='browser.click_coordinates',
			arguments={'coordinate_x': coords['x'], 'coordinate_y': coords['y']},
			call_id='coordinate-click',
		),
		context,
	)
	assert click_result.is_error is False
	assert click_result.call_id == 'coordinate-click'

	readback = await router.execute(
		NativeToolCall(
			tool_name='browser.cdp',
			arguments={
				'method': 'Runtime.evaluate',
				'params': {'expression': "document.getElementById('answer').textContent", 'returnByValue': True},
			},
		),
		context,
	)
	assert readback.structured_content['response']['result']['value'] == 'coordinate-ok'


@pytest.mark.asyncio
async def test_native_tool_router_executes_read_and_inspect_escape_hatches(browser_session, httpserver) -> None:
	httpserver.expect_request('/api/page-data').respond_with_json({'page': 'loaded'})
	httpserver.expect_request('/api/tool-data').respond_with_json({'tool': 'fetch-ok'})
	httpserver.expect_request('/native-read').respond_with_data(
		"""<!doctype html>
<html>
	<head><title>Read Tools</title></head>
	<body>
		<main>
			<h1>Read Tools</h1>
			<button id="inspect" aria-label="Inspect Button" data-kind="escape">Inspect Me</button>
		</main>
		<script>fetch('/api/page-data')</script>
	</body>
</html>""",
		content_type='text/html',
	)

	tools = Tools()
	router = NativeToolRouter.from_tools(tools)
	session = BrowserAgentSession.create(task='Read page in multiple ways')
	turn = session.start_turn(step_index=0)
	context = session.tool_context(turn, tools=tools, browser_session=browser_session, action_timeout=30)

	navigate_result = await router.execute(
		NativeToolCall(tool_name='browser.navigate', arguments={'url': httpserver.url_for('/native-read')}), context
	)
	assert navigate_result.is_error is False

	html_result = await router.execute(
		NativeToolCall(tool_name='browser.html', arguments={'selector': '#inspect', 'max_chars': 2000}), context
	)
	assert html_result.is_error is False
	assert 'Inspect Me' in html_result.structured_content['html']

	markdown_result = await router.execute(NativeToolCall(tool_name='browser.markdown', arguments={'max_chars': 2000}), context)
	assert markdown_result.is_error is False
	assert 'Read Tools' in markdown_result.structured_content['markdown']

	accessibility_result = await router.execute(
		NativeToolCall(tool_name='browser.accessibility', arguments={'max_nodes': 50}), context
	)
	assert accessibility_result.is_error is False
	assert accessibility_result.structured_content['returned_nodes'] > 0
	assert len(accessibility_result.structured_content['session_id']) > 4

	state = await browser_session.get_browser_state_summary(include_screenshot=False)
	button_index = next(
		idx for idx, element in state.dom_state.selector_map.items() if getattr(element, 'attributes', {}).get('id') == 'inspect'
	)
	inspect_result = await router.execute(
		NativeToolCall(tool_name='browser.inspect_element', arguments={'index': button_index}), context
	)
	assert inspect_result.is_error is False
	assert inspect_result.structured_content['backend_node_id'] == button_index
	assert inspect_result.structured_content['target_id']
	assert inspect_result.structured_content['html']['text'].startswith('<button')

	network_result = await router.execute(NativeToolCall(tool_name='browser.network', arguments={'max_entries': 20}), context)
	assert network_result.is_error is False
	assert 'pending_requests' in network_result.structured_content
	assert 'performance_entries' in network_result.structured_content

	fetch_result = await router.execute(
		NativeToolCall(tool_name='browser.http_fetch', arguments={'url': httpserver.url_for('/api/tool-data')}), context
	)
	assert fetch_result.is_error is False
	assert fetch_result.structured_content['status'] == 200
	assert 'fetch-ok' in fetch_result.structured_content['body']


@pytest.mark.asyncio
async def test_native_tool_router_returns_structured_error_without_browser_session() -> None:
	tools = Tools()
	session = BrowserAgentSession.create(task='Inspect state')
	turn = session.start_turn(step_index=0)
	context = session.tool_context(turn, tools=tools)
	router = NativeToolRouter.from_tools(tools)

	result = await router.execute(NativeToolCall(tool_name='browser.get_state', arguments={}), context)

	assert result.is_error is True
	assert 'requires ToolContext.browser_session' in (result.content or '')


def test_click_coordinates_translate_to_current_click_shape() -> None:
	arguments = click_coordinates_as_click_arguments(ClickCoordinatesInput(coordinate_x=10, coordinate_y=20))

	assert arguments == {'coordinate_x': 10, 'coordinate_y': 20}
