"""
Browser Action Server for Claude Code Integration.

This module provides a HTTP server that allows Claude Code sessions to control
browsers through individual action commands without blocking the terminal.

Architecture:
    Claude Code (chat) → HTTP POST → Browser Action Server → Playwright → HTTP Response → Claude Code

Key Features:
- Non-blocking terminal usage
- Individual action commands  
- Real-time feedback
- Session persistence
- Background operation

Usage:
    from browser_use.action_server import BrowserActionServer
    
    server = BrowserActionServer(port=8766)
    await server.start()  # Runs in background
    
    # In Claude Code chat:
    import httpx
    response = httpx.post("http://localhost:8766/navigate", json={"url": "example.com"})
    print(response.json())
"""

from .service import BrowserActionServer
from .views import (
	NavigateRequest,
	ClickRequest, 
	TypeRequest,
	ScrollRequest,
	WaitRequest,
	ActionResponse,
	ErrorResponse,
	PageStatusResponse,
)

__all__ = [
	'BrowserActionServer',
	'NavigateRequest',
	'ClickRequest',
	'TypeRequest', 
	'ScrollRequest',
	'WaitRequest',
	'ActionResponse',
	'ErrorResponse',
	'PageStatusResponse',
]