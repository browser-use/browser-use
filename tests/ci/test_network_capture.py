"""Tests for network capture tools: start_capture → paginate → stop → transform → sync pipeline."""

import asyncio
import json
import tempfile

import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Response

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.service import Tools


@pytest.fixture(scope='session')
def http_server():
	"""HTTP server serving a page that fetches from a JSON API endpoint."""
	server = HTTPServer()
	server.start()

	# API endpoint returning JSON items
	def api_handler(request):
		page = int(request.args.get('page', '1'))
		items = [{'id': (page - 1) * 3 + i, 'name': f'Item-{(page - 1) * 3 + i}', 'price': 10.0 + i} for i in range(1, 4)]
		return Response(
			json.dumps({'items': items, 'page': page}),
			content_type='application/json',
		)

	server.expect_request('/api/items').respond_with_handler(api_handler)

	# Page that fetches from the API and has a "next" button
	page_html = """
	<!DOCTYPE html>
	<html>
	<head><title>Items</title></head>
	<body>
		<h1>Items Page</h1>
		<div id="content"></div>
		<button id="next-btn" onclick="loadNext()">Next Page</button>
		<script>
			let currentPage = 1;
			async function loadNext() {
				currentPage++;
				const resp = await fetch('/api/items?page=' + currentPage);
				const data = await resp.json();
				document.getElementById('content').textContent = JSON.stringify(data);
			}
			// Load first page on init
			fetch('/api/items?page=1')
				.then(r => r.json())
				.then(d => document.getElementById('content').textContent = JSON.stringify(d));
		</script>
	</body>
	</html>
	"""
	server.expect_request('/items').respond_with_data(page_html, content_type='text/html')

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await session.start()
	yield session
	await session.kill()


@pytest.fixture(scope='function')
def tools():
	return Tools()


