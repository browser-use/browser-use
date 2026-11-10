"""MCP server for coding agents: `browser-use --cli-mcp` (browser-harness exec model)."""

from typing import TYPE_CHECKING

if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer
