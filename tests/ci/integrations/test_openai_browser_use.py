from __future__ import annotations

import base64
import json
import re
import sys
import venv
from collections.abc import Awaitable, Callable
from io import BytesIO
from typing import cast

import pytest
from openai.lib.browser import AsyncBrowserToolset, BrowserError
from openai.types.responses import ResponseFunctionToolCall
from PIL import Image

from browser_use import BrowserSession
from browser_use.integrations.openai import BrowserUse


@pytest.fixture
async def driver():
	browser = BrowserSession(headless=True, enable_default_extensions=False, user_data_dir=None)
	await browser.start()
	try:
		async with BrowserUse(browser) as value:
			yield value
		assert browser.is_cdp_connected
	finally:
		await browser.kill()


async def fixture_page(driver, html):
	await driver.new_tab({'url': 'about:blank'})
	page = await driver._page(None)
	await page.evaluate('(html) => { document.body.innerHTML = html; }', html)
	return page


def reference(text, label):
	for line in text.splitlines():
		match = re.search(r'\[(ref_\d+)\]', line)
		if label in line and match:
			return match.group(1)
	raise AssertionError(f'Missing reference for {label!r}: {text}')


@pytest.mark.asyncio
async def test_driver_reads_and_changes_real_form(driver):
	page = await fixture_page(
		driver,
		'<label>Name<input id="name"></label><label>Ready<input type="checkbox" id="ready"></label><button onclick="document.querySelector(\'#result\').textContent=document.querySelector(\'#name\').value">Save</button><p id="result"></p>',
	)
	text = await driver.read_page({'tab_id': None, 'filter': 'interactive'})
	assert 'checked="false"' in next(line for line in text.splitlines() if 'Ready' in line)
	await driver.type({'tab_id': None, 'target': reference(text, 'Name'), 'text': 'OpenAI driver'})
	await driver.set_checked({'tab_id': None, 'target': reference(text, 'Ready'), 'checked': True})
	await driver.set_checked({'tab_id': None, 'target': reference(text, 'Ready'), 'checked': True})
	await driver.click({'tab_id': None, 'target': reference(text, 'Save')})
	assert await page.evaluate("() => document.querySelector('#result').textContent") == 'OpenAI driver'
	assert await page.evaluate("() => document.querySelector('#ready').checked") == 'True'
	updated = await driver.read_page({'tab_id': None, 'filter': 'interactive'})
	assert 'checked="true"' in next(line for line in updated.splitlines() if 'Ready' in line)
	image = await driver.zoom({'tab_id': None, 'region': [0, 0, 100, 80]})
	with Image.open(BytesIO(base64.b64decode(image['image_url'].split(',', 1)[1]))) as crop:
		assert crop.size == (100, 80)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['navigate', 'page_navigation', 'detach', 'new_tab'])
async def test_driver_rejects_stale_or_cross_tab_reference(driver, change):
	page = await fixture_page(driver, '<button id="button">Original</button>')
	text = await driver.read_page({'tab_id': None, 'filter': 'interactive'})
	target = reference(text, 'Original')
	if change == 'navigate':
		await driver.navigate({'tab_id': None, 'url': 'about:blank'})
	elif change == 'page_navigation':
		await page.goto('about:blank?next')
	elif change == 'detach':
		await page.evaluate("() => document.querySelector('#button').remove()")
	elif change == 'new_tab':
		await driver.new_tab({'url': 'about:blank'})
	with pytest.raises(BrowserError):
		await driver.click({'tab_id': None, 'target': target})


@pytest.mark.asyncio
async def test_reads_preserve_current_references_and_report_page_identity(driver):
	page = await fixture_page(
		driver, '<button onclick="document.title=&quot;Clicked&quot;">Original</button><button>Other</button>'
	)
	await page.evaluate("() => { document.title = 'Fixture'; location.hash = 'full-path'; }")
	first = await driver.read_page({'tab_id': None, 'filter': 'interactive'})
	target = reference(first, 'Original')
	assert 'Fixture' in first
	assert 'about:blank#full-path' in first
	await driver.find({'tab_id': None, 'query': 'Other'})
	second = await driver.read_page({'tab_id': None, 'filter': 'interactive'})
	assert reference(second, 'Original') == target
	await driver.click({'tab_id': None, 'target': target})
	assert await page.evaluate('() => document.title') == 'Clicked'


