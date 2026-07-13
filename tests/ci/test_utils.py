from browser_use.utils import redact_sensitive_string


def test_redact_sensitive_string_preserves_empty_string_value():
	value = 'leaked supersecret token'
	sensitive_values = {
		'password': 'supersecret',
		'type': 'secret',
	}

	assert redact_sensitive_string(value, sensitive_values) == 'leaked <secret>password</secret> token'


def test_redact_sensitive_string_preserves_shorter_matches():
	value = 'open nested secret secret code'
	sensitive_values = {
		'outer': 'secret',
		'inner': 'sec',
	}

	# `sec` shouldn't corrupt already-redacted `<secret>outer</secret>` fragments
	assert redact_sensitive_string(value, sensitive_values) == 'open nested <secret>outer</secret> <secret>outer</secret> code'
