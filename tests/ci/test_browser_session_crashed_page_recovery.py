"""
Comprehensive tests for browser session recovery when pages become unresponsive due to blocking JavaScript.

This test module covers:
1. Permanent blocking JavaScript that never unblocks
2. Transient blocking JavaScript that unblocks after a delay
3. Page recovery mechanisms via CDP force-close
4. Minimal demonstrations of Playwright hanging on blocking JS
5. Multiple concurrent sessions handling blocking pages
"""

import asyncio
import os
import signal
import time
import warnings

import pytest
from playwright.async_api import async_playwright
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Response

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

# Suppress TargetClosedError warnings during tests
warnings.filterwarnings('ignore', category=RuntimeWarning, message='.*TargetClosedError.*')


@pytest.fixture(scope='session')
async def playwright():
	async with async_playwright() as p:
		yield p


class TestPlaywrightBlockingJavaScript:
	"""Minimal demonstrations showing that Playwright hangs on blocking JavaScript"""

	async def test_playwright_hangs_on_infinite_loop(self, playwright):
		"""Demonstrate that Playwright operations hang indefinitely on pages with blocking JavaScript"""

		browser = await playwright.chromium.launch(headless=True)
		page = await browser.new_page()

		# Navigate to a page with an infinite loop
		print('1. Navigating to page with infinite JavaScript loop...')
		try:
			await page.goto('data:text/html,<script>while(true){}</script>', wait_until='domcontentloaded', timeout=1000)
		except Exception as e:
			print(f'   Navigation timed out as expected: {type(e).__name__}')
		print('2. Navigation complete (page is now blocked)')

		# Try to evaluate simple JavaScript with asyncio timeout
		print("3. Attempting page.evaluate('1+1') with 2 second timeout...")
		print('   Expected: Should timeout after 2 seconds')
		print('   Reality: In some versions, this may hang forever!\n')

		try:
			# In older Playwright versions, this could hang forever!
			# In newer versions, it may properly timeout
			result = await asyncio.wait_for(page.evaluate('1 + 1'), timeout=2.0)
			print(f'✅ Result: {result} (Playwright handled it properly)')
			assert False, (
				'Playwright is expected to time out here, otherwise congrats, you can remove all the complexity around handling crashed pages!'
			)
		except TimeoutError:
			print('✅ Timed out after 2 seconds as expected because page is crashed (asyncio timeout worked)')
		except Exception as e:
			print(f'⚠️  Other error: {type(e).__name__}: {e}')
			assert False, 'Playwright is expected to time out during all operations on crashed pages, not raise an exception'

	async def test_all_playwright_operations_hang(self, playwright):
		"""Show that ALL Playwright operations hang on a blocked page"""

		browser = await playwright.chromium.launch(headless=True)
		page = await browser.new_page()

		# Navigate to blocking page
		try:
			await page.goto('data:text/html,<script>while(true){}</script>', wait_until='domcontentloaded', timeout=1500)
		except Exception:
			pass  # Expected timeout
		print('✅ Page is now blocked by infinite loop')

		# List of operations that will ALL hang forever
		operations = [
			('page.title()', lambda: page.title()),
			('page.content()', lambda: page.content()),
			('page.screenshot()', lambda: page.screenshot()),
			("page.evaluate('1')", lambda: page.evaluate('1')),
			("page.query_selector('body')", lambda: page.query_selector('body')),
		]

		for op_name, op_func in operations:
			print(f'\n🧪 Testing {op_name} with 1s timeout...')
			try:
				await asyncio.wait_for(op_func(), timeout=1.0)
				print(f'✅ {op_name} succeeded')
			except TimeoutError:
				print(f'⏱️  {op_name} timed out after 1s (expected for blocked page)')
			except Exception as e:
				print(f'❌ {op_name} failed: {type(e).__name__}')

	async def test_transient_vs_permanent_blocking(self, playwright):
		"""Demonstrate the difference between transient and permanent blocking"""

		browser = await playwright.chromium.launch(headless=True)

		# Test 1: Transient blocking (blocks for 2 seconds)
		print('=== Test 1: Transient Blocking ===')
		page1 = await browser.new_page()

		transient_html = """
		<html><body>
		<h1>Transient Block</h1>
		<script>
			const start = Date.now();
			while (Date.now() - start < 2000) {} // Block for 2 seconds
			document.body.innerHTML += '<p>Now responsive!</p>';
		</script>
		</body></html>
		"""

		await page1.goto(f'data:text/html,{transient_html}')
		print('Page loaded with transient blocking script')

		# Wait for block to end
		await asyncio.sleep(2.5)

		# This should work now
		try:
			result = await asyncio.wait_for(page1.evaluate('2 + 2'), timeout=1.0)
			print(f'✅ Transient block ended, evaluate worked: {result}')
		except TimeoutError:
			print('❌ Still blocked after transient period')

		# Test 2: Permanent blocking
		print('\n=== Test 2: Permanent Blocking ===')
		page2 = await browser.new_page()

		try:
			await page2.goto('data:text/html,<script>while(true){}</script>', wait_until='domcontentloaded', timeout=1000)
		except Exception:
			pass  # Expected timeout
		print('Page loaded with permanent blocking script')

		# This will always timeout
		try:
			await asyncio.wait_for(page2.evaluate('3 + 3'), timeout=1.0)
			print('❌ Should not succeed on permanently blocked page')
		except TimeoutError:
			print('✅ Permanently blocked page timed out as expected')

		del page1, page2


