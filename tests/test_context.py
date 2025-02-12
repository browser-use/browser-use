import asyncio
import pytest
import json
import os
import time
import uuid
import base64
import re
import logging
from browser_use.browser.context import BrowserContext, BrowserContextConfig, BrowserSession
from browser_use.dom.views import DOMElementNode
from browser_use.browser.views import BrowserState
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.browser.views import BrowserError
from browser_use.browser.views import BrowserState, BrowserError

@pytest.mark.asyncio
async def test_browser_context_utilities():
    """
    Test utility methods of BrowserContext:
    - _is_url_allowed returns True/False based on allowed_domains config.
    - _convert_simple_xpath_to_css_selector converts a simple XPath correctly.
    - _enhanced_css_selector_for_element returns a valid CSS selector for a DOMElementNode.
    """
    # Create a dummy browser to pass to BrowserContext.
    class DummyBrowser:
        async def get_playwright_browser(self):
            # Return a dummy object with an empty contexts list.
            class DummyPlaywrightBrowser:
                contexts = []
                async def new_context(self, **kwargs):
                    return None
            return DummyPlaywrightBrowser()
    # Setup: allow only example.com for navigation.
    config = BrowserContextConfig(allowed_domains=["example.com"])
    dummy_browser = DummyBrowser()
    bc = BrowserContext(dummy_browser, config)
    # Test _is_url_allowed with various URLs.
    assert bc._is_url_allowed("https://example.com") is True
    assert bc._is_url_allowed("https://sub.example.com/path") is True
    assert bc._is_url_allowed("https://example.org") is False
    # URL with a port should ignore the port portion.
    assert bc._is_url_allowed("https://example.com:443") is True
    # Test _convert_simple_xpath_to_css_selector.
    xpath_input = "/html/body/div"
    css_sel = BrowserContext._convert_simple_xpath_to_css_selector(xpath_input)
    assert css_sel == "html > body > div"
    # Test _enhanced_css_selector_for_element.
    # Create a dummy DOMElementNode.
    node = DOMElementNode(
        tag_name="div",
        is_visible=True,
        parent=None,
        xpath="/html/body/div",
        attributes={"class": "test", "id": "myid"},
        children=[]
    )
    enhanced_selector = BrowserContext._enhanced_css_selector_for_element(node, include_dynamic_attributes=True)
    # Expected behavior:
    # - From the xpath, expect "html > body > div"
    # - Then append ".test" from the class attribute
    # - Then append [id="myid"] for the id attribute.
    expected_selector = 'html > body > div.test[id="myid"]'
    assert enhanced_selector == expected_selector
@pytest.mark.asyncio
async def test_get_initial_state_with_dummy_page():
    """
    Test that _get_initial_state returns the correct initial BrowserState
    when provided with a dummy page object. This ensures that the initial state
    correctly contains the dummy page's URL and a root element with expected default values.
    """
    # Create a dummy browser to pass to BrowserContext.
    class DummyBrowser:
        async def get_playwright_browser(self):
            class DummyPlaywrightBrowser:
                contexts = []
                async def new_context(self, **kwargs):
                    return None
            return DummyPlaywrightBrowser()
    config = BrowserContextConfig()
    bc = BrowserContext(DummyBrowser(), config)
    # Create a dummy page with a url attribute.
    class DummyPage:
        url = "http://dummy.url"
    dummy_page = DummyPage()
    state: BrowserState = bc._get_initial_state(dummy_page)
    assert state.url == "http://dummy.url"
    assert state.title == ""
    assert state.screenshot is None
    assert state.tabs == []
    assert state.selector_map == {}
    # Check that the element tree is a DOMElementNode with the expected defaults.
    assert isinstance(state.element_tree, DOMElementNode)
    assert state.element_tree.tag_name == "root"
