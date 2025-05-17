import base64
from unittest.mock import Mock

import pytest

from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.browser.views import BrowserState
from browser_use.dom.views import DOMElementNode


def test_is_url_allowed():
	"""
	Test the _is_url_allowed method to verify that it correctly checks URLs against
	the allowed domains configuration.
	Scenario 1: When allowed_domains is None, all URLs should be allowed.
	Scenario 2: When allowed_domains is a list, only URLs matching the allowed domain(s) are allowed.
	Scenario 3: When the URL is malformed, it should return False.
	Scenario 4: When allowed_domains contain glob patterns, see: test_url_allowlist_security.py
	"""
	# Create a dummy Browser mock. Only the 'config' attribute is needed for _is_url_allowed.
	dummy_browser = Mock()
	# Set an empty config for dummy_browser; it won't be used in _is_url_allowed.
	dummy_browser.config = Mock()
	# Scenario 1: allowed_domains is None, any URL should be allowed.
	config1 = BrowserContextConfig(allowed_domains=None)
	context1 = BrowserContext(browser=dummy_browser, config=config1)
	assert context1._is_url_allowed('http://anydomain.com') is True
	assert context1._is_url_allowed('https://anotherdomain.org/path') is True
	# Scenario 2: allowed_domains is provided.
	allowed = ['example.com', 'mysite.org']
	config2 = BrowserContextConfig(allowed_domains=allowed)
	context2 = BrowserContext(browser=dummy_browser, config=config2)
	# URL exactly matching
	assert context2._is_url_allowed('http://example.com') is True
	# URL with subdomain (should be allowed)
	assert context2._is_url_allowed('http://sub.example.com/path') is True
	# URL with different domain (should not be allowed)
	assert context2._is_url_allowed('http://notexample.com') is False
	# URL that matches second allowed domain
	assert context2._is_url_allowed('https://mysite.org/page') is True
	# URL with port number, still allowed (port is stripped)
	assert context2._is_url_allowed('http://example.com:8080') is True
	# Scenario 3: Malformed URL or empty domain
	# urlparse will return an empty netloc for some malformed URLs.
	assert context2._is_url_allowed('notaurl') is False


def test_convert_simple_xpath_to_css_selector():
	"""
	Test the _convert_simple_xpath_to_css_selector method of BrowserContext.
	This verifies that simple XPath expressions (with and without indices) are correctly converted to CSS selectors.
	"""
	# Test empty xpath returns empty string
	assert BrowserContext._convert_simple_xpath_to_css_selector('') == ''
	# Test a simple xpath without indices
	xpath = '/html/body/div/span'
	expected = 'html > body > div > span'
	result = BrowserContext._convert_simple_xpath_to_css_selector(xpath)
	assert result == expected
	# Test xpath with an index on one element: [2] should translate to :nth-of-type(2)
	xpath = '/html/body/div[2]/span'
	expected = 'html > body > div:nth-of-type(2) > span'
	result = BrowserContext._convert_simple_xpath_to_css_selector(xpath)
	assert result == expected
	# Test xpath with indices on multiple elements:
	# For "li[3]" -> li:nth-of-type(3) and for "a[1]" -> a:nth-of-type(1)
	xpath = '/ul/li[3]/a[1]'
	expected = 'ul > li:nth-of-type(3) > a:nth-of-type(1)'
	result = BrowserContext._convert_simple_xpath_to_css_selector(xpath)
	assert result == expected


def test_get_initial_state():
	"""
	Test the _get_initial_state method to verify it returns the correct initial BrowserState.
	The test checks that when a dummy page with a URL is provided,
	the returned state contains that URL and other default values.
	"""
	# Create a dummy browser since only its existence is needed.
	dummy_browser = Mock()
	dummy_browser.config = Mock()
	context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())

	# Define a dummy page with a 'url' attribute.
	class DummyPage:
		url = 'http://dummy.com'

	dummy_page = DummyPage()
	# Call _get_initial_state with a page: URL should be set from page.url.
	state_with_page = context._get_initial_state(page=dummy_page)
	assert state_with_page.url == dummy_page.url
	# Verify that the element_tree is initialized with tag 'root'
	assert state_with_page.element_tree.tag_name == 'root'
	# Call _get_initial_state without a page: URL should be empty.
	state_without_page = context._get_initial_state()
	assert state_without_page.url == ''


