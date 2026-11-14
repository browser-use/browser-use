"""MCP client and server integrations for browser-use."""

from typing import TYPE_CHECKING

from browser_use.mcp.client import MCPClient

if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer

__all__ = ['MCPClient']
