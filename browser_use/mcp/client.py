"""MCP (Model Context Protocol) client integration for browser-use.

This module provides integration between external MCP servers and browser-use's action registry.
MCP tools are dynamically discovered and registered as browser-use actions.

Example usage:
    from browser_use import Tools
    from browser_use.mcp.client import MCPClient

    tools = Tools()

    # Connect to an MCP server
    mcp_client = MCPClient(
        server_name="my-server",
        command="npx",
        args=["@mycompany/mcp-server@latest"]
    )

    # Register all MCP tools as browser-use actions
    await mcp_client.register_to_tools(tools)

    # Now use with Agent as normal - MCP tools are available as actions
"""

import asyncio
import logging
import math
import re
import time
from typing import Annotated, Any, ClassVar, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, WithJsonSchema, create_model

from browser_use.agent.views import ActionResult
from browser_use.telemetry import MCPClientTelemetryEvent, ProductTelemetry
from browser_use.tools.registry.service import Registry
from browser_use.tools.service import Tools
from browser_use.utils import create_task_with_error_handling, get_browser_use_version

logger = logging.getLogger(__name__)

# Import MCP SDK
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

MCP_AVAILABLE = True


def _schema_accepts_value(value: Any, schema: dict[str, Any] | bool) -> bool:
	if isinstance(schema, bool):
		return schema

	json_type = schema.get('type')
	if json_type is not None:
		json_types = json_type if isinstance(json_type, list) else [json_type]
		type_matches = any(
			(type_name == 'null' and value is None)
			or (value is None and schema.get('nullable', False))
			or (type_name == 'string' and isinstance(value, str))
			or (type_name == 'boolean' and isinstance(value, bool))
			or (type_name == 'integer' and isinstance(value, int) and not isinstance(value, bool))
			or (type_name == 'number' and isinstance(value, (int, float)) and not isinstance(value, bool))
			or (type_name == 'array' and isinstance(value, list))
			or (type_name == 'object' and isinstance(value, dict))
			for type_name in json_types
		)
		enum_allows_null = value is None and 'enum' in schema and None in schema['enum']
		if not type_matches and not enum_allows_null:
			return False

	if 'enum' in schema and value not in schema['enum']:
		return False
	if 'const' in schema and value != schema['const']:
		return False
	if 'anyOf' in schema and not any(_schema_accepts_value(value, variant) for variant in schema['anyOf']):
		return False
	if 'oneOf' in schema and sum(_schema_accepts_value(value, variant) for variant in schema['oneOf']) != 1:
		return False
	if 'allOf' in schema and not all(_schema_accepts_value(value, variant) for variant in schema['allOf']):
		return False

	if isinstance(value, str):
		if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', math.inf):
			return False
		if 'pattern' in schema and re.search(schema['pattern'], value) is None:
			return False

	if isinstance(value, (int, float)) and not isinstance(value, bool):
		if value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf):
			return False
		if value <= schema.get('exclusiveMinimum', -math.inf) or value >= schema.get('exclusiveMaximum', math.inf):
			return False
		if 'multipleOf' in schema:
			multiple = schema['multipleOf']
			if multiple <= 0 or not math.isclose(value / multiple, round(value / multiple), rel_tol=1e-9, abs_tol=1e-9):
				return False

	if isinstance(value, dict):
		if len(value) < schema.get('minProperties', 0) or len(value) > schema.get('maxProperties', math.inf):
			return False
		if not set(schema.get('required', [])).issubset(value):
			return False
		properties = schema.get('properties', {})
		if any(
			key in value and not _schema_accepts_value(value[key], property_schema) for key, property_schema in properties.items()
		):
			return False
		extra_properties = set(value) - set(properties)
		additional_properties = schema.get('additionalProperties', True)
		if additional_properties is False and extra_properties:
			return False
		if isinstance(additional_properties, (dict, bool)) and any(
			not _schema_accepts_value(value[key], additional_properties) for key in extra_properties
		):
			return False
	if isinstance(value, list):
		if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', math.inf):
			return False
		if schema.get('uniqueItems', False) and any(
			value[left] == value[right] for left in range(len(value)) for right in range(left + 1, len(value))
		):
			return False
		prefix_items = schema.get('prefixItems', [])
		if any(
			index < len(value) and not _schema_accepts_value(value[index], item_schema)
			for index, item_schema in enumerate(prefix_items)
		):
			return False
		items_schema = schema.get('items')
		if isinstance(items_schema, (dict, bool)) and any(
			not _schema_accepts_value(item, items_schema) for index, item in enumerate(value) if index >= len(prefix_items)
		):
			return False
		if 'contains' in schema:
			match_count = sum(_schema_accepts_value(item, schema['contains']) for item in value)
			if match_count < schema.get('minContains', 1) or match_count > schema.get('maxContains', math.inf):
				return False

	return True


def _schema_allows_null(schema: dict[str, Any] | bool) -> bool:
	return _schema_accepts_value(None, schema)


