import asyncio
import json
from pathlib import Path

import pytest

from browser_use.browser.services import BrowserServiceBundle
from browser_use.tools.service import Tools


@pytest.mark.asyncio
async def test_browser_service_bundle_navigates_and_clicks(browser_session, httpserver) -> None:
	httpserver.expect_request('/services').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<button id="reveal" onclick="document.getElementById('answer').textContent = 'services-ok'">Reveal</button>
		<p id="answer">hidden</p>
	</body>
</html>""",
		content_type='text/html',
	)

	services = BrowserServiceBundle.from_session(browser_session)

	await services.navigation.navigate(httpserver.url_for('/services'))
	state = await services.state.get_state(include_screenshot=False)
	button_index = next(
		idx
		for idx, element in state.dom_state.selector_map.items()
		if getattr(element, 'tag_name', None) == 'button' and getattr(element, 'attributes', {}).get('id') == 'reveal'
	)

	await services.actions.click.click_index(button_index)

	cdp_session = await browser_session.get_or_create_cdp_session()
	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('answer').textContent", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	assert readback.get('result', {}).get('value') == 'services-ok'


def test_browser_service_bundle_exposes_lightweight_state(browser_session) -> None:
	services = BrowserServiceBundle.from_session(browser_session)

	assert services.downloads.list_downloads() == browser_session.downloaded_files
	assert services.dialogs.closed_messages() == []
	assert services.actions.navigation is not services.navigation


@pytest.mark.asyncio
async def test_browser_services_can_navigate_and_click_coordinates_without_event_dispatch(
	browser_session, httpserver, monkeypatch
) -> None:
	httpserver.expect_request('/direct-services').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<button id="reveal" style="margin: 40px; width: 160px; height: 60px;"
			onclick="document.getElementById('answer').textContent = 'direct-services-ok'">
			Reveal
		</button>
		<p id="answer">hidden</p>
	</body>
</html>""",
		content_type='text/html',
	)
	services = BrowserServiceBundle.from_session(browser_session)

	await services.navigation.navigate(httpserver.url_for('/direct-services'))
	cdp_session = await browser_session.get_or_create_cdp_session()
	rect_result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': """
const rect = document.getElementById('reveal').getBoundingClientRect();
JSON.stringify({ x: Math.floor(rect.left + rect.width / 2), y: Math.floor(rect.top + rect.height / 2) });
""",
			'returnByValue': True,
		},
		session_id=cdp_session.session_id,
	)

	coords = json.loads(rect_result['result']['value'])

	def fail_dispatch(*args, **kwargs):
		raise AssertionError('Direct click services should not dispatch through the event bus')

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_dispatch)

	await services.actions.click.click_coordinates(coords['x'], coords['y'])
	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('answer').textContent", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)

	assert readback.get('result', {}).get('value') == 'direct-services-ok'


@pytest.mark.asyncio
async def test_browser_services_can_click_and_type_index_without_event_dispatch(browser_session, httpserver, monkeypatch) -> None:
	httpserver.expect_request('/direct-index-services').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<input id="name" value="">
		<button id="reveal" onclick="document.getElementById('answer').textContent =
			document.getElementById('name').value + '-done'">
			Reveal
		</button>
		<p id="answer">hidden</p>
	</body>
</html>""",
		content_type='text/html',
	)
	services = BrowserServiceBundle.from_session(browser_session)

	await services.navigation.navigate(httpserver.url_for('/direct-index-services'))
	state = await services.state.get_state(include_screenshot=False)
	input_index = next(
		idx
		for idx, element in state.dom_state.selector_map.items()
		if getattr(element, 'tag_name', None) == 'input' and getattr(element, 'attributes', {}).get('id') == 'name'
	)
	button_index = next(
		idx
		for idx, element in state.dom_state.selector_map.items()
		if getattr(element, 'tag_name', None) == 'button' and getattr(element, 'attributes', {}).get('id') == 'reveal'
	)

	def fail_dispatch(*args, **kwargs):
		raise AssertionError('Direct services should not dispatch through the event bus')

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_dispatch)

	await services.actions.type.type_index(input_index, 'browser-use')
	await services.actions.click.click_index(button_index)

	cdp_session = await browser_session.get_or_create_cdp_session()
	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('answer').textContent", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)

	assert readback.get('result', {}).get('value') == 'browser-use-done'


