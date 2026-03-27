"""Tests for SessionManager - specifically get_all_page_targets() filtering."""

from unittest.mock import MagicMock

import pytest

from browser_use.browser.session_manager import SessionManager


def _make_target(target_id: str, target_type: str, url: str) -> MagicMock:
	"""Factory: build a mock Target with the given fields."""
	t = MagicMock()
	t.target_id = target_id
	t.target_type = target_type
	t.url = url
	return t


class TestGetAllPageTargets:
	"""Tests for SessionManager.get_all_page_targets()."""

	@pytest.fixture
	def session_manager(self) -> SessionManager:
		"""Build a SessionManager with an empty target dict."""
		browser_session = MagicMock()
		browser_session.logger = MagicMock()
		sm = SessionManager.__new__(SessionManager)
		sm.browser_session = browser_session
		sm.logger = browser_session.logger
		sm._targets = {}
		return sm

	def test_returns_only_page_and_tab_targets(self, session_manager: SessionManager) -> None:
		"""Only targets with type 'page' or 'tab' are returned."""
		session_manager._targets = {
			'id-page': _make_target('id-page', 'page', 'https://example.com'),
			'id-tab': _make_target('id-tab', 'tab', 'https://example.com/tab'),
			'id-iframe': _make_target('id-iframe', 'iframe', 'https://example.com/frame'),
			'id-worker': _make_target('id-worker', 'worker', ''),
		}
		result = session_manager.get_all_page_targets()
		target_ids = {t.target_id for t in result}
		assert target_ids == {'id-page', 'id-tab'}

	def test_filters_chrome_extension_urls(self, session_manager: SessionManager) -> None:
		"""chrome-extension:// URLs are excluded even for page/tab targets."""
		session_manager._targets = {
			'normal-page': _make_target('normal-page', 'page', 'https://example.com'),
			'extension-page': _make_target(
				'extension-page', 'page', 'chrome-extension://abcdefghijklmnop/page.html'
			),
			'extension-tab': _make_target(
				'extension-tab', 'tab', 'chrome-extension://version/'
			),
			'normal-tab': _make_target('normal-tab', 'tab', 'https://example.com/tab'),
		}
		result = session_manager.get_all_page_targets()
		target_ids = {t.target_id for t in result}
		assert target_ids == {'normal-page', 'normal-tab'}
		assert 'extension-page' not in target_ids
		assert 'extension-tab' not in target_ids

	def test_handles_none_url_gracefully(self, session_manager: SessionManager) -> None:
		"""Targets with url=None do not raise AttributeError."""
		session_manager._targets = {
			'null-url': _make_target('null-url', 'page', None),  # type: ignore[arg-type]
			'normal-page': _make_target('normal-page', 'page', 'https://example.com'),
		}
		# Must not raise AttributeError
		result = session_manager.get_all_page_targets()
		target_ids = {t.target_id for t in result}
		assert target_ids == {'normal-page'}

	def test_include_chrome_extensions_true(self, session_manager: SessionManager) -> None:
		"""When include_chrome_extensions=True, chrome-extension:// URLs are included."""
		session_manager._targets = {
			'normal-page': _make_target('normal-page', 'page', 'https://example.com'),
			'extension-page': _make_target(
				'extension-page', 'page', 'chrome-extension://abcdefghijklmnop/page.html'
			),
		}
		result = session_manager.get_all_page_targets(include_chrome_extensions=True)
		target_ids = {t.target_id for t in result}
		assert target_ids == {'normal-page', 'extension-page'}
