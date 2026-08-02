"""Tests for the _log_pretty_url helper in browser_use.utils.

The helper is documented to strip the protocol and a leading ``www.`` *prefix*
only. Earlier it used ``str.replace`` which removed those substrings anywhere in
the URL, mangling domains like ``awwww.com`` and URLs whose query/path contained
``http(s)://`` or ``www.``.
"""

from browser_use.utils import _log_pretty_url


def test_strips_leading_scheme_and_www():
	assert _log_pretty_url('https://www.example.com', max_len=None) == 'example.com'
	assert _log_pretty_url('http://example.com', max_len=None) == 'example.com'


def test_does_not_strip_www_inside_domain():
	# "awwww.com" contains the substring "www." but it is not a prefix.
	assert _log_pretty_url('https://awwww.com', max_len=None) == 'awwww.com'


def test_does_not_corrupt_embedded_scheme_in_query():
	url = 'https://example.com/r?u=https://other.com'
	assert _log_pretty_url(url, max_len=None) == 'example.com/r?u=https://other.com'


def test_does_not_strip_www_inside_path():
	url = 'https://site.com/www.assets/img'
	assert _log_pretty_url(url, max_len=None) == 'site.com/www.assets/img'


def test_truncation_still_applies():
	long_url = 'https://example.com/' + 'a' * 100
	out = _log_pretty_url(long_url, max_len=22)
	assert out == 'example.com/' + 'a' * 10 + '…'
