import asyncio
import base64
import gc
import json
import logging
import os
import pytest
import re
import time
import uuid
from browser_use.browser.context import (
    BrowserContext,
    BrowserContextConfig,
)
from browser_use.browser.views import (
    BrowserError,
    BrowserState,
    TabInfo,
    URLNotAllowedError,
)
from browser_use.dom.service import (
    DomService,
)
from browser_use.dom.views import (
    DOMElementNode,
    SelectorMap,
)
from browser_use.utils import (
    time_execution_async,
    time_execution_sync,
)
from dataclasses import (
    dataclass,
    field,
)
from pathlib import (
    Path,
)
from playwright._impl._errors import (
    TimeoutError,
)
from playwright.async_api import (
    Browser,
    ElementHandle,
    FrameLocator,
    Page,
)
from typing import (
    Optional,
    TypedDict,
)
from unittest.mock import (
    Mock,
)


def test_is_url_allowed():
    """
    Test _is_url_allowed to verify that it correctly checks URLs against allowed domains.
    """
    dummy_browser = Mock()
    dummy_browser.config = Mock()
    config1 = BrowserContextConfig(allowed_domains=None)
    context1 = BrowserContext(browser=dummy_browser, config=config1)
    assert context1._is_url_allowed("http://anydomain.com") is True
    assert context1._is_url_allowed("https://anotherdomain.org/path") is True
    allowed = ["example.com", "mysite.org"]
    config2 = BrowserContextConfig(allowed_domains=allowed)
    context2 = BrowserContext(browser=dummy_browser, config=config2)
    assert context2._is_url_allowed("http://example.com") is True
    assert context2._is_url_allowed("http://sub.example.com/path") is True
    assert context2._is_url_allowed("http://notexample.com") is False
    assert context2._is_url_allowed("https://mysite.org/page") is True
    assert context2._is_url_allowed("http://example.com:8080") is True
    assert context2._is_url_allowed("notaurl") is False


def test_convert_simple_xpath_to_css_selector():
    """
    Test converting a simple XPath to a CSS selector.
    """
    assert BrowserContext._convert_simple_xpath_to_css_selector("") == ""
    xpath = "/html/body/div/span"
    expected = "html > body > div > span"
    result = BrowserContext._convert_simple_xpath_to_css_selector(xpath)
    assert result == expected
    xpath = "/html/body/div[2]/span"
    expected = "html > body > div:nth-of-type(2) > span"
    result = BrowserContext._convert_simple_xpath_to_css_selector(xpath)
    assert result == expected
    xpath = "/ul/li[3]/a[1]"
    expected = "ul > li:nth-of-type(3) > a:nth-of-type(1)"
    result = BrowserContext._convert_simple_xpath_to_css_selector(xpath)
    assert result == expected


def test_get_initial_state():
    """
    Test the _get_initial_state functionality by patching BrowserContext with a dummy version.
    """
    dummy_browser = Mock()
    dummy_browser.config = Mock()
    context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
    context._get_initial_state = dummy_get_initial_state

    class DummyPage:
        url = "http://dummy.com"

    dummy_page = DummyPage()
    state_with_page = context._get_initial_state(page=dummy_page)
    assert state_with_page.url == dummy_page.url
    assert state_with_page.element_tree.tag_name == "root"
    state_without_page = context._get_initial_state()
    assert state_without_page.url == ""


@pytest.mark.asyncio
async def test_execute_javascript():
    """
    Test the execute_javascript method by mocking the current page's evaluate function.
    """

    class DummyPage:

        async def evaluate(self, script):
            return "dummy_result"

    DummyContext = type("DummyContext", (), {})
    dummy_context = DummyContext()
    dummy_context.pages = [DummyPage()]
    dummy_session = type("DummySession", (), {})()
    dummy_session.current_page = dummy_context.pages[0]
    dummy_session.context = dummy_context
    dummy_browser = Mock()
    dummy_browser.config = Mock()
    context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
    context._get_initial_state = dummy_get_initial_state
    context.session = dummy_session
    result = await context.execute_javascript("return 1+1")
    assert result == "dummy_result"


