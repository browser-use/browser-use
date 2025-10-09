import asyncio
import types
import inspect
import pytest

from unittest.mock import AsyncMock, MagicMock

from browser_use.browser.watchdogs import default_action_watchdog as dah_mod


class DummyCDPClient:
    def __init__(self):
        self.send = MagicMock()


class DummyCDPSession:
    def __init__(self):
        self.cdp_client = DummyCDPClient()
        self.session_id = 'S1'
        self.target_id = 'T1'


class DummyElementNode:
    def __init__(self):
        self.tag_name = 'button'
        self.attributes = {}
        self.backend_node_id = 123
        self.element_index = 1
        self.xpath = '/html/body/button'
        self.absolute_position = types.SimpleNamespace(x=10, y=10, width=20, height=10)


@pytest.mark.asyncio
async def test_click_uses_js_fallback_when_occluded(monkeypatch):
    # Arrange
    watchdog_cls = dah_mod.DefaultActionWatchdog
    # Create a real BrowserSession instance (Pydantic model) and patch CDP helpers
    from browser_use.browser.session import BrowserSession

    browser_session = BrowserSession()

    # Provide a dummy cdp session
    dummy_session = DummyCDPSession()

    async def fake_cdp_client_for_node(node):
        return dummy_session

    # Patch methods on the BrowserSession instance
    # Set attributes bypassing Pydantic validation
    object.__setattr__(browser_session, 'cdp_client_for_node', AsyncMock(side_effect=fake_cdp_client_for_node))
    object.__setattr__(browser_session, 'get_or_create_cdp_session', AsyncMock(return_value=dummy_session))
    # don't assign agent_focus to dummy_session (not a real CDPSession model); let get_or_create_cdp_session return our dummy

    # Prepare the runtime.callFunctionOn to simulate occlusion predicate first, then allow JS click
    # First call: check_script -> return {clickable: False, reason: 'occluded'}
    occlusion_response = {'result': {'value': {'clickable': False, 'reason': 'occluded'}}}
    # Second call (scrollIntoView+click) should succeed and return True
    js_click_response = {'result': {'value': True}}

    # Configure send.Runtime.callFunctionOn to return different results based on input
    async def callFunctionOn_side_effect(*, params=None, session_id=None):
        func = params.get('functionDeclaration', '')
        if 'getBoundingClientRect' in func or 'clickable' in func or 'elementFromPoint' in func:
            return occlusion_response
        if 'this.click' in func:
            return js_click_response
        # default
        return {'result': {'value': {}}}

    # Ensure all CDP domain methods are AsyncMock so they can be awaited
    dummy_session.cdp_client.send.Runtime = MagicMock()
    dummy_session.cdp_client.send.Runtime.callFunctionOn = AsyncMock(side_effect=callFunctionOn_side_effect)
    dummy_session.cdp_client.send.Runtime.evaluate = AsyncMock(return_value={'result': {'value': 'about:blank'}})

    # DOM domain
    dummy_session.cdp_client.send.DOM = MagicMock()
    dummy_session.cdp_client.send.DOM.getContentQuads = AsyncMock(return_value={'quads': [[0, 0, 10, 0, 10, 10, 0, 10]]})
    dummy_session.cdp_client.send.DOM.getBoxModel = AsyncMock(return_value={'model': {'content': [0, 0, 10, 0, 10, 10, 0, 10]}})
    dummy_session.cdp_client.send.DOM.resolveNode = AsyncMock(return_value={'object': {'objectId': 'OBJ1'}})
    dummy_session.cdp_client.send.DOM.scrollIntoViewIfNeeded = AsyncMock(return_value={})

    # Page domain
    dummy_session.cdp_client.send.Page = MagicMock()
    dummy_session.cdp_client.send.Page.getLayoutMetrics = AsyncMock(return_value={'layoutViewport': {'clientWidth': 800, 'clientHeight': 600}})

    # Input domain (mouse events)
    dummy_session.cdp_client.send.Input = MagicMock()
    dummy_session.cdp_client.send.Input.dispatchMouseEvent = AsyncMock(return_value={})

    # Create watchdog instance using the real BrowserSession
    watchdog = watchdog_cls(event_bus=browser_session.event_bus, browser_session=browser_session)

    # Act
    element = DummyElementNode()
    # Call the internal method directly
    result = await watchdog._click_element_node_impl(element, while_holding_ctrl=False)

    # Assert
    # When occluded, our callFunctionOn should have been invoked for the js click fallback
    calls = dummy_session.cdp_client.send.Runtime.callFunctionOn.call_args_list
    called_js_click = any('this.click' in str(call.kwargs.get('params', {}).get('functionDeclaration', '')) for call in calls)
    assert called_js_click, 'JS click fallback was not attempted'
    # The result should either be coordinates dict or None (JS click returns None), so just ensure no exception and function completed
    assert result is None or isinstance(result, dict)
