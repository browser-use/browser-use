"""Schema optimizer for Mistral-compatible JSON schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from browser_use.llm.schema import SchemaOptimizer


class MistralSchemaOptimizer:
	"""Create JSON schemas that avoid Mistral's unsupported keywords."""

	UNSUPPORTED_KEYWORDS = {'minLength', 'maxLength', 'pattern', 'format'}

	@classmethod
	def create_mistral_compatible_schema(cls, model: type[BaseModel]) -> dict[str, Any]:
		"""
		Build a Mistral-safe schema by starting with the standard optimized schema and
		then stripping unsupported validation keywords recursively.
		"""
		base_schema = SchemaOptimizer.create_optimized_json_schema(model)
		return cls._strip_unsupported_keywords(base_schema)

	@classmethod
	def _strip_unsupported_keywords(cls, obj: Any) -> Any:
		if isinstance(obj, dict):
			return {
				key: cls._strip_unsupported_keywords(value) for key, value in obj.items() if key not in cls.UNSUPPORTED_KEYWORDS
			}
		if isinstance(obj, list):
			return [cls._strip_unsupported_keywords(item) for item in obj]
		return obj
