"""Regression test: schema compatibility cleanup must not delete user fields named like metadata keywords.

The final `remove_forbidden_fields` pass popped `default`, `minItems` and `min_items` from every dictionary,
including `properties` maps, so fields with those names disappeared while staying in `required`.
"""

from pydantic import BaseModel

from browser_use.llm.schema import SchemaOptimizer


class Output(BaseModel):
	default: bool
	minItems: str
	min_items: str
	optional_value: str = 'fallback'


class Nested(BaseModel):
	inner: Output


def test_fields_named_like_metadata_survive_cleanup() -> None:
	schema = SchemaOptimizer.create_optimized_json_schema(Output, remove_defaults=True, remove_min_items=True)

	assert set(schema['properties']) == {'default', 'minItems', 'min_items', 'optional_value'}
	assert schema['required'] == ['default', 'minItems', 'min_items', 'optional_value']


def test_nested_schema_keeps_named_fields() -> None:
	schema = SchemaOptimizer.create_optimized_json_schema(Nested, remove_defaults=True, remove_min_items=True)

	inner = schema['properties']['inner']
	assert set(inner['properties']) == {'default', 'minItems', 'min_items', 'optional_value'}


def test_actual_metadata_is_still_removed() -> None:
	class WithMetadata(BaseModel):
		items: list[str] = []
		label: str = 'hello'

	schema = SchemaOptimizer.create_optimized_json_schema(WithMetadata, remove_defaults=True, remove_min_items=True)

	assert 'default' not in schema['properties']['label']
	assert 'minItems' not in schema['properties']['items']
	assert 'default' not in schema['properties']['items']
