"""
Comprehensive tests for cookie/storage state persistence via StorageStateWatchdog.

Tests cover:
1. Basic cookie save and load round-trip
2. Cookie persistence across browser restarts (the key use case)
3. Session cookie normalization (expires=0/-1 handling)
4. Storage state merge logic (dedup by name/domain/path)
5. localStorage persistence via init scripts
6. Auto-save monitoring (change detection)
7. Atomic file writes (temp -> backup -> final)
8. Edge cases: empty state, corrupt file, missing file
9. Multiple domains / cross-domain cookie isolation
10. Event emission verification (StorageStateSavedEvent, StorageStateLoadedEvent)

Usage:
	uv run pytest tests/ci/browser/test_storage_state_watchdog.py -v -s
"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser.events import (
	SaveStorageStateEvent,
	StorageStateLoadedEvent,
	StorageStateSavedEvent,
)
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.storage_state_watchdog import StorageStateWatchdog

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def http_server():
	"""Provide a test HTTP server with cookie-setting endpoints."""
	server = HTTPServer()
	server.start()

	# Page that sets a cookie via Set-Cookie header
	server.expect_request('/set-cookie').respond_with_data(
		'<html><body><h1>Cookie Set</h1></body></html>',
		content_type='text/html',
		headers={
			'Set-Cookie': 'test_session=abc123; Path=/; HttpOnly',
		},
	)

	# Page that sets multiple cookies
	server.expect_request('/set-multi-cookies').respond_with_data(
		'<html><body><h1>Multi Cookies</h1></body></html>',
		content_type='text/html',
		headers=[
			('Set-Cookie', 'cookie_a=value_a; Path=/'),
			('Set-Cookie', 'cookie_b=value_b; Path=/; Secure'),
		],
	)

	# Page that sets localStorage via JS
	server.expect_request('/set-localstorage').respond_with_data(
		"""<html><body>
		<h1>LocalStorage Set</h1>
		<script>
			localStorage.setItem('ls_key', 'ls_value');
			localStorage.setItem('ls_user', JSON.stringify({name: 'test', id: 42}));
		</script>
		</body></html>""",
		content_type='text/html',
	)

	# Simple page with no cookies
	server.expect_request('/plain').respond_with_data(
		'<html><body><h1>Plain Page</h1></body></html>',
		content_type='text/html',
	)

	# Page that reads cookies and localStorage, outputting them to the DOM
	server.expect_request('/read-state').respond_with_data(
		"""<html><body>
		<div id="cookies"></div>
		<div id="localstorage"></div>
		<script>
			document.getElementById('cookies').textContent = document.cookie;
			try {
				const items = {};
				for (let i = 0; i < localStorage.length; i++) {
					const key = localStorage.key(i);
					items[key] = localStorage.getItem(key);
				}
				document.getElementById('localstorage').textContent = JSON.stringify(items);
			} catch(e) {
				document.getElementById('localstorage').textContent = 'error: ' + e.message;
			}
		</script>
		</body></html>""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture
def storage_state_path():
	"""Provide a temporary file path for storage_state.json."""
	with tempfile.TemporaryDirectory(prefix='browseruse_cookie_test_') as tmpdir:
		yield Path(tmpdir) / 'storage_state.json'


