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


class Category(BaseModel):
	"""A self-referencing model, e.g. a site's navigation tree."""

	name: str
	subcategories: list['Category']
	parent: 'Category | None' = None


class Person(BaseModel):
	name: str
	employer: 'Company | None' = None


class Company(BaseModel):
	name: str
	employees: list[Person]


def _assert_refs_resolve(schema: dict) -> None:
	def walk(obj):
		if isinstance(obj, dict):
			if isinstance(obj.get('$ref'), str):
				assert obj['$ref'].removeprefix('#/$defs/') in schema.get('$defs', {}), obj['$ref']
			for value in obj.values():
				walk(value)
		elif isinstance(obj, list):
			for item in obj:
				walk(item)

	walk(schema)


def test_optimizer_handles_self_referencing_model():
	"""Recursive models must keep a $ref to a $defs entry instead of inlining forever."""
	schema = SchemaOptimizer.create_optimized_json_schema(Category)

	assert schema['properties']['subcategories']['items'] == {'$ref': '#/$defs/Category'}
	assert set(schema['$defs']) == {'Category'}
	assert schema['$defs']['Category']['additionalProperties'] is False
	assert schema['$defs']['Category']['required'] == ['name', 'subcategories', 'parent']
	_assert_refs_resolve(schema)


def test_optimizer_handles_mutually_recursive_models():
	schema = SchemaOptimizer.create_optimized_json_schema(Company)

	# Person is inlined at the first level, the cycle back to Company stays a $ref
	person_schema = schema['properties']['employees']['items']
	assert person_schema['properties']['name'] == {'type': 'string'}
	assert {'$ref': '#/$defs/Company'} in person_schema['properties']['employer']['anyOf']
	assert set(schema['$defs']) == {'Company'}
	_assert_refs_resolve(schema)


def test_optimizer_handles_recursive_structured_done_action():
	tools = Tools(output_model=Category)
	agent_output_model = AgentOutput.type_with_custom_actions(tools.registry.create_action_model())

	schema = SchemaOptimizer.create_optimized_json_schema(agent_output_model)

	assert 'Category' in schema['$defs']
	_assert_refs_resolve(schema)
