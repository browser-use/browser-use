from types import SimpleNamespace
from typing import cast

from browser_use.browser.session import BrowserSession, Target
from browser_use.browser.session_manager import SessionManager


def _build_session_manager_with_targets(targets: dict[str, Target]) -> SessionManager:
	logger = SimpleNamespace(
		info=lambda *args, **kwargs: None,
		warning=lambda *args, **kwargs: None,
		error=lambda *args, **kwargs: None,
		debug=lambda *args, **kwargs: None,
	)
	browser_session = cast(BrowserSession, SimpleNamespace(logger=logger))
	session_manager = SessionManager(browser_session)
	session_manager._targets = targets
	return session_manager


def test_get_all_page_targets_excludes_chrome_extension_by_default():
	session_manager = _build_session_manager_with_targets(
		{
			'normal': Target(
				target_id='normal',
				target_type='page',
				url='https://example.com',
				title='Example',
			),
			'extension': Target(
				target_id='extension',
				target_type='page',
				url='chrome-extension://abcdef/panel.html',
				title='Extension',
			),
			'tab': Target(
				target_id='tab',
				target_type='tab',
				url='https://news.ycombinator.com',
				title='HN',
			),
			'worker': Target(
				target_id='worker',
				target_type='worker',
				url='https://example.com/worker.js',
				title='Worker',
			),
		}
	)

	target_urls = [target.url for target in session_manager.get_all_page_targets()]

	assert 'https://example.com' in target_urls
	assert 'https://news.ycombinator.com' in target_urls
	assert 'chrome-extension://abcdef/panel.html' not in target_urls
	assert 'https://example.com/worker.js' not in target_urls


def test_get_all_page_targets_can_include_chrome_extension_targets():
	session_manager = _build_session_manager_with_targets(
		{
			'extension': Target(
				target_id='extension',
				target_type='page',
				url='chrome-extension://abcdef/panel.html',
				title='Extension',
			),
		}
	)

	target_urls = [target.url for target in session_manager.get_all_page_targets(include_chrome_extensions=True)]

	assert target_urls == ['chrome-extension://abcdef/panel.html']