@pytest.mark.asyncio
async def test_enhanced_css_selector_for_element():
    """
    Test _enhanced_css_selector_for_element for a dummy DOMElementNode.
    """
    dummy_element = DOMElementNode(
        tag_name="div",
        is_visible=True,
        parent=None,
        xpath="/html/body/div[2]",
        attributes={
            "class": "foo bar",
            "id": "my-id",
            "placeholder": 'some "quoted" text',
            "data-testid": "123",
        },
        children=[],
    )
    actual_selector = BrowserContext._enhanced_css_selector_for_element(
        dummy_element, include_dynamic_attributes=True
    )
    expected_selector = 'html > body > div:nth-of-type(2).foo.bar[id="my-id"][placeholder*="some \\"quoted\\" text"][data-testid="123"]'
    assert (
        actual_selector == expected_selector
    ), f"Expected {expected_selector}, but got {actual_selector}"


@pytest.mark.asyncio
async def test_get_scroll_info():
    """
    Test get_scroll_info by mocking page.evaluate results.
    """

    class DummyPage:

        async def evaluate(self, script):
            if "window.scrollY" in script:
                return 100
            elif "window.innerHeight" in script:
                return 500
            elif "document.documentElement.scrollHeight" in script:
                return 1200
            return None

    dummy_session = type("DummySession", (), {})()
    dummy_page = DummyPage()
    DummyContext = type("DummyContext", (), {})
    dummy_context = DummyContext()
    dummy_context.pages = [dummy_page]
    dummy_session.current_page = dummy_page
    dummy_session.context = dummy_context
    dummy_browser = Mock()
    dummy_browser.config = Mock()
    context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
    context._get_initial_state = dummy_get_initial_state
    context.session = dummy_session
    pixels_above, pixels_below = await context.get_scroll_info(dummy_page)
    assert pixels_above == 100, f"Expected 100 pixels above, got {pixels_above}"
    assert pixels_below == 600, f"Expected 600 pixels below, got {pixels_below}"


@pytest.mark.asyncio
async def test_reset_context():
    """
    Test reset_context to ensure it closes all existing pages, resets state,
    and (simulated in the test) creates a new page, then updates cached_state.
    """

    class DummyPage:

        def __init__(self, url="http://dummy.com"):
            self.url = url
            self.closed = False

        async def close(self):
            self.closed = True

        async def wait_for_load_state(self):
            pass

    class DummyContext:

        def __init__(self):
            self.pages = []

        async def new_page(self):
            new_page = DummyPage(url="")
            self.pages.append(new_page)
            return new_page

    dummy_session = type("DummySession", (), {})()
    dummy_context = DummyContext()
    page1 = DummyPage(url="http://page1.com")
    page2 = DummyPage(url="http://page2.com")
    dummy_context.pages.extend([page1, page2])
    dummy_session.context = dummy_context
    dummy_session.current_page = page1
    dummy_session.cached_state = None
    dummy_browser = Mock()
    dummy_browser.config = Mock()
    context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
    context._get_initial_state = dummy_get_initial_state
    context.session = dummy_session
    assert len(dummy_session.context.pages) == 2
    await context.reset_context()
    assert page1.closed is True
    assert page2.closed is True
    new_page = await dummy_context.new_page()
    dummy_session.current_page = new_page
    dummy_session.cached_state = context._get_initial_state(page=new_page)
    assert new_page.url == ""
    state = dummy_session.cached_state
    assert isinstance(state, BrowserState)
    assert state.url == ""
    assert state.element_tree.tag_name == "root"


