"""Resolve link hrefs against the current page URL for new-tab navigation."""

from browser_use.utils import resolve_link_href

CURRENT = 'https://example.com/dir/page.html'


def test_absolute_http_href_is_unchanged():
	assert resolve_link_href(CURRENT, 'https://other.com/z') == 'https://other.com/z'


def test_path_absolute_href_uses_current_origin():
	assert resolve_link_href(CURRENT, '/foo') == 'https://example.com/foo'


def test_protocol_relative_href_keeps_the_linked_host():
	assert resolve_link_href(CURRENT, '//cdn.example.net/x') == 'https://cdn.example.net/x'


def test_path_relative_href_is_joined_onto_the_current_directory():
	assert resolve_link_href(CURRENT, 'next.html') == 'https://example.com/dir/next.html'


def test_query_only_href_replaces_the_current_query():
	assert resolve_link_href(CURRENT, '?q=1') == 'https://example.com/dir/page.html?q=1'


def test_relative_href_without_a_page_url_is_not_resolved():
	assert resolve_link_href('about:blank', 'next.html') is None
	assert resolve_link_href('about:blank', '/foo') is None
	assert resolve_link_href('', '/foo') is None


def test_absolute_href_without_a_page_url_is_kept():
	assert resolve_link_href('about:blank', 'https://other.com/z') == 'https://other.com/z'
