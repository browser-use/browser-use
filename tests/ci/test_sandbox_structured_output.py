"""
Tests for sandbox structured output handling.

Tests that output_model_schema works correctly when using @sandbox decorator,
specifically that the _output_model_schema private attribute is preserved
through serialization/deserialization.
"""

from pydantic import BaseModel

from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList, BrowserStateHistory
from browser_use.sandbox.sandbox import _parse_with_type_annotation


class ExtractedData(BaseModel):
	"""Example structured output model"""

	title: str
	price: float
	in_stock: bool


class NestedModel(BaseModel):
	"""Nested model for testing complex structures"""

	items: list[ExtractedData]
	total_count: int


class TestGetStructuredOutput:
	"""Tests for AgentHistoryList.get_structured_output method"""

	def test_get_structured_output_parses_final_result(self):
		"""Test that get_structured_output correctly parses final result with provided schema"""
		# Create history with structured JSON as final result
		json_result = '{"title": "Test Product", "price": 29.99, "in_stock": true}'

		history = AgentHistoryList(
			history=[
				AgentHistory(
					model_output=None,
					result=[ActionResult(extracted_content=json_result, is_done=True)],
					state=BrowserStateHistory(url='https://example.com', title='Test', tabs=[], interacted_element=[]),
				)
			]
		)

		# Use get_structured_output with explicit schema
		result = history.get_structured_output(ExtractedData)

		assert result is not None
		assert isinstance(result, ExtractedData)
		assert result.title == 'Test Product'
		assert result.price == 29.99
		assert result.in_stock is True

	def test_get_structured_output_returns_none_when_no_final_result(self):
		"""Test that get_structured_output returns None when there's no final result"""
		history = AgentHistoryList(
			history=[
				AgentHistory(
					model_output=None,
					result=[ActionResult(extracted_content=None)],
					state=BrowserStateHistory(url='https://example.com', title='Test', tabs=[], interacted_element=[]),
				)
			]
		)

		result = history.get_structured_output(ExtractedData)
		assert result is None

	def test_get_structured_output_with_nested_model(self):
		"""Test get_structured_output works with nested Pydantic models"""
		json_result = """
		{
			"items": [
				{"title": "Item 1", "price": 10.0, "in_stock": true},
				{"title": "Item 2", "price": 20.0, "in_stock": false}
			],
			"total_count": 2
		}
		"""

		history = AgentHistoryList(
			history=[
				AgentHistory(
					model_output=None,
					result=[ActionResult(extracted_content=json_result, is_done=True)],
					state=BrowserStateHistory(url='https://example.com', title='Test', tabs=[], interacted_element=[]),
				)
			]
		)

		result = history.get_structured_output(NestedModel)

		assert result is not None
		assert len(result.items) == 2
		assert result.items[0].title == 'Item 1'
		assert result.total_count == 2


class TestSandboxStructuredOutputParsing:
	"""Tests for _parse_with_type_annotation handling of AgentHistoryList[T]"""

	def test_parse_agent_history_list_without_generic(self):
		"""Test parsing AgentHistoryList without generic parameter"""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': '{"title": "Test", "price": 9.99, "in_stock": true}', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Test', 'tabs': []},
				}
			]
		}

		result = _parse_with_type_annotation(data, AgentHistoryList)

		assert isinstance(result, AgentHistoryList)
		assert len(result.history) == 1
		# Without generic, _output_model_schema should be None
		assert result._output_model_schema is None

	def test_parse_agent_history_list_with_generic_parameter(self):
		"""Test parsing AgentHistoryList[ExtractedData] preserves output model schema"""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': '{"title": "Test", "price": 9.99, "in_stock": true}', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Test', 'tabs': []},
				}
			]
		}

		# Parse with generic type annotation
		result = _parse_with_type_annotation(data, AgentHistoryList[ExtractedData])

		assert isinstance(result, AgentHistoryList)
		assert len(result.history) == 1
		# With generic, _output_model_schema should be set
		assert result._output_model_schema is ExtractedData

		# Now structured_output property should work
		structured = result.structured_output
		assert structured is not None
		assert isinstance(structured, ExtractedData)
		assert structured.title == 'Test'
		assert structured.price == 9.99
		assert structured.in_stock is True

	def test_parse_agent_history_list_structured_output_after_sandbox(self):
		"""Simulate full sandbox round-trip with AgentHistoryList[T]"""
		# This simulates what happens when sandbox returns data
		json_content = '{"title": "Product", "price": 49.99, "in_stock": false}'

		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': json_content, 'is_done': True}],
					'state': {'url': 'https://shop.com', 'title': 'Shop', 'tabs': []},
				}
			]
		}

		# Sandbox parses with return type annotation AgentHistoryList[ExtractedData]
		result = _parse_with_type_annotation(data, AgentHistoryList[ExtractedData])

		# User accesses structured_output property
		output = result.structured_output

		assert output is not None
		assert output.title == 'Product'
		assert output.price == 49.99
		assert output.in_stock is False


class TestStructuredOutputPropertyFallback:
	"""Tests for structured_output property behavior with and without _output_model_schema"""

	def test_structured_output_property_works_when_schema_set(self):
		"""Test structured_output property works when _output_model_schema is set"""
		json_result = '{"title": "Test", "price": 5.0, "in_stock": true}'

		history = AgentHistoryList(
			history=[
				AgentHistory(
					model_output=None,
					result=[ActionResult(extracted_content=json_result, is_done=True)],
					state=BrowserStateHistory(url='https://example.com', title='Test', tabs=[], interacted_element=[]),
				)
			]
		)
		# Manually set the schema (as Agent.run() does)
		history._output_model_schema = ExtractedData

		result = history.structured_output

		assert result is not None
		assert isinstance(result, ExtractedData)
		assert result.title == 'Test'

	def test_structured_output_property_returns_none_without_schema(self):
		"""Test structured_output property returns None when _output_model_schema is not set"""
		json_result = '{"title": "Test", "price": 5.0, "in_stock": true}'

		history = AgentHistoryList(
			history=[
				AgentHistory(
					model_output=None,
					result=[ActionResult(extracted_content=json_result, is_done=True)],
					state=BrowserStateHistory(url='https://example.com', title='Test', tabs=[], interacted_element=[]),
				)
			]
		)
		# Don't set _output_model_schema

		result = history.structured_output

		# Property returns None because schema is not set
		assert result is None

		# But get_structured_output with explicit schema works
		explicit_result = history.get_structured_output(ExtractedData)
		assert explicit_result is not None
		assert explicit_result.title == 'Test'
