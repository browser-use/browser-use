"""Full-stack protocol round-trip tests for the mcp 2.x migration.

Unlike the handler-level contract tests (test_mcp_handler_contract.py), which call
``server.get_request_handler(...)`` directly and therefore bypass the JSON-RPC
transport, these tests stand up a *real* client↔server pair over in-memory streams
(``mcp.shared.memory.create_client_server_memory_streams``) and drive the canonical
``initialize → list_tools → call_tool → image`` sequence end-to-end.

The point, per issue #5333: "MCP 2.x installs" is not the same claim as "the browser
tool contract survived the protocol upgrade." Dependency resolution can succeed while
the server silently advertises the wrong protocol version, drops capabilities, renames
a schema field, or mangles an image content block on the wire. These tests observe the
*effective* protocol version, capabilities, and content shapes that an MCP client
actually receives, so compatibility is scoped from evidence instead of inferred.

No real browser, daemon, or LLM is needed — browser-touching helpers are stubbed out;
everything under test is the protocol/transport/serialization layer itself.
"""

from dataclasses import dataclass, field

import anyio
import mcp.types as types
import pytest
from mcp import ClientSession
from mcp.server import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.shared.memory import create_client_server_memory_streams

from browser_use.mcp.cli_mcp import CLIMCPServer
from browser_use.mcp.server import BrowserUseServer

# Base64 for b"hello" — a fixed, decodable payload so the image round-trip can assert
# byte fidelity, not just that *some* string survived.
FIXED_IMAGE_B64 = 'aGVsbG8='


@dataclass
class RoundTripEvidence:
	"""Effective protocol facts observed over the wire for one server.

	This is the scoped-compatibility record: rather than asserting "it installed," we
	capture what the negotiated session actually looks like and assert each fact.
	"""

	protocol_version: str
	server_name: str
	server_version: str
	tools_capability_present: bool
	tool_names: list[str] = field(default_factory=list)
	schemas_by_name: dict[str, dict] = field(default_factory=dict)
	annotations_by_name: dict[str, types.ToolAnnotations | None] = field(default_factory=dict)


class _RunningServer:
	"""Drives one MCP server through a real initialize + list_tools + call_tool session."""

	def __init__(self, mcp_server, server_name: str, server_version: str, instructions: str | None = None):
		self._server = mcp_server
		self._server_name = server_name
		self._server_version = server_version
		self._instructions = instructions

	async def run_session(self, drive):
		"""Run server + client; ``drive(session, evidence)`` performs the client calls."""
		async with create_client_server_memory_streams() as (client_streams, server_streams):
			client_read, client_write = client_streams
			server_read, server_write = server_streams

			async def run_server():
				await self._server.run(
					server_read,
					server_write,
					InitializationOptions(
						server_name=self._server_name,
						server_version=self._server_version,
						instructions=self._instructions,
						capabilities=self._server.get_capabilities(
							notification_options=NotificationOptions(),
							experimental_capabilities={},
						),
					),
					raise_exceptions=False,
				)

			async with anyio.create_task_group() as tg:
				tg.start_soon(run_server)
				try:
					async with ClientSession(client_read, client_write) as session:
						init = await session.initialize()
						tools = await session.list_tools()
						evidence = RoundTripEvidence(
							protocol_version=init.protocol_version,
							server_name=init.server_info.name,
							server_version=init.server_info.version,
							tools_capability_present=init.capabilities.tools is not None,
							tool_names=sorted(t.name for t in tools.tools),
							schemas_by_name={t.name: t.input_schema for t in tools.tools},
							annotations_by_name={t.name: t.annotations for t in tools.tools},
						)
						await drive(session, evidence)
				finally:
					tg.cancel_scope.cancel()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cli_running() -> _RunningServer:
	"""CLIMCPServer with the daemon-dependent screenshot helper stubbed out."""
	srv = CLIMCPServer()
	srv._screenshot = lambda full, max_dim: FIXED_IMAGE_B64  # type: ignore[method-assign]
	return _RunningServer(srv.server, server_name='browser-use', server_version='0.0.0-test', instructions=srv._instructions())


@pytest.fixture
def browser_use_running() -> _RunningServer:
	"""BrowserUseServer with browser/LLM-touching internals stubbed out."""
	srv = BrowserUseServer()

	async def _screenshot_stub(full_page: bool = False) -> tuple[str, str | None]:
		return ('{"size_bytes": 5}', FIXED_IMAGE_B64)

	srv._screenshot = _screenshot_stub  # type: ignore[method-assign]
	srv.browser_session = object()  # type: ignore[assignment]  # avoid real browser init
	return _RunningServer(srv.server, server_name='browser-use', server_version='0.0.0-test')


# ---------------------------------------------------------------------------
# Protocol negotiation (effective version + capabilities)
# ---------------------------------------------------------------------------


async def test_cli_negotiates_protocol_version_and_capabilities(cli_running: _RunningServer) -> None:
	async def drive(session: ClientSession, ev: RoundTripEvidence) -> None:
		# A real protocol version string came back from the handshake (not None/empty).
		assert ev.protocol_version, 'handshake must yield a concrete protocol version'
		assert isinstance(ev.protocol_version, str)
		# Server identity round-tripped through initialize.
		assert ev.server_name == 'browser-use'
		assert ev.server_version == '0.0.0-test'
		# The server advertises a tools capability — without it no client would list tools.
		assert ev.tools_capability_present is True

	await cli_running.run_session(drive)


