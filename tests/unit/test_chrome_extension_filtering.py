"""Tests for chrome-extension target filtering."""
import pytest

from browser_use.browser.session import Target


class MockSessionManager:
    """Minimal mock of SessionManager for testing."""
    
    def __init__(self, targets: dict):
        self._targets = targets
    
    def get_all_page_targets(self, exclude_chrome_extensions: bool = True) -> list:
        """Get all page/tab targets using owned data.

		Args:
			exclude_chrome_extensions: If True, exclude chrome-extension:// URLs from results.
				Defaults to True to prevent agent focus from switching to extension pages.

		Returns:
			List of Target objects for all page/tab targets
		"""
        page_targets = []
        for target in self._targets.values():
            if target.target_type in ('page', 'tab'):
                # Skip chrome-extension URLs to prevent agent focus hijacking
                if exclude_chrome_extensions and target.url.startswith('chrome-extension://'):
                    continue
                page_targets.append(target)
        return page_targets


class TestChromeExtensionFiltering:
    """Tests for excluding chrome-extension targets from agent focus."""

    def test_get_all_page_targets_excludes_chrome_extensions_by_default(self):
        """Test that chrome-extension URLs are excluded by default."""
        # Create mock targets
        mock_targets = {
            'target1': Target(
                target_id='target1',
                target_type='page',
                url='https://example.com',
                title='Example',
            ),
            'target2': Target(
                target_id='target2',
                target_type='page',
                url='chrome-extension://abcdef/options.html',
                title='Extension Options',
            ),
            'target3': Target(
                target_id='target3',
                target_type='page',
                url='https://google.com',
                title='Google',
            ),
        }
        
        manager = MockSessionManager(mock_targets)
        
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
        mock_targets = {
            'target1': Target(
                target_id='target1',
                target_type='page',
                url='https://example.com',
                title='Example',
            ),
            'target2': Target(
                target_id='target2',
                target_type='page',
                url='chrome-extension://abcdef/options.html',
                title='Extension Options',
            ),
        }
        
        manager = MockSessionManager(mock_targets)
        
        # Get page targets without exclusion
        result = manager.get_all_page_targets(exclude_chrome_extensions=False)
        
        # Should include all targets
        assert len(result) == 2
        urls = [t.url for t in result]
        assert 'chrome-extension://abcdef/options.html' in urls

    def test_get_all_page_targets_excludes_service_workers(self):
        """Test that service_worker targets are not included."""
        mock_targets = {
            'target1': Target(
                target_id='target1',
                target_type='page',
                url='https://example.com',
                title='Example',
            ),
            'target2': Target(
                target_id='target2',
                target_type='service_worker',
                url='chrome-extension://abcdef/background.js',
                title='Background Worker',
            ),
        }
        
        manager = MockSessionManager(mock_targets)
        
        result = manager.get_all_page_targets()
        
        # Should only include page targets, not service workers
        assert len(result) == 1
        assert result[0].url == 'https://example.com'