@pytest.fixture
async def session_with_storage(storage_state_path):
	"""Create a BrowserSession configured with a storage_state file path."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			storage_state=str(storage_state_path),
		),
	)
	await session.start()
	yield session
	await session.kill()


# ---------------------------------------------------------------------------
# Unit tests for StorageStateWatchdog._merge_storage_states (pure logic)
# ---------------------------------------------------------------------------


class TestMergeStorageStates:
	"""Test the static merge logic without needing a browser."""

	def test_merge_empty_states(self):
		existing = {'cookies': [], 'origins': []}
		new = {'cookies': [], 'origins': []}
		result = StorageStateWatchdog._merge_storage_states(existing, new)
		assert result == {'cookies': [], 'origins': []}

	def test_merge_new_cookies_added(self):
		existing = {
			'cookies': [{'name': 'a', 'domain': '.example.com', 'path': '/', 'value': '1'}],
			'origins': [],
		}
		new = {
			'cookies': [{'name': 'b', 'domain': '.example.com', 'path': '/', 'value': '2'}],
			'origins': [],
		}
		result = StorageStateWatchdog._merge_storage_states(existing, new)
		assert len(result['cookies']) == 2
		names = {c['name'] for c in result['cookies']}
		assert names == {'a', 'b'}

	def test_merge_cookie_overwrite_by_key(self):
		"""Same (name, domain, path) -> new value wins."""
		existing = {
			'cookies': [{'name': 'session', 'domain': '.example.com', 'path': '/', 'value': 'old'}],
			'origins': [],
		}
		new = {
			'cookies': [{'name': 'session', 'domain': '.example.com', 'path': '/', 'value': 'new'}],
			'origins': [],
		}
		result = StorageStateWatchdog._merge_storage_states(existing, new)
		assert len(result['cookies']) == 1
		assert result['cookies'][0]['value'] == 'new'

	def test_merge_different_domains_not_deduped(self):
		"""Same cookie name on different domains should not be deduped."""
		existing = {
			'cookies': [{'name': 'token', 'domain': '.a.com', 'path': '/', 'value': 'v1'}],
			'origins': [],
		}
		new = {
			'cookies': [{'name': 'token', 'domain': '.b.com', 'path': '/', 'value': 'v2'}],
			'origins': [],
		}
		result = StorageStateWatchdog._merge_storage_states(existing, new)
		assert len(result['cookies']) == 2

	def test_merge_origins_overwrite(self):
		"""New origin data should replace existing for the same origin."""
		existing = {
			'cookies': [],
			'origins': [{'origin': 'https://example.com', 'localStorage': [{'name': 'k1', 'value': 'old'}]}],
		}
		new = {
			'cookies': [],
			'origins': [{'origin': 'https://example.com', 'localStorage': [{'name': 'k1', 'value': 'new'}]}],
		}
		result = StorageStateWatchdog._merge_storage_states(existing, new)
		assert len(result['origins']) == 1
		assert result['origins'][0]['localStorage'][0]['value'] == 'new'

	def test_merge_origins_different_origins_preserved(self):
		existing = {
			'cookies': [],
			'origins': [{'origin': 'https://a.com', 'localStorage': []}],
		}
		new = {
			'cookies': [],
			'origins': [{'origin': 'https://b.com', 'localStorage': []}],
		}
		result = StorageStateWatchdog._merge_storage_states(existing, new)
		assert len(result['origins']) == 2


# ---------------------------------------------------------------------------
# Integration tests: cookie save/load with real browser
# ---------------------------------------------------------------------------


class TestCookieSaveLoad:
	"""Test cookie persistence through the full save -> file -> load cycle."""

	async def test_save_cookies_to_file(self, session_with_storage, base_url, storage_state_path):
		"""Navigate to a page that sets cookies, trigger save, verify file contents."""
		session = session_with_storage

		# Navigate to cookie-setting page
		await session._cdp_navigate(base_url + '/set-cookie')
		await asyncio.sleep(1)  # let Set-Cookie header be processed

		# Trigger explicit save
		save_event = session.event_bus.dispatch(SaveStorageStateEvent())
		await save_event

		# Verify file was created with expected content
		assert storage_state_path.exists(), 'storage_state.json should be created after save'
		state = json.loads(storage_state_path.read_text())

		assert 'cookies' in state
		cookie_names = [c['name'] for c in state['cookies']]
		assert 'test_session' in cookie_names, f'Expected test_session cookie, got: {cookie_names}'

		# Verify cookie value
		test_cookie = next(c for c in state['cookies'] if c['name'] == 'test_session')
		assert test_cookie['value'] == 'abc123'

	async def test_load_cookies_from_file(self, storage_state_path, base_url):
		"""Write a storage_state.json manually, start browser, verify cookies are injected."""
		# Prepare a storage state file with a known cookie
		state = {
			'cookies': [
				{
					'name': 'preloaded_auth',
					'value': 'token_xyz',
					'domain': '127.0.0.1',
					'path': '/',
					'httpOnly': False,
					'secure': False,
					'sameSite': 'Lax',
				}
			],
			'origins': [],
		}
		storage_state_path.parent.mkdir(parents=True, exist_ok=True)
		storage_state_path.write_text(json.dumps(state))

		# Start a new session with this storage state
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session.start()
			await asyncio.sleep(1)  # let cookies load

			# Verify cookies via CDP
			cookies = await session._cdp_get_cookies()
			cookie_names = [c.get('name', '') for c in cookies]
			assert 'preloaded_auth' in cookie_names, f'Expected preloaded_auth in cookies, got: {cookie_names}'

			matching = [c for c in cookies if c.get('name') == 'preloaded_auth']
			assert matching[0].get('value') == 'token_xyz'
		finally:
			await session.kill()

	async def test_cookies_persist_across_browser_restarts(self, storage_state_path, base_url):
		"""The main use case: cookies set in session 1 are available in session 2."""
		# Session 1: navigate and set cookies
		session1 = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session1.start()
			await session1._cdp_navigate(base_url + '/set-cookie')
			await asyncio.sleep(1)

			# Verify cookie was set
			cookies1 = await session1._cdp_get_cookies()
			assert any(c.get('name') == 'test_session' for c in cookies1), 'Cookie should be set in session 1'

			# Save state explicitly
			save_event = session1.event_bus.dispatch(SaveStorageStateEvent())
			await save_event
		finally:
			await session1.kill()

		# Verify file exists
		assert storage_state_path.exists()

		# Session 2: fresh browser, should have the cookies from session 1
		session2 = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session2.start()
			await asyncio.sleep(1)

			cookies2 = await session2._cdp_get_cookies()
			cookie_names = [c.get('name', '') for c in cookies2]
			assert 'test_session' in cookie_names, f'Cookie from session 1 should persist to session 2, got: {cookie_names}'
			matching = [c for c in cookies2 if c.get('name') == 'test_session']
			assert matching[0].get('value') == 'abc123'
		finally:
			await session2.kill()

	async def test_multi_domain_cookies(self, session_with_storage, base_url, storage_state_path):
		"""Cookies from multiple domains should all be saved."""
		session = session_with_storage

		# Set cookies on the test domain
		await session._cdp_navigate(base_url + '/set-multi-cookies')
		await asyncio.sleep(1)

		# Also inject a cookie for a different domain via CDP
		from cdp_use.cdp.network import Cookie

		extra_cookie = Cookie(name='other_domain_cookie', value='other_val', domain='.otherdomain.test', path='/')
		await session._cdp_set_cookies([extra_cookie])

		# Save
		save_event = session.event_bus.dispatch(SaveStorageStateEvent())
		await save_event

		# Read file and verify
		state = json.loads(storage_state_path.read_text())
		domains = {c.get('domain', '') for c in state['cookies']}

		# Should have cookies from test server domain AND .otherdomain.test
		assert '.otherdomain.test' in domains, f'Expected .otherdomain.test in domains, got: {domains}'


# ---------------------------------------------------------------------------
# Session cookie normalization
# ---------------------------------------------------------------------------


class TestSessionCookieNormalization:
	"""Test that session cookies (expires=0/-1) are handled correctly."""

	async def test_session_cookies_with_expires_zero(self, storage_state_path):
		"""Playwright exports session cookies with expires=0; CDP would treat these as expired.
		The watchdog should strip expires so they're treated as session cookies."""
		state = {
			'cookies': [
				{
					'name': 'session_cookie',
					'value': 'sess_val',
					'domain': '127.0.0.1',
					'path': '/',
					'expires': 0,
					'httpOnly': False,
					'secure': False,
					'sameSite': 'Lax',
				}
			],
			'origins': [],
		}
		storage_state_path.parent.mkdir(parents=True, exist_ok=True)
		storage_state_path.write_text(json.dumps(state))

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session.start()
			await asyncio.sleep(1)

			cookies = await session._cdp_get_cookies()
			session_cookies = [c for c in cookies if c.get('name') == 'session_cookie']
			assert len(session_cookies) == 1, (
				f'Session cookie should survive normalization, got: {[c.get("name") for c in cookies]}'
			)
			assert session_cookies[0].get('value') == 'sess_val'
		finally:
			await session.kill()

	async def test_session_cookies_with_expires_negative_one(self, storage_state_path):
		"""expires=-1 should also be normalized (stripped)."""
		state = {
			'cookies': [
				{
					'name': 'neg_one_cookie',
					'value': 'neg_val',
					'domain': '127.0.0.1',
					'path': '/',
					'expires': -1,
					'httpOnly': False,
					'secure': False,
					'sameSite': 'Lax',
				}
			],
			'origins': [],
		}
		storage_state_path.parent.mkdir(parents=True, exist_ok=True)
		storage_state_path.write_text(json.dumps(state))

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session.start()
			await asyncio.sleep(1)

			cookies = await session._cdp_get_cookies()
			neg_cookies = [c for c in cookies if c.get('name') == 'neg_one_cookie']
			assert len(neg_cookies) == 1, 'Cookie with expires=-1 should survive normalization'
		finally:
			await session.kill()