@pytest.mark.asyncio
async def test_toolset_denies_click_without_changing_page(driver):
	page = await fixture_page(driver, '<button onclick="this.textContent=\'Changed\'">Original</button>')
	text = await driver.read_page({'tab_id': None, 'filter': 'interactive'})

	async def deny(context):
		return False

	tools = AsyncBrowserToolset(driver, members=['click'], confirm=deny)
	try:
		output = await tools.execute(
			ResponseFunctionToolCall(
				id='fc_1',
				call_id='call_1',
				type='function_call',
				status='completed',
				name='browser_click',
				arguments=json.dumps({'target': reference(text, 'Original'), 'tab_id': None}),
			)
		)
		assert 'Original' in await page.evaluate('() => document.body.innerText')
		assert 'Changed' not in await page.evaluate('() => document.body.innerText')
		assert output.get('call_id') == 'call_1'
	finally:
		tools.close()


@pytest.mark.asyncio
async def test_tab_selection_and_close_follow_actual_targets(driver):
	await driver.new_tab({'url': 'about:blank'})
	first = next(t['id'] for t in (await driver.state())['tabs'] if t['active'])
	await driver.new_tab({'url': 'about:blank'})
	second = next(t['id'] for t in (await driver.state())['tabs'] if t['active'])
	assert first != second
	await driver.switch_tab({'tab_id': first})
	assert next(t['id'] for t in (await driver.state())['tabs'] if t['active']) == first
	await driver.close_tab({'tab_id': first})
	assert first not in {t['id'] for t in (await driver.state())['tabs']}
	with pytest.raises(BrowserError):
		await driver.get_page_text({'tab_id': first})


@pytest.mark.asyncio
async def test_driver_wait_and_pointer_bounds(driver):
	await fixture_page(driver, '<p>Present</p>')
	await driver.wait_for({'tab_id': None, 'text': 'Present', 'timeout_ms': 100})
	with pytest.raises(BrowserError):
		await driver.wait_for({'tab_id': None, 'text': 'Missing', 'timeout_ms': 10})
	with pytest.raises(BrowserError):
		await driver.click_at({'tab_id': None, 'x': 999999, 'y': 0, 'button': 'left', 'click_count': 1, 'keys': []})
	with pytest.raises(BrowserError):
		await driver.zoom({'tab_id': None, 'region': [0, 0, 999999, 100]})


@pytest.mark.asyncio
async def test_sdk_dispatch_changes_form_and_selects_option(driver):
	page = await fixture_page(
		driver,
		"""<label>Name<input id="name"></label><label>Choice<select id="choice"><option value="a">Alpha</option><option value="b">Beta</option></select></label><button onclick="document.title=document.querySelector('#name').value">Save</button>""",
	)

	async def approve(context):
		return True

	tools = AsyncBrowserToolset(driver, members=['type', 'select_option', 'click'], confirm=approve)
	try:
		text = await driver.read_page({'tab_id': None, 'filter': 'interactive'})
		for member, arguments in [
			('type', {'target': reference(text, 'Name'), 'text': 'SDK result'}),
			('select_option', {'target': reference(text, 'Choice'), 'values': ['b']}),
			('click', {'target': reference(text, 'Save')}),
		]:
			await tools.execute(
				ResponseFunctionToolCall(
					id='fc_' + member,
					call_id='call_' + member,
					type='function_call',
					status='completed',
					name='browser_' + member,
					arguments=json.dumps({'tab_id': None, **arguments}),
				)
			)
		assert await page.evaluate('() => document.title') == 'SDK result'
		assert await page.evaluate("() => document.querySelector('#choice').value") == 'b'
		updated = await driver.read_page({'tab_id': None, 'filter': 'all'})
		assert 'selected=true' in next(line for line in updated.splitlines() if 'option "Beta"' in line)
	finally:
		tools.close()


