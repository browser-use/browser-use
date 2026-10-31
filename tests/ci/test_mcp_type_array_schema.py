"""Regression tests for JSON Schema type arrays in MCP tool registration (#6278)."""

from unittest.mock import MagicMock

from mcp import types

from browser_use import Tools
from browser_use.mcp.client import MCPClient


def _make_client() -> MCPClient:
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	client._connected = True
	client.session = MagicMock()
	return client


def test_json_schema_type_array_nullable_string():
	"""An MCP parameter with type: ['string', 'null'] should resolve to str | None."""
	client = _make_client()
	param_type = client._json_schema_to_python_type({'type': ['string', 'null']})
	assert param_type == (str | None)


def test_json_schema_type_array_nullable_integer():
	"""An MCP parameter with type: ['integer', 'null'] should resolve to int | None."""
	client = _make_client()
	param_type = client._json_schema_to_python_type({'type': ['integer', 'null']})
	assert param_type == (int | None)


def test_json_schema_type_array_multi_type_union():
	"""An MCP parameter with type: ['string', 'integer'] should resolve to str | int."""
	client = _make_client()
	param_type = client._json_schema_to_python_type({'type': ['string', 'integer']})
	assert param_type == (str | int)


def test_json_schema_type_array_with_nullable_flag():
	"""A type array with nullable: True should append NoneType to the union (#6278)."""
	client = _make_client()
	param_type = client._json_schema_to_python_type({'type': ['string'], 'nullable': True})
	assert param_type == (str | None)

	multi_type = client._json_schema_to_python_type({'type': ['integer', 'string'], 'nullable': True})
	assert multi_type == (int | str | None)


def test_json_schema_type_array_with_enum():
	"""A nullable type array with an enum must retain nullability (#6278)."""
	client = _make_client()
	enum_type = client._json_schema_to_python_type({'type': ['string', 'null'], 'enum': ['asc', 'desc']})
	assert enum_type == (str | None)

	enum_flag = client._json_schema_to_python_type({'type': 'string', 'enum': ['asc', 'desc'], 'nullable': True})
	assert enum_flag == (str | None)


def test_register_action_with_type_array_parameter():
	"""Registering an action with a type array parameter must not crash with TypeError (#6278)."""
	client = _make_client()
	tools = Tools()
	tool = types.Tool(
		name='echo_nullable',
		description='Echo tool accepting nullable or union values',
		input_schema={
			'type': 'object',
			'properties': {
				'val_str': {'type': ['string', 'null']},
				'val_int': {'type': ['integer', 'null']},
				'val_union': {'type': ['string', 'number']},
				'val_enum': {'type': ['string', 'null'], 'enum': ['ready', 'pending']},
			},
			'required': ['val_str'],
		},
	)

	# Must succeed without raising TypeError: unhashable type: 'list'
	client._register_tool_as_action(tools.registry, 'echo_nullable', tool)
	assert 'echo_nullable' in tools.registry.registry.actions
