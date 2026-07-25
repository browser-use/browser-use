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


def test_redact_sensitive_string_secret_inside_tag():
	"""
	Verify that if a raw secret is wrapped in a pre-existing <secret> tag,
	the raw secret value inside the tag is correctly replaced with the placeholder.
	"""
	sensitive_values = {
		'password': 'supersecret',
	}
	input_str = '<secret>supersecret</secret> and some raw supersecret'
	expected = '<secret>password</secret> and some raw <secret>password</secret>'

	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected


def test_redact_sensitive_string_multiline_tag():
	"""
	Verify that pre-existing tags containing newlines are correctly matched
	and skipped, rather than causing cascade re-redactions inside tag boundaries.
	"""
	sensitive_values = {
		'password': 'supersecret',
		'key': 'secret',
	}
	input_str = '<secret>first_line\nsecond_line</secret> and supersecret'
	expected = '<secret>first_line\nsecond_line</secret> and <secret>password</secret>'

	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected


def test_redact_sensitive_string_secret_with_tag_chars():
	"""
	Verify that a secret value whose own text contains ``<secret>`` tag markers
	is fully redacted when it appears as plaintext in unredacted prose, i.e. the
	literal marker text is not mistaken for a tag boundary that should be skipped.
	"""
	sensitive_values = {
		'api_key': '<secret>leak',
	}
	input_str = 'The api key is <secret>leak in plaintext'
	expected = 'The api key is <secret>api_key</secret> in plaintext'

	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected
	# The raw secret value (including the literal ``<secret>`` marker) must not
	# survive unredacted in the output.
	assert '<secret>leak' not in actual


def test_redact_sensitive_string_secret_spanning_tags():
	"""
	Verify that a secret value containing a literal ``</secret>...<secret>``
	sequence (i.e. text that looks like it spans a tag boundary) is fully
	redacted when it occurs in unredacted prose, rather than being split or
	skipped as if it were real tag markup.
	"""
	sensitive_values = {
		'token': 'abc</secret>xyz<secret>def',
	}
	input_str = 'token abc</secret>xyz<secret>def here'
	expected = 'token <secret>token</secret> here'

	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected
	assert 'abc</secret>xyz<secret>def' not in actual


def test_redact_sensitive_string_nested_pre_existing_tags():
	"""
	Verify that nested pre-existing <secret> tags are parsed using balanced
	boundaries, not at the first closing tag. The outer tag's inner content
	(including nested tags) should be redacted and re-wrapped correctly.
	"""
	sensitive_values = {
		'password': 'supersecret',
	}
	input_str = '<secret>outer <secret>supersecret</secret> inner</secret>'
	expected = '<secret>outer <secret>password</secret> inner</secret>'

	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected


def test_redact_sensitive_string_unsorted_input():
	"""
	Verify that when keys are supplied in non-alphabetical order and share a
	secret value, the generated placeholder lists the keys in deterministic
	sorted order (alphabetical).
	"""
	sensitive_values = {
		'zeta': 'shared',
		'alpha': 'shared',
	}
	input_str = 'uses shared secret'
	expected = 'uses <secret>alpha, zeta</secret> secret'

	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected
