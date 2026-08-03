"""Regression coverage for redact_sensitive_string cascade leaks (issue #5248).

redact_sensitive_string used to replace secrets one at a time by scanning the
*already partially redacted* string on every pass. Since the placeholder text
`<secret>{key}</secret>` itself contains the literal word "secret", any later
secret whose value contained the substring "secret" would be re-matched
inside a placeholder that had just been inserted, corrupting it into a
malformed / nested tag and leaking structure.
"""

from browser_use.utils import redact_sensitive_string


def test_redact_sensitive_string_does_not_corrupt_placeholder_with_secret_substring():
	sensitive = {
		'api_key': 'secret-token-abc',
		'db_pass': 'secret',
	}
	value = 'key=secret-token-abc pass=secret'

	result = redact_sensitive_string(value, sensitive)

	assert result == 'key=<secret>api_key</secret> pass=<secret>db_pass</secret>'
	# No nested/corrupted tags left behind
	assert '</sec<secret>' not in result


def test_redact_sensitive_string_longest_match_wins_for_overlapping_secrets():
	sensitive = {'short': 'ab', 'long': 'abcdef'}
	value = 'value=abcdef'

	result = redact_sensitive_string(value, sensitive)

	assert result == 'value=<secret>long</secret>'


def test_redact_sensitive_string_leaves_unmatched_text_untouched():
	sensitive = {'api_key': 'abc123'}
	value = 'nothing sensitive here'

	assert redact_sensitive_string(value, sensitive) == value


def test_redact_sensitive_string_ignores_empty_secret_values():
	sensitive = {'unset': '', 'api_key': 'abc123'}
	value = 'key=abc123'

	result = redact_sensitive_string(value, sensitive)

	assert result == 'key=<secret>api_key</secret>'
