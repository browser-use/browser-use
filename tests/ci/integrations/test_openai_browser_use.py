from __future__ import annotations

import base64
import json
import re
from io import BytesIO

import pytest
from openai.lib.browser import AsyncBrowserToolset, BrowserError
from openai.types.responses import ResponseFunctionToolCall
from PIL import Image
from playwright.async_api import async_playwright

from browser_use import BrowserSession
from browser_use.integrations.openai import BrowserUse


@pytest.fixture
async def driver():
	async with async_playwright() as playwright:
		browser = BrowserSession(
			headless=True,
			executable_path=playwright.chromium.executable_path,
			enable_default_extensions=False,
			user_data_dir=None,
		)
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
	with pytest.raises((BrowserError, RuntimeError)):
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