@pytest.mark.asyncio
async def test_execute_javascript():
	"""
	Test the execute_javascript method by mocking the current page's evaluate function.
	This ensures that when execute_javascript is called, it correctly returns the value
	from the page's evaluate method.
	"""

	# Define a dummy page with an async evaluate method.
	class DummyPage:
		async def evaluate(self, script):
			return 'dummy_result'

	# Create a dummy session object with a dummy current_page.
	dummy_session = type('DummySession', (), {})()
	dummy_session.current_page = DummyPage()
	# Create a dummy browser mock with a minimal config.
	dummy_browser = Mock()
	dummy_browser.config = Mock()
	# Initialize the BrowserContext with the dummy browser and config.
	context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
	# Manually set the session to our dummy session.
	context.session = dummy_session
	# Call execute_javascript and verify it returns the expected result.
	result = await context.execute_javascript('return 1+1')
	assert result == 'dummy_result'


@pytest.mark.asyncio
async def test_enhanced_css_selector_for_element():
	"""
	Test the _enhanced_css_selector_for_element method to verify that
	it returns the correct CSS selector string for a dummy DOMElementNode.
	The test checks that:
	  - The provided xpath is correctly converted (handling indices),
	  - Class attributes are appended as CSS classes,
	  - Standard and dynamic attributes (including ones with special characters)
	    are correctly added to the selector.
	"""
	# Create a dummy DOMElementNode instance with a complex set of attributes.
	dummy_element = DOMElementNode(
		tag_name='div',
		is_visible=True,
		parent=None,
		xpath='/html/body/div[2]',
		attributes={'class': 'foo bar', 'id': 'my-id', 'placeholder': 'some "quoted" text', 'data-testid': '123'},
		children=[],
	)
	# Call the method with include_dynamic_attributes=True.
	actual_selector = BrowserContext._enhanced_css_selector_for_element(dummy_element, include_dynamic_attributes=True)
	# Expected conversion:
	# 1. The xpath "/html/body/div[2]" converts to "html > body > div:nth-of-type(2)".
	# 2. The class attribute "foo bar" appends ".foo.bar".
	# 3. The "id" attribute is added as [id="my-id"].
	# 4. The "placeholder" attribute contains quotes; it is added as
	#    [placeholder*="some \"quoted\" text"].
	# 5. The dynamic attribute "data-testid" is added as [data-testid="123"].
	expected_selector = (
		'html > body > div:nth-of-type(2).foo.bar[id="my-id"][placeholder*="some \\"quoted\\" text"][data-testid="123"]'
	)
	assert actual_selector == expected_selector, f'Expected {expected_selector}, but got {actual_selector}'


@pytest.mark.asyncio
async def test_get_scroll_info():
	"""
	Test the get_scroll_info method by mocking the page's evaluate method.
	This dummy page returns preset values for window.scrollY, window.innerHeight,
	and document.documentElement.scrollHeight. The test then verifies that the
	computed scroll information (pixels_above and pixels_below) match the expected values.
	"""

	# Define a dummy page with an async evaluate method returning preset values.
	class DummyPage:
		async def evaluate(self, script):
			if 'window.scrollY' in script:
				return 100  # scrollY
			elif 'window.innerHeight' in script:
				return 500  # innerHeight
			elif 'document.documentElement.scrollHeight' in script:
				return 1200  # total scrollable height
			return None

	# Create a dummy session with a dummy current_page.
	dummy_session = type('DummySession', (), {})()
	dummy_session.current_page = DummyPage()
	# We also need a dummy context attribute but it won't be used in this test.
	dummy_session.context = type('DummyContext', (), {})()
	# Create a dummy browser mock.
	dummy_browser = Mock()
	dummy_browser.config = Mock()
	# Initialize BrowserContext with the dummy browser and config.
	context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
	# Manually set the session to our dummy session.
	context.session = dummy_session
	# Call get_scroll_info on the dummy page.
	pixels_above, pixels_below = await context.get_scroll_info(dummy_session.current_page)
	# Expected calculations:
	# pixels_above = scrollY = 100
	# pixels_below = total_height - (scrollY + innerHeight) = 1200 - (100 + 500) = 600
	assert pixels_above == 100, f'Expected 100 pixels above, got {pixels_above}'
	assert pixels_below == 600, f'Expected 600 pixels below, got {pixels_below}'


