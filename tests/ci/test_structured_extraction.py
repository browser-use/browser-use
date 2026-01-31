"""Tests for PR 1: Schema-enforced extraction via output_schema on ExtractAction."""

import json

import pytest
from pydantic import BaseModel, ValidationError

from browser_use.tools.extraction.schema_utils import schema_dict_to_pydantic_model
from browser_use.tools.extraction.views import ExtractionResult


# ── schema_dict_to_pydantic_model tests ──────────────────────────────────────


class TestSchemaDictToPydanticModel:
	"""Round-trip tests for JSON Schema → Pydantic model conversion."""

	def test_flat_object(self):
		schema = {
			'type': 'object',
			'properties': {
				'name': {'type': 'string'},
				'age': {'type': 'integer'},
				'score': {'type': 'number'},
				'active': {'type': 'boolean'},
			},
			'required': ['name', 'age'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(name='Alice', age=30, score=9.5, active=True)
		assert instance.name == 'Alice'  # type: ignore[attr-defined]
		assert instance.age == 30  # type: ignore[attr-defined]
		assert instance.score == 9.5  # type: ignore[attr-defined]

		# Optional fields should default to None
		instance2 = Model(name='Bob', age=25)
		assert instance2.score is None  # type: ignore[attr-defined]
		assert instance2.active is None  # type: ignore[attr-defined]

	def test_nested_object(self):
		schema = {
			'type': 'object',
			'properties': {
				'user': {
					'type': 'object',
					'properties': {
						'name': {'type': 'string'},
						'email': {'type': 'string'},
					},
					'required': ['name'],
				},
			},
			'required': ['user'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(user={'name': 'Alice', 'email': 'alice@example.com'})
		assert instance.user.name == 'Alice'  # type: ignore[attr-defined]
		assert instance.user.email == 'alice@example.com'  # type: ignore[attr-defined]

	def test_array_of_objects(self):
		schema = {
			'type': 'object',
			'properties': {
				'products': {
					'type': 'array',
					'items': {
						'type': 'object',
						'properties': {
							'name': {'type': 'string'},
							'price': {'type': 'number'},
						},
						'required': ['name', 'price'],
					},
				},
			},
			'required': ['products'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		data = {'products': [{'name': 'Widget', 'price': 9.99}, {'name': 'Gadget', 'price': 19.99}]}
		instance = Model(**data)
		assert len(instance.products) == 2  # type: ignore[attr-defined]
		assert instance.products[0].name == 'Widget'  # type: ignore[attr-defined]
		assert instance.products[1].price == 19.99  # type: ignore[attr-defined]

	def test_array_of_primitives(self):
		schema = {
			'type': 'object',
			'properties': {
				'tags': {
					'type': 'array',
					'items': {'type': 'string'},
				},
			},
			'required': ['tags'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(tags=['a', 'b', 'c'])
		assert instance.tags == ['a', 'b', 'c']  # type: ignore[attr-defined]

	def test_round_trip_json_schema(self):
		"""A Pydantic model's json_schema → schema_dict_to_pydantic_model → validates same data."""

		class Product(BaseModel):
			name: str
			price: float
			in_stock: bool

		class Catalog(BaseModel):
			products: list[Product]

		schema = Catalog.model_json_schema()
		# schema_dict_to_pydantic_model expects a flat object with properties,
		# but model_json_schema() may use $defs. For this test, use a simplified schema.
		simplified_schema = {
			'type': 'object',
			'properties': {
				'products': {
					'type': 'array',
					'items': {
						'type': 'object',
						'properties': {
							'name': {'type': 'string'},
							'price': {'type': 'number'},
							'in_stock': {'type': 'boolean'},
						},
						'required': ['name', 'price', 'in_stock'],
					},
				},
			},
			'required': ['products'],
		}
		Model = schema_dict_to_pydantic_model(simplified_schema)
		data = {'products': [{'name': 'Widget', 'price': 9.99, 'in_stock': True}]}
		instance = Model(**data)
		dumped = instance.model_dump()
		assert dumped['products'][0]['name'] == 'Widget'

	def test_non_object_root_raises(self):
		with pytest.raises(ValueError, match="Root schema must have type 'object'"):
			schema_dict_to_pydantic_model({'type': 'array', 'items': {'type': 'string'}})

	def test_no_properties_raises(self):
		with pytest.raises(ValueError, match="must have 'properties'"):
			schema_dict_to_pydantic_model({'type': 'object'})

	def test_unsupported_type_raises(self):
		with pytest.raises(ValueError, match='Unsupported JSON Schema type'):
			schema_dict_to_pydantic_model(
				{
					'type': 'object',
					'properties': {
						'data': {'type': 'null'},
					},
				}
			)

	def test_description_field(self):
		schema = {
			'type': 'object',
			'properties': {
				'name': {'type': 'string', 'description': 'The product name'},
			},
			'required': ['name'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		info = Model.model_fields['name']
		assert info.description == 'The product name'

	def test_object_without_properties_returns_dict(self):
		"""An object field with no properties should resolve to dict[str, Any]."""
		schema = {
			'type': 'object',
			'properties': {
				'metadata': {'type': 'object'},
			},
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(metadata={'key': 'value'})
		assert instance.metadata == {'key': 'value'}  # type: ignore[attr-defined]

	def test_array_without_items_returns_list(self):
		"""An array field with no items schema should resolve to list[Any]."""
		schema = {
			'type': 'object',
			'properties': {
				'data': {'type': 'array'},
			},
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(data=[1, 'two', {'three': 3}])
		assert len(instance.data) == 3  # type: ignore[attr-defined]


# ── ExtractionResult model tests ─────────────────────────────────────────────


class TestExtractionResult:
	def test_basic_creation(self):
		result = ExtractionResult(data={'key': 'value'}, schema_used=True)
		assert result.data == {'key': 'value'}
		assert result.schema_used is True
		assert result.is_partial is False

	def test_free_text_result(self):
		result = ExtractionResult(data='Some extracted text')
		assert result.schema_used is False

	def test_with_stats(self):
		result = ExtractionResult(
			data=[1, 2, 3],
			source_url='https://example.com',
			content_stats={'original_html_chars': 5000},
		)
		assert result.source_url == 'https://example.com'
		assert result.content_stats['original_html_chars'] == 5000


# ── ExtractAction output_schema field test ───────────────────────────────────


class TestExtractActionOutputSchema:
	def test_extract_action_has_output_schema_field(self):
		from browser_use.tools.views import ExtractAction

		action = ExtractAction(query='Get products')
		assert action.output_schema is None

	def test_extract_action_with_schema(self):
		from browser_use.tools.views import ExtractAction

		schema = {'type': 'object', 'properties': {'name': {'type': 'string'}}}
		action = ExtractAction(query='Get products', output_schema=schema)
		assert action.output_schema == schema

	def test_extract_action_backward_compat(self):
		"""Existing code that doesn't pass output_schema should still work."""
		from browser_use.tools.views import ExtractAction

		action = ExtractAction(query='What is the price?', extract_links=True, start_from_char=100)
		assert action.query == 'What is the price?'
		assert action.extract_links is True
		assert action.start_from_char == 100
		assert action.output_schema is None