@pytest.mark.asyncio
async def test_reset_context_properly_resets_state():
    """
    Test that reset_context correctly closes all existing pages,
    creates a new page, and resets the cached state.
    """
    # Dummy implementations for page and context.
    class DummyPage:
        def __init__(self, id):
            self.id = id
            self.closed = False
            self.url = f"http://dummy.url/{id}"
        async def close(self):
            self.closed = True
        async def wait_for_load_state(self, state="load"):
            pass
        async def bring_to_front(self):
            pass
        async def evaluate(self, script, *args, **kwargs):
            return "result"
        async def title(self):
            return f"Title {self.id}"
    class DummyContext:
        def __init__(self):
            self.pages = [DummyPage(1), DummyPage(2)]
        async def new_page(self):
            new_page = DummyPage(3)
            # Replace the pages list with the new page.
            self.pages = [new_page]
            return new_page
    # Create a dummy browser that returns a dummy playwright browser.
    class DummyBrowser:
        async def get_playwright_browser(self):
            class DummyPlaywrightBrowser:
                contexts = []
                async def new_context(self, **kwargs):
                    return None
            return DummyPlaywrightBrowser()
    # Initialize a dummy context and a session.
    dummy_context = DummyContext()
    current_page = dummy_context.pages[0]
    initial_state = BrowserState(
        element_tree=DOMElementNode(
            tag_name='root',
            is_visible=True,
            parent=None,
            xpath='',
            attributes={},
            children=[]
        ),
        selector_map={},
        url=current_page.url,
        title="dummy",
        screenshot=None,
        tabs=[]
    )
    session = BrowserSession(
        context=dummy_context,
        current_page=current_page,
        cached_state=initial_state,
    )
    # Create a BrowserContext and assign our dummy session.
    config = BrowserContextConfig()
    bc = BrowserContext(DummyBrowser(), config)
    bc.session = session
    # Store original pages references to verify they get closed.
    old_pages = list(dummy_context.pages)
    # Call reset_context to perform the cleanup and re-initialization.
    await bc.reset_context()
    # Verify that all the old pages were closed.
    for page in old_pages:
        assert page.closed is True, f"Old page {page.id} should be closed."
    # Verify that a new page was created and set as the current page.
    new_page = bc.session.current_page
    assert new_page is not None, "A new current page should have been created."
    # The new current page should come from dummy_context.pages.
    assert new_page == dummy_context.pages[0], "The new page should be the first page in the context."
    # Verify that the cached state was reset. _get_initial_state without page returns an empty URL.
    assert bc.session.cached_state.url == "", "Cached state URL should be reset to an empty string."
@pytest.mark.asyncio
async def test_save_cookies_saves_correctly(tmp_path):
    """
    Test that save_cookies correctly saves cookies to file when a cookies_file is specified.
    A dummy context is used that returns a sample cookie. After running save_cookies,
    the file is read and its content is verified.
    """
    # Create a temporary cookies file path
    cookies_file = tmp_path / "cookies.json"
    # Dummy context that simulates the async cookies() method
    class DummyContext:
        async def cookies(self):
            return [{'name': 'cookie_name', 'value': 'cookie_value'}]
    # Dummy Page which provides a url attribute
    class DummyPage:
        url = "http://dummy.url"
    dummy_page = DummyPage()
    # Create initial dummy BrowserState for the session
    initial_state = BrowserState(
        element_tree=DOMElementNode(
            tag_name='root',
            is_visible=True,
            parent=None,
            xpath='',
            attributes={},
            children=[]
        ),
        selector_map={},
        url=dummy_page.url,
        title="",
        screenshot=None,
        tabs=[]
    )
    # Dummy browser just to support the instantiation of BrowserContext
    class DummyBrowser:
        async def get_playwright_browser(self):
            # Return a dummy object with an empty contexts list.
            class DummyPlaywrightBrowser:
                contexts = []
                async def new_context(self, **kwargs):
                    return None
            return DummyPlaywrightBrowser()
    # Setup config to specify a cookies file
    config = BrowserContextConfig(cookies_file=str(cookies_file))
    bc = BrowserContext(DummyBrowser(), config)
    # Assign a dummy session with our DummyContext.
    dummy_context = DummyContext()
    bc.session = BrowserSession(
        context=dummy_context,
        current_page=dummy_page,
        cached_state=initial_state
    )
    # Call save_cookies.
    await bc.save_cookies()
    # Verify that the cookies file exists and contains the expected data.
    assert os.path.exists(cookies_file)
    with open(cookies_file, 'r') as f:
        saved_data = json.load(f)
    assert isinstance(saved_data, list)
    assert saved_data == [{'name': 'cookie_name', 'value': 'cookie_value'}]