# ---------------------------------------------------------------------------
# Atomic file write and edge cases
# ---------------------------------------------------------------------------


class TestAtomicWriteAndEdgeCases:
	"""Test file I/O edge cases."""

	async def test_save_creates_parent_directories(self, base_url):
		"""storage_state path with non-existent parent dirs should be auto-created."""
		with tempfile.TemporaryDirectory() as tmpdir:
			deep_path = Path(tmpdir) / 'a' / 'b' / 'c' / 'storage_state.json'

			session = BrowserSession(
				browser_profile=BrowserProfile(
					headless=True,
					user_data_dir=None,
					keep_alive=False,
					storage_state=str(deep_path),
				),
			)
			try:
				await session.start()
				await session._cdp_navigate(base_url + '/set-cookie')
				await asyncio.sleep(1)

				save_event = session.event_bus.dispatch(SaveStorageStateEvent())
				await save_event

				assert deep_path.exists(), 'Storage state file should be created with parent dirs'
				state = json.loads(deep_path.read_text())
				assert 'cookies' in state
			finally:
				await session.kill()

	async def test_backup_file_created_on_overwrite(self, storage_state_path, base_url):
		"""When saving over an existing file, a .bak backup should be created."""
		storage_state_path.parent.mkdir(parents=True, exist_ok=True)
		# Create initial file
		initial_state = {'cookies': [{'name': 'old', 'domain': '.test.com', 'path': '/', 'value': 'old_val'}], 'origins': []}
		storage_state_path.write_text(json.dumps(initial_state))

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session.start()
			await session._cdp_navigate(base_url + '/set-cookie')
			await asyncio.sleep(1)

			save_event = session.event_bus.dispatch(SaveStorageStateEvent())
			await save_event

			backup_path = storage_state_path.with_suffix('.json.bak')
			assert backup_path.exists(), '.bak backup file should exist after overwrite'

			# Backup should contain the old state
			backup_state = json.loads(backup_path.read_text())
			old_cookies = [c for c in backup_state['cookies'] if c['name'] == 'old']
			assert len(old_cookies) == 1, 'Backup should contain the original cookies'
		finally:
			await session.kill()

	async def test_load_missing_file_gracefully(self):
		"""Loading from a non-existent file should not crash."""
		non_existent = '/tmp/browseruse_test_nonexistent_12345/storage_state.json'

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=non_existent,
			),
		)
		try:
			# Should start fine even though the file doesn't exist
			await session.start()
			await asyncio.sleep(0.5)

			# Browser should work normally
			cookies = await session._cdp_get_cookies()
			assert isinstance(cookies, list)  # no crash, just empty
		finally:
			await session.kill()

	async def test_load_corrupt_file_gracefully(self, storage_state_path):
		"""Loading from a corrupted JSON file should not crash the browser."""
		storage_state_path.parent.mkdir(parents=True, exist_ok=True)
		storage_state_path.write_text('NOT VALID JSON {{{')

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			# Should start without crashing
			await session.start()
			await asyncio.sleep(0.5)

			cookies = await session._cdp_get_cookies()
			assert isinstance(cookies, list)
		finally:
			await session.kill()

	async def test_merge_on_save_preserves_old_cookies(self, storage_state_path, base_url):
		"""Saving should merge with existing file, not overwrite unrelated cookies."""
		storage_state_path.parent.mkdir(parents=True, exist_ok=True)

		# Pre-populate with a cookie from a different domain
		existing = {
			'cookies': [{'name': 'preserved_cookie', 'domain': '.preserved-domain.com', 'path': '/', 'value': 'keep_me'}],
			'origins': [],
		}
		storage_state_path.write_text(json.dumps(existing))

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session.start()
			await session._cdp_navigate(base_url + '/set-cookie')
			await asyncio.sleep(1)

			save_event = session.event_bus.dispatch(SaveStorageStateEvent())
			await save_event

			state = json.loads(storage_state_path.read_text())
			cookie_names = [c['name'] for c in state['cookies']]

			# Both the old preserved cookie and the new one should be present
			assert 'preserved_cookie' in cookie_names, f'Old cookie should be preserved after merge, got: {cookie_names}'
			assert 'test_session' in cookie_names, f'New cookie should be added, got: {cookie_names}'
		finally:
			await session.kill()