def slow_response_handler(request):
	time.sleep(5)  # 5 second delay to guaranteed exceed the 3 second max timeout
	return Response("""<html><body>Finally loaded!</body></html>""", content_type='text/html')


class TestBrowserSessionRecovery:
	"""Test browser-use's recovery mechanisms for unresponsive pages"""

	@pytest.fixture(scope='function')
	async def browser_session(self, playwright):
		"""Create a browser session for testing"""
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				keep_alive=True,
				default_navigation_timeout=30_000,
				minimum_wait_page_load_time=0.1,  # Short wait for testing
				user_data_dir=None,  # No user data dir to avoid race conditions with other tests
			),
			playwright=playwright,
		)
		await session.start()
		yield session
		# Small delay to let pending operations complete before cleanup
		await asyncio.sleep(0.1)
		await session.kill()

	@pytest.mark.timeout(60)  # 60 second timeout
	async def test_permanent_blocking_forces_cdp_recovery(self, httpserver: HTTPServer, browser_session: BrowserSession):
		"""Test critical behaviors:
		1. Crashed pages should never crash the entire agent
		2. Pages should be retried once on the original URL
		3. Then reset to about:blank to prevent browser from becoming unusable
		"""

		# Create a page with permanent blocking JavaScript
		httpserver.expect_request('/permanent-block').respond_with_data(
			"""
			<html>
			<head><title>Permanent Block</title></head>
			<body>
				<h1>This page blocks forever</h1>
				<script>
					console.log('Starting infinite loop...');
					while (true) {
						// Infinite loop - page will never recover
					}
				</script>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Track recovery attempts
		cdp_force_close_count = 0
		reopen_attempts = 0

		# Ensure browser_context is available
		assert browser_session.browser_context is not None, 'Browser context must be initialized'
		original_new_cdp_session = browser_session.browser_context.new_cdp_session
		original_goto = None

		async def track_cdp_force_close(page):
			nonlocal cdp_force_close_count
			cdp_force_close_count += 1
			print(f'🔨 CDP force-close recovery attempted (count: {cdp_force_close_count})')
			return await original_new_cdp_session(page)

		async def track_goto(page_instance, url, **kwargs):
			nonlocal reopen_attempts
			if 'permanent-block' in url and cdp_force_close_count > 0:
				reopen_attempts += 1
				print(f'🔄 Reopening blocked URL attempt #{reopen_attempts}: {url[:50]}...')
			# Get the original goto method for this specific page
			original = page_instance.__class__.goto
			return await original(page_instance, url, **kwargs)

		browser_session.browser_context.new_cdp_session = track_cdp_force_close  # type: ignore[assignment]

		# Navigate to the permanently blocking page
		blocking_url = httpserver.url_for('/permanent-block')
		print(f'1️⃣ Navigating to blocking page: {blocking_url}')
		try:
			await browser_session.navigate(blocking_url)
		except Exception as e:
			# Expected - the page is unresponsive
			print(f'   Navigation raised expected error: {type(e).__name__}')
		await asyncio.sleep(0.5)  # Let blocking script start

		# We need to patch goto on any new pages created during recovery
		pages_patched = set()

		def patch_page_goto(page):
			if page not in pages_patched:
				pages_patched.add(page)
				# Create a bound method that properly tracks goto calls
				import types

				page.goto = types.MethodType(track_goto, page)

		# Patch the current page
		page = await browser_session.get_current_page()
		patch_page_goto(page)

		# Also patch browser context's new_page to catch pages created during recovery
		original_new_page = browser_session.browser_context.new_page

		async def patched_new_page():
			new_page = await original_new_page()
			patch_page_goto(new_page)
			return new_page

		browser_session.browser_context.new_page = patched_new_page  # type: ignore[assignment]

		# Try to take a screenshot - should trigger recovery
		print('\n2️⃣ Attempting screenshot on blocked page (should trigger recovery)...')
		try:
			# Use a longer timeout since recovery takes time
			screenshot = await asyncio.wait_for(
				browser_session.take_screenshot(),
				timeout=40.0,  # 40 seconds should be enough for recovery
			)
			assert screenshot is not None, 'Screenshot should succeed after recovery'
			assert len(screenshot) > 10, 'Screenshot should have content'
		except TimeoutError:
			pytest.fail('Screenshot timed out after 40 seconds - recovery may have failed')

		# Verify current page is on about:blank after recovery
		current_page = await browser_session.get_current_page()
		current_url = current_page.url
		print(f'\n3️⃣ Current URL after recovery: {current_url}')
		assert current_url == 'about:blank', 'Page should be on about:blank after recovery'

		# Verify recovery behavior
		print('\n📊 Recovery statistics:')
		print(f'   - CDP force-close attempts: {cdp_force_close_count}')
		print(f'   - Reopen attempts: {reopen_attempts}')

		assert cdp_force_close_count >= 1, 'CDP force-close should have been attempted at least once'
		assert reopen_attempts == 1, 'Should attempt to reopen the URL exactly once'

		# Verify browser still works by navigating to a normal page
		print('\n4️⃣ Testing browser still works with normal pages...')
		httpserver.expect_request('/normal').respond_with_data(
			'<html><body><h1>Normal Page</h1></body></html>',
			content_type='text/html',
		)

		await browser_session.navigate(httpserver.url_for('/normal'))

		# Take a screenshot to verify browser works
		state2 = await browser_session._get_updated_state()
		assert state2.screenshot is not None
		assert len(state2.screenshot) > 100, 'Browser should still work after recovery'

		print('\n✅ All critical behaviors verified:')
		print('   - Crashed page did not crash the entire agent')
		print('   - Page was retried once on the original URL')
		print('   - Page was reset to about:blank to remain usable')

	async def test_transient_blocking_recovers_naturally(self, httpserver: HTTPServer, browser_session: BrowserSession):
		"""Test that transiently blocked pages recover without intervention"""
		# Create page that blocks for 3 seconds
		httpserver.expect_request('/transient-block').respond_with_data(
			"""<html><body>
			<h1>Blocking temporarily...</h1>
			<script>
				const start = Date.now();
				while (Date.now() - start < 3000) {}
				document.body.innerHTML += '<p>Page recovered!</p>';
			</script>
			</body></html>""",
			content_type='text/html',
		)

		await browser_session.navigate(httpserver.url_for('/transient-block'))
		await asyncio.sleep(3.5)  # Wait for block to end

		# Should work without recovery
		screenshot = await browser_session.take_screenshot()
		assert screenshot is not None and len(screenshot) > 100

		page = await browser_session.get_current_page()
		content = await page.content()
		assert 'Page recovered!' in content

	async def test_multiple_blocking_recovery_cycles(self, httpserver: HTTPServer, browser_session: BrowserSession):
		"""Test multiple cycles of blocking and recovery"""

		# Create pages
		httpserver.expect_request('/block1').respond_with_data(
			'<html><body><script>while(true){}</script></body></html>',
			content_type='text/html',
		)

		httpserver.expect_request('/normal1').respond_with_data(
			'<html><body><h1>Normal Page 1</h1></body></html>',
			content_type='text/html',
		)

		httpserver.expect_request('/block2').respond_with_data(
			'<html><body><script>while(true){}</script></body></html>',
			content_type='text/html',
		)

		httpserver.expect_request('/normal2').respond_with_data(
			'<html><body><h1>Normal Page 2</h1></body></html>',
			content_type='text/html',
		)

		# First blocking cycle
		print('=== Cycle 1: Navigate to blocking page ===')
		try:
			await browser_session.navigate(httpserver.url_for('/block1'))
		except RuntimeError as e:
			# Expected - navigation to blocking page will fail
			print(f'   Navigation to blocking page failed as expected: {type(e).__name__}')

		# Try screenshot (may trigger recovery)
		try:
			await browser_session.take_screenshot()
		except Exception:
			pass

		# Navigate to normal page
		print('=== Cycle 1: Navigate to normal page ===')
		await browser_session.navigate(httpserver.url_for('/normal1'))
		page = await browser_session.get_current_page()
		content = await page.content()
		assert 'Normal Page 1' in content

		# Second blocking cycle
		print('=== Cycle 2: Navigate to another blocking page ===')
		try:
			await browser_session.navigate(httpserver.url_for('/block2'))
		except RuntimeError as e:
			# Expected - navigation to blocking page will fail
			print(f'   Navigation to blocking page failed as expected: {type(e).__name__}')

		# Try screenshot again
		try:
			await browser_session.take_screenshot()
		except Exception:
			pass

		# Navigate to second normal page
		print('=== Cycle 2: Navigate to another normal page ===')
		await browser_session.navigate(httpserver.url_for('/normal2'))
		page = await browser_session.get_current_page()
		content = await page.content()
		assert 'Normal Page 2' in content

		print('✅ Multiple recovery cycles completed successfully')

	async def test_navigation_timeout_warning_appears(self, httpserver: HTTPServer, browser_session: BrowserSession):
		"""Test that navigation handles slow page loads without hanging"""
		# Set up a page that takes 4 seconds to load
		httpserver.expect_request('/delayed').respond_with_handler(slow_response_handler)

		# Navigate with a timeout - navigation should complete even though page is slow
		start_time = time.time()
		page = await browser_session.navigate(httpserver.url_for('/delayed'), timeout_ms=3500)
		elapsed = time.time() - start_time

		# Navigation should complete within a reasonable time (not hang for full 4 seconds)
		assert elapsed < 3.5, f'Navigation took too long: {elapsed:.2f}s'

		# Browser should still be functional
		assert page is not None

		# Verify we can navigate to another page
		httpserver.expect_request('/normal').respond_with_data('<html><body>Normal</body></html>')
		page2 = await browser_session.navigate(httpserver.url_for('/normal'))
		assert 'normal' in page2.url

	async def test_browser_crash_throws_hard_error_no_restart(self, browser_session: BrowserSession):
		"""Test that browser crashes throw hard errors instead of restarting the browser"""
		# Get the browser process PID
		browser_pid = browser_session.browser_pid
		assert browser_pid is not None, 'Browser PID must be available'

		print(f'1️⃣ Browser PID: {browser_pid}')

		# Force kill the browser process to simulate a hard crash
		print('2️⃣ Killing browser process to simulate crash...')
		try:
			os.kill(browser_pid, signal.SIGKILL)
		except ProcessLookupError:
			# Process might have already exited
			pass

		# Wait a bit for the process to die
		await asyncio.sleep(1)

		# Try to use the browser session - should raise error (TargetClosedError or RuntimeError)
		print('3️⃣ Attempting to use crashed browser session...')
		with pytest.raises(Exception) as exc_info:
			await browser_session.navigate('about:blank')

		# Verify the error indicates browser disconnection/crash
		error_msg = str(exc_info.value).lower()
		error_type = type(exc_info.value).__name__
		print(f'4️⃣ Got expected error ({error_type}): {error_msg}')
		assert (
			'closed' in error_msg or 'crash' in error_msg or 'cannot be recovered' in error_msg or 'connection lost' in error_msg
		), f'Error message should indicate browser crash/closure, got: {error_msg}'

		# Verify browser was NOT restarted (PID should still be the same dead one)
		assert browser_session.browser_pid == browser_pid or browser_session.browser_pid is None, (
			'Browser PID should not change (no restart should occur)'
		)

		print('✅ Browser crash correctly threw hard error without restarting')

	async def test_unresponsive_page_recovery_with_crashed_browser(self, browser_session: BrowserSession):
		"""Test that _recover_unresponsive_page throws error if browser has crashed"""
		# Navigate to a page first
		await browser_session.navigate('about:blank')

		# Get the browser process PID
		browser_pid = browser_session.browser_pid
		assert browser_pid is not None

		print(f'1️⃣ Browser PID: {browser_pid}')

		# Force kill the browser process
		print('2️⃣ Killing browser process...')
		try:
			os.kill(browser_pid, signal.SIGKILL)
		except ProcessLookupError:
			pass

		# Wait for process to die
		await asyncio.sleep(1)

		# Try to recover unresponsive page - should raise RuntimeError
		print('3️⃣ Attempting page recovery on crashed browser...')
		with pytest.raises(RuntimeError) as exc_info:
			await browser_session._recover_unresponsive_page('test_method')

		# Verify error indicates browser crash
		error_msg = str(exc_info.value).lower()
		print(f'4️⃣ Got expected error: {error_msg}')
		assert 'browser process has crashed' in error_msg or 'browser connection lost' in error_msg, (
			f'Error should indicate browser crash, got: {error_msg}'
		)

		print('✅ Page recovery correctly detected crashed browser and threw error')

	async def test_singleton_lock_error_throws_hard_error(self, browser_session: BrowserSession):
		"""Test that SingletonLock errors throw hard error instead of restarting"""
		# Create a conflicting user data directory scenario
		import tempfile
		from pathlib import Path

		# Create a temp directory for user data
		temp_dir = tempfile.mkdtemp(prefix='browseruse-test-')

		# Create a fake SingletonLock file to simulate conflict
		singleton_lock = Path(temp_dir) / 'SingletonLock'
		singleton_lock.write_text('fake-lock')

		# Create a session with this directory
		session = BrowserSession(browser_profile=BrowserProfile(user_data_dir=temp_dir, headless=True))

		# Modify the Chrome launch args to trigger SingletonLock error
		original_args = session.browser_profile.args.copy()
		# Add an arg that will cause Chrome to exit with SingletonLock error
		session.browser_profile.args.append('--no-sandbox')
		session.browser_profile.args.append('--disable-setuid-sandbox')

		print(f'1️⃣ Attempting to launch browser with potentially conflicting user_data_dir: {temp_dir}')

		# Note: This test is checking that IF a SingletonLock error occurs,
		# it throws a hard error instead of restarting. The actual error might
		# not always occur depending on the system state.
		try:
			await session.start()
			# If it succeeds, that's OK - we can't reliably trigger SingletonLock
			print('2️⃣ Browser launched successfully (SingletonLock error did not occur)')
			await session.kill()
		except RuntimeError as e:
			# If we get a RuntimeError with SingletonLock, that's what we want
			error_msg = str(e)
			print(f'2️⃣ Got expected error: {error_msg}')
			if 'SingletonLock' in error_msg:
				print('✅ SingletonLock error correctly threw hard error without restart')
			else:
				# Some other RuntimeError - re-raise it
				raise
		except Exception as e:
			# Unexpected error type
			print(f'2️⃣ Got unexpected error type {type(e).__name__}: {e}')
			raise
		finally:
			# Cleanup
			import shutil

			try:
				shutil.rmtree(temp_dir, ignore_errors=True)
			except Exception:
				pass


@pytest.mark.timeout(90)
async def test_multiple_sessions_with_blocking_pages(httpserver: HTTPServer):
	"""Test multiple browser sessions with blocking pages simultaneously"""
	httpserver.expect_request('/infinite-loop').respond_with_data(
		"""<html><body><script>while(true){}</script></body></html>""",
		content_type='text/html',
	)

	sessions = []
	for i in range(3):
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				keep_alive=False,
				default_navigation_timeout=6000,  # 5 second timeout
				user_data_dir=None,
			)
		)
		sessions.append(session)

	try:
		await asyncio.gather(*[s.start() for s in sessions])

		# Navigate to blocking pages - should handle without crashing
		nav_tasks = []
		for s in sessions:
			nav_tasks.append(s.navigate(httpserver.url_for('/infinite-loop'), timeout_ms=5000))

		# All navigations should complete within 5s (they may fail but shouldn't hang forever)
		results = await asyncio.gather(*nav_tasks, return_exceptions=True)

		# Check that navigations completed (with or without errors)
		for i, result in enumerate(results):
			if isinstance(result, Exception):
				print(f'Session {i} navigation failed as expected: {type(result).__name__}')

		# Sessions should still be functional, test by creating a new page and executing JS
		for i, session in enumerate(sessions):
			assert await (await session.browser_context.new_page()).evaluate('1+1') == 2, f'Session {i} page failed to execute JS'

	finally:
		# Kill sessions with exception handling to avoid cascade failures
		results = await asyncio.gather(*[s.kill() for s in sessions], return_exceptions=True)
		# Log any exceptions but don't fail the test
		for i, result in enumerate(results):
			if isinstance(result, Exception):
				print(f'Warning: Session {i} kill raised exception: {type(result).__name__}: {result}')