@pytest.mark.asyncio
async def test_sdk_accepts_uncommitted_tab_without_url(driver, monkeypatch):
	read_targets = driver.browser.cdp_client.send.Target.getTargets

	async def uncommitted_targets(*args, **kwargs):
		result = await read_targets(*args, **kwargs)
		for target in result['targetInfos']:
			if target['type'] == 'page':
				target['url'] = ''
		return result

	monkeypatch.setattr(driver.browser.cdp_client.send.Target, 'getTargets', uncommitted_targets)
	tools = AsyncBrowserToolset(driver, members=['list_tabs'])
	try:
		output = await tools.execute(
			ResponseFunctionToolCall(
				id='fc_tabs',
				call_id='call_tabs',
				type='function_call',
				status='completed',
				name='browser_list_tabs',
				arguments='{}',
			)
		)
		assert isinstance(output['output'], list)
		assert output['output'][0]['type'] == 'input_text'
		assert isinstance(output['output'], list)
		assert output['output'][0]['type'] == 'input_text'
		result = json.loads(output['output'][0]['text'])
		assert result['ok'] is True
		assert result['state']['tabs']
		assert all(tab['url'] == 'about:blank' for tab in result['state']['tabs'])
	finally:
		tools.close()


@pytest.mark.asyncio
async def test_screenshot_and_pointer_share_css_pixels_at_double_scale(driver):
	page = await fixture_page(
		driver,
		"""<button style="position:fixed;left:100px;top:100px;width:100px;height:50px;background:blue" onclick="document.title='Clicked'">Target</button>""",
	)
	await driver.browser.cdp_client.send.Emulation.setDeviceMetricsOverride(
		{'width': 400, 'height': 300, 'deviceScaleFactor': 2, 'mobile': False},
		session_id=await page.session_id,
	)
	screenshot = await driver.screenshot({'tab_id': None})
	with Image.open(BytesIO(base64.b64decode(screenshot['image_url'].split(',', 1)[1]))) as image:
		assert image.size == (400, 300)
		assert image.convert('RGB').getpixel((110, 110)) == (0, 0, 255)
	await driver.click_at({'tab_id': None, 'x': 150, 'y': 125, 'button': 'left', 'click_count': 1, 'keys': []})
	assert await page.evaluate('() => document.title') == 'Clicked'


@pytest.mark.asyncio
@pytest.mark.parametrize('custom_python', [False, True])
async def test_openai_bash_creates_deliverable_without_inherited_secrets(tmp_path, monkeypatch, custom_python):
	from browser_use.integrations.openai import Bash
	from browser_use.integrations.openai.bash import BashInput

	monkeypatch.setenv('OPENAI_API_KEY', 'private-test-value')
	python = None
	expected_prefix = sys.prefix
	if custom_python:
		environment = tmp_path / 'python-env'
		venv.EnvBuilder().create(environment)
		python = environment / 'bin' / 'python'
		expected_prefix = str(environment)
	tool = Bash(output_dir=tmp_path, python_executable=python)
	execute = cast(Callable[[BashInput], Awaitable[str]], tool.execute)
	result = json.loads(await execute(BashInput(command='printf result > report.txt; printenv OPENAI_API_KEY || true')))
	assert result['exit_code'] == 0
	assert result['output'] == ''
	assert (tmp_path / 'report.txt').read_text() == 'result'
	result = json.loads(await execute(BashInput(command="python -c 'import sys; print(sys.prefix)'")))
	assert result['exit_code'] == 0, result
	assert result['output'].strip() == expected_prefix
	result = json.loads(await execute(BashInput(command='printenv HOME')))
	assert result['output'].strip() == str(tmp_path / '.tmp' / 'home')


