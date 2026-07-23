"""Backward-compatible MCP integration.

New integrations should use :class:`browser_use.mcp.client.MCPClient`.
"""

import warnings

from browser_use.mcp.client import MCPClient
from browser_use.tools.registry.service import Registry


class MCPToolWrapper(MCPClient):
	"""Deprecated compatibility adapter for the original registry-based API."""

	def __init__(self, registry: Registry, mcp_command: str, mcp_args: list[str] | None = None):
		"""Initialize the legacy wrapper.

		Args:
			registry: Browser-use action registry to register MCP tools with
			mcp_command: Command used to start the MCP server
			mcp_args: Arguments passed to the MCP server command
		"""
		warnings.warn(
			'MCPToolWrapper is deprecated; use MCPClient.register_to_tools() instead.',
			DeprecationWarning,
			stacklevel=2,
		)
		super().__init__(server_name=mcp_command, command=mcp_command, args=mcp_args)
		self.registry = registry

		# Preserve the original public attribute names for existing callers.
		self.mcp_command = mcp_command
		self.mcp_args = self.args

	async def connect(self) -> None:
		"""Connect to the MCP server and register its tools without blocking."""
		await super().connect()
		await self.register_to_registry(self.registry)


async def register_mcp_tools(registry: Registry, mcp_command: str, mcp_args: list[str] | None = None) -> MCPToolWrapper:
	"""Connect an MCP server and register its tools with a registry.

	Deprecated:
		Use :meth:`MCPClient.register_to_tools` for new integrations.

	Args:
		registry: Browser-use action registry
		mcp_command: Command used to start the MCP server
		mcp_args: Arguments passed to the MCP server command

	Returns:
		A connected compatibility wrapper. Call ``disconnect()`` when finished.
	"""
	wrapper = MCPToolWrapper(registry, mcp_command, mcp_args)
	await wrapper.connect()
	return wrapper
