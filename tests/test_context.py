import pytest
import asyncio
from browser_use.browser.context import BrowserContext, BrowserContextConfig, BrowserSession
from browser_use.dom.views import DOMElementNode
from browser_use.browser.views import BrowserError
import os
import json
import time
import uuid
import logging
import re

def test_convert_simple_xpath_to_css_selector():
    """
    Test converting a simple XPath with numeric indices into the equivalent CSS selector.
    """
    xpath = "/html/body/div[2]/span"
    expected = "html > body > div:nth-of-type(2) > span"
    css_selector = BrowserContext._convert_simple_xpath_to_css_selector(xpath)
    assert css_selector == expected, f"Expected: {expected}, got: {css_selector}"
def test_convert_empty_xpath_to_css_selector():
    """
    Test that providing an empty XPath returns an empty string as the CSS selector.
    """
    xpath = ""
    expected = ""
    css_selector = BrowserContext._convert_simple_xpath_to_css_selector(xpath)
    assert css_selector == expected
def test_enhanced_css_selector_for_element_with_dynamic_attributes():
    """
    Test that _enhanced_css_selector_for_element returns a correct CSS selector
    including static attributes (like "type") and dynamic attributes (like "data-cy"),
    as well as proper conversion of the XPath with an index.
    """
    element = DOMElementNode(
        tag_name="input",
        is_visible=True,
        parent=None,
        xpath="/html/body/input[1]",
        attributes={
            "class": "test",
            "type": "file",
            "data-cy": "upload"
        },
        children=[]
    )
    css_selector = BrowserContext._enhanced_css_selector_for_element(element, include_dynamic_attributes=True)
    expected = 'html > body > input:nth-of-type(1).test[type="file"][data-cy="upload"]'
    assert css_selector == expected, f"Expected: {expected}, got: {css_selector}"
def test_enhanced_css_selector_without_dynamic_attributes():
    """
    Test _enhanced_css_selector_for_element when include_dynamic_attributes is False.
    Ensures that dynamic attributes and the class attribute are not appended to the CSS selector.
    """
    element = DOMElementNode(
        tag_name="button",
        is_visible=True,
        parent=None,
        xpath="/html/body/button[1]",
        attributes={
            "class": "btn primary",  # should be ignored when include_dynamic_attributes is False
            "type": "submit",
            "data-cy": "login",  # dynamic attribute, expected not to appear
        },
        children=[]
    )
    css_selector = BrowserContext._enhanced_css_selector_for_element(element, include_dynamic_attributes=False)
    expected = 'html > body > button:nth-of-type(1)[type="submit"]'
    assert css_selector == expected, f"Expected: {expected}, got: {css_selector}"
@pytest.mark.asyncio
async def test_navigate_to_non_allowed_url():
    """
    Test that navigating to a non-allowed URL (not whitelisted by allowed_domains)
    properly raises a BrowserError.
    """
    class DummyBrowser:
        async def get_playwright_browser(self):
            raise Exception("DummyBrowser: get_playwright_browser should not be called in this test.")
        config = type("DummyConfig", (), {"cdp_url": None, "chrome_instance_path": None})()
        
    config = BrowserContextConfig(allowed_domains=["example.com"])
    context = BrowserContext(browser=DummyBrowser(), config=config)
    non_allowed_url = "http://notallowed.com/page"
    with pytest.raises(BrowserError) as exc_info:
        await context.navigate_to(non_allowed_url)
    assert non_allowed_url in str(exc_info.value)
