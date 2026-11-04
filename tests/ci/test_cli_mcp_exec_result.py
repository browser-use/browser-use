"""Exercise the MCP result for Python snippets sent to browser_exec."""

import asyncio
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import mcp.types as types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from browser_use.browser import BrowserSession


async def test_browser_exec_reports_snippet_outcome(browser_session: BrowserSession) -> None:
	cdp_url = browser_session.cdp_url
	assert cdp_url is not None

	# A short, isolated path keeps the daemon socket within Unix path limits.
	with TemporaryDirectory(prefix='bu-mcp-') as directory:
		env = {
			**get_default_environment(),
			'ANONYMIZED_TELEMETRY': 'false',
			'BROWSER_USE_CONFIG_DIR': directory,
			'BH_HOME': directory,
			'BH_RUNTIME_DIR': directory,
			'BU_CDP_WS': cdp_url,
			'NO_PROXY': 'localhost,127.0.0.1,::1',
		}
		server = StdioServerParameters(
			command=sys.executable,
			args=['-m', 'browser_use', '--cli-mcp'],
			cwd=Path(__file__).resolve().parents[2],
			env=env,
		)
		try:
			async with stdio_client(server) as (read, write), ClientSession(read, write, read_timeout_seconds=75) as session:
				await session.initialize()
				cases = (
					("assert daemon_alive()\nlist_tabs()\nprint('ok')", False, 'ok\n'),
					('pass', False, '(no output)'),
					("print('before failure')\nraise RuntimeError('snippet failed')", True, 'RuntimeError: snippet failed'),
				)
				for code, is_error, expected_text in cases:
					result = await session.call_tool('browser_exec', {'code': code})
					assert result.is_error is is_error, result.content
					assert len(result.content) == 1
					content = result.content[0]
					assert isinstance(content, types.TextContent)
					if is_error:
						assert content.text.startswith('before failure\nTraceback')
						assert expected_text in content.text
					else:
						assert content.text == expected_text
		finally:
			# The daemon is independent of the stdio process and must be stopped explicitly.
			await asyncio.to_thread(
				subprocess.run,
				[sys.executable, '-c', 'from browser_harness.admin import restart_daemon; restart_daemon()'],
				env=env,
				check=True,
				timeout=25,
			)