@pytest.mark.asyncio
async def test_execute_javascript_returns_expected_result():
    """
    Test that execute_javascript correctly evaluates JavaScript code
    on a dummy page and returns the expected result.
    """
    # Create a dummy page with an evaluate method.
    class DummyPage:
        url = "http://dummy.url"
        async def evaluate(self, script):
            # For simple script, return expected result.
            if "2+2" in script:
                return 4
            return None
        async def wait_for_load_state(self, state="load"):
            pass
    # Create a dummy context (only used for session, does not need full implementation).
    class DummyContext:
        pages = []
    dummy_page = DummyPage()
    dummy_context = DummyContext()
    # Create an initial BrowserState using the dummy page for the session.
    initial_state = BrowserState(
        element_tree=DOMElementNode(
            tag_name='root',
            is_visible=True,
            parent=None,
            xpath='',
            attributes={},
            children=[]
        ),
        selector_map={},
        url=dummy_page.url,
        title="",
        screenshot=None,
        tabs=[]
    )
    # Create a dummy browser that supports the instantiation of BrowserContext.
    class DummyBrowser:
        async def get_playwright_browser(self):
            # Return a dummy object with an empty contexts list.
            class DummyPlaywrightBrowser:
                contexts = []
            return DummyPlaywrightBrowser()
    config = BrowserContextConfig()
    bc = BrowserContext(DummyBrowser(), config)
    # Manually assign a dummy session with our DummyContext and DummyPage.
    bc.session = BrowserSession(
        context=dummy_context,
        current_page=dummy_page,
        cached_state=initial_state
    )
    # Call execute_javascript with a script that computes 2+2.
    result = await bc.execute_javascript("return 2+2;")
    assert result == 4, "The evaluated JavaScript should return 4."
@pytest.mark.asyncio
async def test_take_screenshot_returns_base64_encoded_string():
    """
    Test that take_screenshot returns a correctly base64 encoded string.
    A DummyPage with a dummy screenshot method is used to simulate the screenshot bytes.
    """
    class DummyPage:
        url = "http://dummy.url"
        async def screenshot(self, full_page=False, animations=None):
            # Return dummy bytes representing screenshot data.
            return b"dummydata"
        async def wait_for_load_state(self, state="load"):
            pass
    class DummyContext:
        pages = []
        async def new_page(self):
            new_page = DummyPage()
            self.pages = [new_page]
            return new_page
    class DummyBrowser:
        async def get_playwright_browser(self):
            # Return a dummy playwright browser with empty contexts list.
            class DummyPlaywrightBrowser:
                contexts = []
            return DummyPlaywrightBrowser()
    # Create a dummy page and dummy context with a single page.
    dummy_page = DummyPage()
    dummy_context = DummyContext()
    dummy_context.pages = [dummy_page]
    initial_state = BrowserState(
        element_tree=DOMElementNode(
            tag_name="root",
            is_visible=True,
            parent=None,
            xpath='',
            attributes={},
            children=[]
        ),
        selector_map={},
        url=dummy_page.url,
        title="",
        screenshot=None,
        tabs=[]
    )
    session = BrowserSession(
        context=dummy_context,
        current_page=dummy_page,
        cached_state=initial_state,
    )
    config = BrowserContextConfig()
    bc = BrowserContext(DummyBrowser(), config)
    bc.session = session
    # Call take_screenshot and verify its base64-encoded output.
    result = await bc.take_screenshot(full_page=True)
    expected_encoded = base64.b64encode(b"dummydata").decode("utf-8")
    assert result == expected_encoded, "The base64 encoded screenshot should match expected output."
