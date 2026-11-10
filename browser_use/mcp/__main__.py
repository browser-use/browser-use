"""python -m browser_use.mcp: the 0.x module form of `browser-use --mcp`, with the same own Chromium (never the user's
Chrome) and quiet stdout."""

import sys

from browser_use.cli import _run_mcp_server

if __name__ == '__main__':
	sys.exit(_run_mcp_server('python -m browser_use.mcp'))
