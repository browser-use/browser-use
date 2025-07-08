"""MCP (Model Context Protocol) support for browser-use.

This module provides integration with MCP servers and clients for browser automation.
"""

from browser_use.mcp.client import MCPClient
from browser_use.mcp.controller import MCPToolWrapper
from browser_use.mcp.server import BrowserUseServer

__all__ = ['MCPClient', 'MCPToolWrapper', 'BrowserUseServer']
