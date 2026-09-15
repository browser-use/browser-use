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
