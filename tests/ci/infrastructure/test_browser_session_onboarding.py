from browser_use.browser.session import BrowserSession


def test_is_welcome_page_url_detects_welcome_keyword():
	assert BrowserSession._is_welcome_page_url('https://app.browser-use.com/welcome') is True
	assert BrowserSession._is_welcome_page_url('https://app.browser-use.com/onboarding') is True
	assert BrowserSession._is_welcome_page_url('https://example.com/get-started') is True
	assert BrowserSession._is_welcome_page_url('https://example.com/profile') is False


def test_is_extension_onboarding_url_detects_extension_paths():
	session = BrowserSession()
	assert session._is_extension_onboarding_url('chrome-extension://abcd1234/welcome.html') is True
	assert session._is_extension_onboarding_url('chrome-extension://abcd1234/options.html') is True
	assert session._is_extension_onboarding_url('chrome-extension://abcd1234/onboarding.html') is True
	assert session._is_extension_onboarding_url('chrome-extension://abcd1234/random.html') is False
