"""Compatibility shims for the MCP Python SDK 1.x and 2.x.

mcp 2.0 removed the ``@server.list_tools()`` / ``@server.call_tool()`` decorator
registration API in favor of handler callbacks passed to the ``Server``
constructor, and renamed pydantic model attributes from camelCase to
snake_case (e.g. ``Tool.inputSchema`` -> ``Tool.input_schema``,
``CallToolResult.isError`` -> ``CallToolResult.is_error``). Constructor
keyword aliases (``inputSchema=...``, ``isError=...``) are still accepted by
2.x, so only handler registration and attribute reads need shims.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import mcp.types as types
from mcp.server import Server

MCP_SDK_V2 = not hasattr(Server, 'call_tool')
"""True when the installed MCP SDK is >= 2.0 (decorator registration removed)."""

ListToolsFn = Callable[[], Awaitable[list[types.Tool]]]
CallToolFn = Callable[[str, dict[str, Any] | None], Awaitable[list[Any]]]
ListResourcesFn = Callable[[], Awaitable[list[types.Resource]]]
ListPromptsFn = Callable[[], Awaitable[list[types.Prompt]]]


def create_server(
	name: str,
	*,
	list_tools: ListToolsFn,
	call_tool: CallToolFn,
	list_resources: ListResourcesFn | None = None,
	list_prompts: ListPromptsFn | None = None,
) -> Server:
	"""Create a low-level MCP ``Server`` with handlers registered for either SDK major version.

	Handlers use the mcp 1.x shapes regardless of the installed SDK: the list
	handlers take no arguments and return a plain list, and ``call_tool`` takes
	``(name, arguments)`` and returns a list of content blocks. Under mcp 2.x
	they are adapted to the constructor-callback API (request context + params
	in, result models out).
	"""
	if MCP_SDK_V2:

		async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
			return types.ListToolsResult(tools=await list_tools())

		async def on_call_tool(ctx: Any, params: Any) -> types.CallToolResult:
			content = await call_tool(params.name, params.arguments)
			return types.CallToolResult.model_validate({'content': content, 'isError': False})

		handlers: dict[str, Any] = {'on_list_tools': on_list_tools, 'on_call_tool': on_call_tool}

		if list_resources is not None:

			async def on_list_resources(ctx: Any, params: Any) -> types.ListResourcesResult:
				return types.ListResourcesResult(resources=await list_resources())

			handlers['on_list_resources'] = on_list_resources

		if list_prompts is not None:

			async def on_list_prompts(ctx: Any, params: Any) -> types.ListPromptsResult:
				return types.ListPromptsResult(prompts=await list_prompts())

			handlers['on_list_prompts'] = on_list_prompts

		return Server(name, **handlers)

	# mcp 1.x: handlers are registered through decorators, which are plain
	# callables, so they can be applied directly.
	server = Server(name)
	for decorator_name, handler in (
		('list_resources', list_resources),
		('list_prompts', list_prompts),
		('list_tools', list_tools),
		('call_tool', call_tool),
	):
		if handler is not None:
			getattr(server, decorator_name)()(handler)
	return server


def make_tool(
	name: str,
	description: str | None = None,
	input_schema: dict[str, Any] | None = None,
	read_only_hint: bool = False,
) -> types.Tool:
	"""Construct a ``types.Tool`` in a way that type-checks under both mcp 1.x and 2.x.

	Both SDKs accept the camelCase JSON-schema keys at validation time (they are
	the field names in 1.x and the validation aliases in 2.x), so building from a
	dict sidesteps the renamed constructor keyword arguments (``inputSchema`` ->
	``input_schema``, ``readOnlyHint`` -> ``read_only_hint``).
	"""
	payload: dict[str, Any] = {'name': name}
	if description is not None:
		payload['description'] = description
	if input_schema is not None:
		payload['inputSchema'] = input_schema
	if read_only_hint:
		payload['annotations'] = {'readOnlyHint': True}
	return types.Tool.model_validate(payload)


def make_image_content(data: str, mime_type: str = 'image/png') -> types.ImageContent:
	"""Construct a ``types.ImageContent`` that type-checks under both mcp 1.x and 2.x (see :func:`make_tool`)."""
	return types.ImageContent.model_validate({'type': 'image', 'data': data, 'mimeType': mime_type})


def get_input_schema(tool: Any) -> dict[str, Any]:
	"""Return an MCP tool's JSON input schema (``input_schema`` in 2.x, ``inputSchema`` in 1.x)."""
	return getattr(tool, 'input_schema', None) or getattr(tool, 'inputSchema', None) or {}


def is_error_result(result: Any) -> bool:
	"""Return whether a ``CallToolResult`` reports an error (``is_error`` in 2.x, ``isError`` in 1.x)."""
	is_error = getattr(result, 'is_error', None)
	if is_error is None:
		is_error = getattr(result, 'isError', False)
	return bool(is_error)