async def dispatch(driver, member, arguments):
	async def approve(context):
		return True

	tools = AsyncBrowserToolset(driver, members=[member], confirm=approve)
	try:
		output = await tools.execute(
			ResponseFunctionToolCall(
				id='fc_' + member,
				call_id='call_' + member,
				type='function_call',
				name='browser_' + member,
				arguments=json.dumps(arguments),
			)
		)
		assert isinstance(output['output'], list)
		assert output['output'][0]['type'] == 'input_text'
		result = json.loads(output['output'][0]['text'])
		assert result['ok'], result
		return result['result']
	finally:
		tools.close()


@pytest.mark.parametrize(('label', 'scope_label'), [('', 'main'), ('猫' * 100, 'main'), ('Save', '猫' * 100)])
async def test_scoped_reads_accept_unnamed_and_multibyte_controls(driver, label, scope_label):
	await fixture_page(driver, '<main aria-label="' + scope_label + '"><button>' + label + '</button></main>')
	args = {'tab_id': None, 'root': None, 'depth': 8, 'filter': 'all'}
	discovered = await dispatch(driver, 'read_page_scoped', args)
	assert all(0 < len(scope['label'].encode()) <= 256 for scope in discovered['scopes'])
	args['root'] = next(scope['ref'] for scope in discovered['scopes'] if scope['label'].startswith(scope_label[:1]))
	read = await dispatch(driver, 'read_page_scoped', args)
	assert len(read['elements']) == 1
	element = read['elements'][0]
	assert 0 < len(element['label'].encode()) <= 256
	assert element['label'] == (label or 'Unnamed button').encode()[:256].decode('utf-8', errors='ignore')
	await driver.click({'tab_id': None, 'target': element['ref']})


async def test_scoped_read_bounds_text_and_elements_together(driver):
	await fixture_page(driver, '<main>' + ('<button>' + 'large label ' * 30 + '</button>') * 100 + '</main>')
	args = {'tab_id': None, 'root': None, 'depth': 8, 'filter': 'all'}
	discovered = await dispatch(driver, 'read_page_scoped', args)
	args['root'] = next(scope['ref'] for scope in discovered['scopes'] if scope['label'] == 'main')
	read = await dispatch(driver, 'read_page_scoped', args)
	assert len(json.dumps(read)) <= 10000
	assert read['omitted'] == ['report_limit']
	assert read['elements']


@pytest.mark.asyncio
async def test_scoped_read_limits_region_and_rejects_stale_scope(driver):
	await fixture_page(driver, '<main><button>Inside</button></main><nav><button>Outside</button></nav>')
	discovered = await dispatch(driver, 'read_page_scoped', {'tab_id': None, 'root': None, 'depth': 8, 'filter': 'all'})
	root = next(scope['ref'] for scope in discovered['scopes'] if scope['label'] == 'main')
	read = await dispatch(driver, 'read_page_scoped', {'tab_id': None, 'root': root, 'depth': 8, 'filter': 'all'})
	assert 'Inside' in read['text']
	assert 'Outside' not in read['text']
	await driver.click({'tab_id': None, 'target': read['elements'][0]['ref']})
	with pytest.raises(BrowserError):
		await driver.click({'tab_id': None, 'target': root})
	await driver.navigate({'tab_id': None, 'url': 'about:blank'})
	with pytest.raises(BrowserError):
		await driver.read_page_scoped({'tab_id': None, 'root': root, 'depth': 8, 'filter': 'all'})


@pytest.mark.asyncio
async def test_diagnostics_reads_console_and_bounds_output(driver):
	page = await fixture_page(driver, '<p>Diagnostics</p>')
	await page.evaluate("() => {console.log('first'); console.warn('second');}")
	await driver._diagnostic_client.send.Runtime.evaluate(
		{'expression': '0'}, session_id=driver._diagnostic_sessions[page._target_id]
	)
	read = await dispatch(driver, 'read_diagnostics', {'tab_id': None, 'source': 'console', 'limit': 1})
	assert 'second' in read['text']
	assert 'first' not in read['text']
	assert 'report_limit' in read['omitted']


