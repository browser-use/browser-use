"""Tests for chrome-extension target filtering."""
from unittest.mock import MagicMock

import pytest

from browser_use.browser.session import BrowserSession, Target
from browser_use.browser.session_manager import SessionManager


class TestChromeExtensionFiltering:
    """Tests for excluding chrome-extension targets from agent focus."""

    def test_get_all_page_targets_excludes_chrome_extensions_by_default(self):
        """Test that chrome-extension URLs are excluded by default."""
        # Create mock BrowserSession
        mock_browser_session = MagicMock(spec=BrowserSession)
        mock_browser_session.logger = MagicMock()

        # Create SessionManager with mock
        manager = SessionManager(mock_browser_session)

        # Create mock targets
        target1 = Target(
            target_id='target1',
            target_type='page',
            url='https://example.com',
            title='Example',
        )
        target2 = Target(
            target_id='target2',
            target_type='page',
            url='chrome-extension://abcdef/options.html',
            title='Extension Options',
        )
        target3 = Target(
            target_id='target3',
            target_type='page',
            url='https://google.com',
            title='Google',
        )

        # Inject targets into SessionManager's internal state
        manager._targets = {
            'target1': target1,
            'target2': target2,
            'target3': target3,
        }

        # Get page targets with default exclusion
        result = manager.get_all_page_targets()

        # Should only include non-extension targets
        assert len(result) == 2
        urls = [t.url for t in result]
        assert 'https://example.com' in urls
        assert 'https://google.com' in urls
        assert 'chrome-extension://abcdef/options.html' not in urls

    def test_get_all_page_targets_includes_chrome_extensions_when_disabled(self):
        """Test that chrome-extension URLs can be included if requested."""
        mock_browser_session = MagicMock(spec=BrowserSession)
        mock_browser_session.logger = MagicMock()

        manager = SessionManager(mock_browser_session)

        target1 = Target(
            target_id='target1',
            target_type='page',
            url='https://example.com',
            title='Example',
        )
        target2 = Target(
            target_id='target2',
            target_type='page',
            url='chrome-extension://abcdef/options.html',
            title='Extension Options',
        )

        manager._targets = {
            'target1': target1,
            'target2': target2,
        }

        # Get page targets without exclusion
        result = manager.get_all_page_targets(exclude_chrome_extensions=False)

        # Should include all targets
        assert len(result) == 2
        urls = [t.url for t in result]
        assert 'chrome-extension://abcdef/options.html' in urls

    def test_get_all_page_targets_excludes_service_workers(self):
        """Test that service_worker targets are not included (type filter, not URL filter)."""
        mock_browser_session = MagicMock(spec=BrowserSession)
        mock_browser_session.logger = MagicMock()

        manager = SessionManager(mock_browser_session)

        target1 = Target(
            target_id='target1',
            target_type='page',
            url='https://example.com',
            title='Example',
        )
        target2 = Target(
            target_id='target2',
            target_type='service_worker',
            url='chrome-extension://abcdef/background.js',
            title='Background Worker',
        )

        manager._targets = {
            'target1': target1,
            'target2': target2,
        }

        result = manager.get_all_page_targets()

        # Should only include page targets, not service workers
        assert len(result) == 1
        assert result[0].url == 'https://example.com'

    def test_get_all_page_targets_empty_targets(self):
        """Test that empty targets list is handled correctly."""
        mock_browser_session = MagicMock(spec=BrowserSession)
        mock_browser_session.logger = MagicMock()

        manager = SessionManager(mock_browser_session)
        manager._targets = {}

        result = manager.get_all_page_targets()

        assert result == []

    def test_get_all_page_targets_only_extension_targets(self):
        """Test behavior when only extension targets exist."""
        mock_browser_session = MagicMock(spec=BrowserSession)
        mock_browser_session.logger = MagicMock()

        manager = SessionManager(mock_browser_session)

        target1 = Target(
            target_id='target1',
            target_type='page',
            url='chrome-extension://abc/options.html',
            title='Options',
        )
        target2 = Target(
            target_id='target2',
            target_type='page',
            url='chrome-extension://def/popup.html',
            title='Popup',
        )

        manager._targets = {
            'target1': target1,
            'target2': target2,
        }

        # Default: should exclude all extension targets
        result = manager.get_all_page_targets()
        assert result == []

        # With exclusion disabled: should include all
        result_with_ext = manager.get_all_page_targets(exclude_chrome_extensions=False)
        assert len(result_with_ext) == 2
