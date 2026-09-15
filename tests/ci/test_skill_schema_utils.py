import pytest
from pydantic import ValidationError

from browser_use.skills.utils import convert_json_schema_to_pydantic


def test_convert_json_schema_preserves_string_enum_constraint() -> None:
	model = convert_json_schema_to_pydantic(
		{
			'type': 'object',
			'properties': {'status': {'type': 'string', 'enum': ['ok', 'error']}},
			'required': ['status'],
		}
	)

	assert model(status='ok').model_dump() == {'status': 'ok'}
	with pytest.raises(ValidationError):
		model(status='typo')


def test_convert_json_schema_preserves_optional_integer_enum_constraint() -> None:
	model = convert_json_schema_to_pydantic({'type': 'object', 'properties': {'priority': {'type': 'integer', 'enum': [1, 2]}}})

	assert model().model_dump() == {'priority': None}
	assert model(priority=2).model_dump() == {'priority': 2}
	with pytest.raises(ValidationError):
		model(priority=3)


def test_convert_json_schema_preserves_array_item_enum_constraint() -> None:
	model = convert_json_schema_to_pydantic(
		{
			'type': 'object',
			'properties': {'statuses': {'type': 'array', 'items': {'type': 'string', 'enum': ['ok', 'error']}}},
			'required': ['statuses'],
		}
	)

	assert model(statuses=['ok', 'error']).model_dump() == {'statuses': ['ok', 'error']}
	with pytest.raises(ValidationError):
		model(statuses=['ok', 'typo'])