@pytest.mark.asyncio
async def test_file_grants_transfer_real_bytes_and_reject_reuse(driver, tmp_path):
	page = await fixture_page(driver, '<label>Upload<input type="file" id="file"></label>')
	source = tmp_path / 'source.txt'
	source.write_bytes(b'approved bytes\x00')
	text = await driver.read_page({'tab_id': None, 'filter': 'interactive'})
	grant = await driver.grant_upload(source, target=reference(text, 'Upload'))
	source.write_text('changed after approval')
	await dispatch(driver, 'upload_file', {'grant_id': grant})
	assert await page.evaluate("() => document.querySelector('#file').files[0].text()") == 'approved bytes\x00'
	with pytest.raises(BrowserError):
		await driver.upload_file({'grant_id': grant})
	url = await page.evaluate("() => URL.createObjectURL(new Blob(['download bytes']))")
	destination = tmp_path / 'download.txt'
	grant = await driver.grant_download(url, destination)
	await dispatch(driver, 'download_file', {'grant_id': grant})
	assert destination.read_bytes() == b'download bytes'
	with pytest.raises(BrowserError):
		await driver.download_file({'grant_id': grant})


@pytest.mark.asyncio
async def test_file_grant_rejects_navigation_and_existing_destination(driver, tmp_path):
	page = await fixture_page(driver, '<p>Download</p>')
	url = await page.evaluate("() => URL.createObjectURL(new Blob(['bytes']))")
	destination = tmp_path / 'download.txt'
	grant = await driver.grant_download(url, destination)
	await driver.navigate({'tab_id': None, 'url': 'about:blank'})
	with pytest.raises(BrowserError):
		await driver.download_file({'grant_id': grant})
	assert not destination.exists()
	destination.write_text('keep')
	with pytest.raises(BrowserError):
		await driver.grant_download(url, destination)
	assert destination.read_text() == 'keep'


@pytest.mark.asyncio
async def test_network_diagnostics_strip_query_and_capture_status(driver, httpserver):
	httpserver.expect_request('/diagnostic', query_string='secret=hidden').respond_with_data('ok')
	await fixture_page(driver, '<p>Before</p>')
	await driver.navigate({'tab_id': None, 'url': httpserver.url_for('/diagnostic?secret=hidden')})
	read = await dispatch(driver, 'read_diagnostics', {'tab_id': None, 'source': 'network', 'limit': 100})
	assert '200' in read['text']
	assert '/diagnostic' in read['text']
	assert 'secret' not in read['text']
	assert 'hidden' not in read['text']


async def test_page_read_preserves_structure_and_control_state(driver):
	await fixture_page(
		driver,
		'<main><h1>Account</h1><section aria-label="Preferences"><label>Name<input value="Alice"></label><button disabled>Save</button><button aria-expanded="false">Details</button></section></main>',
	)
	text = await driver.read_page({'tab_id': None, 'filter': 'all'})
	lines = text.splitlines()
	main = next(line for line in lines if 'main ' in line)
	heading = next(line for line in lines if 'heading "Account"' in line)
	assert len(heading) - len(heading.lstrip()) > len(main) - len(main.lstrip())
	assert 'value="Alice"' in next(line for line in lines if 'textbox' in line)
	assert 'disabled=true' in next(line for line in lines if 'Save' in line)
	assert 'expanded=false' in next(line for line in lines if 'Details' in line)


async def test_page_read_bounds_large_observations(driver):
	await fixture_page(
		driver,
		'<main><p>'
		+ 'large content ' * 5000
		+ '</p>'
		+ ('<button>' + 'filler ' * 100 + '</button>') * 100
		+ '<button>Last</button></main>',
	)
	text = await driver.read_page({'tab_id': None, 'filter': 'all'})
	assert len(text) <= 10000
	assert 'truncated' in text.lower()
	plain = await driver.get_page_text({'tab_id': None})
	assert len(plain) <= 10000
	assert 'truncated' in plain.lower()
	script = await driver.run_script({'tab_id': None, 'source': 'document.body.innerText', 'timeout_ms': 1000})
	assert len(script) <= 10000
	assert 'truncated' in script.lower()
	assert await driver.run_script({'tab_id': None, 'source': '1 + 2', 'timeout_ms': 1000}) == '3'
	controls = await driver.find({'tab_id': None, 'query': 'Last'})
	await driver.click({'tab_id': None, 'target': reference(controls, 'Last')})


