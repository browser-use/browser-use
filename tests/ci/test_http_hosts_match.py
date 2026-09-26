"""Same-host checks for navigation timeout must not crash on malformed URLs."""

from browser_use.utils import http_hosts_match


def test_malformed_http_scheme_does_not_raise():
	assert http_hosts_match('http', 'https://example.com/foo') is False
	assert http_hosts_match('https', 'https://example.com/foo') is False


def test_same_host_is_true_across_http_and_https():
	assert http_hosts_match('https://example.com/a', 'http://example.com/b') is True


def test_different_hosts_are_false():
	assert http_hosts_match('https://a.example/x', 'https://b.example/x') is False


def test_non_http_urls_are_false():
	assert http_hosts_match('about:blank', 'https://example.com') is False
	assert http_hosts_match('https://example.com', 'chrome://newtab') is False
