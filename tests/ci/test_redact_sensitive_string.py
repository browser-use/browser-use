from browser_use.utils import redact_sensitive_string


def test_redact_sensitive_string_cascade():
	"""
	Verify that sensitive values containing the word "secret" do not cause
	cascade re-redaction of already generated <secret>...</secret> tags.
	"""
	sensitive_values = {
		'password': 'supersecret',
		'key': 'secret',
	}
	input_str = 'My password is supersecret'
	expected_correct = 'My password is <secret>password</secret>'
	
	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected_correct


def test_redact_sensitive_string_duplicate_keys():
	"""
	Verify that when multiple keys map to the same secret value, they are grouped
	and sorted inside a single tag: <secret>key1, key2</secret>
	"""
	sensitive_values = {
		'password': 'admin',
		'api_key': 'admin',
	}
	input_str = 'Login with admin'
	expected = 'Login with <secret>api_key, password</secret>'
	
	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected


def test_redact_sensitive_string_substrings():
	"""
	Verify that longer secrets are matched and redacted before shorter substrings,
	avoiding partial leaks.
	"""
	sensitive_values = {
		'short': 'abc',
		'long': 'abcdef',
	}
	input_str = 'Match abcdef and abc'
	expected = 'Match <secret>long</secret> and <secret>short</secret>'
	
	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected


def test_redact_sensitive_string_falsy_values():
	"""
	Verify that empty or falsy secrets are ignored and do not cause corrupt redactions.
	"""
	sensitive_values = {
		'empty_pwd': '',
		'valid_pwd': 'safe',
	}
	input_str = 'Input is safe'
	expected = 'Input is <secret>valid_pwd</secret>'
	
	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected
