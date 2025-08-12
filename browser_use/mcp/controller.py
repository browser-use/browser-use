"""MCP (Model Context Protocol) tool wrapper for browser-use.

This module provides integration between MCP tools and browser-use's action registry system.
MCP tools are dynamically discovered and registered as browser-use actions.
"""

import asyncio
import logging
from typing import Any

from pydantic import Field, create_model

from browser_use.agent.views import ActionResult
from browser_use.controller.registry.service import Registry

logger = logging.getLogger(__name__)

try:
	from mcp import ClientSession, StdioServerParameters
	from mcp.client.stdio import stdio_client
	from mcp.types import TextContent, Tool

	MCP_AVAILABLE = True
except ImportError:
	MCP_AVAILABLE = False
	logger.warning('MCP SDK not installed. Install with: pip install mcp')


class MCPToolWrapper:
	"""Wrapper to integrate MCP tools as browser-use actions."""

	def __init__(self, registry: Registry, mcp_command: str, mcp_args: list[str] | None = None):
		"""Initialize MCP tool wrapper.

		Args:
			registry: Browser-use action registry to register MCP tools
			mcp_command: Command to start MCP server (e.g., "npx")
			mcp_args: Arguments for MCP command (e.g., ["@playwright/mcp@latest"])
		"""
		if not MCP_AVAILABLE:
			raise ImportError('MCP SDK not installed. Install with: pip install mcp')

		self.registry = registry
		self.mcp_command = mcp_command
		self.mcp_args = mcp_args or []
		self.session: ClientSession | None = None
		self._tools: dict[str, Tool] = {}
		self._registered_actions: set[str] = set()
		self._shutdown_event = asyncio.Event()

	async def connect(self):
		"""Connect to MCP server and discover available tools."""
		if self.session:
			return  # Already connected

		logger.info(f'🔌 Connecting to MCP server: {self.mcp_command} {" ".join(self.mcp_args)}')

		# Create server parameters
		server_params = StdioServerParameters(command=self.mcp_command, args=self.mcp_args, env=None)

		# Connect to the MCP server
		async with stdio_client(server_params) as (read, write):
			async with ClientSession(read, write) as session:
				self.session = session

				# Initialize the connection
				await session.initialize()

				# Discover available tools
				tools_response = await session.list_tools()
				self._tools = {tool.name: tool for tool in tools_response.tools}

				logger.info(f'📦 Discovered {len(self._tools)} MCP tools: {list(self._tools.keys())}')

				# Register all discovered tools as actions
				for tool_name, tool in self._tools.items():
					self._register_tool_as_action(tool_name, tool)

				# Keep session alive while tools are being used
				await self._keep_session_alive()

	async def _keep_session_alive(self):
		"""Keep the MCP session alive."""
		# This will block until the session is closed
		# In practice, you'd want to manage this lifecycle better
		try:
			await self._shutdown_event.wait()
		except asyncio.CancelledError:
			pass

	def _register_tool_as_action(self, tool_name: str, tool: Tool):
		"""Register an MCP tool as a browser-use action.

		Args:
			tool_name: Name of the MCP tool
			tool: MCP Tool object with schema information
		"""
		if tool_name in self._registered_actions:
			return  # Already registered

		# Parse tool parameters to create Pydantic model
		param_fields = {}

		if tool.inputSchema:
			# MCP tools use JSON Schema for parameters
			properties = tool.inputSchema.get('properties', {})
			required = set(tool.inputSchema.get('required', []))

			for param_name, param_schema in properties.items():
				# Convert JSON Schema type to Python type
				param_type = self._json_schema_to_python_type(param_schema)

				# Determine if field is required
				if param_name in required:
					default = ...  # Required field
				else:
					default = param_schema.get('default', None)

				# Add field description if available
				field_kwargs = {}
				if 'description' in param_schema:
					field_kwargs['description'] = param_schema['description']

				param_fields[param_name] = (param_type, Field(default, **field_kwargs))

		# Create Pydantic model for the tool parameters
		param_model = create_model(f'{tool_name}_Params', **param_fields) if param_fields else None

		# Determine if this is a browser-specific tool
		is_browser_tool = tool_name.startswith('browser_')
		domains = None
		# Note: page_filter has been removed since we no longer use Page objects

		# Create wrapper function for the MCP tool
		async def mcp_action_wrapper(**kwargs):
			"""Wrapper function that calls the MCP tool."""
			if not self.session:
				raise RuntimeError(f'MCP session not connected for tool {tool_name}')

			# Extract parameters (excluding special injected params)
			special_params = {
				'page',
				'browser_session',
				'context',
				'page_extraction_llm',
				'file_system',
				'available_file_paths',
				'has_sensitive_data',
				'browser',
				'browser_context',
			}

			tool_params = {k: v for k, v in kwargs.items() if k not in special_params}

			logger.debug(f'🔧 Calling MCP tool {tool_name} with params: {tool_params}')

			try:
				# Call the MCP tool
				result = await self.session.call_tool(tool_name, tool_params)

				# Convert MCP result to ActionResult
				# MCP tools return results in various formats
				if hasattr(result, 'content'):
					# Handle structured content responses
					if isinstance(result.content, list):
						# Multiple content items
						content_parts = []
						for item in result.content:
							if isinstance(item, TextContent):
								content_parts.append(item.text)  # type: ignore[reportAttributeAccessIssue]
							else:
								content_parts.append(str(item))
						extracted_content = '\n'.join(content_parts)
					else:
						extracted_content = str(result.content)
				else:
					# Direct result
					extracted_content = str(result)

				return ActionResult(extracted_content=extracted_content)

			except Exception as e:
				logger.error(f'❌ MCP tool {tool_name} failed: {e}')
				return ActionResult(extracted_content=f'MCP tool {tool_name} failed: {str(e)}', error=str(e))

		# Set function name for better debugging
		mcp_action_wrapper.__name__ = tool_name
		mcp_action_wrapper.__qualname__ = f'mcp.{tool_name}'

		# Register the action with browser-use
		description = tool.description or f'MCP tool: {tool_name}'

		# Use the decorator to register the action
		decorated_wrapper = self.registry.action(description=description, param_model=param_model, domains=domains)(
			mcp_action_wrapper
		)

		self._registered_actions.add(tool_name)
		logger.info(f'✅ Registered MCP tool as action: {tool_name}')

	async def disconnect(self):
		"""Disconnect from the MCP server and clean up resources."""
		self._shutdown_event.set()
		if self.session:
			# Session cleanup will be handled by the context manager
			self.session = None

	def _json_schema_to_python_type(self, schema: dict) -> Any:
		"""Convert JSON Schema type to Python type.

		Args:
			schema: JSON Schema definition

		Returns:
			Python type corresponding to the schema
		"""
		json_type = schema.get('type', 'string')

		type_mapping = {
			'string': str,
			'number': float,
			'integer': int,
			'boolean': bool,
			'array': list,
			'object': dict,
		}

		base_type = type_mapping.get(json_type, str)

		# Handle nullable types
		if schema.get('nullable', False):
			return base_type | None

		return base_type


# Convenience function for easy integration
async def register_mcp_tools(registry: Registry, mcp_command: str, mcp_args: list[str] | None = None) -> MCPToolWrapper:
	"""Register MCP tools with a browser-use registry.

	Args:
		registry: Browser-use action registry
		mcp_command: Command to start MCP server
		mcp_args: Arguments for MCP command

	Returns:
		MCPToolWrapper instance (connected)

	Example:
		```python
	        from browser_use import Controller
	        from browser_use.mcp.controller import register_mcp_tools

	        controller = Controller()

	        # Register Playwright MCP tools
	        mcp = await register_mcp_tools(controller.registry, 'npx', ['@playwright/mcp@latest', '--headless'])

	        # Now all MCP tools are available as browser-use actions
		```
	"""
	wrapper = MCPToolWrapper(registry, mcp_command, mcp_args)
	await wrapper.connect()
	return wrapper
