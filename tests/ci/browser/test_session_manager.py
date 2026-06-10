from types import SimpleNamespace
from unittest.mock import MagicMock

from browser_use.browser.session_manager import SessionManager


def _target(target_type: str, url: str):
	return SimpleNamespace(target_type=target_type, url=url)


def test_get_all_page_targets_skips_chrome_extension_pages():
	session_manager = SessionManager(MagicMock())
	session_manager._targets = {
		'page': _target('page', 'https://example.com'),
		'tab': _target('tab', 'about:blank'),
		'extension': _target('page', 'chrome-extension://abcd/side-panel.html'),
		'iframe': _target('iframe', 'https://example.com/frame'),
	}

	assert session_manager.get_all_page_targets() == [
		session_manager._targets['page'],
		session_manager._targets['tab'],
	]