def _schema_for_composed_object(schema: dict[str, Any]) -> dict[str, Any]:
	"""Expose intersected allOf fields at the top level for tool-call schemas."""
	json_schema = dict(schema)
	properties = dict(json_schema.get('properties', {}))
	required = set(json_schema.get('required', []))

	for branch in schema.get('allOf', []):
		if not isinstance(branch, dict):
			continue
		for name, property_schema in branch.get('properties', {}).items():
			if name in properties and properties[name] != property_schema:
				existing_schema = properties[name]
				existing_branches = (
					existing_schema.get('allOf')
					if isinstance(existing_schema, dict) and set(existing_schema) == {'allOf'}
					else None
				)
				properties[name] = {'allOf': [*(existing_branches or [existing_schema]), property_schema]}
			else:
				properties[name] = property_schema
		required.update(branch.get('required', []))

	if properties:
		json_schema['type'] = 'object'
		json_schema['properties'] = properties
	if required:
		json_schema['required'] = sorted(required)
	return json_schema


def _nullable_python_type(python_type: Any) -> Any:
	return python_type if python_type is type(None) else python_type | None


def _serialize_mcp_params(value: Any) -> Any:
	"""Serialize MCP parameters without dropping explicit nullable values."""
	if isinstance(value, BaseModel):
		serialized = value.model_dump(exclude_none=True)
		nullable_fields = getattr(value.__class__, '__mcp_nullable_fields__', frozenset())

		for field_name in value.__class__.model_fields:
			field_value = getattr(value, field_name)
			if field_value is None:
				if field_name in nullable_fields and field_name in value.model_fields_set:
					serialized[field_name] = None
			elif field_name in serialized:
				serialized[field_name] = _serialize_mcp_params(field_value)

		return serialized
	if isinstance(value, dict):
		return {key: _serialize_mcp_params(item) for key, item in value.items()}
	if isinstance(value, list):
		return [_serialize_mcp_params(item) for item in value]
	return value