@pytest.mark.asyncio
async def test_is_file_uploader_behavior():
    """
    Test the is_file_uploader method with various DOMElementNode structures:
    - A direct file uploader element (input with type "file")
    - A direct non-file uploader element (input with type "text")
    - A nested structure where a file uploader exists in a subtree.
    """
    class DummyBrowser:
        async def get_playwright_browser(self):
            raise Exception("DummyBrowser: get_playwright_browser should not be called in this test.")
        config = type("DummyConfig", (), {"cdp_url": None, "chrome_instance_path": None})()
    
    config = BrowserContextConfig()
    context = BrowserContext(browser=DummyBrowser(), config=config)
    
    # Case 1: Direct file uploader element (input type "file")
    uploader_node = DOMElementNode(
        tag_name="input",
        is_visible=True,
        parent=None,
        xpath="/html/body/input[1]",
        attributes={"type": "file"},
        children=[],
    )
    result = await context.is_file_uploader(uploader_node)
    assert result is True, "Expected direct file uploader element (input type 'file') to return True"
    
    # Case 2: Non-uploader element (input type "text")
    non_uploader_node = DOMElementNode(
        tag_name="input",
        is_visible=True,
        parent=None,
        xpath="/html/body/input[1]",
        attributes={"type": "text"},
        children=[],
    )
    result = await context.is_file_uploader(non_uploader_node)
    assert result is False, "Expected non-file uploader element (input type 'text') to return False"
    
    # Case 3: Nested structure with file uploader:
    file_input_node = DOMElementNode(
        tag_name="input",
        is_visible=True,
        parent=None,
        xpath="/html/body/div/input[1]",
        attributes={"type": "file"},
        children=[],
    )
    intermediate_node = DOMElementNode(
        tag_name="div",
        is_visible=True,
        parent=None,
        xpath="/html/body/div[1]",
        attributes={},
        children=[file_input_node],
    )
    file_input_node.parent = intermediate_node
    parent_node = DOMElementNode(
        tag_name="section",
        is_visible=True,
        parent=None,
        xpath="/html/body/section[1]",
        attributes={},
        children=[intermediate_node],
    )
    intermediate_node.parent = parent_node
    
    result = await context.is_file_uploader(parent_node)
    assert result is True, "Expected nested file uploader in DOM tree to return True"
@pytest.mark.asyncio
async def test_reset_context_resets_state():
    """
    Test that reset_context properly closes the original pages in the session's context,
    resets the cached state, and creates a new current page.
    Only the original pages are expected to be closed, while the new page remains open.
    """
    class DummyPage:
        def __init__(self, url):
            self.url = url
            self.closed = False
        async def close(self):
            self.closed = True
        async def wait_for_load_state(self):
            return
        async def bring_to_front(self):
            return
    class DummyContext:
        def __init__(self, pages):
            self.pages = pages
        async def new_page(self):
            new_page = DummyPage("http://dummy/new")
            self.pages.append(new_page)
            return new_page
    dummy_pages = [DummyPage("http://dummy/1"), DummyPage("http://dummy/2")]
    dummy_context = DummyContext(dummy_pages)
    class DummyBrowser:
        async def get_playwright_browser(self):
            pass
        config = type("DummyConfig", (), {"cdp_url": None, "chrome_instance_path": None})()
    temp_context = BrowserContext(browser=DummyBrowser(), config=BrowserContextConfig())
    dummy_cached_state = temp_context._get_initial_state()
    dummy_session = BrowserSession(context=dummy_context, current_page=dummy_pages[0], cached_state=dummy_cached_state)
    context = BrowserContext(browser=DummyBrowser(), config=BrowserContextConfig())
    context.session = dummy_session
    original_page_count = len(dummy_pages)
    await context.reset_context()
    for page in dummy_pages[:original_page_count]:
        assert page.closed, "Expected original page to be closed after reset_context"
    new_page = context.session.current_page
    assert new_page is not None, "Expected a new current page to be created"
    assert new_page.url == "http://dummy/new", "Expected new page URL to be 'http://dummy/new'"
    state = context.session.cached_state
    assert state.url == "", "Expected initial state's URL to be empty"
    assert state.title == "", "Expected initial state's title to be empty"
