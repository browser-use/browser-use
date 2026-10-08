import logging

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import AgentError
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.tools.service import Tools


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True, enable_default_extensions=False)
	)
	await session.start()
	yield session
	await session.kill()
	await session.event_bus.stop(clear=True, timeout=5)


@pytest.mark.parametrize('error_type', [TimeoutError, ConnectionError, AssertionError])
def test_format_error_names_an_exception_without_message(error_type):
	assert AgentError.format_error(error_type()) == error_type.__name__
	assert AgentError.format_error(error_type(), include_trace=True).startswith(f'{error_type.__name__}\nStacktrace:')
	assert AgentError.format_error(error_type('net::ERR_TUNNEL_CONNECTION_FAILED')) == 'net::ERR_TUNNEL_CONNECTION_FAILED'


@pytest.mark.parametrize(
	'action, expected_error, expected_log',
	[
		('navigate', 'Navigation failed: ConnectionError', '❌ Navigation failed: ConnectionError'),
		(
			'search',
			'Failed to search duckduckgo for "browser automation": ConnectionError',
			'Failed to search duckduckgo: ConnectionError',
		),
	],
	ids=['navigate', 'search'],
)
async def test_navigation_error_without_message_names_the_exception(
	browser_session, httpserver: HTTPServer, monkeypatch, caplog, action, expected_error, expected_log
):
	async def navigate_losing_connection(*args, **kwargs):
		raise ConnectionError()

	monkeypatch.setattr(BrowserSession, '_navigate_and_wait', navigate_losing_connection)
	tools = Tools()

	# the browser_use logger does not propagate to the root logger, so attach caplog's handler to it directly
	caplog.set_level(logging.INFO, logger='browser_use')
	browser_use_logger = logging.getLogger('browser_use')
	browser_use_logger.addHandler(caplog.handler)
	try:
		if action == 'navigate':
			result = await tools.navigate(url=httpserver.url_for('/'), new_tab=False, browser_session=browser_session)
		else:
			result = await tools.search(query='browser automation', engine='duckduckgo', browser_session=browser_session)
	finally:
		browser_use_logger.removeHandler(caplog.handler)

	assert result.error == expected_error
	assert expected_log in [record.getMessage() for record in caplog.records]
