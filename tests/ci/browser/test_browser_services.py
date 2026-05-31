import asyncio
import inspect
import json
from pathlib import Path

import pytest

from browser_use.browser.services import BrowserServiceBundle, ClickService, DropdownService, TypeService
from browser_use.filesystem.file_system import FileSystem
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


def test_direct_action_services_do_not_define_event_bus_fallbacks() -> None:
	for service in (
		ClickService.click_index,
		ClickService.click_coordinates,
		TypeService.type_index,
		DropdownService.get_options,
		DropdownService.select_option,
	):
		assert 'event_bus.dispatch' not in inspect.getsource(service)


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
async def test_navigation_service_clears_selector_cache_between_pages(browser_session, httpserver) -> None:
	httpserver.expect_request('/cache-one').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<button id="old-action">Old Action</button>
	</body>
</html>""",
		content_type='text/html',
	)
	httpserver.expect_request('/cache-two').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<button id="new-action">New Action</button>
	</body>
</html>""",
		content_type='text/html',
	)
	services = BrowserServiceBundle.from_session(browser_session)

	await services.navigation.navigate(httpserver.url_for('/cache-one'))
	first_state = await services.state.get_state(include_screenshot=False)
	assert any(node.attributes.get('id') == 'old-action' for node in first_state.dom_state.selector_map.values())
	assert browser_session._cached_selector_map

	await services.navigation.navigate(httpserver.url_for('/cache-two'), verify_not_empty=False)

	assert browser_session._cached_selector_map == {}
	second_state = await services.state.get_state(include_screenshot=False)
	assert not any(node.attributes.get('id') == 'old-action' for node in second_state.dom_state.selector_map.values())
	assert any(node.attributes.get('id') == 'new-action' for node in second_state.dom_state.selector_map.values())


@pytest.mark.asyncio
async def test_tab_service_switch_and_close_do_not_require_event_dispatch(browser_session, httpserver, monkeypatch) -> None:
	httpserver.expect_request('/tab-one').respond_with_data(
		"""<!doctype html>
<html>
	<body><p id="page">one</p></body>
</html>""",
		content_type='text/html',
	)
	httpserver.expect_request('/tab-two').respond_with_data(
		"""<!doctype html>
<html>
	<body><p id="page">two</p></body>
</html>""",
		content_type='text/html',
	)
	services = BrowserServiceBundle.from_session(browser_session)

	await services.navigation.navigate(httpserver.url_for('/tab-one'))
	first_target = browser_session.agent_focus_target_id
	assert first_target is not None
	second_target = await browser_session._cdp_create_new_page(httpserver.url_for('/tab-two'))
	await browser_session.get_or_create_cdp_session(target_id=second_target, focus=False)

	def fail_dispatch(*args, **kwargs):
		raise AssertionError('Tab service should not require event dispatch to switch or close tabs')

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_dispatch)

	switched = await services.tabs.switch(second_target)
	assert switched == second_target
	assert browser_session.agent_focus_target_id == second_target

	await services.tabs.close(second_target)
	assert browser_session.agent_focus_target_id == first_target

	state = await services.state.get_state(include_screenshot=False)
	assert state.url.endswith('/tab-one')


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
async def test_public_upload_tool_uses_direct_service(browser_session, httpserver, tmp_path, monkeypatch) -> None:
	upload_path = tmp_path / 'codexify-upload.txt'
	upload_path.write_text('upload-ok', encoding='utf-8')
	httpserver.expect_request('/direct-upload').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<input id="file" type="file" onchange="document.getElementById('answer').textContent = this.files[0].name">
		<p id="answer">hidden</p>
	</body>
</html>""",
		content_type='text/html',
	)
	tools = Tools()
	services = BrowserServiceBundle.from_session(browser_session)
	await services.navigation.navigate(httpserver.url_for('/direct-upload'))
	state = await services.state.get_state(include_screenshot=False)
	file_index = next(
		idx for idx, element in state.dom_state.selector_map.items() if getattr(element, 'attributes', {}).get('id') == 'file'
	)

	original_dispatch = browser_session.event_bus.dispatch

	def fail_upload_dispatch(event, *args, **kwargs):
		if event.__class__.__name__ == 'UploadFileEvent':
			raise AssertionError('Public upload should use direct services, not UploadFileEvent')
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_upload_dispatch)

	upload_result = await tools.registry.execute_action(
		action_name='upload_file',
		params={'index': file_index, 'path': str(upload_path)},
		browser_session=browser_session,
		available_file_paths=[str(upload_path)],
		file_system=FileSystem(tmp_path / 'files', create_default_files=False),
	)
	assert upload_result.error is None

	cdp_session = await browser_session.get_or_create_cdp_session()
	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('answer').textContent", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	assert readback.get('result', {}).get('value') == upload_path.name


@pytest.mark.asyncio
async def test_public_find_text_tool_uses_direct_service(browser_session, httpserver, monkeypatch) -> None:
	httpserver.expect_request('/direct-find-text').respond_with_data(
		"""<!doctype html>
