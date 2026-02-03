"""
Test DomService collect_accessibility_tree flag.

Verifies that:
1. DomService respects collect_accessibility_tree=False (returns empty AX tree)
2. BrowserProfile accepts collect_accessibility_tree parameter
"""

from unittest.mock import MagicMock

from browser_use.browser.profile import BrowserProfile
from browser_use.dom.service import DomService


class TestDomServiceCollectAccessibilityTree:
	"""Test DomService accessibility tree collection flag."""

	def test_browser_profile_accepts_collect_accessibility_tree(self):
		"""BrowserProfile accepts collect_accessibility_tree parameter."""
		profile = BrowserProfile(collect_accessibility_tree=False)
		assert profile.collect_accessibility_tree is False

		profile_default = BrowserProfile()
		assert profile_default.collect_accessibility_tree is True

	def test_dom_service_respects_collect_accessibility_tree_false(self):
		"""DomService with collect_accessibility_tree=False has flag set."""
		mock_session = MagicMock()
		dom = DomService(browser_session=mock_session, collect_accessibility_tree=False)
		assert dom.collect_accessibility_tree is False

	async def test_resolve_ax_tree_returns_empty_when_disabled(self):
		"""When collect_accessibility_tree=False, _resolve_ax_tree returns empty nodes without CDP call."""
		mock_session = MagicMock()
		mock_session.session_manager = None
		dom = DomService(browser_session=mock_session, collect_accessibility_tree=False)
		result = await dom._resolve_ax_tree(target_id='test-target-id')
		assert result == {'nodes': []}
		mock_session.get_or_create_cdp_session.assert_not_called()