@pytest.mark.asyncio
async def test_take_screenshot():
    """
    Test take_screenshot returns a base64 encoded string using a dummy page.
    """

    class DummyPage:

        async def bring_to_front(self):
            pass

        async def wait_for_load_state(self):
            pass

        async def screenshot(self, full_page, animations):
            assert full_page is True, "full_page parameter not forwarded as expected"
            assert (
                animations == "disabled"
            ), "animations parameter not forwarded as expected"
            return b"test"

    dummy_page = DummyPage()
    dummy_session = type("DummySession", (), {})()
    dummy_session.current_page = dummy_page
    DummyContext = type("DummyContext", (), {})
    dummy_context = DummyContext()
    dummy_context.pages = [dummy_page]
    dummy_session.context = dummy_context
    dummy_browser = Mock()
    dummy_browser.config = Mock()
    context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
    context._get_initial_state = dummy_get_initial_state
    context.session = dummy_session
    result = await context.take_screenshot(full_page=True)
    expected = base64.b64encode(b"test").decode("utf-8")
    assert result == expected, f"Expected {expected}, but got {result}"


@pytest.mark.asyncio
async def test_refresh_page_behavior():
    """
    Test refresh_page to verify that the dummy page's reload and wait_for_load_state are called.
    """

    class DummyPage:

        def __init__(self):
            self.reload_called = False
            self.wait_for_load_state_called = False

        async def reload(self):
            self.reload_called = True

        async def wait_for_load_state(self):
            self.wait_for_load_state_called = True

    dummy_page = DummyPage()
    dummy_session = type("DummySession", (), {})()
    dummy_session.current_page = dummy_page
    DummyContext = type("DummyContext", (), {})
    dummy_context = DummyContext()
    dummy_context.pages = [dummy_page]
    dummy_session.context = dummy_context
    dummy_browser = Mock()
    dummy_browser.config = Mock()
    context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
    context._get_initial_state = dummy_get_initial_state
    context.session = dummy_session
    await context.refresh_page()
    assert dummy_page.reload_called is True, "Expected reload() to be called"
    assert (
        dummy_page.wait_for_load_state_called is True
    ), "Expected wait_for_load_state() to be called"


@pytest.mark.asyncio
async def test_remove_highlights_failure():
    """
    Test remove_highlights to ensure errors from evaluate are caught and do not propagate.
    """

    class DummyPage:

        async def evaluate(self, script):
            raise Exception("dummy error")

    dummy_session = type("DummySession", (), {})()
    dummy_session.current_page = DummyPage()
    dummy_session.context = None
    dummy_browser = Mock()
    dummy_browser.config = Mock()
    context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
    context._get_initial_state = dummy_get_initial_state
    context.session = dummy_session
    try:
        await context.remove_highlights()
    except Exception as e:
        pytest.fail(f"remove_highlights raised an exception: {e}")


def dummy_get_initial_state(page=None):
    """
    Returns an initial BrowserState based on a dummy element tree.
    The element_tree is a dummy with tag_name 'root' and url is read from the given page (if any).
    """
    DummyElement = type("DummyElement", (), {})
    dummy_tree = DummyElement()
    dummy_tree.tag_name = "root"
    url = page.url if page and hasattr(page, "url") else ""
    return BrowserState(
        url=url,
        element_tree=dummy_tree,
        selector_map={},
        title="",
        tabs=[],
        screenshot="",
        pixels_above=0,
        pixels_below=0,
    )


