from unittest.mock import MagicMock

from browser_use.actor.page import Page


def test_page_client_delegates_to_active_browser_session_cdp_client():
	mock_session = MagicMock()
	client_1 = MagicMock()
	client_2 = MagicMock()
	mock_session.cdp_client = client_1

	page = Page(mock_session, target_id='target-1', session_id='session-1')
	assert page._client is client_1

	# Browser reconnect updates session.cdp_client
	mock_session.cdp_client = client_2
	assert page._client is client_2

	# Explicit client override
	override = MagicMock()
	page._client = override
	assert page._client is override

	# Reset override restores delegation to live session
	page._client = None
	assert page._client is client_2