<html>
	<body style="margin:0">
		<div style="height: 2200px">top</div>
		<p id="target">Codexify target text</p>
	</body>
</html>""",
		content_type='text/html',
	)
	tools = Tools()
	services = BrowserServiceBundle.from_session(browser_session)
	await services.navigation.navigate(httpserver.url_for('/direct-find-text'))

	original_dispatch = browser_session.event_bus.dispatch

	def fail_scroll_to_text_dispatch(event, *args, **kwargs):
		if event.__class__.__name__ == 'ScrollToTextEvent':
			raise AssertionError('Public find_text should use direct services, not ScrollToTextEvent')
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_scroll_to_text_dispatch)

	find_result = await tools.registry.execute_action(
		action_name='find_text',
		params={'text': 'Codexify target text'},
		browser_session=browser_session,
	)
	assert find_result.error is None

	cdp_session = await browser_session.get_or_create_cdp_session()
	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': 'window.scrollY', 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	assert readback.get('result', {}).get('value') > 0


@pytest.mark.asyncio
async def test_public_dropdown_tools_use_direct_service(browser_session, httpserver, monkeypatch) -> None:
	httpserver.expect_request('/direct-dropdown').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<select id="choice" onchange="document.getElementById('answer').textContent = this.value">
			<option value="alpha">Alpha</option>
			<option value="beta">Beta</option>
		</select>
		<p id="answer">hidden</p>
	</body>
</html>""",
		content_type='text/html',
	)
	tools = Tools()
	services = BrowserServiceBundle.from_session(browser_session)
	await services.navigation.navigate(httpserver.url_for('/direct-dropdown'))
	state = await services.state.get_state(include_screenshot=False)
	select_index = next(
		idx for idx, element in state.dom_state.selector_map.items() if getattr(element, 'attributes', {}).get('id') == 'choice'
	)

	def fail_dropdown_dispatch(event, *args, **kwargs):
		if event.__class__.__name__ in {'GetDropdownOptionsEvent', 'SelectDropdownOptionEvent'}:
			raise AssertionError('Public dropdown tools should use direct services, not dropdown events')
		return original_dispatch(event, *args, **kwargs)

	original_dispatch = browser_session.event_bus.dispatch
	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_dropdown_dispatch)

	options_result = await tools.registry.execute_action(
		action_name='dropdown_options',
		params={'index': select_index},
		browser_session=browser_session,
	)
	select_result = await tools.registry.execute_action(
		action_name='select_dropdown',
		params={'index': select_index, 'text': 'Beta'},
		browser_session=browser_session,
	)
	assert options_result.error is None
	assert 'Beta' in (options_result.extracted_content or '')
	assert select_result.error is None

	cdp_session = await browser_session.get_or_create_cdp_session()
	readback = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('answer').textContent", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	assert readback.get('result', {}).get('value') == 'beta'


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
async def test_print_button_click_tracks_pdf_without_download_event_dispatch(browser_session, httpserver, monkeypatch) -> None:
	httpserver.expect_request('/print-button').respond_with_data(
		"""<!doctype html>
<html>
	<head><title>Codexify Print Smoke</title></head>
	<body>
		<button id="print" onclick="window.print()">Print</button>
		<p>content for generated pdf</p>
	</body>
</html>""",
		content_type='text/html',
	)
	services = BrowserServiceBundle.from_session(browser_session)

	await services.navigation.navigate(httpserver.url_for('/print-button'))
	state = await services.state.get_state(include_screenshot=False)
	button_index = next(
		idx for idx, element in state.dom_state.selector_map.items() if getattr(element, 'attributes', {}).get('id') == 'print'
	)

	original_dispatch = browser_session.event_bus.dispatch

	def fail_download_dispatch(event, *args, **kwargs):
		if event.__class__.__name__ == 'FileDownloadedEvent':
			raise AssertionError('Print-button PDF tracking should call the direct download handler, not FileDownloadedEvent')
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', fail_download_dispatch)

	result = await services.actions.click.click_index(button_index)

	assert result is not None
	assert result.get('pdf_generated') is True
	path = Path(result['path'])
	assert path.exists()
	assert path.suffix == '.pdf'
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
