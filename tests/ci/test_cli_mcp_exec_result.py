"""Exercise the MCP result for Python snippets sent to browser_exec."""

import mcp.types as types
import pytest

from browser_use.mcp.cli_mcp import CLIMCPServer


@pytest.mark.parametrize(
	('code', 'is_error', 'expected_text'),
	[
		("print('ok')", False, 'ok\n'),
		('pass', False, '(no output)'),
		("print('before failure')\nraise RuntimeError('snippet failed')", True, 'RuntimeError: snippet failed'),
	],
)
async def test_browser_exec_reports_snippet_outcome(
	monkeypatch: pytest.MonkeyPatch, code: str, is_error: bool, expected_text: str
) -> None:
	server = CLIMCPServer()
	monkeypatch.setattr(server, '_ensure_daemon', lambda code: None)
	monkeypatch.setattr(server, '_namespace', {})
	handler = server.server.get_request_handler('tools/call')
	assert handler is not None

	result = await handler.handler(
		None,  # type: ignore[arg-type]
		types.CallToolRequestParams(name='browser_exec', arguments={'code': code}),
	)

	assert isinstance(result, types.CallToolResult)
	assert result.is_error is is_error
	assert len(result.content) == 1
	assert isinstance(result.content[0], types.TextContent)
	assert expected_text in result.content[0].text
	if is_error:
		assert result.content[0].text.startswith('before failure\nTraceback')
