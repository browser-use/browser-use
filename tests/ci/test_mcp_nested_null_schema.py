import inspect
import sys
import textwrap

import pytest
from mcp import types
from pydantic import ValidationError

from browser_use.mcp import MCPClient
from browser_use.mcp.client import _serialize_mcp_params
from browser_use.tools import Tools


def _parameters_model(schema: dict) -> type:
	client = MCPClient(server_name='test', command='unused')
	tool = types.Tool(
		name='test_tool',
		input_schema=schema,
	)
	model = client._create_parameters_model('test_tool', tool)
	assert model is not None
	return model


def test_nested_explicit_nulls_and_omitted_fields_are_serialized_correctly():
	model = _parameters_model(
		{
			'type': 'object',
			'properties': {
				'payload': {
					'type': 'object',
					'properties': {
						'note': {'type': ['string', 'null']},
						'values': {'type': 'array', 'items': {'type': ['string', 'null']}},
					},
					'required': ['note', 'values'],
				},
				'optional': {'type': 'string'},
			},
			'required': ['payload'],
		}
	)

	params = model.model_validate({'payload': {'note': None, 'values': ['first', None]}})

	assert _serialize_mcp_params(params) == {'payload': {'note': None, 'values': ['first', None]}}


def test_schema_defaults_are_included_but_omitted_null_fields_are_not():
	model = _parameters_model(
		{
			'type': 'object',
			'properties': {
				'nullable': {'type': ['string', 'null']},
				'fallback': {'type': 'string', 'default': 'schema default'},
			},
		}
	)

	assert _serialize_mcp_params(model.model_validate({})) == {'fallback': 'schema default'}
	assert _serialize_mcp_params(model.model_validate({'nullable': None})) == {
		'nullable': None,
		'fallback': 'schema default',
	}


def test_json_schema_type_arrays_are_preserved_for_the_action_model():
	model = _parameters_model(
		{
			'type': 'object',
			'properties': {'value': {'type': ['string', 'null'], 'description': 'A nullable value'}},
			'required': ['value'],
		}
	)

	assert model.model_json_schema(by_alias=True)['properties']['value']['anyOf'] == [
		{'type': 'string'},
		{'type': 'null'},
	]


def test_composed_nullable_schema_keeps_absence_distinct_from_null():
	model = _parameters_model(
		{
			'type': 'object',
			'properties': {
				'payload': {
					'anyOf': [
						{
							'type': 'object',
							'properties': {'name': {'type': 'string'}},
							'required': ['name'],
						},
						{'type': 'null'},
					]
				}
			},
		}
	)

	assert _serialize_mcp_params(model.model_validate({})) == {}
	assert _serialize_mcp_params(model.model_validate({'payload': None})) == {'payload': None}
	with pytest.raises(ValidationError):
		model.model_validate({'payload': {}})


@pytest.mark.parametrize(
	'nullable_schema',
	[
		{'type': 'object', 'nullable': True, 'properties': {'name': {'type': 'string'}}},
		{'type': 'array', 'nullable': True, 'items': {'type': 'string'}},
		{'type': 'string', 'enum': ['ready', None]},
		{'type': 'null'},
		{'type': ['string', 'null']},
		{'anyOf': [{'type': 'string'}, {'type': 'null'}]},
		{'oneOf': [{'type': 'string'}, {'type': 'null'}]},
	],
)
def test_nullable_schema_forms_accept_and_transmit_null(nullable_schema):
	model = _parameters_model(
		{
			'type': 'object',
			'properties': {'value': nullable_schema},
			'required': ['value'],
		}
	)

	assert _serialize_mcp_params(model.model_validate({'value': None})) == {'value': None}


def test_composition_enforces_sibling_type_and_object_constraints():
	model = _parameters_model(
		{
			'type': 'object',
			'properties': {
				'text': {'type': 'string', 'anyOf': [{'type': 'string'}, {'type': 'null'}]},
				'payload': {
					'type': 'object',
					'properties': {'name': {'type': 'string'}},
					'required': ['name'],
					'anyOf': [{'type': 'object'}],
				},
			},
			'required': ['text', 'payload'],
		}
	)

	for value in (
		{'text': None, 'payload': {'name': 'member'}},
		{'text': 'hello', 'payload': {}},
	):
		with pytest.raises(ValidationError):
			model.model_validate(value)
	assert model.model_validate({'text': 'hello', 'payload': {'name': 'member'}})