class MCPToolParameters(BaseModel):
	model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True)

	__mcp_nullable_fields__: ClassVar[frozenset[str]] = frozenset()


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
			self._stdio_task = create_task_with_error_handling(
				self._run_stdio_client(server_params), name='mcp_stdio_client', suppress_exceptions=True
			)

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

	async def register_to_tools(
		self,
		tools: Tools,
		tool_filter: list[str] | None = None,
		prefix: str | None = None,
	) -> None:
		"""Register MCP tools as actions in the browser-use tools.

		Args:
			tools: Browser-use tools to register actions to
			tool_filter: Optional list of tool names to register (None = all tools)
			prefix: Optional prefix to add to action names (e.g., "playwright_")
		"""
		if not self._connected:
			await self.connect()

		registry = tools.registry

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
		nullable_fields = set()

		if tool.input_schema:
			# MCP tools use JSON Schema for parameters
			properties = tool.input_schema.get('properties', {})
			required = set(tool.input_schema.get('required', []))

			for param_name, param_schema in properties.items():
				# Convert JSON Schema type to Python type
				param_type = self._json_schema_to_python_type(param_schema, f'{action_name}_{param_name}')
				if _schema_allows_null(param_schema):
					nullable_fields.add(param_name)

				# Determine if field is required and handle defaults
				if param_name in required:
					default = ...  # Required field
				else:
					# Optional field - make type optional and handle default
					param_type = _nullable_python_type(param_type)
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
			param_model = create_model(f'{action_name}_Params', __base__=MCPToolParameters, **param_fields)
			setattr(param_model, '__mcp_nullable_fields__', frozenset(nullable_fields))
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

				# Preserve explicit nulls allowed by the schema while omitting absent optional values.
				tool_params = _serialize_mcp_params(params)

				logger.debug(f"🔧 Calling MCP tool '{tool.name}' with params: {tool_params}")

				start_time = time.time()
				error_msg = None

				try:
					# Call the MCP tool
					result = await self.session.call_tool(tool.name, tool_params)

					# Convert MCP result to ActionResult
					extracted_content = self._format_mcp_result(result)

					if result.is_error:
						error_msg = f"MCP tool '{tool.name}' reported an error: {extracted_content}"
						return ActionResult(error=error_msg, success=False)

					return ActionResult(
						extracted_content=extracted_content,
						long_term_memory=f"Used MCP tool '{tool.name}' from {self.server_name}",
						include_extracted_content_only_once=True,
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

					if result.is_error:
						error_msg = f"MCP tool '{tool.name}' reported an error: {extracted_content}"
						return ActionResult(error=error_msg, success=False)

					return ActionResult(
						extracted_content=extracted_content,
						long_term_memory=f"Used MCP tool '{tool.name}' from {self.server_name}",
						include_extracted_content_only_once=True,
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
		compositions = {composition: schema[composition] for composition in ('allOf', 'anyOf', 'oneOf') if composition in schema}
		if compositions:
			if any(not isinstance(variants, list) for variants in compositions.values()):
				raise ValueError('JSON Schema allOf, anyOf, and oneOf values must be lists')

			base_schema = {key: value for key, value in schema.items() if key not in compositions}
			if base_schema.get('type') == 'object':
				python_type = dict
			elif 'type' in base_schema:
				python_type = self._json_schema_to_python_type(base_schema, model_name)
			elif 'allOf' in compositions:
				variant_types = []
				for variant in compositions['allOf']:
					if isinstance(variant, bool):
						continue
					if not isinstance(variant, dict):
						raise ValueError('JSON Schema allOf entries must be objects or booleans')
					if variant.get('type') == 'object':
						variant_types.append(dict)
					elif 'type' in variant:
						variant_types.append(self._json_schema_to_python_type(variant, model_name))
				python_types = list(dict.fromkeys(variant_types))
				python_type = python_types[0] if len(python_types) == 1 else Any
			else:
				python_types = []
				for variants in compositions.values():
					for variant in variants:
						if isinstance(variant, bool):
							variant_type = Any
						elif isinstance(variant, dict):
							variant_type = self._json_schema_to_python_type(variant, model_name)
						else:
							raise ValueError('JSON Schema composition entries must be objects or booleans')
						if variant_type not in python_types:
							python_types.append(variant_type)
				if not python_types:
					raise ValueError('JSON Schema compositions must contain at least one schema')
				python_type = python_types[0] if len(python_types) == 1 else Union[tuple(python_types)]

			def validate_composition(value: Any) -> Any:
				if not _schema_accepts_value(value, schema):
					raise ValueError('Value does not satisfy its JSON Schema composition')
				return value

			metadata: list[Any] = [BeforeValidator(validate_composition)]
			if 'allOf' in compositions:
				metadata.append(WithJsonSchema(_schema_for_composed_object(schema)))
			return Annotated[python_type, *metadata]

		json_type = schema.get('type', 'string')

		if isinstance(json_type, list):
			python_types = [
				self._json_schema_to_python_type({**schema, 'type': single_type}, model_name)
				for single_type in dict.fromkeys(json_type)
				if single_type != 'null'
			]
			if _schema_allows_null(schema):
				python_types.append(type(None))
			if not python_types:
				return type(None)
			return python_types[0] if len(python_types) == 1 else Union[tuple(python_types)]

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
			return _nullable_python_type(str) if _schema_allows_null(schema) else str

		# Handle objects with nested properties
		if json_type == 'object':
			properties = schema.get('properties', {})
			if properties:
				# Create nested pydantic model for objects with properties
				nested_fields = {}
				nullable_fields = set()
				required_fields = set(schema.get('required', []))

				for prop_name, prop_schema in properties.items():
					# Recursively process nested properties
					prop_type = self._json_schema_to_python_type(prop_schema, f'{model_name}_{prop_name}')
					if _schema_allows_null(prop_schema):
						nullable_fields.add(prop_name)

					# Determine if field is required and handle defaults
					if prop_name in required_fields:
						default = ...  # Required field
					else:
						# Optional field - make type optional and handle default
						prop_type = _nullable_python_type(prop_type)
						if 'default' in prop_schema:
							default = prop_schema['default']
						else:
							default = None

					# Add field with description if available
					field_kwargs = {}
					if 'description' in prop_schema:
						field_kwargs['description'] = prop_schema['description']

					nested_fields[prop_name] = (prop_type, Field(default, **field_kwargs))

				try:
					# Create and return nested pydantic model
					nested_model = create_model(model_name, __base__=MCPToolParameters, **nested_fields)
					setattr(nested_model, '__mcp_nullable_fields__', frozenset(nullable_fields))
					return _nullable_python_type(nested_model) if _schema_allows_null(schema) else nested_model
				except Exception as e:
					logger.error(f'Failed to create nested model {model_name}: {e}')
					logger.debug(f'Fields: {nested_fields}')
					# Fallback to basic dict if model creation fails
					return _nullable_python_type(dict) if _schema_allows_null(schema) else dict
			else:
				# Object without properties - just return dict
				return _nullable_python_type(dict) if _schema_allows_null(schema) else dict

		# Handle arrays with specific item types
		if json_type == 'array':
			if 'items' in schema:
				# Get the item type recursively
				item_type = self._json_schema_to_python_type(schema['items'], f'{model_name}_item')
				# Return properly typed list
				array_type = list[item_type]
			else:
				# Array without item type specification
				array_type = list
			return _nullable_python_type(array_type) if _schema_allows_null(schema) else array_type

		# Get base type for non-object types
		base_type = type_mapping.get(json_type, str)

		# Handle nullable/optional types
		if _schema_allows_null(schema):
			return _nullable_python_type(base_type)

		return base_type

	async def __aenter__(self):
		"""Async context manager entry."""
		await self.connect()
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		"""Async context manager exit."""
		await self.disconnect()
