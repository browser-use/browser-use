from browser_use.utils import sanitize_url_candidate


def test_balanced_trailing_parenthesis_preserved():
	"""A Wikipedia-style URL with a balanced trailing ``)`` is preserved."""
	url = 'https://en.wikipedia.org/wiki/Python_(programming_language)'
	assert sanitize_url_candidate(url) == url


def test_balanced_trailing_bracket_preserved():
	"""A URL with a balanced trailing ``]`` is preserved."""
	url = 'https://example.com/path/[item]'
	assert sanitize_url_candidate(url) == url


def test_unbalanced_trailing_parenthesis_stripped():
	"""A trailing ``)`` with no matching ``(`` is stripped."""
	assert sanitize_url_candidate('https://example.com/foo)') == 'https://example.com/foo'


def test_unbalanced_trailing_bracket_stripped():
	"""A trailing ``]`` with no matching ``[`` is stripped."""
	assert sanitize_url_candidate('https://example.com/bar]') == 'https://example.com/bar'


def test_nested_balanced_parens_preserved():
	"""Nested balanced parentheses are kept intact."""
	url = 'https://example.com/(a(b)c)'
	assert sanitize_url_candidate(url) == url


def test_extra_closing_paren_stripped():
	"""Only the unbalanced trailing ``)`` is stripped; balanced ones remain."""
	assert sanitize_url_candidate('https://example.com/(foo))') == 'https://example.com/(foo)'


def test_trailing_punctuation_stripped():
	"""Trailing ``.,;:!?`` are stripped."""
	for suffix in '.,;:!?':
		assert sanitize_url_candidate(f'https://example.com/foo{suffix}') == 'https://example.com/foo'


def test_punctuation_after_balanced_paren_stripped():
	"""Trailing punctuation after a balanced ``)`` is stripped, ``)`` kept."""
	assert sanitize_url_candidate('https://en.wikipedia.org/wiki/Python_(programming_language).') == (
		'https://en.wikipedia.org/wiki/Python_(programming_language)'
	)


def test_escaped_newline_truncation_unchanged():
	"""Escaped-newline prose truncation still happens before balance handling."""
	# The split on escaped newlines keeps everything before the first \\n, then
	# the trailing ``.`` is stripped as punctuation.
	assert sanitize_url_candidate('https://example.com/search.\\n2. Next step') == 'https://example.com/search'


def test_empty_input():
	"""Empty input returns empty string."""
	assert sanitize_url_candidate('') == ''


def test_whitespace_only_input():
	"""Whitespace-only input returns empty string after strip."""
	assert sanitize_url_candidate('   ') == ''
