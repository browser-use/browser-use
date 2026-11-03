"""
Tests for the SchemaOptimizer to ensure it correctly processes and
optimizes the schemas for agent actions without losing information.
"""

from pydantic import BaseModel, Field

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


def test_optimizer_preserves_instance_keyword_values():
	"""Schema-shaped dictionaries in defaults and examples are still user data."""

	class Search(BaseModel):
		filters: dict[str, str] = Field(default={'title': 'Engineer', 'type': 'object'})
		columns: list[dict[str, str]] = Field(default=[{'title': 'Name', 'description': ''}])

		model_config = {'json_schema_extra': {'examples': [{'type': 'object', 'properties': {'title': 'data'}}]}}

	schema = SchemaOptimizer.create_optimized_json_schema(Search)
	properties = schema['properties']

	assert properties['filters']['default'] == {'title': 'Engineer', 'type': 'object'}
	assert properties['columns']['default'] == [{'title': 'Name', 'description': ''}]
	assert schema['examples'] == [{'type': 'object', 'properties': {'title': 'data'}}]
	assert properties['filters']['additionalProperties'] is False


def test_remove_defaults_does_not_rewrite_other_instance_values():
	"""Removing schema defaults leaves const, enum, and examples untouched."""

	class Value(BaseModel):
		choice: str = Field(default='x', json_schema_extra={'const': {'title': 'fixed'}, 'examples': [{'type': 'object'}]})

	schema = SchemaOptimizer.create_optimized_json_schema(Value, remove_defaults=True)
	field_schema = schema['properties']['choice']

	assert 'default' not in field_schema
	assert field_schema['const'] == {'title': 'fixed'}
	assert field_schema['examples'] == [{'type': 'object'}]
