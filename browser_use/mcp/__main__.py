"""Entry point for running MCP server as a module.

Usage:
    python -m browser_use.mcp
"""

import asyncio
import sys

from browser_use.mcp.server import main, parse_mcp_server_args

if __name__ == '__main__':
	asyncio.run(main(**parse_mcp_server_args(sys.argv[1:])))
