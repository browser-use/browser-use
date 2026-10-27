"""Tests for redact_sensitive_string to ensure no cascading/corruption."""

from browser_use.utils import redact_sensitive_string


def test_normal_redaction():
	"""Basic redaction replaces secret values with tagged placeholders."""
	sensitive = {'password': 'hunter2'}
	result = redact_sensitive_string('my password is hunter2', sensitive)
	assert result == 'my password is <secret>password</secret>'


def test_cascade_substring_secret():
	"""A shorter secret that is a substring of a placeholder tag must not corrupt output.

	Regression test for issue #5135.
	"""
	sensitive = {'password': 'supersecret', 'type': 'secret'}
	result = redact_sensitive_string('supersecret', sensitive)
	# 'supersecret' should be replaced first (longest), and 'secret' must NOT
	# then corrupt the '<secret>password</secret>' tag.
	assert result == '<secret>password</secret>'


def test_multiple_overlapping_secrets():
	"""Multiple secrets where one is a prefix/substring of another."""
	sensitive = {'short': 'abc', 'long': 'abcdef'}
	result = redact_sensitive_string('abcdef and abc', sensitive)
	assert result == '<secret>long</secret> and <secret>short</secret>'


def test_empty_secrets_returns_original():
	"""An empty sensitive_values dict returns the original string unchanged."""
	assert redact_sensitive_string('nothing to redact', {}) == 'nothing to redact'


def test_secret_value_matches_tag_syntax():
	"""A secret whose value looks like XML tag syntax is handled correctly."""
	sensitive = {'key': '<secret>'}
	result = redact_sensitive_string('the value is <secret>', sensitive)
	assert result == 'the value is <secret>key</secret>'


def test_multiple_occurrences():
	"""All occurrences of the same secret are replaced."""
	sensitive = {'tok': 'xyz'}
	result = redact_sensitive_string('xyz-xyz-xyz', sensitive)
	assert result == '<secret>tok</secret>-<secret>tok</secret>-<secret>tok</secret>'