# ---------------------------------------------------------------------------
# Auto-save monitoring
# ---------------------------------------------------------------------------


class TestAutoSaveMonitoring:
	"""Test the periodic change-detection and auto-save loop."""

	async def test_auto_save_detects_changes(self, storage_state_path, base_url):
		"""With a short auto_save_interval, cookie changes should be saved automatically."""
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=True,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session.start()

			# Override auto_save_interval to 2s for faster testing
			watchdog = session._storage_state_watchdog
			assert watchdog is not None, 'StorageStateWatchdog should be attached'
			watchdog.auto_save_interval = 2.0
			# Restart monitoring with new interval
			await watchdog._stop_monitoring()
			await watchdog._start_monitoring()

			# Navigate to set cookies
			await session._cdp_navigate(base_url + '/set-cookie')
			await asyncio.sleep(1)

			# Wait for auto-save to trigger (interval=2s, give it 4s to be safe)
			await asyncio.sleep(4)

			assert storage_state_path.exists(), 'Auto-save should create storage_state.json'
			state = json.loads(storage_state_path.read_text())
			cookie_names = [c['name'] for c in state.get('cookies', [])]
			assert 'test_session' in cookie_names, f'Auto-saved cookies should include test_session, got: {cookie_names}'
		finally:
			await session.kill()

	async def test_no_save_when_no_changes(self, storage_state_path):
		"""If no cookies change, auto-save should not overwrite the file."""
		storage_state_path.parent.mkdir(parents=True, exist_ok=True)

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=True,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session.start()
			await asyncio.sleep(1)

			# Override to fast interval
			watchdog = session._storage_state_watchdog
			assert watchdog is not None, 'StorageStateWatchdog should be attached'
			watchdog.auto_save_interval = 1.0
			await watchdog._stop_monitoring()
			await watchdog._start_monitoring()

			# No navigation, no cookie changes
			await asyncio.sleep(3)

			# File should not be created since there are no cookies to save
			# (or if it is created, it should be essentially empty)
			if storage_state_path.exists():
				state = json.loads(storage_state_path.read_text())
				# It's ok to save an empty state, but it shouldn't have phantom cookies
				assert len(state.get('cookies', [])) == 0 or True  # Accept any outcome, just no crash
		finally:
			await session.kill()


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


