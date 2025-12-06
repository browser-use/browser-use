from typing import cast

import pytest

from browser_use.browser.views import BrowserStateSummary
from browser_use.dom.views import EnhancedDOMTreeNode
from browser_use.tools.assertion_helpers import (
	assert_text_absent,
	assert_text_present,
	assert_title,
	assert_url,
	is_visible_node,
)


class DummyBounds:
	def __init__(self, width: int, height: int):
		self.width = width
		self.height = height


class DummySnapshot:
	def __init__(self, bounds: DummyBounds | None):
		self.bounds = bounds


class DummyNode:
	def __init__(self, is_visible=True, bounds: DummyBounds | None = None):
		self.is_visible = is_visible
		self.snapshot_node = DummySnapshot(bounds) if bounds else None
		self.absolute_position = bounds


class DummySummary:
	def __init__(self, url: str, title: str):
		self.url = url
		self.title = title


def test_assert_text_present_partial_case_insensitive():
	page = 'Welcome SUBMISSION successful'
	assert assert_text_present(page, 'submission', case_sensitive=False, partial=True)
	assert not assert_text_present(page, 'submission', case_sensitive=True, partial=True)


def test_assert_text_absent():
	page = 'Hello world'
	assert assert_text_absent(page, 'Bye', case_sensitive=False)
	assert not assert_text_absent(page, 'Hello', case_sensitive=False)


@pytest.mark.parametrize(
	'mode,expected,actual,ok',
	[
		('equals', 'https://a.com/x', 'https://a.com/x', True),
		('equals', 'https://a.com/x', 'https://a.com/y', False),
		('prefix', 'https://a.com', 'https://a.com/x', True),
		('contains', 'a.com/x', 'https://a.com/x?y=1', True),
		('regex', r'a\\.com/\\w+', 'https://a.com/x', True),
	],
)
def test_assert_url(mode, expected, actual, ok):
	summary = DummySummary(url=actual, title='')
	assert assert_url(cast(BrowserStateSummary, summary), expected, mode) is ok


def test_assert_title_modes():
	summary = DummySummary(url='', title='Dashboard - Example')
	assert assert_title(cast(BrowserStateSummary, summary), 'Dashboard - Example', 'equals')
	assert assert_title(cast(BrowserStateSummary, summary), 'Dashboard', 'prefix')
	assert assert_title(cast(BrowserStateSummary, summary), 'Example', 'contains')
	assert assert_title(cast(BrowserStateSummary, summary), r'Dash.*Example', 'regex')


def test_is_visible_node():
	visible = DummyNode(is_visible=True, bounds=DummyBounds(10, 5))
	hidden = DummyNode(is_visible=False, bounds=DummyBounds(10, 5))
	zero_bounds = DummyNode(is_visible=True, bounds=DummyBounds(0, 0))

	assert is_visible_node(cast(EnhancedDOMTreeNode, visible))
	assert not is_visible_node(cast(EnhancedDOMTreeNode, hidden))
	assert not is_visible_node(cast(EnhancedDOMTreeNode, zero_bounds))
	assert not is_visible_node(None)