@pytest.mark.asyncio
async def test_reset_context():
	"""
	Test the reset_context method to ensure it correctly closes all existing tabs,
	resets the cached state, and creates a new page.
	"""

	# Dummy Page with close and wait_for_load_state methods.
	class DummyPage:
		def __init__(self, url='http://dummy.com'):
			self.url = url
			self.closed = False

		async def close(self):
			self.closed = True

		async def wait_for_load_state(self):
			pass

	# Dummy Context that holds pages and can create a new page.
	class DummyContext:
		def __init__(self):
			self.pages = []

		async def new_page(self):
			new_page = DummyPage(url='')
			self.pages.append(new_page)
			return new_page

	# Create a dummy session with a context containing two pages.
	dummy_session = type('DummySession', (), {})()
	dummy_context = DummyContext()
	page1 = DummyPage(url='http://page1.com')
	page2 = DummyPage(url='http://page2.com')
	dummy_context.pages.extend([page1, page2])
	dummy_session.context = dummy_context
	dummy_session.current_page = page1
	dummy_session.cached_state = None
	# Create a dummy browser mock.
	dummy_browser = Mock()
	dummy_browser.config = Mock()
	# Initialize BrowserContext using our dummy_browser and config,
	# and manually set its session to our dummy session.
	context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
	context.session = dummy_session
	# Confirm session has 2 pages before reset.
	assert len(dummy_session.context.pages) == 2
	# Call reset_context which should close existing pages,
	# reset the cached state, and create a new page as current_page.
	await context.reset_context()
	# Verify that initial pages were closed.
	assert page1.closed is True
	assert page2.closed is True
	# Check that a new page is created and set as current_page.
	assert dummy_session.current_page is not None
	new_page = dummy_session.current_page
	# New page URL should be empty as per _get_initial_state.
	assert new_page.url == ''
	# Verify that cached_state is reset to an initial BrowserState.
	state = dummy_session.cached_state
	assert isinstance(state, BrowserState)
	assert state.url == ''
	assert state.element_tree.tag_name == 'root'


@pytest.mark.asyncio
async def test_take_screenshot():
	"""
	Test the take_screenshot method to verify that it returns a base64 encoded screenshot string.
	A dummy page with a mocked screenshot method is used, returning a predefined byte string.
	"""

	class DummyPage:
		async def screenshot(self, full_page, animations):
			# Verify that parameters are forwarded correctly.
			assert full_page is True, 'full_page parameter was not correctly passed'
			assert animations == 'disabled', 'animations parameter was not correctly passed'
			# Return a test byte string.
			return b'test'

	# Create a dummy session with the DummyPage as the current_page.
	dummy_session = type('DummySession', (), {})()
	dummy_session.current_page = DummyPage()
	dummy_session.context = None  # Not used in this test
	# Create a dummy browser mock.
	dummy_browser = Mock()
	dummy_browser.config = Mock()
	# Initialize the BrowserContext with the dummy browser and config.
	context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
	# Manually set the session to our dummy session.
	context.session = dummy_session
	# Call take_screenshot and check that it returns the expected base64 encoded string.
	result = await context.take_screenshot(full_page=True)
	expected = base64.b64encode(b'test').decode('utf-8')
	assert result == expected, f'Expected {expected}, but got {result}'


@pytest.mark.asyncio
async def test_refresh_page_behavior():
	"""
	Test the refresh_page method of BrowserContext to verify that it correctly reloads the current page
	and waits for the page's load state. This is done by creating a dummy page that flags when its
	reload and wait_for_load_state methods are called.
	"""

	class DummyPage:
		def __init__(self):
			self.reload_called = False
			self.wait_for_load_state_called = False

		async def reload(self):
			self.reload_called = True

		async def wait_for_load_state(self):
			self.wait_for_load_state_called = True

	# Create a dummy session with the dummy page as the current_page.
	dummy_page = DummyPage()
	dummy_session = type('DummySession', (), {})()
	dummy_session.current_page = dummy_page
	dummy_session.context = None  # Not required for this test
	# Create a dummy browser mock
	dummy_browser = Mock()
	dummy_browser.config = Mock()
	# Initialize BrowserContext with the dummy browser and config,
	# and manually set its session to our dummy session.
	context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
	context.session = dummy_session
	# Call refresh_page and verify that reload and wait_for_load_state were called.
	await context.refresh_page()
	assert dummy_page.reload_called is True, 'Expected the page to call reload()'
	assert dummy_page.wait_for_load_state_called is True, 'Expected the page to call wait_for_load_state()'


@pytest.mark.asyncio
async def test_remove_highlights_failure():
	"""
	Test the remove_highlights method to ensure that if the page.evaluate call fails,
	the exception is caught and does not propagate (i.e. the method handles errors gracefully).
	"""

	# Dummy page that always raises an exception when evaluate is called.
	class DummyPage:
		async def evaluate(self, script):
			raise Exception('dummy error')

	# Create a dummy session with the DummyPage as current_page.
	dummy_session = type('DummySession', (), {})()
	dummy_session.current_page = DummyPage()
	dummy_session.context = None  # Not used in this test
	# Create a dummy browser mock.
	dummy_browser = Mock()
	dummy_browser.config = Mock()
	# Initialize BrowserContext with the dummy browser and configuration.
	context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
	context.session = dummy_session
	# Call remove_highlights and verify that no exception is raised.
	try:
		await context.remove_highlights()
	except Exception as e:
		pytest.fail(f'remove_highlights raised an exception: {e}')