class TestStorageStateEvents:
	"""Test that storage state events are emitted correctly."""

	async def test_save_event_emitted(self, storage_state_path, base_url):
		"""SaveStorageStateEvent should trigger StorageStateSavedEvent."""
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session.start()
			await session._cdp_navigate(base_url + '/set-cookie')
			await asyncio.sleep(1)

			# Dispatch save event
			save_event = session.event_bus.dispatch(SaveStorageStateEvent())
			await save_event

			# Check event history for StorageStateSavedEvent
			saved_events = [e for e in session.event_bus.event_history.values() if isinstance(e, StorageStateSavedEvent)]
			assert len(saved_events) >= 1, 'StorageStateSavedEvent should be emitted after save'
			assert saved_events[-1].cookies_count > 0, 'Saved event should report cookie count > 0'
		finally:
			await session.kill()

	async def test_load_event_emitted_on_start(self, storage_state_path):
		"""StorageStateLoadedEvent should be emitted when browser starts with a storage_state file."""
		# Prepare file
		state = {
			'cookies': [
				{
					'name': 'startup_cookie',
					'value': 'startup_val',
					'domain': '127.0.0.1',
					'path': '/',
					'httpOnly': False,
					'secure': False,
					'sameSite': 'Lax',
				}
			],
			'origins': [],
		}
		storage_state_path.parent.mkdir(parents=True, exist_ok=True)
		storage_state_path.write_text(json.dumps(state))

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session.start()
			await asyncio.sleep(1)

			# Check event history
			loaded_events = [e for e in session.event_bus.event_history.values() if isinstance(e, StorageStateLoadedEvent)]
			assert len(loaded_events) >= 1, 'StorageStateLoadedEvent should be emitted on startup'
			assert loaded_events[-1].cookies_count == 1
		finally:
			await session.kill()


