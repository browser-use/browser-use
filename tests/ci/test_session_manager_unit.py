"""Unit tests for SessionManager."""

from __future__ import annotations

from unittest.mock import MagicMock

from browser_use.browser.session import Target


class TestGetAllPageTargets:
    """Tests for SessionManager.get_all_page_targets()."""

    @staticmethod
    def _make_manager(targets: list[Target]) -> object:
        """Build a SessionManager with given targets, no CDP needed."""
        from browser_use.browser.session_manager import SessionManager

        mock_session = MagicMock()
        mock_session.logger = MagicMock()
        manager = SessionManager(mock_session)
        manager._targets = {t.target_id: t for t in targets}
        return manager

    def test_returns_only_page_and_tab_targets(self):
        """Only 'page' and 'tab' target types are returned."""

        targets = [
            Target(target_id='p1', target_type='page', url='https://example.com'),
            Target(target_id='t1', target_type='tab', url='https://example.org'),
            Target(target_id='i1', target_type='iframe', url='https://example.net'),
            Target(target_id='w1', target_type='worker', url=''),
        ]
        manager = self._make_manager(targets)
        results = manager.get_all_page_targets()
        assert len(results) == 2
        assert {r.target_id for r in results} == {'p1', 't1'}

    def test_filters_out_chrome_extension_urls(self):
        """chrome-extension:// URLs are excluded from page targets."""

        targets = [
            Target(target_id='p1', target_type='page', url='https://example.com'),
            Target(target_id='p2', target_type='page', url='chrome-extension://abc123/popup.html'),
            Target(target_id='p3', target_type='page', url='chrome-extension://def456/options.html'),
            Target(target_id='t1', target_type='tab', url='chrome-extension://xyz/tab.html'),
            Target(target_id='t2', target_type='tab', url='https://app.example.com'),
        ]
        manager = self._make_manager(targets)
        results = manager.get_all_page_targets()
        assert len(results) == 2
        assert {r.target_id for r in results} == {'p1', 't2'}

    def test_returns_normal_urls(self):
        """Normal http/https/file URLs are returned."""
        targets = [
            Target(target_id='p1', target_type='page', url='https://example.com'),
            Target(target_id='p2', target_type='page', url='http://localhost:8080'),
            Target(target_id='p3', target_type='page', url='file:///home/user/page.html'),
            Target(target_id='p4', target_type='page', url='about:blank'),
        ]
        manager = self._make_manager(targets)
        results = manager.get_all_page_targets()
        assert len(results) == 4
        assert {r.url for r in results} == {
            'https://example.com',
            'http://localhost:8080',
            'file:///home/user/page.html',
            'about:blank',
        }

    def test_returns_empty_list_when_no_targets(self):
        """Empty list is returned when there are no targets."""
        manager = self._make_manager([])
        assert manager.get_all_page_targets() == []

    def test_returns_empty_list_when_only_non_page_targets(self):
        """Empty list when targets exist but none are 'page' or 'tab'."""
        targets = [
            Target(target_id='i1', target_type='iframe', url='https://example.com'),
            Target(target_id='w1', target_type='worker', url=''),
            Target(target_id='b1', target_type='browser', url=''),
        ]
        manager = self._make_manager(targets)
        assert manager.get_all_page_targets() == []

    def test_chrome_extension_with_slash_slash_only(self):
        """URLs that START with chrome-extension:// are filtered; others are kept."""
        targets = [
            Target(target_id='p1', target_type='page', url='not-chrome-extension://example.com'),
            Target(target_id='p2', target_type='page', url='chrome-extension://abc/'),
            Target(target_id='p3', target_type='page', url='HTTP://EXAMPLE.COM'),
        ]
        manager = self._make_manager(targets)
        results = manager.get_all_page_targets()
        # 'not-chrome-extension://' does NOT start with 'chrome-extension://'
        assert {r.target_id for r in results} == {'p1', 'p3'}

    def test_include_chrome_extensions_true(self):
        """When include_chrome_extensions=True, chrome-extension URLs are included."""
        targets = [
            Target(target_id='p1', target_type='page', url='https://example.com'),
            Target(target_id='p2', target_type='page', url='chrome-extension://abc/popup.html'),
        ]
        manager = self._make_manager(targets)
        results = manager.get_all_page_targets(include_chrome_extensions=True)
        assert {r.target_id for r in results} == {'p1', 'p2'}
