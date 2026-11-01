"""
Tests for the SchemaOptimizer to ensure it correctly processes and
optimizes the schemas for agent actions without losing information.
"""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, Field

from browser_use.agent.views import AgentOutput
from browser_use.llm.messages import SystemMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.vercel import ChatVercel
from browser_use.tools.service import Tools

# Marker ChatVercel.ainvoke puts in front of the schema it asks the model to match.
SCHEMA_INSTRUCTION_MARKER = 'that exactly matches this schema:\n'


class ProductInfo(BaseModel):
	"""A sample structured output model with multiple fields."""

	price: str
	title: str
	rating: float | None = None


class VercelProduct(BaseModel):
	title: str
	price: str


def test_optimizer_preserves_all_fields_in_structured_done_action():
	"""
	Ensures the SchemaOptimizer does not drop fields from a custom structured
	output model when creating the schema for the 'done' action.

	This test specifically checks for a bug where fields were being lost
	during the optimization process.
	"""
	# 1. Setup a tools with a custom output model, simulating an Agent
	#    being created with an `output_model_schema`.
	tools = Tools(output_model=ProductInfo)

	# 2. Get the dynamically created AgentOutput model, which includes all registered actions.
	ActionModel = tools.registry.create_action_model()
	agent_output_model = AgentOutput.type_with_custom_actions(ActionModel)

	# 3. Run the schema optimizer on the agent's output model.
	optimized_schema = SchemaOptimizer.create_optimized_json_schema(agent_output_model)

	# 4. Find the 'done' action schema within the optimized output.
	# The path is properties -> action -> items -> anyOf -> [schema with 'done'].
	done_action_schema = None
	actions_schemas = optimized_schema.get('properties', {}).get('action', {}).get('items', {}).get('anyOf', [])
	for action_schema in actions_schemas:
		if 'done' in action_schema.get('properties', {}):
			done_action_schema = action_schema
			break

	# 5. Assert that the 'done' action schema was successfully found.
	assert done_action_schema is not None, "Could not find 'done' action in the optimized schema."

	# 6. Navigate to the schema for our custom data model within the 'done' action.
	# The path is properties -> done -> properties -> data -> properties.
	done_params_schema = done_action_schema.get('properties', {}).get('done', {})
	structured_data_schema = done_params_schema.get('properties', {}).get('data', {})
	final_properties = structured_data_schema.get('properties', {})

	# 7. Assert that the set of fields in the optimized schema matches the original model's fields.
	original_fields = set(ProductInfo.model_fields.keys())
	optimized_fields = set(final_properties.keys())

	assert original_fields == optimized_fields, (
		f"Field mismatch between original and optimized structured 'done' action schema.\n"
		f'Missing from optimized: {original_fields - optimized_fields}\n'
		f'Unexpected in optimized: {optimized_fields - original_fields}'
	)


def test_gemini_schema_retains_required_fields():
	"""Gemini schema should keep explicit required arrays for mandatory fields."""
	schema = SchemaOptimizer.create_gemini_optimized_schema(ProductInfo)

	assert 'required' in schema, 'Gemini schema removed required fields.'

	required_fields = set(schema['required'])
	assert {'price', 'title'}.issubset(required_fields), 'Mandatory fields must stay required for Gemini.'


def test_optimizer_treats_property_names_as_data_not_schema_keywords():
	"""Nested fields named after schema keywords must still have their refs flattened."""

	class Details(BaseModel):
		summary: str

	class Article(BaseModel):
		description: Details
		properties: Details
		additional_properties: Details = Field(alias='additionalProperties')
		defs: Details = Field(alias='$defs')

	schema = SchemaOptimizer.create_optimized_json_schema(Article)

	assert '$defs' not in schema
	for field_name in ('description', 'properties', 'additionalProperties', '$defs'):
		field_schema = schema['properties'][field_name]
		assert '$ref' not in field_schema
		assert field_schema['properties']['summary']['type'] == 'string'


def test_vercel_gemini_schema_preserves_title_property():
	"""Vercel Gemini cleanup must preserve a user field named ``title``."""
	chat = ChatVercel(model='openai/gpt-4o', api_key='test')
	schema = {
		'type': 'object',
		'title': 'ProductInfo',
		'properties': {
			'title': {'type': 'string', 'title': 'Title'},
			'price': {'type': 'number', 'title': 'Price'},
		},
		'required': ['title', 'price'],
	}

	cleaned = chat._fix_gemini_schema(schema)

	assert 'title' not in cleaned, 'The top-level metadata title must still be stripped.'
	assert set(cleaned['properties']) == {'title', 'price'}
	assert 'title' not in cleaned['properties']['title']
	assert cleaned['required'] == ['title', 'price']


def test_vercel_gemini_schema_strips_title_under_property_named_properties():
	"""Properties-map context must be tracked structurally, not by the parent key name."""
	chat = ChatVercel(model='openai/gpt-4o', api_key='test')
	schema = {
		'type': 'object',
		'title': 'Outer',
		'properties': {
			'properties': {
				'type': 'object',
				'title': 'Inner',
				'properties': {'title': {'type': 'string', 'title': 'Inner title'}},
				'required': ['title'],
			},
			'title': {'type': 'string', 'title': 'Outer title'},
		},
		'required': ['properties', 'title'],
	}

	cleaned = chat._fix_gemini_schema(schema)

	# Both property names survive, including the one literally called 'properties'.
	assert set(cleaned['properties']) == {'properties', 'title'}
	# Its sub-schema is a schema again, so the metadata titles inside it are stripped...
	assert 'title' not in cleaned['properties']['properties']
	assert 'title' not in cleaned['properties']['title']
	# ...while its own real 'title' field is still a real field.
	assert cleaned['properties']['properties']['properties'] == {'title': {'type': 'string'}}
	assert cleaned['properties']['title'] == {'type': 'string'}
	assert cleaned['required'] == ['properties', 'title']


