from pydantic import BaseModel, Field

from browser_use.llm.mistral.schema import MistralSchemaOptimizer


class NestedExample(BaseModel):
	code: str = Field(..., min_length=2, max_length=4, pattern='[A-Z]+')
	description: str


class RootExample(BaseModel):
	item: NestedExample
	email: str = Field(..., json_schema_extra={'format': 'email'})


def test_mistral_schema_strips_unsupported_keywords():
	schema = MistralSchemaOptimizer.create_mistral_compatible_schema(RootExample)

	def _assert_no_banned_keys(obj):
		if isinstance(obj, dict):
			for key, value in obj.items():
				assert key not in {'minLength', 'maxLength', 'pattern', 'format'}
				_assert_no_banned_keys(value)
		elif isinstance(obj, list):
			for item in obj:
				_assert_no_banned_keys(item)

	_assert_no_banned_keys(schema)
