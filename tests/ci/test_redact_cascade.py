"""Tests for redact_sensitive_string to ensure no cascading/corruption."""

from browser_use.utils import collect_sensitive_data_values, redact_sensitive_string


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


def test_cross_domain_same_key_collision():
	"""Every value of a placeholder scoped to multiple domains gets redacted.

	Regression test for issue #5592: collect_sensitive_data_values used to keep
	only the last domain's value when several domains shared a placeholder
	name, so the dropped values leaked verbatim into LLM-visible history.
	"""
	sensitive = {
		'github.com': {'password': 'gh-login-aaa'},
		'gitlab.com': {'password': 'gl-login-bbb'},
	}
	values = collect_sensitive_data_values(sensitive)
	result = redact_sensitive_string('sign in with gh-login-aaa and gl-login-bbb', values)
	assert result == 'sign in with <secret>password</secret> and <secret>password</secret>'


def test_collect_same_key_same_value_deduplicated():
	"""Identical values under a colliding key collapse to a single entry."""
	sensitive = {
		'a.com': {'token': 'shared-token'},
		'b.com': {'token': 'shared-token'},
	}
	assert collect_sensitive_data_values(sensitive) == {'token': 'shared-token'}


def test_legacy_and_domain_key_collision():
	"""A legacy global value and a domain-scoped value sharing a key are both redacted."""
	sensitive = {'password': 'first-login', 'example.com': {'password': 'second-login'}}
	values = collect_sensitive_data_values(sensitive)
	result = redact_sensitive_string('first-login second-login', values)
	assert result == '<secret>password</secret> <secret>password</secret>'


def test_empty_secret_value_is_ignored():
	"""An empty secret value must not create an empty regex alternative.

	An empty alternative in the alternation matches at every position and
	corrupts the whole output with placeholder tags.
	"""
	assert redact_sensitive_string('abc', {'k': ''}) == 'abc'
