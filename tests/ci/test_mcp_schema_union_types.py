"""Tests for MCP tool input schemas that use a JSON Schema `type` array (#6278).

JSON Schema permits `"type": ["string", "null"]`, and MCP servers emit it for
nullable tool arguments. `MCPClient._json_schema_to_python_type` used to pass
the list to a dict lookup and raise `TypeError: unhashable type: 'list'`, which
aborted registration of every following tool.
"""

import pytest

from browser_use.mcp.client import MCPClient


@pytest.fixture
def client() -> MCPClient:
	return MCPClient(server_name='test', command='python')


def test_union_type_with_null(client: MCPClient) -> None:
	assert client._json_schema_to_python_type({'type': ['string', 'null']}) == (str | None)


def test_union_type_without_null(client: MCPClient) -> None:
	assert client._json_schema_to_python_type({'type': ['string', 'integer']}) == (str | int)


@pytest.mark.parametrize(
	('schema', 'expected'),
	[
		({'type': ['null']}, type(None)),
		({'type': []}, str),
		({'type': ['array'], 'items': {'type': ['string', 'null']}}, list[str | None]),
	],
)
def test_edge_cases(client: MCPClient, schema: dict, expected: object) -> None:
	assert client._json_schema_to_python_type(schema) == expected


def test_union_type_inside_object_properties(client: MCPClient) -> None:
	model = client._json_schema_to_python_type(
		{
			'type': 'object',
			'properties': {'value': {'type': ['string', 'null']}},
			'required': ['value'],
		},
		'TypedEcho',
	)

	validated = model(value='hello')
	assert validated.value == 'hello'
	assert model(value=None).value is None
	with pytest.raises(ValueError):
		model(value=42)
