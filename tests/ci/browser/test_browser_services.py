import json

import pytest

from browser_use.browser.services import BrowserServiceBundle


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
