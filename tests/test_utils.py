import pytest

from browser_use.utils import (
	collect_sensitive_data_values,
	has_url_negation,
	is_placeholder_url,
	sanitize_url_candidate,
)


def test_is_placeholder_url():
	# Mock placeholder hostnames (all-x labels) must be detected
	assert is_placeholder_url('https://XXX.XX') is True
	assert is_placeholder_url('XXX.XX') is True
	# Real hostnames must not be flagged
	assert is_placeholder_url('https://example.com') is False
	assert is_placeholder_url('not-a-url') is False
	# Empty / missing hostname is not a placeholder
	assert is_placeholder_url('') is False


def test_sanitize_url_candidate():
	# Trailing prose punctuation is stripped
	assert sanitize_url_candidate('https://example.com/a. ') == 'https://example.com/a'
	# Escaped newlines from benchmark prose are truncated
	assert sanitize_url_candidate('https://x.com/a\\nb') == 'https://x.com/a'
	# A closing bracket the URL itself opened is kept
	assert sanitize_url_candidate('(see https://x.com/a)') == '(see https://x.com/a)'


def test_has_url_negation():
	assert has_url_negation("don't navigate") is True
	assert has_url_negation('never go there') is True
	assert has_url_negation('please visit the site') is False


def test_collect_sensitive_data_values():
	# None and empty inputs yield empty mapping
	assert collect_sensitive_data_values(None) == {}
	assert collect_sensitive_data_values({'a': ''}) == {}
	# Flat legacy form
	assert collect_sensitive_data_values({'a': '1'}) == {'a': '1'}
	# Domain-scoped form is flattened
	assert collect_sensitive_data_values({'d': {'k': 'v'}}) == {'k': 'v'}
