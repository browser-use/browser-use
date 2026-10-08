"""The DOM the agent sees must show the value a form field currently holds.

Regression test for #5647: values set by JavaScript, autofill, or a framework
live in the element's `value` property, not in the `value` attribute, so the
agent used to see pre-filled fields as empty.
"""

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser.events import NavigateToUrlEvent

PAGE = """<!DOCTYPE html>
<html><head><title>Prefilled form</title></head>
<body>
	<label for="name">Name</label>
	<input id="name" type="text" placeholder="Your name">
	<label for="notes">Notes</label>
	<textarea id="notes"></textarea>
	<input id="secret" type="password">
	<input id="otp" type="text" autocomplete="section-login one-time-code">
	<input id="card" type="text" autocomplete="section-checkout billing cc-number">
	<input id="address" type="text" autocomplete="section-checkout shipping street-address">
	<input id="agree" type="checkbox" checked>
	<input id="news" type="checkbox">
	<script>
		document.getElementById('name').value = 'Ada Lovelace';
		document.getElementById('notes').value = 'call back tuesday';
		document.getElementById('secret').value = 'hunter2';
		document.getElementById('otp').value = '493021';
		document.getElementById('card').value = '4242424242424242';
		document.getElementById('address').value = '12 Analytical Engine Way';
		document.getElementById('agree').checked = false;
		document.getElementById('news').checked = true;
	</script>
</body></html>"""


@pytest.fixture(scope='module')
def http_server():
	server = HTTPServer()
	server.start()
	server.expect_request('/prefilled').respond_with_data(PAGE, content_type='text/html')
	yield server
	server.stop()


async def test_live_input_values_reach_the_agent(browser_session, http_server):
	event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=http_server.url_for('/prefilled')))
	await event
	await event.event_result(raise_if_any=True, raise_if_none=False)

	state = await browser_session.get_browser_state_summary()
	by_id = {node.attributes.get('id'): node for node in state.dom_state.selector_map.values() if node.attributes}

	assert by_id['name'].attributes.get('value') == 'Ada Lovelace'
	assert by_id['notes'].attributes.get('value') == 'call back tuesday'
	assert by_id['secret'].attributes.get('value') is None, 'password values must not be exposed'
	assert by_id['otp'].attributes.get('value') is None, 'one-time codes must not be exposed'
	assert by_id['card'].attributes.get('value') is None, 'card numbers must not be exposed'
	assert by_id['address'].attributes.get('value') == '12 Analytical Engine Way'
	assert by_id['secret'].snapshot_node is not None and by_id['secret'].snapshot_node.input_value is None
	assert by_id['otp'].snapshot_node is not None and by_id['otp'].snapshot_node.input_value is None
	assert by_id['card'].snapshot_node is not None and by_id['card'].snapshot_node.input_value is None
	assert by_id['address'].snapshot_node is not None
	assert by_id['address'].snapshot_node.input_value == '12 Analytical Engine Way'
	assert by_id['agree'].attributes.get('checked') is None, 'live unchecked state wins over the checked attribute'
	assert by_id['news'].attributes.get('checked') == 'true'

	llm_view = state.dom_state.llm_representation()
	assert 'Ada Lovelace' in llm_view
	assert 'call back tuesday' in llm_view
	assert '12 Analytical Engine Way' in llm_view
	assert 'hunter2' not in llm_view
	assert '493021' not in llm_view
	assert '4242424242424242' not in llm_view
