from browser_use.utils import _get_redact_pattern_and_mapping, redact_sensitive_string


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


def test_redact_sensitive_string_idempotent_when_secret_equals_key_list():
	"""
	Verify idempotence: if a secret value equals the key list text used inside a
	generated placeholder tag, re-redacting the tag must not produce nested tags.
	"""
	sensitive_values = {
		'password': 'password',
	}
	input_str = '<secret>password</secret> and password'
	expected = '<secret>password</secret> and <secret>password</secret>'

	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected


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


def test_redact_sensitive_string_secret_is_full_tag():
	"""
	Verify that a configured secret that is itself a full balanced <secret> tag
	(e.g. "<secret>foo</secret>") is redacted rather than mistaken for a
	pre-existing placeholder and leaked unchanged.
	"""
	sensitive_values = {
		'password': '<secret>foo</secret>',
	}
	# Appearing as raw plaintext.
	input_str = 'leak: <secret>foo</secret>'
	expected = 'leak: <secret>password</secret>'
	assert redact_sensitive_string(input_str, sensitive_values) == expected
	assert '<secret>foo</secret>' not in redact_sensitive_string(input_str, sensitive_values)


def test_redact_sensitive_string_empty_tag_preserved():
	"""
	Verify that an empty pre-existing <secret></secret> marker is preserved
	rather than silently removed from the message.
	"""
	sensitive_values = {
		'password': 'supersecret',
	}
	input_str = 'before <secret></secret> after'
	expected = 'before <secret></secret> after'

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


def test_redact_sensitive_string_secret_spanning_balanced_tag():
	"""
	Verify that a configured secret whose value contains a balanced
	<secret>...</secret> pair (e.g. "x<secret>y</secret>z") is fully redacted
	when it appears in plain prose, instead of being shredded by tag splitting
	and leaking unchanged.
	"""
	sensitive_values = {
		'token': 'x<secret>y</secret>z',
	}
	input_str = 'value x<secret>y</secret>z here'
	expected = 'value <secret>token</secret> here'

	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected
	# The raw secret value must not survive unredacted in the output.
	assert 'x<secret>y</secret>z' not in actual
	# Idempotence: re-redacting the output must not change it.
	assert redact_sensitive_string(actual, sensitive_values) == expected


def test_redact_sensitive_string_secret_with_nested_balanced_tags():
	"""
	Verify that a configured secret containing nested balanced <secret> pairs
	(e.g. "a<secret>b<secret>c</secret>d</secret>e") is fully redacted rather
	than leaked via fake tag re-wrapping.
	"""
	sensitive_values = {
		'token': 'a<secret>b<secret>c</secret>d</secret>e',
	}
	input_str = 'prefix a<secret>b<secret>c</secret>d</secret>e suffix'
	expected = 'prefix <secret>token</secret> suffix'

	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected
	assert 'a<secret>b<secret>c</secret>d</secret>e' not in actual
	assert redact_sensitive_string(actual, sensitive_values) == expected


def test_redact_sensitive_string_key_list_collision_with_secret():
	"""
	Verify that when a generated key-list string is itself another key's raw
	secret value, the raw secret inside an existing tag is redacted to its own
	keys instead of being preserved as a placeholder and leaking.
	"""
	sensitive_values = {
		'k2': 'k1',
		'k1': 'xyz',
	}
	input_str = '<secret>k1</secret> and xyz'
	expected = '<secret>k2</secret> and <secret>k1</secret>'

	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected
	# No raw secret value may survive in the output.
	assert 'xyz' not in actual
	# Redaction converges: after the placeholder texts themselves stabilize, a
	# further pass must not change the output.
	second = redact_sensitive_string(actual, sensitive_values)
	third = redact_sensitive_string(second, sensitive_values)
	assert second == third


def test_redact_sensitive_string_secret_is_empty_marker():
	"""
	Verify that a configured secret whose value is the empty
	<secret></secret> marker is redacted, while empty pre-existing markers
	with no matching secret remain preserved.
	"""
	sensitive_values = {
		'pwd': '<secret></secret>',
	}
	input_str = 'foo <secret></secret> bar'
	expected = 'foo <secret>pwd</secret> bar'

	actual = redact_sensitive_string(input_str, sensitive_values)
	assert actual == expected
	assert '<secret></secret>' not in actual
	assert redact_sensitive_string(actual, sensitive_values) == expected
	# Unrelated empty markers must still be preserved.
	unrelated = redact_sensitive_string('before <secret></secret> after', {'password': 'supersecret'})
	assert unrelated == 'before <secret></secret> after'


def test_redact_pattern_helper_holds_no_process_global_secret_cache():
	"""The pattern/mapping helper must not keep raw secret material in a
	process-global @lru_cache, so secrets cannot outlive the redaction call.
	"""
	# No @lru_cache machinery may be attached to the helper.
	assert not hasattr(_get_redact_pattern_and_mapping, 'cache_info')
	assert not hasattr(_get_redact_pattern_and_mapping, 'cache_clear')

	secrets_a = (('token', 'super-secret-value-a'),)
	secrets_b = (('token', 'super-secret-value-b'),)

	_pattern_a, mapping_a, plain_a = _get_redact_pattern_and_mapping(secrets_a)
	_pattern_b, mapping_b, plain_b = _get_redact_pattern_and_mapping(secrets_b)

	# Independent objects per call: no shared cached state to mutate or inspect
	# across requests.
	assert mapping_a is not mapping_b
	assert plain_a is not plain_b
	# A's compiled maps must not retain a different call's secret text.
	assert 'super-secret-value-b' not in mapping_a
	assert 'super-secret-value-a' not in mapping_b

	# After redacting with secret A, a subsequent B lookup must still be clean
	# of A's secret (no lingering global retention).
	redact_sensitive_string('leak super-secret-value-a', {'token': 'super-secret-value-a'})
	_, mapping_b2, _ = _get_redact_pattern_and_mapping(secrets_b)
	assert 'super-secret-value-a' not in mapping_b2


def test_redact_inside_existing_tag_uses_single_pass_no_cascade():
	"""Inner tag content is redacted in a single pass: a secret whose generated
	key-list text coincides with another secret's value must not be re-redacted
	into the other key inside the existing tag (no cascade re-redaction).
	"""
	# 'say k1 now' (key=k1) sits inside an existing tag. Its placeholder is 'k1',
	# which is also the secret value for key k2 — but placeholders are never
	# re-scanned, so the result stays 'k1', not a cascaded 'k2'.
	result = redact_sensitive_string('<secret>say k1 now</secret>', {'k2': 'k1', 'k1': 'say k1 now'})
	assert result == '<secret>k1</secret>'