class TestNetworkCapture:
	"""Tests for the network capture → transform → sync pipeline."""

	async def test_actions_registered(self, tools):
		"""Verify all 5 capture actions are present in the registry."""
		expected = ['start_capture', 'stop_capture', 'transform_captured_data', 'sync_captured_data', 'paginate_and_capture']
		for name in expected:
			assert name in tools.registry.registry.actions, f'{name} not registered'

	async def test_start_and_stop_capture(self, tools, browser_session, base_url):
		"""Start capture, navigate to trigger API calls, then stop."""
		# Navigate to the items page first (triggers initial API fetch)
		await tools.navigate(url=f'{base_url}/items', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(1)  # Wait for page load + initial fetch

		# Start capture
		result = await tools.start_capture(
			session_name='test',
			url_patterns=['*/api/items*'],
			browser_session=browser_session,
		)
		assert isinstance(result, ActionResult)
		assert result.error is None
		assert 'Capturing' in result.extracted_content

		# Stop capture
		result = await tools.stop_capture(browser_session=browser_session)
		assert isinstance(result, ActionResult)
		assert result.error is None
		assert 'Stopped' in result.extracted_content

	async def test_capture_and_paginate(self, tools, browser_session, base_url):
		"""Capture API responses while paginating."""
		# Navigate to items page
		await tools.navigate(url=f'{base_url}/items', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(1)

		# Start capture
		result = await tools.start_capture(
			session_name='paginate_test',
			url_patterns=['*/api/items*'],
			browser_session=browser_session,
		)
		assert result.error is None

		# Paginate 3 pages
		result = await tools.paginate_and_capture(
			button_selector='#next-btn',
			pages=3,
			wait_ms=1500,
			browser_session=browser_session,
		)
		assert isinstance(result, ActionResult)
		assert result.error is None
		assert 'Paginated' in result.extracted_content
		# Should have paginated some pages (button exists)
		assert '0/3' not in result.extracted_content

		# Stop capture
		result = await tools.stop_capture(browser_session=browser_session)
		assert result.error is None
		# Should have captured some responses
		assert 'captured' in result.extracted_content.lower()

	async def test_full_pipeline(self, tools, browser_session, base_url):
		"""End-to-end: capture → paginate → stop → transform → sync."""
		# Navigate
		await tools.navigate(url=f'{base_url}/items', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(1)

		# Start capture
		result = await tools.start_capture(
			session_name='full_test',
			url_patterns=['*/api/items*'],
			browser_session=browser_session,
		)
		assert result.error is None

		# Paginate to collect responses
		result = await tools.paginate_and_capture(
			button_selector='#next-btn',
			pages=2,
			wait_ms=1500,
			browser_session=browser_session,
		)
		assert result.error is None

		# Stop capture
		result = await tools.stop_capture(browser_session=browser_session)
		assert result.error is None

		# Transform: parse JSON bodies and collect all items
		transform_js = """
		const allItems = [];
		for (const resp of responses) {
			try {
				const data = JSON.parse(resp.body);
				if (data.items) {
					for (const item of data.items) {
						allItems.push(item);
					}
				}
			} catch (e) {}
		}
		const __result_count = await _writeResults(db, allItems);
		"""
		result = await tools.transform_captured_data(
			js_code=transform_js,
			browser_session=browser_session,
		)
		assert isinstance(result, ActionResult)
		assert result.error is None
		assert 'complete' in result.extracted_content.lower() or 'items' in result.extracted_content.lower()

		# Sync to filesystem
		with tempfile.TemporaryDirectory() as temp_dir:
			file_system = FileSystem(temp_dir)

			result = await tools.sync_captured_data(
				file_name='items.json',
				source='results',
				browser_session=browser_session,
				file_system=file_system,
			)
			assert isinstance(result, ActionResult)
			assert result.error is None
			assert 'items.json' in result.extracted_content

			# Verify file was written
			file_path = file_system.get_dir() / 'items.json'
			assert file_path.exists()
			content = json.loads(file_path.read_text())
			assert isinstance(content, list)
			assert len(content) > 0
			# Each item should have id, name, price
			assert 'name' in content[0]

	async def test_sync_raw_responses(self, tools, browser_session, base_url):
		"""Sync raw captured responses (source=responses) to JSONL."""
		# Navigate and capture
		await tools.navigate(url=f'{base_url}/items', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(1)

		result = await tools.start_capture(
			session_name='raw_test',
			url_patterns=['*/api/items*'],
			browser_session=browser_session,
		)
		assert result.error is None

		# Paginate once to trigger a capture
		result = await tools.paginate_and_capture(
			button_selector='#next-btn',
			pages=1,
			wait_ms=1500,
			browser_session=browser_session,
		)
		assert result.error is None

		result = await tools.stop_capture(browser_session=browser_session)
		assert result.error is None

		# Sync raw responses as JSONL
		with tempfile.TemporaryDirectory() as temp_dir:
			file_system = FileSystem(temp_dir)

			result = await tools.sync_captured_data(
				file_name='raw.jsonl',
				source='responses',
				browser_session=browser_session,
				file_system=file_system,
			)
			assert result.error is None
			assert 'raw.jsonl' in result.extracted_content

			file_path = file_system.get_dir() / 'raw.jsonl'
			assert file_path.exists()
			lines = file_path.read_text().strip().split('\n')
			assert len(lines) >= 1
			first = json.loads(lines[0])
			assert 'url' in first
			assert 'body' in first

	async def test_paginate_stop_selector(self, tools, browser_session, base_url):
		"""Pagination with stop_selector stops when element is missing."""
		await tools.navigate(url=f'{base_url}/items', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(1)

		# Use a stop selector that doesn't exist — should stop immediately
		result = await tools.paginate_and_capture(
			button_selector='#next-btn',
			pages=10,
			wait_ms=500,
			stop_selector='#nonexistent-element',
			browser_session=browser_session,
		)
		assert result.error is None
		# Should have paginated 0 pages since stop selector wasn't found
		assert 'Paginated 0/' in result.extracted_content

	async def test_stop_without_start(self, tools, browser_session):
		"""Stopping capture when not active is a no-op."""
		result = await tools.stop_capture(browser_session=browser_session)
		assert result.error is None
		assert 'Stopped' in result.extracted_content or 'captured' in result.extracted_content.lower()

	async def test_watchdog_not_initialized(self):
		"""Tools should return error when watchdog is not initialized."""
		tools = Tools()
		# Create a session but don't start it (no watchdog attached)
		session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None))
		# Session not started, so _network_capture_watchdog is None
		result = await tools.start_capture(
			session_name='test',
			url_patterns=['*'],
			browser_session=session,
		)
		assert result.error is not None
		assert 'not initialized' in result.error