async def test_page_read_does_not_expose_password_value(driver):
	await fixture_page(driver, '<label>Password<input type="password" value="private-password-value"></label>')
	text = await driver.read_page({'tab_id': None, 'filter': 'all'})
	assert 'private-password-value' not in text
	assert 'Password' in text


@pytest.mark.asyncio
async def test_state_recovers_after_temporary_transport_failure(driver, monkeypatch):
	page = await fixture_page(driver, '<p>Preserved</p>')
	target = driver.browser.cdp_client.send.Target
	original = target.getTargets

	async def fail_once(*args, **kwargs):
		monkeypatch.setattr(target, 'getTargets', original)
		raise TimeoutError('transport stalled')

	monkeypatch.setattr(target, 'getTargets', fail_once)
	state = await driver.state()
	assert page._target_id in {tab['id'] for tab in state['tabs']}
	assert await driver.get_page_text({'tab_id': page._target_id}) == 'Preserved'


@pytest.mark.asyncio
async def test_diagnostics_timeout_does_not_block_page_read(driver, monkeypatch):
	import asyncio

	import browser_use.integrations.openai.browser_use as implementation

	page = await fixture_page(driver, '<p>Readable without diagnostics</p>')
	driver._diagnostic_sessions.pop(page._target_id)
	client = driver._diagnostic_client
	cancelled = asyncio.Event()

	async def never_attach(*args, **kwargs):
		try:
			await asyncio.Event().wait()
		finally:
			cancelled.set()

	monkeypatch.setattr(implementation, '_DIAGNOSTIC_TIMEOUT_S', 0.05)
	monkeypatch.setattr(client.send.Target, 'attachToTarget', never_attach)
	assert await driver.get_page_text({'tab_id': page._target_id}) == 'Readable without diagnostics'
	assert cancelled.is_set()
	assert driver._diagnostic_client is None
	assert not driver._diagnostic_sessions
	assert not driver._diagnostics


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['timeout', 'corrupt'])
async def test_screenshot_retries_temporary_capture_failure(driver, monkeypatch, failure):
	page = await fixture_page(driver, '<p>Screenshot retry</p>')
	target = driver.browser.cdp_client.send.Page
	original = target.captureScreenshot

	async def fail_once(*args, **kwargs):
		monkeypatch.setattr(target, 'captureScreenshot', original)
		if failure == 'corrupt':
			return {'data': base64.b64encode(b'not an image').decode()}
		raise TimeoutError('capture stalled')

	monkeypatch.setattr(target, 'captureScreenshot', fail_once)
	result = await driver.screenshot({'tab_id': page._target_id})
	with Image.open(BytesIO(base64.b64decode(result['image_url'].split(',', 1)[1]))) as image:
		assert image.width > 0
		assert image.height > 0


@pytest.mark.asyncio
async def test_crashed_page_returns_error_and_other_tabs_remain_usable(driver):
	page = await fixture_page(driver, '<p>Lost page</p>')
	driver._target_crashed({'targetId': page._target_id})
	with pytest.raises(BrowserError, match='page crashed'):
		await driver.get_page_text({'tab_id': page._target_id})
	other = await fixture_page(driver, '<p>Still usable</p>')
	assert await driver.get_page_text({'tab_id': other._target_id}) == 'Still usable'


@pytest.mark.asyncio
async def test_page_read_retries_temporary_accessibility_failure(driver, monkeypatch):
	await fixture_page(driver, '<button>Recovered control</button>')
	target = driver.browser.cdp_client.send.Accessibility
	original = target.getFullAXTree

	async def fail_once(*args, **kwargs):
		monkeypatch.setattr(target, 'getFullAXTree', original)
		raise TimeoutError('accessibility stalled')

	monkeypatch.setattr(target, 'getFullAXTree', fail_once)
	text = await driver.read_page({'tab_id': None, 'filter': 'interactive'})
	assert reference(text, 'Recovered control')