@pytest.mark.asyncio
async def test_remove_highlights_handles_exception():
    """
    Test that remove_highlights gracefully handles errors
    when the page.evaluate call fails (simulated by raising an exception).
    """
    # Define a dummy page that raises an exception on evaluate.
    class DummyPage:
        async def evaluate(self, script):
            raise Exception("Simulated evaluate error")
        async def wait_for_load_state(self, state="load"):
            pass
    
    dummy_page = DummyPage()
    
    # Create a dummy context for the BrowserSession.
    class DummyContext:
        pages = []
    
    dummy_context = DummyContext()
    
    # Create an initial BrowserState with a root element.
    root_element = DOMElementNode(
        tag_name="root",
        is_visible=True,
        parent=None,
        xpath="",
        attributes={},
        children=[]
    )
    initial_state = BrowserState(
        element_tree=root_element,
        selector_map={},
        url="http://dummy.url",
        title="",
        screenshot=None,
        tabs=[]
    )
    
    # Create a dummy session using the dummy context and dummy page.
    session = BrowserSession(
        context=dummy_context,
        current_page=dummy_page,
        cached_state=initial_state,
    )
    
    # Create a dummy browser to support BrowserContext instantiation.
    class DummyBrowser:
        async def get_playwright_browser(self):
            class DummyPlaywrightBrowser:
                contexts = []
            return DummyPlaywrightBrowser()
    
    config = BrowserContextConfig()
    bc = BrowserContext(DummyBrowser(), config)
    bc.session = session
    
    # Call remove_highlights.
    # Even though DummyPage.evaluate() raises an Exception,
    # remove_highlights should catch it so that no exception bubbles up.
    await bc.remove_highlights()
    
    # If no exception is raised the test passes.
    assert True  # Test passes if no exception is thrown.
@pytest.mark.asyncio
async def test_is_file_uploader_detects_file_input():
    """
    Test that is_file_uploader correctly detects file input elements.
    This verifies the method correctly identifies:
    - A DOMElementNode that is an <input type="file"> returns True.
    - A non-file input element returns False.
    - A parent element containing a nested file input is detected as a file uploader.
    """
    # Dummy browser class needed for BrowserContext instantiation.
    class DummyBrowser:
        async def get_playwright_browser(self):
            class DummyPlaywrightBrowser:
                contexts = []
            return DummyPlaywrightBrowser()
    config = BrowserContextConfig()
    bc = BrowserContext(DummyBrowser(), config)
    # Case 1: Direct file input element.
    direct_file_input = DOMElementNode(
        tag_name="input",
        is_visible=True,
        parent=None,
        xpath="/html/body/input",
        attributes={"type": "file"},
        children=[]
    )
    result_direct = await bc.is_file_uploader(direct_file_input)
    assert result_direct is True, "Direct file input should be detected as a file uploader."
    # Case 2: An element that is not a file uploader.
    non_file_element = DOMElementNode(
        tag_name="div",
        is_visible=True,
        parent=None,
        xpath="/html/body/div",
        attributes={},
        children=[]
    )
    result_non_file = await bc.is_file_uploader(non_file_element)
    assert result_non_file is False, "An element without file input should not be detected as a file uploader."
    # Case 3: A parent element containing a nested file input element.
    nested_file_input = DOMElementNode(
        tag_name="input",
        is_visible=True,
        parent=None,
        xpath="/html/body/div/input",
        attributes={"type": "file"},
        children=[]
    )
    parent_with_nested = DOMElementNode(
        tag_name="div",
        is_visible=True,
        parent=None,
        xpath="/html/body/div",
        attributes={},
        children=[nested_file_input]
    )
    # Establish parent-child relationship.
    nested_file_input.parent = parent_with_nested
    result_nested = await bc.is_file_uploader(parent_with_nested)
    assert result_nested is True, "A parent containing a nested file input should be detected as a file uploader."
