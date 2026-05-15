"""NavigateAction strips JSON/tool-call tails some models append to navigate URLs."""

from browser_use.tools.views import NavigateAction


def test_navigate_url_strips_plain_brace_leak():
	a = NavigateAction(url='https://www.baidu.com/}}]')
	assert a.url == 'https://www.baidu.com/'


def test_navigate_url_strips_percent_encoded_leak():
	a = NavigateAction(url='https://www.baidu.com/%7D%7D]%7D')
	assert a.url == 'https://www.baidu.com/'


def test_navigate_url_unchanged_when_no_double_brace_leak():
	u = 'https://example.com/path?q=x%7D'
	a = NavigateAction(url=u)
	assert a.url == u