@pytest.mark.asyncio
async def test_public_tools_click_and_type_use_direct_services(browser_session, httpserver, monkeypatch) -> None:
	httpserver.expect_request('/direct-tool-actions').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<input id="name" value="">
		<button id="reveal" onclick="document.getElementById('answer').textContent =
			document.getElementById('name').value + '-tools-done'">
			Reveal
		</button>
		<p id="answer">hidden</p>
	</body>
</html>""",
		content_type='text/html',
	)
	services = BrowserServiceBundle.from_session(browser_session)
	tools = Tools()

	await services.navigation.navigate(httpserver.url_for('/direct-tool-actions'))
	state = await services.state.get_state(include_screenshot=False)
	input_index = next(
		idx
		for idx, element in state.dom_state.selector_map.items()
		if getattr(element, 'tag_name', None) == 'input' and getattr(element, 'attributes', {}).get('id') == 'name'
	)
	button_index = next(
		idx
		for idx, element in state.dom_state.selector_map.items()
		if getattr(element, 'tag_name', None) == 'button' and getattr(element, 'attributes', {}).get('id') == 'reveal'
	)

	def fail_dispatch(*args, **kwargs):
		raise AssertionError('Public click/input tools should use direct services, not event bus dispatch')

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_dispatch)

	type_result = await tools.registry.execute_action(
		action_name='input',
		params={'index': input_index, 'text': 'browser-use'},
		browser_session=browser_session,
	)
	click_result = await tools.registry.execute_action(
		action_name='click',
		params={'index': button_index},
		browser_session=browser_session,
	)

	assert type_result.error is None
	assert click_result.error is None

	cdp_session = await browser_session.get_or_create_cdp_session()
	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('answer').textContent", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)

	assert readback.get('result', {}).get('value') == 'browser-use-tools-done'


@pytest.mark.asyncio
async def test_public_navigation_and_keyboard_tools_use_direct_services(browser_session, httpserver, monkeypatch) -> None:
	httpserver.expect_request('/direct-public-one').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<input id="keys" value="">
		<p id="page">one</p>
	</body>
</html>""",
		content_type='text/html',
	)
	httpserver.expect_request('/direct-public-two').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<p id="page">two</p>
	</body>
</html>""",
		content_type='text/html',
	)
	tools = Tools()
	original_dispatch = browser_session.event_bus.dispatch
	forbidden_control_events = {'NavigateToUrlEvent', 'GoBackEvent', 'SendKeysEvent'}

	def fail_action_dispatch(event, *args, **kwargs):
		if event.__class__.__name__ in forbidden_control_events:
			raise AssertionError('Public navigation/keyboard tools should use direct services, not old control-flow events')
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_action_dispatch)

	first_url = httpserver.url_for('/direct-public-one')
	second_url = httpserver.url_for('/direct-public-two')
	first_result = await tools.registry.execute_action(
		action_name='navigate',
		params={'url': first_url},
		browser_session=browser_session,
	)
	second_result = await tools.registry.execute_action(
		action_name='navigate',
		params={'url': second_url},
		browser_session=browser_session,
	)
	back_result = await tools.registry.execute_action(
		action_name='go_back',
		params={},
		browser_session=browser_session,
	)

	assert first_result.error is None
	assert second_result.error is None
	assert back_result.error is None

	cdp_session = await browser_session.get_or_create_cdp_session()
	path_result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': 'location.pathname', 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	assert path_result.get('result', {}).get('value') == '/direct-public-one'

	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('keys').focus()", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	keys_result = await tools.registry.execute_action(
		action_name='send_keys',
		params={'keys': 'abc'},
		browser_session=browser_session,
	)
	assert keys_result.error is None

	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('keys').value", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	assert readback.get('result', {}).get('value') == 'abc'


@pytest.mark.asyncio
async def test_public_page_scroll_tool_uses_direct_service(browser_session, httpserver, monkeypatch) -> None:
	httpserver.expect_request('/direct-public-scroll').respond_with_data(
		"""<!doctype html>
<html>
	<body style="margin:0">
		<div style="height: 2600px; padding-top: 20px">top</div>
		<p id="bottom">bottom</p>
	</body>