@pytest.mark.asyncio
async def test_create_new_tab_navigates_to_allowed_url():
    """
    Test that create_new_tab correctly creates a new tab and navigates to the given allowed URL.
    This verifies that the new page is properly created, appended to the dummy context,
    and its URL is set via the goto call.
    """
    # Define dummy implementations for page and context.
    class DummyPage:
        def __init__(self, url=""):
            self.url = url
            self.load_state_called = False
        async def wait_for_load_state(self, state="load"):
            self.load_state_called = True
        async def goto(self, url):
            self.url = url
        async def title(self):
            return "Dummy Title"
    class DummyContext:
        def __init__(self):
            self.pages = []
        async def new_page(self):
            new_page = DummyPage()
            self.pages.append(new_page)
            return new_page
    class DummyBrowser:
        async def get_playwright_browser(self):
            # Return a dummy object to satisfy the BrowserContext requirements.
            class DummyPlaywrightBrowser:
                contexts = []
            return DummyPlaywrightBrowser()
    # Configure the allowed_domains to include the dummy domain.
    config = BrowserContextConfig(allowed_domains=["dummy.url"])
    bc = BrowserContext(DummyBrowser(), config)
    # Manually assign a dummy session with a dummy context and an initial dummy page.
    dummy_ctx = DummyContext()
    initial_page = DummyPage(url="http://dummy.url/original")
    initial_state = bc._get_initial_state(initial_page)
    bc.session = BrowserSession(
        context=dummy_ctx,
        current_page=initial_page,
        cached_state=initial_state
    )
    # Call create_new_tab with an allowed URL.
    allowed_url = "http://dummy.url/newtab"
    await bc.create_new_tab(allowed_url)
    # Verify that a new page was created and set as the current page.
    new_page = bc.session.current_page
    # Since DummyPage.goto simply sets its URL, we can assert that URL was updated.
    assert new_page.url == allowed_url, "The new tab should navigate to the allowed URL provided."
@pytest.mark.asyncio
async def test_click_element_node_success():
    """
    Test that _click_element_node correctly performs a click action on a dummy DOMElementNode.
    This test simulates a scenario where the element is located successfully and its click method is invoked.
    """
    # Create a dummy DOMElementNode representing a button.
    dummy_node = DOMElementNode(
        tag_name="button",
        is_visible=True,
        parent=None,
        xpath="/html/body/button",
        attributes={},
        children=[]
    )
    # Create a dummy ElementHandle that simulates a successful click.
    class DummyElementHandle:
        def __init__(self):
            self.clicked = False
        async def click(self, timeout):
            self.clicked = True
        async def scroll_into_view_if_needed(self, timeout=None):
            pass
    dummy_element_handle = DummyElementHandle()
    # Create a dummy page that includes the required methods.
    class DummyPage:
        url = "http://dummy.url"
        async def wait_for_load_state(self, state="load"):
            pass
        async def evaluate(self, script, *args):
            # This fallback click method should not be needed if click() succeeds.
            return None
    dummy_page = DummyPage()
    # Create a dummy context with the dummy page.
    class DummyContext:
        pages = [dummy_page]
    dummy_context = DummyContext()
    # Create an initial BrowserState.
    initial_state = BrowserState(
        element_tree=DOMElementNode(
            tag_name="root",
            is_visible=True,
            parent=None,
            xpath="",
            attributes={},
            children=[]
        ),
        selector_map={},
        url=dummy_page.url,
        title="",
        screenshot=None,
        tabs=[]
    )
    # Create a dummy browser that returns a dummy playwright browser.
    class DummyBrowser:
        async def get_playwright_browser(self):
            class DummyPlaywrightBrowser:
                contexts = []
            return DummyPlaywrightBrowser()
    # Configure allowed_domains to include "dummy.url".
    config = BrowserContextConfig(allowed_domains=["dummy.url"])
    bc = BrowserContext(DummyBrowser(), config)
    # Manually create a session with our dummy context and page.
    bc.session = BrowserSession(
        context=dummy_context,
        current_page=dummy_page,
        cached_state=initial_state
    )
    # Monkeypatch get_locate_element to return our dummy_element_handle.
    async def dummy_get_locate_element(element):
        return dummy_element_handle
    bc.get_locate_element = dummy_get_locate_element
    # Call _click_element_node on the dummy DOMElementNode.
    result = await bc._click_element_node(dummy_node)
    # Verify that the dummy element handle's click method was invoked.
    assert dummy_element_handle.clicked is True, "The element handle's click() should have been called."
    # Since no download is simulated, the result should be None.
    assert result is None