@pytest.mark.asyncio
async def test_is_file_uploader():
    """
    Test is_file_uploader to verify that it correctly identifies file input elements,
    both directly and nested within other elements, and returns False for non-file inputs.
    """
    dummy_browser = Mock()
    dummy_browser.config = Mock()
    config = BrowserContextConfig()
    context = BrowserContext(browser=dummy_browser, config=config)
    file_input_node = DOMElementNode(
        tag_name="input",
        is_visible=True,
        parent=None,
        xpath="/html/body/input[1]",
        attributes={"type": "file"},
        children=[],
    )
    result = await context.is_file_uploader(file_input_node)
    assert result is True, "Expected file input to be detected using type='file'"
    file_input_with_accept = DOMElementNode(
        tag_name="input",
        is_visible=True,
        parent=None,
        xpath="/html/body/input[2]",
        attributes={"type": "text", "accept": ".png, .jpg"},
        children=[],
    )
    result = await context.is_file_uploader(file_input_with_accept)
    assert (
        result is True
    ), "Expected file input to be detected with an 'accept' attribute"
    non_file_input = DOMElementNode(
        tag_name="input",
        is_visible=True,
        parent=None,
        xpath="/html/body/input[3]",
        attributes={"type": "text"},
        children=[],
    )
    result = await context.is_file_uploader(non_file_input)
    assert result is False, "Expected non-file input to return False"
    nested_file_input = DOMElementNode(
        tag_name="div",
        is_visible=True,
        parent=None,
        xpath="/html/body/div[1]",
        attributes={},
        children=[
            DOMElementNode(
                tag_name="input",
                is_visible=True,
                parent=None,
                xpath="/html/body/div[1]/input[1]",
                attributes={"type": "file"},
                children=[],
            )
        ],
    )
    result = await context.is_file_uploader(nested_file_input)
    assert (
        result is True
    ), "Expected nested file input to be detected when present in children"
    not_a_dom_node = {"tag_name": "input", "attributes": {"type": "file"}}
    result = await context.is_file_uploader(not_a_dom_node)
    assert result is False, "Expected non-DOMElementNode input to return False"


@pytest.mark.asyncio
async def test_get_unique_filename(tmp_path):
    """
    Test _get_unique_filename to ensure it returns a unique filename when a file already exists.
    The test first verifies that if no file exists, the original filename is returned.
    Then, it creates one or more files and verifies that _get_unique_filename produces a new name.
    """
    dummy_browser = Mock()
    dummy_browser.config = Mock()
    context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
    dir_path = str(tmp_path)
    unique = await context._get_unique_filename(dir_path, "test.txt")
    assert (
        unique == "test.txt"
    ), f"Expected 'test.txt' when file not present, got '{unique}'"
    file_path = tmp_path / "test.txt"
    file_path.write_text("dummy content")
    unique = await context._get_unique_filename(dir_path, "test.txt")
    assert (
        unique == "test (1).txt"
    ), f"Expected 'test (1).txt' when file exists, got '{unique}'"
    file_path2 = tmp_path / "test (1).txt"
    file_path2.write_text("dummy content")
    unique = await context._get_unique_filename(dir_path, "test.txt")
    assert (
        unique == "test (2).txt"
    ), f"Expected 'test (2).txt' when both files exist, got '{unique}'"


@pytest.mark.asyncio
async def test_navigate_to_behavior():
    """
    Test the navigate_to method to verify that:
    1. When given an allowed URL, the dummy page's goto and wait_for_load_state methods are called.
    2. When given a URL not allowed by the configuration, a BrowserError is raised.
    """

    class DummyPage:

        def __init__(self, url=""):
            self.url = url
            self.goto_called_with = None
            self.wait_for_load_state_called = False

        async def goto(self, url):
            self.goto_called_with = url
            self.url = url

        async def wait_for_load_state(self, state="load"):
            self.wait_for_load_state_called = True

    class DummyContext:

        def __init__(self, page):
            self.pages = [page]

    class DummySession:

        def __init__(self, page):
            self.context = DummyContext(page)

    dummy_page = DummyPage(url="http://initial.com")
    dummy_session = DummySession(dummy_page)
    dummy_browser = Mock()
    dummy_browser.config = Mock()
    config = BrowserContextConfig(allowed_domains=["allowed.com"])
    context = BrowserContext(browser=dummy_browser, config=config)
    context.session = dummy_session
    allowed_url = "http://allowed.com"
    await context.navigate_to(allowed_url)
    assert (
        dummy_page.goto_called_with == allowed_url
    ), f"Expected goto to be called with '{allowed_url}', got '{dummy_page.goto_called_with}'"
    assert (
        dummy_page.wait_for_load_state_called is True
    ), "Expected wait_for_load_state to be called"
    disallowed_url = "http://notallowed.com"
    with pytest.raises(BrowserError):
        await context.navigate_to(disallowed_url)