@pytest.mark.asyncio
async def test_remove_highlights_handles_exception():
    """
    Test that remove_highlights properly handles exceptions when the page's evaluate method
    fails, ensuring that errors inside remove_highlights do not propagate.
    """
    # Create a dummy page that raises an exception when evaluate is called.
    class DummyPage:
        async def evaluate(self, script):
            raise Exception("Dummy error in evaluate")
        async def wait_for_load_state(self):
            return
        async def scroll_into_view_if_needed(self, timeout=None):
            return
    # Create a dummy context that has the required methods.
    class DummyContext:
        def __init__(self, pages):
            self.pages = pages
        def on(self, event, func):
            pass
        def remove_listener(self, event, func):
            pass
    # Create a dummy browser whose get_playwright_browser is not used.
    class DummyBrowser:
        async def get_playwright_browser(self):
            # Not used in this test.
            return None
        config = type("DummyConfig", (), {"cdp_url": None, "chrome_instance_path": None})()
    # Set up the dummy session with a DummyPage that always fails when evaluate is called.
    dummy_page = DummyPage()
    dummy_context = DummyContext([dummy_page])
    # Use _get_initial_state with None since we don't need an actual page state here.
    dummy_cached_state = BrowserContext._get_initial_state(None)
    dummy_session = BrowserSession(context=dummy_context, current_page=dummy_page, cached_state=dummy_cached_state)
    # Create the BrowserContext with a dummy browser and assign our dummy session.
    context = BrowserContext(browser=DummyBrowser(), config=BrowserContextConfig())
    context.session = dummy_session
    # Call remove_highlights() and verify that it handles the error gracefully.
    # We expect no exception to be raised despite DummyPage.evaluate always throwing.
    await context.remove_highlights()
    # If we reached this point without an exception, the test has passed.
    assert True  # Explicitly mark the test as passed.
@pytest.mark.asyncio
async def test_execute_javascript_returns_correct_value():
    """
    Test that execute_javascript properly evaluates a JavaScript snippet and returns the expected result.
    """
    # Define a dummy page that implements evaluate to return a fixed value.
    class DummyPage:
        async def evaluate(self, script):
            if script == "return 42":
                return 42
            return None
        async def wait_for_load_state(self):
            return
        async def scroll_into_view_if_needed(self, timeout=None):
            return
        async def bring_to_front(self):
            return
        @property
        def url(self):
            return "http://dummy"
    # Dummy context can be an empty object as it is not used in the test.
    class DummyContext:
        pass
    dummy_page = DummyPage()
    dummy_context = DummyContext()
    dummy_state = BrowserContext._get_initial_state(dummy_page)
    # Create a dummy session with our dummy page.
    dummy_session = BrowserSession(
        context=dummy_context,
        current_page=dummy_page,
        cached_state=dummy_state
    )
    # Define a dummy browser.
    class DummyBrowser:
        async def get_playwright_browser(self):
            # Not used in this test.
            pass
        config = type("DummyConfig", (), {"cdp_url": None, "chrome_instance_path": None})()
    # Create the BrowserContext and manually assign our dummy session.
    context = BrowserContext(browser=DummyBrowser(), config=BrowserContextConfig())
    context.session = dummy_session
    # Execute the JavaScript and verify the result.
    result = await context.execute_javascript("return 42")
    assert result == 42, f"Expected 42, got {result}"
@pytest.mark.asyncio
async def test_get_page_html_returns_correct_content():
    """
    Test that the get_page_html method returns the expected HTML content.
    This is done by creating a dummy page with a fixed HTML content.
    """
    # Define a dummy page with a fixed content and required methods.
    class DummyPage:
        def __init__(self, url, content_str):
            self._url = url
            self._content = content_str
        async def content(self):
            return self._content
        async def wait_for_load_state(self):
            return
    # Define a dummy context with a list of pages.
    class DummyContext:
        def __init__(self, pages):
            self.pages = pages
        async def new_page(self):
            new_page = DummyPage("http://dummy/new", "<html><body>New Page</body></html>")
            self.pages.append(new_page)
            return new_page
    # Create a dummy browser to pass to BrowserContext.
    class DummyBrowser:
        async def get_playwright_browser(self):
            # Not used in this test.
            return None
        config = type("DummyConfig", (), {"cdp_url": None, "chrome_instance_path": None})()
    # Setup a dummy page and context.
    dummy_html = "<html><body>Dummy Content</body></html>"
    dummy_page = DummyPage("http://dummy", dummy_html)
    dummy_context = DummyContext(pages=[dummy_page])
    # Create a dummy cached state using _get_initial_state with dummy_page.
    dummy_cached_state = BrowserContext._get_initial_state(dummy_page)
    # Create the dummy session.
    dummy_session = BrowserSession(context=dummy_context, current_page=dummy_page, cached_state=dummy_cached_state)
    # Create a BrowserContext with a dummy browser and assign our dummy session.
    context = BrowserContext(browser=DummyBrowser(), config=BrowserContextConfig())
    context.session = dummy_session
    # Call get_page_html and assert the returned content.
    result = await context.get_page_html()
    assert result == dummy_html, f"Expected HTML content '{dummy_html}', got '{result}'"