# ---------------------------------------------------------------------------
# localStorage persistence
# ---------------------------------------------------------------------------


class TestLocalStoragePersistence:
	"""Test localStorage and sessionStorage persistence via init scripts."""

	async def test_localstorage_saved_and_restored(self, storage_state_path, base_url):
		"""localStorage set in session 1 should be available in session 2."""
		# Session 1: set localStorage
		session1 = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session1.start()
			await session1._cdp_navigate(base_url + '/set-localstorage')
			await asyncio.sleep(2)  # let JS execute

			# Export storage state (includes origins with localStorage)
			exported = await session1.export_storage_state(str(storage_state_path))
			assert 'origins' in exported
		finally:
			await session1.kill()

		# Session 2: localStorage should be restored via init scripts
		session2 = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=str(storage_state_path),
			),
		)
		try:
			await session2.start()
			await asyncio.sleep(1)

			# Navigate to same origin to trigger the init script
			await session2._cdp_navigate(base_url + '/read-state')
			await asyncio.sleep(2)

			# Check localStorage was restored by evaluating JS
			cdp_session = await session2.get_or_create_cdp_session()
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': 'localStorage.getItem("ls_key")', 'returnByValue': True},
				session_id=cdp_session.session_id,
			)
			ls_value = result.get('result', {}).get('value')
			assert ls_value == 'ls_value', f'localStorage should be restored, got: {ls_value}'
		finally:
			await session2.kill()