@pytest.mark.asyncio
async def test_get_cdp_targets():
    """
    Test _get_cdp_targets to verify that it returns a list of target infos from a dummy CDP session.
    We simulate a dummy Playwright page context with a new_cdp_session method returning dummy target info.
    This fix ensures the dummy page has a 'context' attribute with the required new_cdp_session method.
    """

    class DummyCDPSession:

        async def send(self, command):
            return {
                "targetInfos": [{"targetId": "dummy_target", "url": "http://dummy.com"}]
            }

        async def detach(self):
            pass

    class DummyContext:

        def __init__(self):
            self.pages = []

        async def new_cdp_session(self, page):
            return DummyCDPSession()

    class DummyPage:

        def __init__(self):
            self.url = "http://dummy.com"
            self.context = None

    dummy_context = DummyContext()
    dummy_page = DummyPage()
    dummy_page.context = dummy_context
    dummy_context.pages.append(dummy_page)
    dummy_session = type("DummySession", (), {})()
    dummy_session.context = dummy_context
    dummy_browser = type("DummyBrowser", (), {})()
    dummy_browser.config = BrowserContextConfig()
    setattr(dummy_browser.config, "cdp_url", "http://dummy-cdp-url")
    context = BrowserContext(browser=dummy_browser, config=dummy_browser.config)
    context.session = dummy_session
    targets = await context._get_cdp_targets()
    expected_targets = [{"targetId": "dummy_target", "url": "http://dummy.com"}]
    assert isinstance(targets, list)
    assert (
        targets == expected_targets
    ), f"Expected {expected_targets}, but got {targets}"


@pytest.mark.asyncio
async def test_click_element_node_with_download(tmp_path):
    """
    Test _click_element_node by simulating a download scenario.
    This test creates dummy implementations for the page's expect_download method,
    a dummy download object, and a dummy element handle, ensuring that _click_element_node
    correctly returns the download path after saving the file.
    """

    class DummyDownload:
        suggested_filename = "download.png"
        saved_path = None

        async def save_as(self, path):
            self.saved_path = path

    class DummyDownloadInfo:

        def __init__(self, value_awaitable):
            self.value = value_awaitable

    class DummyDownloadCM:

        async def __aenter__(self):
            return DummyDownloadInfo(asyncio.sleep(0, result=DummyDownload()))

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class DummyElementHandle:

        async def click(self, timeout, button):
            return None

    class DummyPage:

        def __init__(self):
            self.goto_called_with = None
            self.reload_called = False
            self.wait_for_load_state_called = False

        async def bring_to_front(self):
            pass

        async def wait_for_load_state(self, state="load"):
            self.wait_for_load_state_called = True

        def expect_download(self, timeout):
            return DummyDownloadCM()

        async def evaluate(self, script, arg=None):
            return None

    class DummyContext:

        def __init__(self, page):
            self.pages = [page]

        async def new_page(self):
            new_page = DummyPage()
            self.pages.append(new_page)
            return new_page

    class DummySession:

        def __init__(self, page):
            self.current_page = page
            self.context = DummyContext(page)

    dummy_dom_node = DOMElementNode(
        tag_name="button",
        is_visible=True,
        parent=None,
        xpath="/html/body/button[1]",
        attributes={"id": "download-btn"},
        children=[],
    )
    dummy_element_handle = DummyElementHandle()
    dummy_page = DummyPage()
    dummy_session = DummySession(dummy_page)
    dummy_browser = type("DummyBrowser", (), {})()
    dummy_browser.config = BrowserContextConfig(save_downloads_path=str(tmp_path))
    context = BrowserContext(browser=dummy_browser, config=dummy_browser.config)

    async def dummy_get_locate_element(element):
        return dummy_element_handle

    context.get_locate_element = dummy_get_locate_element

    async def dummy_get_current_page():
        return dummy_page

    context.get_current_page = dummy_get_current_page
    context.session = dummy_session
    download_path = await context._click_element_node(dummy_dom_node, right_click=False)
    expected_path = os.path.join(str(tmp_path), "download.png")
    assert (
        download_path == expected_path
    ), f"Expected download path {expected_path}, got {download_path}"


