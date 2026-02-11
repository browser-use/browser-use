"""WebMCP service for discovering and invoking page-provided tools.

Implements the agent side of the W3C WebMCP API (navigator.modelContext)
A JS bridge is injected via Page.addScriptToEvaluateOnNewDocument that
provides navigator.modelContext and captures tool registrations. Discovery
and invocation happen via CDP Runtime.evaluate calls against the bridge

Spec: https://github.com/webmachinelearning/webmcp/blob/main/docs/proposal.md
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from browser_use.agent.views import ActionResult
from browser_use.tools.registry.service import Registry
from browser_use.webmcp.views import WebMCPToolDescriptor, WebMCPToolResult

logger = logging.getLogger(__name__)

_BRIDGE_JS: str | None = None


def _load_bridge_js() -> str:
	"""Load the bridge.js file contents (cached after first call)."""
	global _BRIDGE_JS
	if _BRIDGE_JS is None:
		bridge_path = Path(__file__).parent / 'bridge.js'
		_BRIDGE_JS = bridge_path.read_text()
	return _BRIDGE_JS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _origin_from_url(url: str) -> str:
	"""Extract origin (hostname + port) from a URL for domain filtering."""
	from urllib.parse import urlparse

	parsed = urlparse(url)
	if not parsed.hostname:
		return url
	origin = parsed.hostname
	if parsed.port and parsed.port not in (80, 443):
		origin = f'{parsed.hostname}:{parsed.port}'
	return origin


def _sanitize_tool_name(name: str) -> str:
	"""Convert a WebMCP tool name to a valid action name.

	e.g. 'add-todo' -> 'webmcp_add_todo', 'getDresses' -> 'webmcp_getDresses'
	"""
	safe = name.replace('-', '_').replace('.', '_').replace(' ', '_')
	return f'webmcp_{safe}'


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class WebMCPService:
	"""Handles WebMCP tool discovery and invocation for a browser session.

	Communicates with the injected bridge.js via CDP Runtime.evaluate to
	enumerate tools registered through navigator.modelContext and call their
	execute callbacks.
	"""

	def __init__(self) -> None:
		self._registered_actions: dict[str, str] = {}  # action_name -> original_tool_name
		self._current_origin: str | None = None

	@staticmethod
	def get_bridge_js() -> str:
		"""Return the JS bridge source to be injected via addScriptToEvaluateOnNewDocument."""
		return _load_bridge_js()

	async def discover_tools(self, browser_session: Any) -> list[WebMCPToolDescriptor]:
		"""Query the injected bridge for tools registered via navigator.modelContext.

		Returns an empty list if the bridge isn't present or no tools are registered.
		"""
		try:
			cdp_session = await browser_session.get_or_create_cdp_session()
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': 'window.__buWebMCP ? window.__buWebMCP.listTools() : \'{"tools":[]}\'',
					'returnByValue': True,
					'awaitPromise': True,
				},
				session_id=cdp_session.session_id,
			)

			raw_value = result.get('result', {}).get('value', '{"tools":[]}')
			if isinstance(raw_value, str):
				data = json.loads(raw_value)
			else:
				data = raw_value

			tools_list = data.get('tools', [])
			descriptors: list[WebMCPToolDescriptor] = []
			for info in tools_list:
				descriptors.append(
					WebMCPToolDescriptor(
						name=info.get('name', ''),
						description=info.get('description', ''),
						input_schema=info.get('inputSchema', {}),
					)
				)
			return descriptors

		except Exception as e:
			logger.debug(f'WebMCP tool discovery failed: {e}')
			return []

	async def call_tool(self, browser_session: Any, tool_name: str, args: dict[str, Any]) -> WebMCPToolResult:
		"""Call a WebMCP tool's execute callback via the injected bridge."""
		name_js = json.dumps(tool_name)
		args_js = json.dumps(args)
		js = f'window.__buWebMCP.callTool({name_js}, {args_js})'

		try:
			cdp_session = await browser_session.get_or_create_cdp_session()
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': js,
					'returnByValue': True,
					'awaitPromise': True,
				},
				session_id=cdp_session.session_id,
			)

			exception_details = result.get('exceptionDetails')
			if exception_details:
				error_text = exception_details.get('text', '')
				exception_obj = exception_details.get('exception', {})
				error_desc = exception_obj.get('description', error_text)
				return WebMCPToolResult(error=f'WebMCP tool error: {error_desc}')

			raw_value = result.get('result', {}).get('value', '{}')
			if isinstance(raw_value, str):
				parsed = json.loads(raw_value)
			else:
				parsed = raw_value

			if 'error' in parsed and isinstance(parsed['error'], str):
				return WebMCPToolResult(error=parsed['error'])

			return WebMCPToolResult.model_validate(parsed)

		except Exception as e:
			return WebMCPToolResult(error=f'WebMCP call failed: {e}')

	def sync_actions_to_registry(
		self,
		registry: Registry,
		tools: list[WebMCPToolDescriptor],
		page_url: str,
		browser_session: Any,
	) -> None:
		"""Synchronize discovered WebMCP tools with the action registry.

		Removes stale WebMCP actions and registers new ones. Each action is
		domain-scoped to the page origin so it only appears when relevant.
		"""
		origin = _origin_from_url(page_url)
		new_tool_names = {_sanitize_tool_name(t.name) for t in tools}

		# Remove stale actions
		stale = [name for name in self._registered_actions if name not in new_tool_names]
		for action_name in stale:
			if action_name in registry.registry.actions:
				del registry.registry.actions[action_name]
			del self._registered_actions[action_name]
			logger.debug(f'Unregistered stale WebMCP action: {action_name}')

		# Register new actions
		for tool in tools:
			action_name = _sanitize_tool_name(tool.name)
			if action_name in self._registered_actions:
				continue
			self._register_tool_as_action(registry, action_name, tool, origin, browser_session)
			self._registered_actions[action_name] = tool.name

		if tools:
			self._log_discovered_tools(tools, origin)

		self._current_origin = origin

	def clear_all_actions(self, registry: Registry) -> None:
		"""Remove all WebMCP actions from the registry."""
		for action_name in list(self._registered_actions.keys()):
			if action_name in registry.registry.actions:
				del registry.registry.actions[action_name]
		self._registered_actions.clear()
		self._current_origin = None

	def _register_tool_as_action(
		self,
		registry: Registry,
		action_name: str,
		tool: WebMCPToolDescriptor,
		origin: str,
		browser_session: Any,
	) -> None:
		"""Register a single WebMCP tool as a browser-use action."""
		param_fields: dict[str, Any] = {}

		if tool.input_schema:
			properties = tool.input_schema.get('properties', {})
			required = set(tool.input_schema.get('required', []))

			for param_name, param_schema in properties.items():
				param_type = _json_schema_to_python_type(param_schema, f'{action_name}_{param_name}')

				if param_name in required:
					default = ...
				else:
					param_type = param_type | None
					default = param_schema.get('default', None)

				field_kwargs: dict[str, Any] = {}
				if 'description' in param_schema:
					field_kwargs['description'] = param_schema['description']

				param_fields[param_name] = (param_type, Field(default, **field_kwargs))

		if param_fields:

			class ConfiguredBaseModel(BaseModel):
				model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True)

			param_model: type[BaseModel] | None = create_model(
				f'{action_name}_Params', __base__=ConfiguredBaseModel, **param_fields
			)
		else:
			param_model = None

		# Capture in closure
		original_name = tool.name
		_service = self
		_browser_session = browser_session

		if param_model:

			async def webmcp_action_wrapper(params: param_model) -> ActionResult:  # type: ignore[valid-type]
				tool_params = params.model_dump(exclude_none=True)
				logger.debug(f"Calling WebMCP tool '{original_name}' with params: {tool_params}")
				result = await _service.call_tool(_browser_session, original_name, tool_params)
				if result.error:
					return ActionResult(error=result.error)
				extracted = _format_webmcp_result(result)
				return ActionResult(
					extracted_content=extracted,
					long_term_memory=f"Called WebMCP tool '{original_name}' on {origin}",
				)

		else:

			async def webmcp_action_wrapper() -> ActionResult:  # type: ignore[no-redef]
				logger.debug(f"Calling WebMCP tool '{original_name}' with no params")
				result = await _service.call_tool(_browser_session, original_name, {})
				if result.error:
					return ActionResult(error=result.error)
				extracted = _format_webmcp_result(result)
				return ActionResult(
					extracted_content=extracted,
					long_term_memory=f"Called WebMCP tool '{original_name}' on {origin}",
				)

		webmcp_action_wrapper.__name__ = action_name
		webmcp_action_wrapper.__qualname__ = f'webmcp.{origin}.{action_name}'

		description = f'[WebMCP] {tool.description}' if tool.description else f'[WebMCP] Tool from {origin}: {tool.name}'

		registry.action(description=description, param_model=param_model, domains=[f'*{origin}*'])(webmcp_action_wrapper)

	def _log_discovered_tools(self, tools: list[WebMCPToolDescriptor], origin: str) -> None:
		tool_names = [t.name for t in tools]
		logger.info(f'WebMCP: discovered {len(tools)} tools on {origin}: {tool_names}')


