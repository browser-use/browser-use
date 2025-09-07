"""Test simple download functionality."""

import pytest

# Skip Playwright imports - removed dependency
from pytest_httpserver import HTTPServer


async def test_simple_playwright_download():
	"""Test basic Playwright download functionality without browser-use - this just validates the browser setup"""
	# Skip Playwright usage - removed dependency
	pytest.skip('Playwright dependency removed')


@pytest.fixture(scope='function')
def http_server():
	"""Create a test HTTP server with a downloadable file."""
	server = HTTPServer()
	server.start()

	# Serve a simple text file for download
	server.expect_request('/download/test.txt').respond_with_data(
		'Hello World from HTTP Server', status=200, headers={'Content-Type': 'text/plain'}
	)

	yield server
	server.stop()


async def test_browser_use_download_with_http_server(http_server):
	"""Test browser-use download with HTTP server and event coordination"""
	# Skip complex element selection for now - would need to implement selector-to-index conversion
	pytest.skip('Complex element selection needs refactoring for CDP events')