class DummyPage:

    def __init__(self):
        self.called_wait_for_load_state = False

    async def go_back(self, timeout, wait_until):
        raise Exception("Simulated go_back failure")

    async def go_forward(self, timeout, wait_until):
        raise Exception("Simulated go_forward failure")

    async def wait_for_load_state(self, state="load"):
        self.called_wait_for_load_state = True


class DummyContext:

    def __init__(self, page):
        self.pages = [page]


class DummySession:

    def __init__(self, page):
        self.context = DummyContext(page)
        self.current_page = page


@pytest.mark.asyncio
async def test_go_back_and_go_forward_error_handling():
    """
    Test that BrowserContext.go_back and go_forward properly
    catch exceptions from the page methods and do not propagate errors.
    A DummyPage is used that always raises an exception when calling go_back/go_forward.
    """
    dummy_page = DummyPage()
    dummy_session = DummySession(dummy_page)
    dummy_browser = type("DummyBrowser", (), {})()
    dummy_browser.config = BrowserContextConfig()
    context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
    context.session = dummy_session

    async def dummy_get_current_page():
        return dummy_page

    context.get_current_page = dummy_get_current_page
    try:
        await context.go_back()
    except Exception as exc:
        pytest.fail(f"go_back raised an exception: {exc}")
    try:
        await context.go_forward()
    except Exception as exc:
        pytest.fail(f"go_forward raised an exception: {exc}")


@pytest.mark.asyncio
async def test_input_text_element_node_noncontenteditable():
    """
    Test _input_text_element_node for a non-contenteditable element.
    The test patches get_locate_element to return a dummy element handle,
    and ensures that the fill() method is called with the expected text.
    """

    class DummyElementHandle:

        def __init__(self):
            self.filled_text = None

        async def wait_for_element_state(self, state, timeout):
            pass

        async def scroll_into_view_if_needed(self, timeout=None):
            pass

        async def get_property(self, prop):

            class DummyProperty:

                async def json_value(self):
                    return False

            return DummyProperty()

        async def fill(self, text):
            self.filled_text = text

    dummy_browser = Mock()
    dummy_browser.config = Mock()
    context = BrowserContext(browser=dummy_browser, config=BrowserContextConfig())
    dummy_handle = DummyElementHandle()

    async def dummy_get_locate_element(element: DOMElementNode):
        return dummy_handle

    context.get_locate_element = dummy_get_locate_element
    dummy_element = DOMElementNode(
        tag_name="input",
        is_visible=True,
        parent=None,
        xpath="/html/body/input[1]",
        attributes={"type": "text"},
        children=[],
    )
    test_text = "test input"
    await context._input_text_element_node(dummy_element, test_text)
    assert (
        dummy_handle.filled_text == test_text
    ), f"Expected fill to be called with '{test_text}', got '{dummy_handle.filled_text}'"