def _format_webmcp_result(result: WebMCPToolResult) -> str:
	"""Format a WebMCPToolResult into a string for ActionResult.extracted_content."""
	parts: list[str] = []
	for item in result.content:
		if item.text:
			parts.append(item.text)
	return '\n'.join(parts) if parts else 'Tool executed successfully.'


def _json_schema_to_python_type(schema: dict[str, Any], model_name: str = 'NestedModel') -> Any:
	"""Convert a JSON Schema type to a Python type. Mirrors MCPClient._json_schema_to_python_type."""
	json_type = schema.get('type', 'string')

	type_mapping: dict[str, type] = {
		'string': str,
		'number': float,
		'integer': int,
		'boolean': bool,
		'array': list,
		'null': type(None),
	}

	if 'enum' in schema:
		return str

	if json_type == 'object':
		properties = schema.get('properties', {})
		if properties:
			nested_fields: dict[str, Any] = {}
			required_fields = set(schema.get('required', []))

			for prop_name, prop_schema in properties.items():
				prop_type = _json_schema_to_python_type(prop_schema, f'{model_name}_{prop_name}')

				if prop_name in required_fields:
					default = ...
				else:
					prop_type = prop_type | None
					default = prop_schema.get('default', None)

				field_kwargs: dict[str, Any] = {}
				if 'description' in prop_schema:
					field_kwargs['description'] = prop_schema['description']

				nested_fields[prop_name] = (prop_type, Field(default, **field_kwargs))

			class ConfiguredBaseModel(BaseModel):
				model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True)

			try:
				return create_model(model_name, __base__=ConfiguredBaseModel, **nested_fields)
			except Exception as e:
				logger.error(f'Failed to create nested model {model_name}: {e}')
				return dict
		else:
			return dict

	if json_type == 'array':
		if 'items' in schema:
			item_type = _json_schema_to_python_type(schema['items'], f'{model_name}_item')
			return list[item_type]
		return list

	base_type = type_mapping.get(json_type, str)

	if schema.get('nullable', False) or json_type == 'null':
		return base_type | None

	return base_type
