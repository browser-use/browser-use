"""MCP (Model Context Protocol) client integration for browser-use.

This module provides integration between external MCP servers and browser-use's action registry.
MCP tools are dynamically discovered and registered as browser-use actions.

Example usage:
    from browser_use import Controller
    from browser_use.mcp.client import MCPClient

    controller = Controller()

    # Connect to an MCP server
    mcp_client = MCPClient(
        server_name="my-server",
        command="npx",
        args=["@mycompany/mcp-server@latest"]
    )

    # Register all MCP tools as browser-use actions
    await mcp_client.register_to_controller(controller)

    # Now use with Agent as normal - MCP tools are available as actions
"""

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field, create_model

from browser_use.agent.views import ActionResult
from browser_use.controller.registry.service import Registry
from browser_use.controller.service import Controller

logger = logging.getLogger(__name__)

# Try to import MCP SDK
try:
	from mcp import ClientSession, StdioServerParameters, types
	from mcp.client.stdio import stdio_client

	MCP_AVAILABLE = True
except ImportError:
	MCP_AVAILABLE = False
	logger.warning('MCP SDK not installed. Install with: pip install mcp')


class MCPClient:
	"""Client for connecting to MCP servers and exposing their tools as browser-use actions."""

	def __init__(
		self,
		server_name: str,
		command: str,
		args: list[str] | None = None,
		env: dict[str, str] | None = None,
	):
		"""Initialize MCP client.

		Args:
			server_name: Name of the MCP server (for logging and identification)
			command: Command to start the MCP server (e.g., "npx", "python")
			args: Arguments for the command (e.g., ["@playwright/mcp@latest"])
			env: Environment variables for the server process
		"""
		if not MCP_AVAILABLE:
			raise ImportError('MCP SDK not installed. Install with: pip install mcp')

		self.server_name = server_name
		self.command = command
		self.args = args or []
		self.env = env

		self.session: ClientSession | None = None
		self._stdio_task = None
		self._read_stream = None
		self._write_stream = None
		self._tools: dict[str, types.Tool] = {}
		self._registered_actions: set[str] = set()
		self._connected = False
		self._disconnect_event = asyncio.Event()

	async def connect(self) -> None:
		"""Connect to the MCP server and discover available tools."""
		if self._connected:
			logger.debug(f'Already connected to {self.server_name}')
			return

		logger.info(f"🔌 Connecting to MCP server '{self.server_name}': {self.command} {' '.join(self.args)}")

		# Create server parameters
		server_params = StdioServerParameters(command=self.command, args=self.args, env=self.env)

		# Start stdio client in background task
		self._stdio_task = asyncio.create_task(self._run_stdio_client(server_params))

		# Wait for connection to be established
		retries = 0
		while not self._connected and retries < 30:  # 3 second timeout
			await asyncio.sleep(0.1)
			retries += 1

		if not self._connected:
			raise RuntimeError(f"Failed to connect to MCP server '{self.server_name}' after 3 seconds")

		logger.info(f"📦 Discovered {len(self._tools)} tools from '{self.server_name}': {list(self._tools.keys())}")

	async def _run_stdio_client(self, server_params: StdioServerParameters):
		"""Run the stdio client connection in a background task."""
		try:
			async with stdio_client(server_params) as (read_stream, write_stream):
				self._read_stream = read_stream
				self._write_stream = write_stream

				# Create and initialize session
				async with ClientSession(read_stream, write_stream) as session:
					self.session = session

					# Initialize the connection
					await session.initialize()

					# Discover available tools
					tools_response = await session.list_tools()
					self._tools = {tool.name: tool for tool in tools_response.tools}

					# Mark as connected
					self._connected = True

					# Keep the connection alive until disconnect is called
					await self._disconnect_event.wait()

		except Exception as e:
			logger.error(f'MCP server connection error: {e}')
			self._connected = False
			raise
		finally:
			self._connected = False
			self.session = None

	async def disconnect(self) -> None:
		"""Disconnect from the MCP server."""
		if not self._connected:
			return

		logger.info(f"🔌 Disconnecting from MCP server '{self.server_name}'")

		# Signal disconnect
		self._connected = False
		self._disconnect_event.set()

		# Wait for stdio task to finish
		if self._stdio_task:
			try:
				await asyncio.wait_for(self._stdio_task, timeout=2.0)
			except TimeoutError:
				logger.warning(f"Timeout waiting for MCP server '{self.server_name}' to disconnect")
				self._stdio_task.cancel()
				try:
					await self._stdio_task
				except asyncio.CancelledError:
					pass

		self._tools.clear()
		self._registered_actions.clear()

	async def register_to_controller(
		self,
		controller: Controller,
		tool_filter: list[str] | None = None,
		prefix: str | None = None,
	) -> None:
		"""Register MCP tools as actions in the browser-use controller.

		Args:
			controller: Browser-use controller to register actions to
			tool_filter: Optional list of tool names to register (None = all tools)
			prefix: Optional prefix to add to action names (e.g., "playwright_")
		"""
		if not self._connected:
			await self.connect()

		registry = controller.registry

		for tool_name, tool in self._tools.items():
			# Skip if not in filter
			if tool_filter and tool_name not in tool_filter:
				continue

			# Apply prefix if specified
			action_name = f'{prefix}{tool_name}' if prefix else tool_name

			# Skip if already registered
			if action_name in self._registered_actions:
				continue

			# Register the tool as an action
			self._register_tool_as_action(registry, action_name, tool)
			self._registered_actions.add(action_name)

		logger.info(f"✅ Registered {len(self._registered_actions)} MCP tools from '{self.server_name}' as browser-use actions")

	def _register_tool_as_action(self, registry: Registry, action_name: str, tool: Any) -> None:
		"""Register a single MCP tool as a browser-use action.

		Args:
			registry: Browser-use registry to register action to
			action_name: Name for the registered action
			tool: MCP Tool object with schema information
		"""
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

				# Add field with description if available
				field_kwargs = {}
				if 'description' in param_schema:
					field_kwargs['description'] = param_schema['description']

				param_fields[param_name] = (param_type, Field(default, **field_kwargs))

		# Create Pydantic model for the tool parameters
		if param_fields:
			param_model = create_model(f'{action_name}_Params', __base__=BaseModel, **param_fields)
		else:
			# No parameters - create empty model
			param_model = None

		# Determine if this is a browser-specific tool
		is_browser_tool = tool.name.startswith('browser_') or 'page' in tool.name.lower()

		# Set up action filters
		domains = None
		page_filter = None

		if is_browser_tool:
			# Browser tools should only be available when on a web page
			page_filter = lambda page: page and page.url != 'about:blank'

		# Create async wrapper function for the MCP tool
		# Need to define function with explicit parameters to satisfy registry validation
		if param_model:
			# Type 1: Function takes param model as first parameter
			async def mcp_action_wrapper(params: param_model) -> ActionResult:  # type: ignore[no-redef]
				"""Wrapper function that calls the MCP tool."""
				if not self.session or not self._connected:
					return ActionResult(error=f"MCP server '{self.server_name}' not connected", success=False)

				# Convert pydantic model to dict for MCP call
				tool_params = params.model_dump()

				logger.debug(f"🔧 Calling MCP tool '{tool.name}' with params: {tool_params}")

				try:
					# Call the MCP tool
					result = await self.session.call_tool(tool.name, tool_params)

					# Convert MCP result to ActionResult
					extracted_content = self._format_mcp_result(result)

					return ActionResult(
						extracted_content=extracted_content,
						long_term_memory=f"Used MCP tool '{tool.name}' from {self.server_name}",
					)

				except Exception as e:
					error_msg = f"MCP tool '{tool.name}' failed: {str(e)}"
					logger.error(error_msg)
					return ActionResult(error=error_msg, success=False)
		else:
			# No parameters - empty function signature
			async def mcp_action_wrapper() -> ActionResult:  # type: ignore[no-redef]
				"""Wrapper function that calls the MCP tool."""
				if not self.session or not self._connected:
					return ActionResult(error=f"MCP server '{self.server_name}' not connected", success=False)

				logger.debug(f"🔧 Calling MCP tool '{tool.name}' with no params")

				try:
					# Call the MCP tool with empty params
					result = await self.session.call_tool(tool.name, {})

					# Convert MCP result to ActionResult
					extracted_content = self._format_mcp_result(result)

					return ActionResult(
						extracted_content=extracted_content,
						long_term_memory=f"Used MCP tool '{tool.name}' from {self.server_name}",
					)

				except Exception as e:
					error_msg = f"MCP tool '{tool.name}' failed: {str(e)}"
					logger.error(error_msg)
					return ActionResult(error=error_msg, success=False)

		# Set function metadata for better debugging
		mcp_action_wrapper.__name__ = action_name
		mcp_action_wrapper.__qualname__ = f'mcp.{self.server_name}.{action_name}'

		# Register the action with browser-use
		description = tool.description or f'MCP tool from {self.server_name}: {tool.name}'

		# Use the registry's action decorator
		registry.action(description=description, param_model=param_model, domains=domains, page_filter=page_filter)(
			mcp_action_wrapper
		)

		logger.debug(f"✅ Registered MCP tool '{tool.name}' as action '{action_name}'")

	def _format_mcp_result(self, result: Any) -> str:
		"""Format MCP tool result into a string for ActionResult.

		Args:
			result: Raw result from MCP tool call

		Returns:
			Formatted string representation of the result
		"""
		# Handle different MCP result formats
		if hasattr(result, 'content'):
			# Structured content response
			if isinstance(result.content, list):
				# Multiple content items
				parts = []
				for item in result.content:
					if hasattr(item, 'text'):
						parts.append(item.text)
					elif hasattr(item, 'type') and item.type == 'text':
						parts.append(str(item))
					else:
						parts.append(str(item))
				return '\n'.join(parts)
			else:
				return str(result.content)
		elif isinstance(result, list):
			# List of content items
			parts = []
			for item in result:
				if hasattr(item, 'text'):
					parts.append(item.text)
				else:
					parts.append(str(item))
			return '\n'.join(parts)
		else:
			# Direct result or unknown format
			return str(result)

	def _json_schema_to_python_type(self, schema: dict) -> Any:
		"""Convert JSON Schema type to Python type.

		Args:
			schema: JSON Schema definition

		Returns:
			Python type corresponding to the schema
		"""
		json_type = schema.get('type', 'string')

		# Basic type mapping
		type_mapping = {
			'string': str,
			'number': float,
			'integer': int,
			'boolean': bool,
			'array': list,
			'object': dict,
			'null': type(None),
		}

		# Handle enums (they're still strings)
		if 'enum' in schema:
			return str

		# Get base type
		base_type = type_mapping.get(json_type, str)

		# Handle arrays with specific item types
		if json_type == 'array' and 'items' in schema:
			# For now, just use generic list
			# TODO: Could use list[item_type] with proper type inference
			return list

		# Handle nullable/optional types
		if schema.get('nullable', False) or json_type == 'null':
			return base_type | None

		return base_type

	async def __aenter__(self):
		"""Async context manager entry."""
		await self.connect()
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		"""Async context manager exit."""
		await self.disconnect()
