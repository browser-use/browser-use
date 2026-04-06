"""Tests for schema-enforced structured extraction."""

import asyncio
import json
import tempfile
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.tools.extraction.schema_utils import schema_dict_to_pydantic_model
from browser_use.tools.extraction.views import ExtractionResult
from browser_use.tools.service import Tools

# ---------------------------------------------------------------------------
# Unit tests: schema_dict_to_pydantic_model
# ---------------------------------------------------------------------------


class TestSchemaDictToPydanticModel:
	"""Unit tests for the JSON-Schema → Pydantic model converter."""

	def test_flat_object(self):
		schema = {
			'type': 'object',
			'properties': {
				'name': {'type': 'string'},
				'age': {'type': 'integer'},
			},
			'required': ['name', 'age'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(name='Alice', age=30)
		assert instance.name == 'Alice'  # type: ignore[attr-defined]
		assert instance.age == 30  # type: ignore[attr-defined]

	def test_nested_object(self):
		schema = {
			'type': 'object',
			'properties': {
				'person': {
					'type': 'object',
					'properties': {
						'first': {'type': 'string'},
						'last': {'type': 'string'},
					},
					'required': ['first'],
				},
			},
			'required': ['person'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(person={'first': 'Bob', 'last': 'Smith'})
		assert instance.person.first == 'Bob'  # type: ignore[attr-defined]

	def test_array_of_objects(self):
		schema = {
			'type': 'object',
			'properties': {
				'items': {
					'type': 'array',
					'items': {
						'type': 'object',
						'properties': {
							'id': {'type': 'integer'},
							'label': {'type': 'string'},
						},
						'required': ['id', 'label'],
					},
				},
			},
			'required': ['items'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(items=[{'id': 1, 'label': 'a'}, {'id': 2, 'label': 'b'}])
		assert len(instance.items) == 2  # type: ignore[attr-defined]
		assert instance.items[0].id == 1  # type: ignore[attr-defined]

	def test_array_of_primitives(self):
		schema = {
			'type': 'object',
			'properties': {
				'tags': {'type': 'array', 'items': {'type': 'string'}},
			},
			'required': ['tags'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(tags=['a', 'b', 'c'])
		assert instance.tags == ['a', 'b', 'c']  # type: ignore[attr-defined]

	def test_enum_field(self):
		schema = {
			'type': 'object',
			'properties': {
				'status': {'type': 'string', 'enum': ['active', 'inactive']},
			},
			'required': ['status'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(status='active')
		assert instance.status == 'active'  # type: ignore[attr-defined]

	def test_optional_enum_defaults_to_none(self):
		"""Non-required enum fields default to None, not an out-of-set empty string."""
		schema = {
			'type': 'object',
			'properties': {
				'name': {'type': 'string'},
				'priority': {'type': 'string', 'enum': ['low', 'medium', 'high']},
			},
			'required': ['name'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(name='task1')
		assert instance.priority is None  # type: ignore[attr-defined]
		# Serialized output must not contain an out-of-set value
		dumped = instance.model_dump(mode='json')
		assert dumped['priority'] is None

		# When provided, value still works
		instance2 = Model(name='task2', priority='high')
		assert instance2.priority == 'high'  # type: ignore[attr-defined]

	def test_optional_fields_get_type_appropriate_defaults(self):
		schema = {
			'type': 'object',
			'properties': {
				'name': {'type': 'string'},
				'nickname': {'type': 'string'},
				'score': {'type': 'number'},
				'rank': {'type': 'integer'},
				'active': {'type': 'boolean'},
				'tags': {'type': 'array', 'items': {'type': 'string'}},
			},
			'required': ['name'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(name='Alice')
		assert instance.name == 'Alice'  # type: ignore[attr-defined]
		assert instance.nickname == ''  # type: ignore[attr-defined]
		assert instance.score == 0.0  # type: ignore[attr-defined]
		assert instance.rank == 0  # type: ignore[attr-defined]
		assert instance.active is False  # type: ignore[attr-defined]
		assert instance.tags == []  # type: ignore[attr-defined]

	def test_optional_non_nullable_rejects_null(self):
		"""Non-required fields that aren't nullable must reject explicit null."""
		schema = {
			'type': 'object',
			'properties': {
				'name': {'type': 'string'},
				'nickname': {'type': 'string'},
			},
			'required': ['name'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		with pytest.raises(ValidationError):
			Model(name='Alice', nickname=None)

	def test_optional_with_explicit_default(self):
		schema = {
			'type': 'object',
			'properties': {
				'name': {'type': 'string'},
				'color': {'type': 'string', 'default': 'blue'},
			},
			'required': ['name'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(name='Alice')
		assert instance.color == 'blue'  # type: ignore[attr-defined]

	def test_optional_nested_object_defaults_to_none(self):
		"""Non-required nested objects fall back to None since constructing a default is not feasible."""
		schema = {
			'type': 'object',
			'properties': {
				'name': {'type': 'string'},
				'address': {
					'type': 'object',
					'properties': {'city': {'type': 'string'}},
					'required': ['city'],
				},
			},
			'required': ['name'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(name='Alice')
		assert instance.address is None  # type: ignore[attr-defined]

	def test_model_name_from_title(self):
		schema = {
			'title': 'ProductInfo',
			'type': 'object',
			'properties': {'sku': {'type': 'string'}},
			'required': ['sku'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		assert Model.__name__ == 'ProductInfo'

	def test_model_validate_json_roundtrip(self):
		schema = {
			'type': 'object',
			'properties': {
				'x': {'type': 'number'},
				'y': {'type': 'boolean'},
			},
			'required': ['x', 'y'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(x=3.14, y=True)
		raw = instance.model_dump_json()
		restored = Model.model_validate_json(raw)
		assert restored.x == instance.x  # type: ignore[attr-defined]
		assert restored.y == instance.y  # type: ignore[attr-defined]

	def test_rejects_ref(self):
		schema = {
			'type': 'object',
			'properties': {'item': {'$ref': '#/$defs/Item'}},
			'$defs': {'Item': {'type': 'object', 'properties': {'name': {'type': 'string'}}}},
		}
		with pytest.raises(ValueError, match='Unsupported JSON Schema keyword'):
			schema_dict_to_pydantic_model(schema)

	def test_rejects_allOf(self):
		schema = {
			'type': 'object',
			'properties': {'x': {'allOf': [{'type': 'string'}]}},
		}
		with pytest.raises(ValueError, match='Unsupported JSON Schema keyword'):
			schema_dict_to_pydantic_model(schema)

	def test_rejects_non_object_toplevel(self):
		with pytest.raises(ValueError, match='type "object"'):
			schema_dict_to_pydantic_model({'type': 'array', 'items': {'type': 'string'}})

	def test_rejects_empty_properties(self):
		with pytest.raises(ValueError, match='at least one property'):
			schema_dict_to_pydantic_model({'type': 'object', 'properties': {}})

	def test_extra_fields_forbidden(self):
		schema = {
			'type': 'object',
			'properties': {'name': {'type': 'string'}},
			'required': ['name'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		with pytest.raises(ValidationError):
			Model(name='ok', bogus='nope')

	def test_nullable_field(self):
		schema = {
			'type': 'object',
			'properties': {
				'value': {'type': 'string', 'nullable': True},
			},
			'required': ['value'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		instance = Model(value=None)
		assert instance.value is None  # type: ignore[attr-defined]

	def test_field_descriptions_preserved(self):
		schema = {
			'type': 'object',
			'properties': {
				'price': {'type': 'number', 'description': 'The price in USD'},
			},
			'required': ['price'],
		}
		Model = schema_dict_to_pydantic_model(schema)
		field_info = Model.model_fields['price']
		assert field_info.description == 'The price in USD'


# ---------------------------------------------------------------------------
# Unit tests: ExtractionResult
# ---------------------------------------------------------------------------


class TestExtractionResult:
	def test_construction(self):
		er = ExtractionResult(
			data={'name': 'Alice'},
			schema_used={'type': 'object', 'properties': {'name': {'type': 'string'}}},
		)
		assert er.data == {'name': 'Alice'}
		assert er.is_partial is False
		assert er.source_url is None

	def test_serialization_roundtrip(self):
		er = ExtractionResult(
			data={'items': [1, 2]},
			schema_used={'type': 'object', 'properties': {'items': {'type': 'array'}}},
			is_partial=True,
			source_url='http://example.com',
			content_stats={'original_html_chars': 5000},
		)
		raw = er.model_dump_json()
		restored = ExtractionResult.model_validate_json(raw)
		assert restored == er


# ---------------------------------------------------------------------------
# Integration tests: extract action via Tools
# ---------------------------------------------------------------------------


def _make_extraction_llm(structured_response: dict | None = None, freetext_response: str = 'free text result') -> BaseChatModel:
	"""Create a mock LLM that handles both structured and freetext extraction calls."""
	llm = AsyncMock(spec=BaseChatModel)
	llm.model = 'mock-extraction-llm'
	llm._verified_api_keys = True
	llm.provider = 'mock'
	llm.name = 'mock-extraction-llm'
	llm.model_name = 'mock-extraction-llm'

	async def mock_ainvoke(messages, output_format=None, **kwargs):
		if output_format is not None and structured_response is not None:
			# Structured path: parse the dict through the model
			instance = output_format.model_validate(structured_response)
			return ChatInvokeCompletion(completion=instance, usage=None)
		# Freetext path
		return ChatInvokeCompletion(completion=freetext_response, usage=None)

	llm.ainvoke.side_effect = mock_ainvoke
	return llm


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	yield session
	await session.kill()
	await session.event_bus.stop(clear=True, timeout=5)


@pytest.fixture(scope='session')
def http_server():
	server = HTTPServer()
	server.start()
	server.expect_request('/products').respond_with_data(
		"""<html><body>
		<h1>Products</h1>
		<ul>
			<li>Widget A - $9.99</li>
			<li>Widget B - $19.99</li>
		</ul>
		</body></html>""",
		content_type='text/html',
	)
	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


class TestExtractStructured:
	"""Integration tests for the extract action's structured extraction path."""

	async def test_structured_extraction_returns_json(self, browser_session, base_url):
		"""When output_schema is provided, extract returns structured JSON in <structured_result> tags."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		output_schema = {
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

		mock_data = {'products': [{'name': 'Widget A', 'price': 9.99}, {'name': 'Widget B', 'price': 19.99}]}
		extraction_llm = _make_extraction_llm(structured_response=mock_data)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract(
				query='List all products with prices',
				output_schema=output_schema,
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<structured_result>' in result.extracted_content
		assert '</structured_result>' in result.extracted_content

		# Parse the JSON out of the tags
		start = result.extracted_content.index('<structured_result>') + len('<structured_result>')
		end = result.extracted_content.index('</structured_result>')
		parsed = json.loads(result.extracted_content[start:end].strip())
		assert parsed == mock_data

		# Metadata
		assert result.metadata is not None
		assert result.metadata['structured_extraction'] is True
		meta = result.metadata['extraction_result']
		assert meta['data'] == mock_data
		assert meta['schema_used'] == output_schema

	async def test_freetext_extraction_unchanged(self, browser_session, base_url):
		"""When output_schema is None, extract returns free-text in <result> tags (backward compat)."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_extraction_llm(freetext_response='Widget A costs $9.99, Widget B costs $19.99')

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract(
				query='What products are listed?',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<result>' in result.extracted_content
		assert '</result>' in result.extracted_content
		assert '<structured_result>' not in result.extracted_content
		assert result.metadata is None

	async def test_invalid_schema_falls_back_to_freetext(self, browser_session, base_url):
		"""When output_schema contains unsupported keywords, fall back to free-text gracefully."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		bad_schema = {
			'type': 'object',
			'properties': {'item': {'$ref': '#/$defs/Item'}},
			'$defs': {'Item': {'type': 'object', 'properties': {'name': {'type': 'string'}}}},
		}

		extraction_llm = _make_extraction_llm(freetext_response='fallback text')

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract(
				query='Get products',
				output_schema=bad_schema,
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		# Should have used the free-text path
		assert '<result>' in result.extracted_content
		assert '<structured_result>' not in result.extracted_content
		assert result.metadata is None


# ---------------------------------------------------------------------------
# Integration tests: extraction_schema injection via special parameter
# ---------------------------------------------------------------------------

PRODUCT_SCHEMA = {
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

MOCK_PRODUCTS = {'products': [{'name': 'Widget A', 'price': 9.99}, {'name': 'Widget B', 'price': 19.99}]}


class TestExtractionSchemaInjection:
	"""Tests that extraction_schema injected as a special parameter triggers structured extraction."""

	async def test_injected_extraction_schema_triggers_structured_path(self, browser_session, base_url):
		"""extraction_schema passed via act() triggers structured extraction even without output_schema in params."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_extraction_llm(structured_response=MOCK_PRODUCTS)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract(
				query='List all products with prices',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
				extraction_schema=PRODUCT_SCHEMA,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<structured_result>' in result.extracted_content

		# Parse and verify JSON
		start = result.extracted_content.index('<structured_result>') + len('<structured_result>')
		end = result.extracted_content.index('</structured_result>')
		parsed = json.loads(result.extracted_content[start:end].strip())
		assert parsed == MOCK_PRODUCTS

		assert result.metadata is not None
		assert result.metadata['structured_extraction'] is True

	async def test_output_schema_takes_precedence_over_extraction_schema(self, browser_session, base_url):
		"""When the LLM provides output_schema in params, it should take precedence over injected extraction_schema."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		# Different schema than the injected one — just a name list
		param_schema = {
			'type': 'object',
			'properties': {
				'names': {'type': 'array', 'items': {'type': 'string'}},
			},
			'required': ['names'],
		}
		param_response = {'names': ['Widget A', 'Widget B']}
		extraction_llm = _make_extraction_llm(structured_response=param_response)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract(
				query='List product names',
				output_schema=param_schema,
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
				extraction_schema=PRODUCT_SCHEMA,  # should be ignored
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<structured_result>' in result.extracted_content

		start = result.extracted_content.index('<structured_result>') + len('<structured_result>')
		end = result.extracted_content.index('</structured_result>')
		parsed = json.loads(result.extracted_content[start:end].strip())
		# Should match param_schema response, NOT PRODUCT_SCHEMA
		assert parsed == param_response
		assert result.metadata is not None
		assert result.metadata['extraction_result']['schema_used'] == param_schema

	async def test_no_schema_uses_freetext_path(self, browser_session, base_url):
		"""When neither output_schema nor extraction_schema is provided, free-text path is used (backward compat)."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_extraction_llm(freetext_response='Widget A costs $9.99')

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract(
				query='What products are listed?',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
				# No extraction_schema, no output_schema
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<result>' in result.extracted_content
		assert '<structured_result>' not in result.extracted_content
		assert result.metadata is None

	async def test_extraction_schema_threads_through_act(self, browser_session, base_url):
		"""extraction_schema passed to act() reaches extract() via the registry's special parameter injection."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_extraction_llm(structured_response=MOCK_PRODUCTS)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)

			# Build an ActionModel for the extract action
			action_model = tools.registry.create_action_model()
			action = action_model.model_validate({'extract': {'query': 'List products'}})

			result = await tools.act(
				action=action,
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
				extraction_schema=PRODUCT_SCHEMA,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<structured_result>' in result.extracted_content
