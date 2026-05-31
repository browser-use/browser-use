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