@pytest.mark.asyncio
async def test_save_cookies_creates_file(tmp_path):
    """
    Test that save_cookies correctly saves cookies to a file by simulating a dummy session context.
    """
    dummy_cookies = [{"name": "test", "value": "cookie"}]

    class DummyContext:

        async def cookies(self):
            return dummy_cookies

    dummy_context = DummyContext()
    dummy_context.pages = []
    dummy_session = type("DummySession", (), {})()
    dummy_session.context = dummy_context
    cookie_file_path = tmp_path / "cookies.json"
    config = BrowserContextConfig(cookies_file=str(cookie_file_path))
    dummy_browser = Mock()
    dummy_browser.config = config
    context = BrowserContext(browser=dummy_browser, config=config)
    context.session = dummy_session
    await context.save_cookies()
    assert cookie_file_path.exists(), "Cookies file was not created."
    with open(cookie_file_path, "r") as f:
        saved_cookies = json.load(f)
    assert (
        saved_cookies == dummy_cookies
    ), "Saved cookies do not match the expected dummy cookies."


@pytest.mark.asyncio
async def test_update_state_fallback(monkeypatch):
    """
    Test _update_state to verify that when the first (failing) page raises an exception during evaluate,
    BrowserContext falls back to using a working page. This test patches the needed methods to simulate
    dummy clickable elements, screenshots, and scroll info. Also, it sets dummy_browser.config.cdp_url to None
    to prevent attribute errors.
    """

    class DummyFailPage:

        def __init__(self):
            self.url = "http://fail.com"

        async def evaluate(self, script):
            if script == "1":
                raise Exception("Simulated failure")
            return None

        async def wait_for_load_state(self, state="load"):
            pass

        async def bring_to_front(self):
            pass

        async def title(self):
            return "Fail Page"

    class DummyWorkPage:

        def __init__(self):
            self.url = "http://work.com"

        async def evaluate(self, script):
            return 1

        async def wait_for_load_state(self, state="load"):
            pass

        async def bring_to_front(self):
            pass

        async def title(self):
            return "Dummy Title"

    class DummyContext:

        def __init__(self, pages):
            self.pages = pages

        async def new_page(self):
            page = DummyWorkPage()
            self.pages.append(page)
            return page

    fail_page = DummyFailPage()
    work_page = DummyWorkPage()
    dummy_context = DummyContext(pages=[fail_page, work_page])
    dummy_session = type("DummySession", (), {})()
    dummy_session.context = dummy_context
    dummy_browser = type("DummyBrowser", (), {})()
    dummy_browser.config = BrowserContextConfig(allowed_domains=None)
    setattr(dummy_browser.config, "cdp_url", None)
    context = BrowserContext(browser=dummy_browser, config=dummy_browser.config)
    context.session = dummy_session

    async def dummy_remove_highlights():
        return

    monkeypatch.setattr(context, "remove_highlights", dummy_remove_highlights)

    class DummyClickable:
        pass

    dummy_clickable = DummyClickable()
    dummy_clickable.element_tree = type("DummyElementTree", (), {})()
    dummy_clickable.element_tree.tag_name = "dummy"
    dummy_clickable.selector_map = {}

    async def dummy_get_clickable_elements(*args, **kwargs):
        return dummy_clickable

    from browser_use.dom.service import DomService

    monkeypatch.setattr(
        DomService, "get_clickable_elements", dummy_get_clickable_elements
    )

    async def dummy_take_screenshot(full_page=False):
        return "dummy_screenshot_base64"

    monkeypatch.setattr(context, "take_screenshot", dummy_take_screenshot)

    async def dummy_get_scroll_info(page):
        return (10, 20)

    monkeypatch.setattr(context, "get_scroll_info", dummy_get_scroll_info)

    async def dummy_get_current_page():
        return await context._get_current_page(dummy_session)

    monkeypatch.setattr(context, "get_current_page", dummy_get_current_page)
    state = await context._update_state()
    assert (
        state.url == "http://work.com"
    ), f"Expected url 'http://work.com', got '{state.url}'"
    assert (
        state.element_tree.tag_name == "dummy"
    ), "Expected element_tree tag_name to be 'dummy'"
    assert (
        state.screenshot == "dummy_screenshot_base64"
    ), "Expected dummy screenshot base64 string"
    assert (
        state.pixels_above == 10 and state.pixels_below == 20
    ), "Expected scroll info to match dummy values"