async def test_browser_use_negotiates_protocol_version_and_capabilities(browser_use_running: _RunningServer) -> None:
	async def drive(session: ClientSession, ev: RoundTripEvidence) -> None:
		assert ev.protocol_version
		assert ev.server_name == 'browser-use'
		assert ev.tools_capability_present is True

	await browser_use_running.run_session(drive)


# ---------------------------------------------------------------------------
# Tool list over the wire (schema names + required fields survive serialization)
# ---------------------------------------------------------------------------


async def test_cli_tool_schemas_survive_wire(cli_running: _RunningServer) -> None:
	async def drive(session: ClientSession, ev: RoundTripEvidence) -> None:
		assert ev.tool_names == ['browser_exec', 'browser_screenshot']

		exec_schema = ev.schemas_by_name['browser_exec']
		assert exec_schema['type'] == 'object'
		assert 'code' in exec_schema['properties']
		assert exec_schema['required'] == ['code']

		# The screenshot schema's integer field with a minimum constraint must survive.
		shot_schema = ev.schemas_by_name['browser_screenshot']
		max_dim = shot_schema['properties']['max_dim']
		assert max_dim['type'] == 'integer'
		assert max_dim['minimum'] == 1

	await cli_running.run_session(drive)


async def test_browser_use_tool_schemas_and_annotations_survive_wire(browser_use_running: _RunningServer) -> None:
	async def drive(session: ClientSession, ev: RoundTripEvidence) -> None:
		# Every advertised tool carried a populated input_schema across the wire.
		for name in ev.tool_names:
			assert ev.schemas_by_name[name], f'tool {name!r} lost its input_schema in transit'

		# The image-producing tool is present with its expected schema shape.
		assert 'browser_screenshot' in ev.tool_names
		shot = ev.schemas_by_name['browser_screenshot']
		assert shot['properties']['full_page']['type'] == 'boolean'

		# The read-only annotation set at decoration time must reach the client.
		annotations = ev.annotations_by_name['browser_screenshot']
		assert annotations is not None, 'browser_screenshot lost its ToolAnnotations over the wire'
		assert annotations.read_only_hint is True

	await browser_use_running.run_session(drive)


# ---------------------------------------------------------------------------
# Call round-trip: text result, image result, and structured is_error
# ---------------------------------------------------------------------------


async def test_cli_text_result_round_trip(cli_running: _RunningServer) -> None:
	async def drive(session: ClientSession, ev: RoundTripEvidence) -> None:
		# browser_exec with a real (failing-fast) input: missing/blank code → is_error over the wire.
		result = await session.call_tool('browser_exec', {'code': '   '})
		assert isinstance(result, types.CallToolResult)
		assert result.is_error is True
		text = ''.join(getattr(b, 'text', '') for b in result.content)
		assert 'code' in text

	await cli_running.run_session(drive)


async def test_cli_image_block_round_trips_with_byte_fidelity(cli_running: _RunningServer) -> None:
	async def drive(session: ClientSession, ev: RoundTripEvidence) -> None:
		result = await session.call_tool('browser_screenshot', {})
		assert result.is_error is not True
		assert len(result.content) == 1
		block = result.content[0]
		# The image content block survived serialization as a real ImageContent...
		assert isinstance(block, types.ImageContent)
		# ...with its mime_type intact (this is the field 1.x→2.x is most likely to drop)...
		assert block.mime_type == 'image/png'
		# ...and byte-for-byte identical base64 payload.
		assert block.data == FIXED_IMAGE_B64

	await cli_running.run_session(drive)


async def test_browser_use_mixed_text_and_image_blocks_round_trip(browser_use_running: _RunningServer) -> None:
	async def drive(session: ClientSession, ev: RoundTripEvidence) -> None:
		result = await session.call_tool('browser_screenshot', {})
		assert result.is_error is not True
		texts = [b for b in result.content if isinstance(b, types.TextContent)]
		images = [b for b in result.content if isinstance(b, types.ImageContent)]
		assert texts and texts[0].text == '{"size_bytes": 5}'
		assert images and images[0].data == FIXED_IMAGE_B64
		assert images[0].mime_type == 'image/png'

	await browser_use_running.run_session(drive)


async def test_cli_unknown_tool_is_error_over_wire(cli_running: _RunningServer) -> None:
	async def drive(session: ClientSession, ev: RoundTripEvidence) -> None:
		result = await session.call_tool('no_such_tool', {})
		assert isinstance(result, types.CallToolResult)
		assert result.is_error is True
		text = ''.join(getattr(b, 'text', '') for b in result.content)
		assert 'Unknown tool' in text

	await cli_running.run_session(drive)


async def test_browser_use_unknown_tool_is_error_over_wire(browser_use_running: _RunningServer) -> None:
	async def drive(session: ClientSession, ev: RoundTripEvidence) -> None:
		result = await session.call_tool('no_such_tool', {})
		assert result.is_error is True
		text = ''.join(getattr(b, 'text', '') for b in result.content)
		assert 'Unknown tool' in text

	await browser_use_running.run_session(drive)
