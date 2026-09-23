"""One Anthropic custom tool over Browser Use's existing Python/CDP executor.

Uses the normal Anthropic SDK dependency, not the browser-toolset helpers::

    import os
    from anthropic import AsyncAnthropic
    from browser_use.integrations.anthropic_code import browser_code_tool


    async def run(task: str):
        async with browser_code_tool(daemon_name='default') as browser_execute:
            async with AsyncAnthropic() as client:
                async for message in client.beta.messages.tool_runner(
                    model=os.environ['ANTHROPIC_MODEL'],
                    max_tokens=4096,
                    max_iterations=30,
                    tools=[browser_execute],
                    messages=[{'role': 'user', 'content': task}],
                ):
                    print(message.content)

The executor is a separate MCP subprocess; Python variables persist per context.
Code runs on the host with normal Python privileges, not in a sandbox or inside
the page. This reuses Browser Harness's Python helpers and raw ``cdp(...)``;
it does not run BrowserCode's JavaScript runtime or a nested Browser Use Agent.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from anthropic.lib.tools import BetaAsyncFunctionTool, BetaFunctionToolResultType, beta_async_tool
from anthropic.types.beta.beta_tool_result_block_param import Content
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult


@asynccontextmanager
async def browser_code_tool(
	*, daemon_name: str = 'default', timeout: float = 60, env: Mapping[str, str] | None = None
) -> AsyncIterator[BetaAsyncFunctionTool[Any]]:
	"""Yield one ``browser_execute`` tool, using the installed CLI MCP backend.

	``daemon_name`` selects the same named daemon as ``BU_NAME`` in Browser
	Harness. The CLI retains its normal daemon startup/reconnection behavior.
	The daemon/browser are borrowed: exiting closes only this MCP subprocess.
	Provision and stop cloud browsers separately using the existing cloud API.
	Use a dedicated daemon/browser per task; Python namespace isolation does
	not isolate two executors controlling the same browser.

	``env`` explicitly forwards extra subprocess settings, such as BU_CDP_URL.
	Each MCP request has a timeout. A transport failure invalidates the tool;
	leave this context to terminate the executor before starting another one.
	A timeout does not roll back browser actions or interrupt running Python
	until the context exits. The runner should have a finite iteration limit.
	"""
	if timeout <= 0:
		raise ValueError('timeout must be positive')
	parameters = StdioServerParameters(
		command=sys.executable,
		args=['-m', 'browser_use.mcp.cli_mcp'],
		env={**(env or {}), 'BU_NAME': daemon_name, 'BH_CLIENT': 'anthropic-sdk'},
	)
	async with stdio_client(parameters) as (read, write), ClientSession(read, write, read_timeout_seconds=timeout) as session:
		initialized = await session.initialize()
		await session.list_tools()
		lock = asyncio.Lock()
		unavailable = False

		async def request(name: str, arguments: dict[str, Any]) -> CallToolResult:
			nonlocal unavailable
			if unavailable:
				raise RuntimeError('Executor is unavailable after a transport failure. Exit this context before retrying.')
			try:
				return await session.call_tool(name, arguments, read_timeout_seconds=timeout)
			except BaseException:
				# A timed-out/cancelled code cell may still be running. Never overlap a retry.
				unavailable = True
				raise

		def content(result: CallToolResult) -> list[Content]:
			blocks: list[Content] = []
			for item in result.content:
				if item.type == 'text':
					blocks.append({'type': 'text', 'text': item.text})
				elif item.type == 'image':
					if item.mime_type not in ('image/png', 'image/jpeg', 'image/gif', 'image/webp'):
						raise RuntimeError(f'Unsupported screenshot media type: {item.mime_type}')
					blocks.append(
						{'type': 'image', 'source': {'type': 'base64', 'media_type': item.mime_type, 'data': item.data}}
					)
				else:
					raise RuntimeError(f'Unsupported executor content type: {item.type}')
			if result.is_error:
				# The pinned Anthropic runner converts exceptions into is_error tool results.
				raise RuntimeError('\n'.join(item.text for item in result.content if item.type == 'text'))
			return blocks

		description = (
			'Execute Python against a persistent Browser Harness/CDP session. '
			'Use print(...) for output; variables persist. Set screenshot=True to receive an image after the code. '
			'This is host Python, not page JavaScript. Start with new_tab(url). '
			'Browser control reference:\n\n' + (initialized.instructions or '')
		)

		@beta_async_tool(description=description)
		async def browser_execute(code: str, screenshot: bool = False) -> BetaFunctionToolResultType:
			"""Execute code and optionally capture the resulting viewport.

			Args:
				code: Python code using pre-imported browser helpers or raw cdp(method, **params).
				screenshot: Return a viewport PNG after successful execution (default false).
			"""
			if not code.strip():
				raise ValueError('code must not be empty')
			async with lock:
				blocks = content(await request('browser_exec', {'code': code}))
				if screenshot:
					try:
						blocks.extend(content(await request('browser_screenshot', {'full': False})))
					except Exception as exc:
						output = '\n'.join(str(block.get('text', '')) for block in blocks)
						raise RuntimeError(
							f'Code completed; screenshot failed. Do not repeat the action blindly.\n{output}\n{exc}'
						) from exc
				return blocks

		try:
			yield browser_execute
		finally:
			unavailable = True