def test_vercel_gemini_schema_preserves_properties_named_like_schema_keywords():
	"""Fields named 'default' or 'additionalProperties' are data, not schema keywords."""
	chat = ChatVercel(model='openai/gpt-4o', api_key='test')
	schema = {
		'type': 'object',
		'properties': {
			'default': {'type': 'string'},
			'additionalProperties': {'type': 'string'},
		},
		'required': ['default', 'additionalProperties'],
		'additionalProperties': False,
	}

	cleaned = chat._fix_gemini_schema(schema)

	# The property names survive - only the schema keyword itself is dropped.
	assert set(cleaned['properties']) == {'default', 'additionalProperties'}
	assert cleaned['properties']['default'] == {'type': 'string'}
	assert cleaned['properties']['additionalProperties'] == {'type': 'string'}
	# 'required' must not reference properties that were dropped.
	assert cleaned['required'] == ['default', 'additionalProperties']
	assert set(cleaned['required']) == set(cleaned['properties'])
	# The keyword form is still removed from the schema itself.
	assert 'additionalProperties' not in {k for k in cleaned if k != 'properties'}


def test_vercel_gemini_schema_keeps_properties_and_required_consistent_for_default_only_field():
	"""A lone field named 'default' must not be replaced by a placeholder property."""
	chat = ChatVercel(model='openai/gpt-4o', api_key='test')
	schema = {
		'type': 'object',
		'properties': {'default': {'type': 'string'}},
		'required': ['default'],
	}

	cleaned = chat._fix_gemini_schema(schema)

	assert cleaned['properties'] == {'default': {'type': 'string'}}
	assert cleaned['required'] == ['default']


def _find_keys(node: Any, key: str) -> list[Any]:
	"""Collect every occurrence of ``key`` anywhere in a nested schema fragment."""
	found: list[Any] = []
	if isinstance(node, dict):
		for current_key, value in node.items():
			if current_key == key:
				found.append(value)
			found.extend(_find_keys(value, key))
	elif isinstance(node, list):
		for item in node:
			found.extend(_find_keys(item, key))
	return found


async def _ainvoke_prompt_schema(llm: ChatVercel, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
	"""Run ChatVercel.ainvoke and return the JSON schema it embedded in the prompt."""
	captured: dict[str, Any] = {}

	class FakeCompletions:
		async def create(self, **kwargs):
			captured.update(kwargs)
			return SimpleNamespace(
				choices=[
					SimpleNamespace(message=SimpleNamespace(content='{"title": "Widget", "price": "9.99"}'), finish_reason='stop')
				],
				usage=None,
			)

	monkeypatch.setattr(llm, 'get_client', lambda: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())))

	result = await llm.ainvoke([SystemMessage(content='Extract the product info.')], output_format=VercelProduct)
	assert result.completion.title == 'Widget'

	prompt = next(
		message['content']
		for message in captured['messages']
		if isinstance(message.get('content'), str) and SCHEMA_INSTRUCTION_MARKER in message['content']
	)
	return json.loads(prompt.split(SCHEMA_INSTRUCTION_MARKER, 1)[1])


async def test_vercel_gemini_ainvoke_sends_cleaned_schema(monkeypatch):
	"""ChatVercel.ainvoke must send the Gemini-cleaned schema, not the raw optimized one."""
	llm = ChatVercel(model='google/gemini-2.5-flash', api_key='test-key')
	schema = await _ainvoke_prompt_schema(llm, monkeypatch)

	# Gemini rejects additionalProperties, and the only 'title' left may be the real field.
	assert _find_keys(schema, 'additionalProperties') == []
	assert _find_keys(schema, 'title') == [schema['properties']['title']]
	assert schema == {
		'type': 'object',
		'properties': {'title': {'type': 'string'}, 'price': {'type': 'string'}},
		'required': ['title', 'price'],
	}


async def test_vercel_anthropic_ainvoke_keeps_non_gemini_schema_keywords(monkeypatch):
	"""The Gemini cleanup must not be applied to Anthropic, which accepts those keywords."""
	llm = ChatVercel(model='anthropic/claude-sonnet-4-5', api_key='test-key')
	schema = await _ainvoke_prompt_schema(llm, monkeypatch)

	# Anthropic understands 'additionalProperties' and 'default', so they must survive.
	assert schema['additionalProperties'] is False
	assert 'additionalProperties' not in schema['properties']
	assert _find_keys(schema, 'title') == [schema['properties']['title']]


async def test_vercel_reasoning_ainvoke_keeps_non_gemini_schema_keywords(monkeypatch):
	"""The Gemini cleanup must not be applied to non-Google reasoning models either."""
	llm = ChatVercel(model='deepseek/deepseek-r1', api_key='test-key')
	schema = await _ainvoke_prompt_schema(llm, monkeypatch)

	assert schema['additionalProperties'] is False
	assert _find_keys(schema, 'title') == [schema['properties']['title']]
