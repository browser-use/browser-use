"""
Browser-Use MCP Server

This module provides a Model Context Protocol (MCP) server that enables
Claude Code to control browser automation through our existing Browser Action Server.

The MCP server acts as a thin wrapper, translating MCP tool calls into HTTP requests
to the Browser Action Server and returning responses in MCP format.
"""

from browser_use.mcp_server.server import BrowserMCPServer

__all__ = ['BrowserMCPServer']