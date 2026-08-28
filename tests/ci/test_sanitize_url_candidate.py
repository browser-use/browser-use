from browser_use.utils import sanitize_url_candidate


def test_sanitize_url_candidate_balanced_brackets():
	# Issue #5575: URLs with balanced closing brackets should not be truncated
	assert (
		sanitize_url_candidate('https://en.wikipedia.org/wiki/Python_(programming_language)')
		== 'https://en.wikipedia.org/wiki/Python_(programming_language)'
	)
	assert (
		sanitize_url_candidate('https://en.wikipedia.org/wiki/Berlin_(disambiguation)')
		== 'https://en.wikipedia.org/wiki/Berlin_(disambiguation)'
	)
	assert sanitize_url_candidate('https://example.com/a[1]') == 'https://example.com/a[1]'


def test_sanitize_url_candidate_unmatched_trailing_brackets():
	# Trailing prose closing brackets should be stripped
	assert sanitize_url_candidate('https://example.com/docs)') == 'https://example.com/docs'
	assert sanitize_url_candidate('https://example.com/docs]') == 'https://example.com/docs'
	assert sanitize_url_candidate('https://example.com/docs.') == 'https://example.com/docs'
	assert sanitize_url_candidate('https://example.com/docs...') == 'https://example.com/docs'
	assert sanitize_url_candidate('https://example.com/docs,') == 'https://example.com/docs'
	assert sanitize_url_candidate('https://example.com/docs!?:;') == 'https://example.com/docs'
