"""python -m browser_use.mcp runs the CLI MCP server."""

import asyncio

from browser_use.mcp.cli_mcp import main

if __name__ == '__main__':
	asyncio.run(main())