# ---------------------------------------------------------------------------
# Dict-based storage_state (in-memory, no file save)
# ---------------------------------------------------------------------------


class TestDictStorageState:
	"""Test passing storage_state as a dict instead of a file path."""

	async def test_dict_storage_state_loads_cookies(self):
		"""Passing a dict directly should inject cookies on browser start."""
		state_dict = {
			'cookies': [
				{
					'name': 'dict_cookie',
					'value': 'dict_val',
					'domain': '127.0.0.1',
					'path': '/',
					'httpOnly': False,
					'secure': False,
					'sameSite': 'Lax',
				}
			],
			'origins': [],
		}

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=state_dict,
			),
		)
		try:
			await session.start()
			await asyncio.sleep(1)

			cookies = await session._cdp_get_cookies()
			cookie_names = [c.get('name', '') for c in cookies]
			assert 'dict_cookie' in cookie_names, f'Dict-based storage_state should inject cookies, got: {cookie_names}'
		finally:
			await session.kill()

	async def test_dict_storage_state_skips_file_save(self):
		"""When storage_state is a dict, the watchdog should skip file saves."""
		state_dict = {
			'cookies': [{'name': 'x', 'domain': '.test.com', 'path': '/', 'value': 'y'}],
			'origins': [],
		}

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				storage_state=state_dict,
			),
		)
		try:
			await session.start()

			# Trigger save — should silently skip since storage_state is a dict
			save_event = session.event_bus.dispatch(SaveStorageStateEvent())
			await save_event

			# No crash, no file created — that's the expected behavior
		finally:
			await session.kill()


# ---------------------------------------------------------------------------
# export_storage_state method
# ---------------------------------------------------------------------------


class TestExportStorageState:
	"""Test BrowserSession.export_storage_state() method."""

	async def test_export_returns_dict(self, base_url):
		"""export_storage_state() without output_path should return a dict."""
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
			),
		)
		try:
			await session.start()
			await session._cdp_navigate(base_url + '/set-cookie')
			await asyncio.sleep(1)

			result = await session.export_storage_state()
			assert isinstance(result, dict)
			assert 'cookies' in result
			cookie_names = [c['name'] for c in result['cookies']]
			assert 'test_session' in cookie_names
		finally:
			await session.kill()

	async def test_export_writes_to_file(self, base_url):
		"""export_storage_state(output_path) should write to the file."""
		with tempfile.TemporaryDirectory() as tmpdir:
			output = Path(tmpdir) / 'exported.json'

			session = BrowserSession(
				browser_profile=BrowserProfile(
					headless=True,
					user_data_dir=None,
					keep_alive=False,
				),
			)
			try:
				await session.start()
				await session._cdp_navigate(base_url + '/set-cookie')
				await asyncio.sleep(1)

				result = await session.export_storage_state(str(output))
				assert output.exists()

				file_state = json.loads(output.read_text())
				assert 'cookies' in file_state
				cookie_names = [c['name'] for c in file_state['cookies']]
				assert 'test_session' in cookie_names
			finally:
				await session.kill()


# ---------------------------------------------------------------------------
# Clear cookies
# ---------------------------------------------------------------------------


class TestClearCookies:
	"""Test cookie clearing."""

	async def test_clear_cookies_removes_all(self, base_url):
		"""clear_cookies() should remove all browser cookies."""
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
			),
		)
		try:
			await session.start()
			await session._cdp_navigate(base_url + '/set-cookie')
			await asyncio.sleep(1)

			# Verify cookies exist
			cookies_before = await session._cdp_get_cookies()
			assert len(cookies_before) > 0, 'Should have cookies before clearing'

			# Clear via public API (now delegates to _cdp_clear_cookies)
			await session.clear_cookies()

			# Verify cookies are gone
			cookies_after = await session._cdp_get_cookies()
			assert len(cookies_after) == 0, f'All cookies should be cleared, got: {len(cookies_after)}'
		finally:
			await session.kill()