def test_one_of_rejects_values_matching_multiple_alternatives():
	model = _parameters_model(
		{
			'type': 'object',
			'properties': {
				'value': {
					'oneOf': [
						{'type': 'string'},
						{'anyOf': [{'type': 'string'}, {'type': 'number'}]},
					]
				}
			},
			'required': ['value'],
		}
	)

	with pytest.raises(ValidationError):
		model.model_validate({'value': 'matches-both'})
	assert model.model_validate({'value': 3})


def test_all_of_object_intersections_and_boolean_alternatives():
	model = _parameters_model(
		{
			'type': 'object',
			'properties': {
				'payload': {
					'allOf': [
						{'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
						{'type': 'object', 'properties': {'age': {'type': 'integer'}}, 'required': ['age']},
					]
				},
				'choice': {'anyOf': [False, {'type': 'string'}]},
			},
			'required': ['payload', 'choice'],
		}
	)

	assert model.model_validate({'payload': {'name': 'member', 'age': 3}, 'choice': 'accepted'})
	for value in (
		{'payload': {'name': 'member'}, 'choice': 'accepted'},
		{'payload': {'name': 'member', 'age': 3}, 'choice': 1},
	):
		with pytest.raises(ValidationError):
			model.model_validate(value)


def test_json_schema_enum_const_and_unique_items_use_json_equality():
	model = _parameters_model(
		{
			'type': 'object',
			'properties': {
				'enum_value': {'type': 'integer', 'enum': [1]},
				'constant': {'type': 'integer', 'const': 1},
				'values': {
					'type': 'array',
					'items': {'type': ['integer', 'boolean']},
					'uniqueItems': True,
				},
			},
			'required': ['enum_value', 'constant', 'values'],
		}
	)

	assert model.model_validate({'enum_value': 1, 'constant': 1, 'values': [1, True]})
	for field in ('enum_value', 'constant'):
		invalid_values = {'enum_value': 1, 'constant': 1, 'values': []}
		invalid_values[field] = True
		with pytest.raises(ValidationError):
			model.model_validate(invalid_values)
	with pytest.raises(ValidationError):
		model.model_validate({'enum_value': 1, 'constant': 1, 'values': [1, 1]})


@pytest.mark.parametrize(
	('schema', 'invalid_value'),
	[
		({'type': 'number', 'multipleOf': 0.1}, 0.15),
		({'type': 'string', 'minLength': 2, 'pattern': '^[a-z]+$'}, 'A'),
		({'type': 'array', 'minItems': 2, 'items': {'type': 'integer'}}, [1]),
		({'type': 'array', 'contains': {'const': 'required'}}, ['other']),
	],
)
def test_composed_and_scalar_constraints_reject_invalid_values(schema, invalid_value):
	model = _parameters_model(
		{
			'type': 'object',
			'properties': {'value': schema},
			'required': ['value'],
		}
	)

	with pytest.raises(ValidationError):
		model.model_validate({'value': invalid_value})


def test_false_boolean_schema_alternative_rejects_values():
	model = _parameters_model(
		{
			'type': 'object',
			'properties': {'value': False},
			'required': ['value'],
		}
	)

	with pytest.raises(ValidationError):
		model.model_validate({'value': 'not allowed'})


async def test_stdio_mcp_tool_receives_explicit_nullable_value():
	server_code = textwrap.dedent(
		"""
		import asyncio
		from mcp.server.mcpserver import MCPServer
		from pydantic import BaseModel

		server = MCPServer('nullable-test')

		class Payload(BaseModel):
			note: str | None
			values: list[str | None]

		@server.tool()
		def save_payload(payload: Payload) -> str:
			return payload.model_dump_json()

		@server.tool()
		def ping() -> str:
			return 'pong'

		asyncio.run(server.run_stdio_async())
		"""
	)
	client = MCPClient(server_name='nullable-test', command=sys.executable, args=['-c', server_code])
	tools = Tools()

	async with client:
		await client.register_to_tools(tools)
		save_payload = next(tool for tool in tools.functions if tool.name == 'save_payload')
		parameters = inspect.signature(save_payload.function).parameters['params'].annotation
		result = await client._call_tool(
			'save_payload',
			_serialize_mcp_params(parameters(payload={'note': None, 'values': ['first', None]})),
		)
		assert any(tool.name == 'ping' for tool in tools.functions)
		ping_result = await client._call_tool('ping', {})

	assert result.error is None
	assert result.extracted_content == '{"note":null,"values":["first",null]}'
	assert ping_result.error is None
	assert ping_result.extracted_content == 'pong'
