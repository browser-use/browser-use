"""
Test to reproduce and verify fix for GitHub issue #2470:
"Python field with name 'type' handled differently between Gemini and OpenAI GPT"
"""

from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.schema import SchemaOptimizer


class TestGeminiTypeFieldHandling:
	"""Test class for reproducing the type field issue with Gemini schema processing."""

	def test_gemini_schema_with_dict_type_field(self):
		"""
		Test that Gemini schema processing handles dict 'type' field gracefully.
		Reproduces the AttributeError: 'dict' object has no attribute 'upper'
		"""
		chat_google = ChatGoogle(model='gemini-2.0-flash-exp')

		# Schema with dict instead of string in type field
		problematic_schema = {'type': {'malformed': 'dict_type'}, 'properties': {}}

		result = chat_google._fix_gemini_schema(problematic_schema)
		assert result is not None
		assert isinstance(result, dict)
		assert result['type'] == {'malformed': 'dict_type'}

	def test_gemini_schema_with_nested_dict_type_field(self):
		"""
		Test that nested dict 'type' fields are handled gracefully.
		"""
		chat_google = ChatGoogle(model='gemini-2.0-flash-exp')

		# Schema with nested dict type field
		problematic_schema = {
			'type': 'object',
			'properties': {'nested_field': {'type': {'malformed': 'dict_instead_of_string'}, 'properties': {}}},
		}

		result = chat_google._fix_gemini_schema(problematic_schema)
		assert result is not None
		assert isinstance(result, dict)
		nested_type = result['properties']['nested_field']['type']
		assert nested_type == {'malformed': 'dict_instead_of_string'}

	def test_gemini_schema_with_none_type_field(self):
		"""Test handling of None type field."""
		chat_google = ChatGoogle(model='gemini-2.0-flash-exp')

		problematic_schema = {'type': 'object', 'properties': {'nested_field': {'type': None, 'properties': {}}}}

		result = chat_google._fix_gemini_schema(problematic_schema)
		assert result is not None

	def test_gemini_schema_with_valid_string_type(self):
		"""Test that valid string type fields work correctly."""
		chat_google = ChatGoogle(model='gemini-2.0-flash-exp')

		valid_schema = {'type': 'object', 'properties': {'nested_field': {'type': 'object', 'properties': {}}}}

		# Should work without issues
		result = chat_google._fix_gemini_schema(valid_schema)
		assert result is not None
		assert isinstance(result, dict)

	def test_gemini_schema_with_empty_properties_object(self):
		"""Test handling of empty properties in object type."""
		chat_google = ChatGoogle(model='gemini-2.0-flash-exp')

		schema_with_empty_props = {
			'type': 'object',
			'properties': {
				'empty_object': {
					'type': 'object',
					'properties': {},  # Empty properties should get placeholder
				}
			},
		}

		result = chat_google._fix_gemini_schema(schema_with_empty_props)

		nested_props = result['properties']['empty_object']['properties']
		assert '_placeholder' in nested_props
		assert nested_props['_placeholder']['type'] == 'string'

	def test_consistency_between_providers(self):
		"""
		Test that both Gemini and OpenAI handle schemas consistently.
		The original issue was that Gemini would fail where OpenAI succeeded.
		"""
		from pydantic import BaseModel, Field

		# Create a test model that generates a schema with dict type
		class TestModel(BaseModel):
			field_with_dict_type: dict = Field(default_factory=dict)

		# OpenAI uses SchemaOptimizer directly
		openai_schema = SchemaOptimizer.create_optimized_json_schema(TestModel)
		assert openai_schema is not None

		# Gemini processes the schema through _fix_gemini_schema
		chat_google = ChatGoogle(model='gemini-2.0-flash-exp')
		gemini_result = chat_google._fix_gemini_schema(openai_schema)
		assert gemini_result is not None

		# Both should handle the schema without errors
		# This demonstrates that the fix makes Gemini consistent with OpenAI
