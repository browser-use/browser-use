"""Test that input_text fires a real blur (element.blur()) after typing.

Some JS frameworks and custom contenteditable widgets only commit their
field value when focus actually leaves the element — not when a synthetic
blur event is dispatched.  element.blur() does both: moves focus AND fires
the native blur/focusout sequence.

Tests cover:
- Contenteditable span that commits value only on real blur (not synthetic)
- Standard input that commits value on blur
- Blur fires focusout so parent listeners also run
"""

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools


@pytest.fixture(scope='session')
def http_server():
	server = HTTPServer()
	server.start()

	# Page: contenteditable span that only commits on real blur (element.blur())
	# dispatchEvent(new Event('blur')) would NOT trigger this because it doesn't
	# actually move focus, so document.activeElement stays on the span.
	server.expect_request('/commit-on-blur').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Commit on Blur Test</title></head>
		<body>
			<span
				id="editor"
				contenteditable="true"
				style="border:1px solid #ccc; padding:4px; display:inline-block; min-width:200px;"
			></span>
			<div id="committed"></div>
			<script>
				const editor = document.getElementById('editor');
				const committed = document.getElementById('committed');

				// Only commit when focus genuinely leaves the element.
				// This is the exact pattern that breaks when only a synthetic
				// blur event is dispatched instead of calling element.blur().
				editor.addEventListener('blur', function() {
					if (document.activeElement !== editor) {
						committed.textContent = editor.textContent;
					}
				});
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Page: plain input that commits on focusout (bubbling version of blur)
	server.expect_request('/commit-on-focusout').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Commit on Focusout Test</title></head>
		<body>
			<input id="field" type="text" />
			<div id="committed"></div>
			<script>
				// focusout bubbles; only fires on real focus change, not synthetic blur
				document.addEventListener('focusout', function(e) {
					if (e.target.id === 'field') {
						document.getElementById('committed').textContent = e.target.value;
					}
				});
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	yield server
	server.clear()
	if server.is_running():
		server.stop()


@pytest.fixture
async def browser_session():
	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)
	await session.start()
	yield session
	await session.stop()


@pytest.fixture
async def tools(browser_session):
	return Tools(browser_session)


async def test_contenteditable_commits_value_on_blur(http_server, tools, browser_session):
	"""Contenteditable span should commit its value after input because
	element.blur() genuinely moves focus, triggering the blur listener."""
	url = f'http://localhost:{http_server.port}/commit-on-blur'
	await browser_session.navigate_to(url)

	# Type into the contenteditable span (index 0)
	await tools.input(index=0, text='hello world', browser_session=browser_session)

	# The #committed div should now contain the typed text because blur fired
	page = await browser_session.get_current_page()
	committed = await page.evaluate("document.getElementById('committed').textContent")
	assert committed == 'hello world', (
		f'Expected "hello world" committed after blur, got "{committed}". element.blur() may not have been called after typing.'
	)


async def test_input_commits_value_on_focusout(http_server, tools, browser_session):
	"""Standard input should commit its value via focusout after input."""
	url = f'http://localhost:{http_server.port}/commit-on-focusout'
	await browser_session.navigate_to(url)

	await tools.input(index=0, text='test value', browser_session=browser_session)

	page = await browser_session.get_current_page()
	committed = await page.evaluate("document.getElementById('committed').textContent")
	assert committed == 'test value', f'Expected "test value" committed via focusout, got "{committed}".'
