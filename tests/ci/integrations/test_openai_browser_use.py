from __future__ import annotations

import base64
import json
import re
from io import BytesIO

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
	await driver.type({'tab_id': None, 'target': reference(text, 'Name'), 'text': 'OpenAI driver'})
	await driver.set_checked({'tab_id': None, 'target': reference(text, 'Ready'), 'checked': True})
	await driver.set_checked({'tab_id': None, 'target': reference(text, 'Ready'), 'checked': True})
	await driver.click({'tab_id': None, 'target': reference(text, 'Save')})
	assert await page.evaluate("() => document.querySelector('#result').textContent") == 'OpenAI driver'
	assert await page.evaluate("() => document.querySelector('#ready').checked") == 'True'
	image = await driver.zoom({'tab_id': None, 'region': [0, 0, 100, 80]})
	with Image.open(BytesIO(base64.b64decode(image['image_url'].split(',', 1)[1]))) as crop:
		assert crop.size == (100, 80)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['navigate', 'detach', 'new_tab', 'reread'])
async def test_driver_rejects_stale_or_cross_tab_reference(driver, change):
	page = await fixture_page(driver, '<button id="button">Original</button>')
	text = await driver.read_page({'tab_id': None, 'filter': 'interactive'})
	target = reference(text, 'Original')
	if change == 'navigate':
		await driver.navigate({'tab_id': None, 'url': 'about:blank'})
	elif change == 'detach':
		await page.evaluate("() => document.querySelector('#button').remove()")
	elif change == 'new_tab':
		await driver.new_tab({'url': 'about:blank'})
	else:
		await driver.read_page({'tab_id': None, 'filter': 'interactive'})
	with pytest.raises(BrowserError):
		await driver.click({'tab_id': None, 'target': target})


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
		result = json.loads(output['output'][0]['text'])
		assert result['ok'] is True
		assert result['state']['tabs']
		assert all(tab['url'] == 'about:blank' for tab in result['state']['tabs'])
	finally:
		tools.close()
