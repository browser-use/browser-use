"""Tests for the find_text (scroll to text) action."""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.tools.service import Tools


@pytest.fixture(scope='session')
def http_server():
	"""Test HTTP server serving pages with quoted text."""
	server = HTTPServer()
	server.start()

	server.expect_request('/quotes').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Quotes Page</title></head>
		<body>
			<h1>Click "OK" to continue</h1>
			<p>She said "yes" and 'no' at the same time</p>
			<p>Normal text without quotes</p>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture
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


@pytest.fixture
def tools():
	return Tools()


async def _navigate_and_wait(tools, browser_session, url):
	await tools.navigate(url=url, new_tab=False, browser_session=browser_session)
	await asyncio.sleep(0.5)


class TestFindText:
	"""Tests for the find_text action."""

	async def test_text_with_double_quotes(self, tools, browser_session, base_url):
		"""find_text locates text containing double quotes."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/quotes')

		result = await tools.find_text(text='Click "OK" to continue', browser_session=browser_session)

		assert result.error is None
		assert 'Scrolled to text' in result.extracted_content

	async def test_text_with_mixed_quotes(self, tools, browser_session, base_url):
		"""find_text locates text containing both single and double quotes."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/quotes')

		result = await tools.find_text(text='She said "yes" and \'no\' at the same time', browser_session=browser_session)

		assert result.error is None
		assert 'Scrolled to text' in result.extracted_content

	async def test_text_without_quotes(self, tools, browser_session, base_url):
		"""find_text still works for normal text without quotes."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/quotes')

		result = await tools.find_text(text='Normal text without quotes', browser_session=browser_session)

		assert result.error is None
		assert 'Scrolled to text' in result.extracted_content

	async def test_text_not_found(self, tools, browser_session, base_url):
		"""find_text returns not-found message for absent text."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/quotes')

		result = await tools.find_text(text='nonexistent text', browser_session=browser_session)

		assert result.error is None
		assert 'not found' in result.extracted_content
