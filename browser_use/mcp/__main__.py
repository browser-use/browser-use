"""Entry point for running MCP server as a module.

Usage:
    python -m browser_use.mcp
"""

import asyncio

from browser_use.mcp.server import main

if __name__ == '__main__':
	asyncio.run(main())
