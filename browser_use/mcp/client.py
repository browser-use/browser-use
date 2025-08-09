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
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from browser_use.agent.views import ActionResult
from browser_use.controller.registry.service import Registry
from browser_use.controller.service import Controller
from browser_use.telemetry import MCPClientTelemetryEvent, ProductTelemetry
from browser_use.utils import get_browser_use_version

logger = logging.getLogger(__name__)

# Import MCP SDK
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

MCP_AVAILABLE = True


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
		self._telemetry = ProductTelemetry()

	async def connect(self) -> None:
		"""Connect to the MCP server and discover available tools."""
		if self._connected:
			logger.debug(f'Already connected to {self.server_name}')
			return

		start_time = time.time()
		error_msg = None

		try:
			logger.info(f"🔌 Connecting to MCP server '{self.server_name}': {self.command} {' '.join(self.args)}")

			# Create server parameters
			server_params = StdioServerParameters(command=self.command, args=self.args, env=self.env)

			# Start stdio client in background task
			self._stdio_task = asyncio.create_task(self._run_stdio_client(server_params))

			# Wait for connection to be established
			retries = 0
			max_retries = 100  # 10 second timeout (increased for parallel test execution)
			while not self._connected and retries < max_retries:
				await asyncio.sleep(0.1)
				retries += 1

			if not self._connected:
				error_msg = f"Failed to connect to MCP server '{self.server_name}' after {max_retries * 0.1} seconds"
				raise RuntimeError(error_msg)

			logger.info(f"📦 Discovered {len(self._tools)} tools from '{self.server_name}': {list(self._tools.keys())}")

		except Exception as e:
			error_msg = str(e)
			raise
		finally:
			# Capture telemetry for connect action
			duration = time.time() - start_time
			self._telemetry.capture(
				MCPClientTelemetryEvent(
					server_name=self.server_name,
					command=self.command,
					tools_discovered=len(self._tools),
					version=get_browser_use_version(),
					action='connect',
					duration_seconds=duration,
					error_message=error_msg,
				)
			)

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

		start_time = time.time()
		error_msg = None

		try:
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

		except Exception as e:
			error_msg = str(e)
			logger.error(f'Error disconnecting from MCP server: {e}')
		finally:
			# Capture telemetry for disconnect action
			duration = time.time() - start_time
			self._telemetry.capture(
				MCPClientTelemetryEvent(
					server_name=self.server_name,
					command=self.command,
					tools_discovered=0,  # Tools cleared on disconnect
					version=get_browser_use_version(),
					action='disconnect',
					duration_seconds=duration,
					error_message=error_msg,
				)
			)
			self._telemetry.flush()

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
				param_type = self._json_schema_to_python_type(param_schema, f'{action_name}_{param_name}')

				# Determine if field is required and handle defaults
				if param_name in required:
					default = ...  # Required field
				else:
					# Optional field - make type optional and handle default
					param_type = param_type | None
					if 'default' in param_schema:
						default = param_schema['default']
					else:
						default = None

				# Add field with description if available
				field_kwargs = {}
				if 'description' in param_schema:
					field_kwargs['description'] = param_schema['description']

				param_fields[param_name] = (param_type, Field(default, **field_kwargs))

		# Create Pydantic model for the tool parameters
		if param_fields:
			# Create a BaseModel class with proper configuration
			class ConfiguredBaseModel(BaseModel):
				model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True)

			param_model = create_model(f'{action_name}_Params', __base__=ConfiguredBaseModel, **param_fields)
		else:
			# No parameters - create empty model
			param_model = None

		# Determine if this is a browser-specific tool
		is_browser_tool = tool.name.startswith('browser_') or 'page' in tool.name.lower()

		# Set up action filters
		domains = None
		# Note: page_filter has been removed since we no longer use Page objects
		# Browser tools filtering would need to be done via domain filters instead

		# Create async wrapper function for the MCP tool
		# Need to define function with explicit parameters to satisfy registry validation
		if param_model:
			# Type 1: Function takes param model as first parameter
			async def mcp_action_wrapper(params: param_model) -> ActionResult:  # type: ignore[no-redef]
				"""Wrapper function that calls the MCP tool."""
				if not self.session or not self._connected:
					return ActionResult(error=f"MCP server '{self.server_name}' not connected", success=False)

				# Convert pydantic model to dict for MCP call
				tool_params = params.model_dump(exclude_none=True)

				logger.debug(f"🔧 Calling MCP tool '{tool.name}' with params: {tool_params}")

				start_time = time.time()
				error_msg = None

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
				finally:
					# Capture telemetry for tool call
					duration = time.time() - start_time
					self._telemetry.capture(
						MCPClientTelemetryEvent(
							server_name=self.server_name,
							command=self.command,
							tools_discovered=len(self._tools),
							version=get_browser_use_version(),
							action='tool_call',
							tool_name=tool.name,
							duration_seconds=duration,
							error_message=error_msg,
						)
					)
		else:
			# No parameters - empty function signature
			async def mcp_action_wrapper() -> ActionResult:  # type: ignore[no-redef]
				"""Wrapper function that calls the MCP tool."""
				if not self.session or not self._connected:
					return ActionResult(error=f"MCP server '{self.server_name}' not connected", success=False)

				logger.debug(f"🔧 Calling MCP tool '{tool.name}' with no params")

				start_time = time.time()
				error_msg = None

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
				finally:
					# Capture telemetry for tool call
					duration = time.time() - start_time
					self._telemetry.capture(
						MCPClientTelemetryEvent(
							server_name=self.server_name,
							command=self.command,
							tools_discovered=len(self._tools),
							version=get_browser_use_version(),
							action='tool_call',
							tool_name=tool.name,
							duration_seconds=duration,
							error_message=error_msg,
						)
					)

		# Set function metadata for better debugging
		mcp_action_wrapper.__name__ = action_name
		mcp_action_wrapper.__qualname__ = f'mcp.{self.server_name}.{action_name}'

		# Register the action with browser-use
		description = tool.description or f'MCP tool from {self.server_name}: {tool.name}'

		# Use the registry's action decorator
		registry.action(description=description, param_model=param_model, domains=domains)(mcp_action_wrapper)

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

	def _json_schema_to_python_type(self, schema: dict, model_name: str = 'NestedModel') -> Any:
		"""Convert JSON Schema type to Python type.

		Args:
			schema: JSON Schema definition
			model_name: Name for nested models

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
			'null': type(None),
		}

		# Handle enums (they're still strings)
		if 'enum' in schema:
			return str

		# Handle objects with nested properties
		if json_type == 'object':
			properties = schema.get('properties', {})
			if properties:
				# Create nested pydantic model for objects with properties
				nested_fields = {}
				required_fields = set(schema.get('required', []))

				for prop_name, prop_schema in properties.items():
					# Recursively process nested properties
					prop_type = self._json_schema_to_python_type(prop_schema, f'{model_name}_{prop_name}')

					# Determine if field is required and handle defaults
					if prop_name in required_fields:
						default = ...  # Required field
					else:
						# Optional field - make type optional and handle default
						prop_type = prop_type | None
						if 'default' in prop_schema:
							default = prop_schema['default']
						else:
							default = None

					# Add field with description if available
					field_kwargs = {}
					if 'description' in prop_schema:
						field_kwargs['description'] = prop_schema['description']

					nested_fields[prop_name] = (prop_type, Field(default, **field_kwargs))

				# Create a BaseModel class with proper configuration
				class ConfiguredBaseModel(BaseModel):
					model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True)

				try:
					# Create and return nested pydantic model
					return create_model(model_name, __base__=ConfiguredBaseModel, **nested_fields)
				except Exception as e:
					logger.error(f'Failed to create nested model {model_name}: {e}')
					logger.debug(f'Fields: {nested_fields}')
					# Fallback to basic dict if model creation fails
					return dict
			else:
				# Object without properties - just return dict
				return dict

		# Handle arrays with specific item types
		if json_type == 'array':
			if 'items' in schema:
				# Get the item type recursively
				item_type = self._json_schema_to_python_type(schema['items'], f'{model_name}_item')
				# Return properly typed list
				return list[item_type]
			else:
				# Array without item type specification
				return list

		# Get base type for non-object types
		base_type = type_mapping.get(json_type, str)

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
