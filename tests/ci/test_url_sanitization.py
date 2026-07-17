from browser_use.utils import sanitize_url_candidate


def test_sanitize_url_candidate_strips_wrapping_quotes_and_angle_brackets():
	assert sanitize_url_candidate('<"https://example.com/path">') == 'https://example.com/path'


def test_sanitize_url_candidate_keeps_query_punctuation():
	assert sanitize_url_candidate('https://example.com/search?q=a,b.') == 'https://example.com/search?q=a,b'
