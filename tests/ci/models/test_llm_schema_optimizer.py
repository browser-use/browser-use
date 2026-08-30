"""
Tests for the SchemaOptimizer to ensure it correctly processes and
optimizes the schemas for agent actions without losing information.
"""

import json

from pydantic import BaseModel

from browser_use.agent.views import AgentOutput
from browser_use.llm.schema import SchemaOptimizer
from browser_use.tools.service import Tools


class ProductInfo(BaseModel):
	"""A sample structured output model with multiple fields."""

	price: str
	title: str
	rating: float | None = None


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


class Details(BaseModel):
	"""Nested model used behind a field whose name collides with a JSON Schema keyword."""

	summary: str
	bullets: list[str]


class Article(BaseModel):
	"""Structured output model with a field named after a JSON Schema keyword."""

	headline: str
	description: Details


def _find_refs(obj, path='') -> list[str]:
	"""Collect the location of every $ref left in a schema."""
	refs = []
	if isinstance(obj, dict):
		for key, value in obj.items():
			if key == '$ref':
				refs.append(f'{path}/$ref -> {value}')
			refs.extend(_find_refs(value, f'{path}/{key}'))
	elif isinstance(obj, list):
		for index, value in enumerate(obj):
			refs.extend(_find_refs(value, f'{path}[{index}]'))
	return refs


def test_optimizer_flattens_ref_behind_field_named_description():
	"""A model field named `description` must still get its $ref inlined.

	`$defs` is stripped from the optimized schema, so any $ref left behind points at
	nothing and the provider rejects the whole request.
	"""
	schema = SchemaOptimizer.create_optimized_json_schema(Article)

	assert _find_refs(schema) == [], f'Unresolved $ref left in schema: {_find_refs(schema)}'
	assert '$defs' not in json.dumps(schema)

	description_schema = schema['properties']['description']
	assert set(description_schema['properties']) == {'summary', 'bullets'}
	assert description_schema['additionalProperties'] is False


def test_structured_done_action_has_no_dangling_ref():
	"""Same bug through the public path: Agent(output_model_schema=...) -> done action."""
	tools = Tools(output_model=Article)
	ActionModel = tools.registry.create_action_model()
	agent_output_model = AgentOutput.type_with_custom_actions(ActionModel)

	optimized_schema = SchemaOptimizer.create_optimized_json_schema(agent_output_model)

	assert _find_refs(optimized_schema) == [], f'Unresolved $ref left in schema: {_find_refs(optimized_schema)}'


def test_optimizer_keeps_fields_named_after_schema_keywords():
	"""Field names that collide with JSON Schema keywords must survive optimization."""

	class KeywordFields(BaseModel):
		title: str
		description: str
		type: str
		properties: str
		items: str
		required: str

	schema = SchemaOptimizer.create_optimized_json_schema(KeywordFields)

	assert set(schema['properties']) == set(KeywordFields.model_fields)
	# metadata titles are still dropped from the property schemas themselves
	assert schema['properties']['description'] == {'type': 'string'}
	assert schema['properties']['properties'] == {'type': 'string'}
