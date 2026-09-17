
import asyncio
import os
import json
import base64
from unittest.mock import AsyncMock, MagicMock
import pytest
from pathlib import Path

from browser_use.mcp.server import BrowserUseServer
from browser_use.browser.session import BrowserSession

@pytest.mark.asyncio
async def test_browser_screenshot_returns_path_not_blob():
    """Verify that browser_screenshot returns a file path instead of a base64 blob."""
    # Mocking BrowserSession
    mock_session = AsyncMock(spec=BrowserSession)
    mock_session.take_screenshot.return_value = b"fake_screenshot_data"
    mock_session.id = "test_session_screenshot"
    
    mock_state = MagicMock()
    mock_state.page_info = MagicMock()
    mock_state.page_info.viewport_width = 1280
    mock_state.page_info.viewport_height = 720
    mock_session.get_browser_state_summary.return_value = mock_state
    
    server = BrowserUseServer()
    server.browser_session = mock_session
    
    result = await server._execute_tool("browser_screenshot", {"full_page": False})
    
    assert isinstance(result, str)
    data = json.loads(result)
    assert "screenshot_path" in data
    assert os.path.exists(data["screenshot_path"])
    assert data["screenshot_path"].endswith(".png")
    # Ensure no large base64 blob is returned in the text payload (Suggestion C)
    assert "data:image" not in result
    assert len(result) < 10000

@pytest.mark.asyncio
async def test_browser_get_state_returns_path_when_requested():
    """Verify that browser_get_state returns a file path when include_screenshot=True."""
    mock_session = AsyncMock(spec=BrowserSession)
    mock_session.id = "test_session_state"
    
    mock_state = MagicMock()
    mock_state.url = "https://example.com"
    mock_state.title = "Example"
    mock_state.tabs = []
    mock_state.screenshot = base64.b64encode(b"fake_state_screenshot").decode()
    
    pi = MagicMock()
    pi.viewport_width = 1280
    pi.viewport_height = 720
    pi.page_width = 1280
    pi.page_height = 720
    pi.scroll_x = 0
    pi.scroll_y = 0
    mock_state.page_info = pi
    
    ds = MagicMock()
    ds.selector_map = {}
    mock_state.dom_state = ds
    
    mock_session.get_browser_state_summary.return_value = mock_state
    
    server = BrowserUseServer()
    server.browser_session = mock_session
    
    result = await server._execute_tool("browser_get_state", {"include_screenshot": True})
    
    assert isinstance(result, str)
    data = json.loads(result)
    assert "screenshot_path" in data
    assert os.path.exists(data["screenshot_path"])
    # Ensure no large base64 blob is returned in the text payload (Suggestion C)
    assert "data:image" not in result
    assert len(result) < 10000

@pytest.mark.asyncio
async def test_screenshot_cleanup_on_session_close():
    """Verify that screenshots are cleaned up when the session is closed."""
    mock_session = AsyncMock(spec=BrowserSession)
    mock_session.take_screenshot.return_value = b"cleanup_test_data"
    mock_session.id = "cleanup_session"
    
    mock_state = MagicMock()
    pi = MagicMock()
    pi.viewport_width = 1280
    pi.viewport_height = 720
    mock_state.page_info = pi
    mock_session.get_browser_state_summary.return_value = mock_state
    
    server = BrowserUseServer()
    server.browser_session = mock_session
    server.active_sessions["cleanup_session"] = {
        'session': mock_session,
        'created_at': 0,
        'last_activity': 0,
        'url': "https://example.com",
    }
    
    await server._execute_tool("browser_screenshot", {})
    screenshot_path = server.screenshot_files[0]
    assert os.path.exists(screenshot_path)
    
    await server._close_session("cleanup_session")
    assert not os.path.exists(screenshot_path)