</html>""",
		content_type='text/html',
	)
	tools = Tools()
	services = BrowserServiceBundle.from_session(browser_session)
	await services.navigation.navigate(httpserver.url_for('/direct-public-scroll'))

	original_dispatch = browser_session.event_bus.dispatch

	def fail_scroll_dispatch(event, *args, **kwargs):
		if event.__class__.__name__ == 'ScrollEvent':
			raise AssertionError('Public page scroll should use direct services, not ScrollEvent')
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_scroll_dispatch)

	scroll_result = await tools.registry.execute_action(
		action_name='scroll',
		params={'down': True, 'pages': 1.0},
		browser_session=browser_session,
	)
	assert scroll_result.error is None

	cdp_session = await browser_session.get_or_create_cdp_session()
	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': 'window.scrollY', 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	assert readback.get('result', {}).get('value') > 0


@pytest.mark.asyncio
async def test_public_element_scroll_tool_uses_direct_service(browser_session, httpserver, monkeypatch) -> None:
	httpserver.expect_request('/direct-element-scroll').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<div id="scroller" tabindex="0" role="region"
			style="height: 140px; width: 300px; overflow-y: auto; border: 1px solid black">
			<div style="height: 1200px">scrollable content</div>
		</div>
	</body>
</html>""",
		content_type='text/html',
	)
	tools = Tools()
	services = BrowserServiceBundle.from_session(browser_session)
	await services.navigation.navigate(httpserver.url_for('/direct-element-scroll'))
	state = await services.state.get_state(include_screenshot=False)
	scroll_index = next(
		idx for idx, element in state.dom_state.selector_map.items() if getattr(element, 'attributes', {}).get('id') == 'scroller'
	)

	original_dispatch = browser_session.event_bus.dispatch

	def fail_scroll_dispatch(event, *args, **kwargs):
		if event.__class__.__name__ == 'ScrollEvent':
			raise AssertionError('Public element scroll should use direct services, not ScrollEvent')
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_scroll_dispatch)

	scroll_result = await tools.registry.execute_action(
		action_name='scroll',
		params={'down': True, 'pages': 1.0, 'index': scroll_index},
		browser_session=browser_session,
	)
	assert scroll_result.error is None

	cdp_session = await browser_session.get_or_create_cdp_session()
	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('scroller').scrollTop", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	assert readback.get('result', {}).get('value') > 0


@pytest.mark.asyncio
async def test_browser_download_service_downloads_and_tracks_without_event_dispatch(
	browser_session, httpserver, monkeypatch
) -> None:
	httpserver.expect_request('/download-page').respond_with_data(
		'<!doctype html><html><body>download page</body></html>',
		content_type='text/html',
	)
	httpserver.expect_request('/files/report.csv').respond_with_data(
		'name,value\ncodexify,1\n',
		content_type='text/csv',
	)
	services = BrowserServiceBundle.from_session(browser_session)

	await services.navigation.navigate(httpserver.url_for('/download-page'))

	def fail_dispatch(*args, **kwargs):
		raise AssertionError('Direct download services should not dispatch through the event bus')

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_dispatch)

	result = await services.downloads.download_url(
		httpserver.url_for('/files/report.csv'),
		suggested_filename='../../report.csv',
		content_type='text/csv',
	)

	assert result is not None
	path = Path(result['path'])
	downloads_dir = Path(browser_session.browser_profile.downloads_path).expanduser().resolve()
	assert path.name == 'report.csv'
	assert downloads_dir in path.resolve().parents
	assert path.read_text(encoding='utf-8') == 'name,value\ncodexify,1\n'
	assert str(path) in services.downloads.list_downloads()


@pytest.mark.asyncio
async def test_browser_dialog_service_records_auto_closed_dialogs_without_click_dispatch(
	browser_session, httpserver, monkeypatch
) -> None:
	httpserver.expect_request('/dialog-services').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<button id="alert" onclick="alert('dialog-service-ok'); document.getElementById('answer').textContent = 'after-alert'">
			Alert
		</button>
		<p id="answer">hidden</p>
	</body>
</html>""",
		content_type='text/html',
	)
	services = BrowserServiceBundle.from_session(browser_session)
	services.dialogs.clear_closed_messages()

	await services.navigation.navigate(httpserver.url_for('/dialog-services'))
	state = await services.state.get_state(include_screenshot=False)
	button_index = next(
		idx
		for idx, element in state.dom_state.selector_map.items()
		if getattr(element, 'tag_name', None) == 'button' and getattr(element, 'attributes', {}).get('id') == 'alert'
	)

	def fail_dispatch(*args, **kwargs):
		raise AssertionError('Direct click services should not dispatch through the event bus')

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_dispatch)

	await services.actions.click.click_index(button_index)
	await asyncio.sleep(0.1)

	cdp_session = await browser_session.get_or_create_cdp_session()
	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('answer').textContent", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)

	assert readback.get('result', {}).get('value') == 'after-alert'
	assert '[alert] dialog-service-ok' in services.dialogs.closed_messages()
