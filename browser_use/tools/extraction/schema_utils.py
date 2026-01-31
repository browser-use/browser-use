"""Utilities for converting JSON Schema dicts to runtime Pydantic models."""

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

logger = logging.getLogger(__name__)

# JSON Schema type → Python type mapping
_JSON_SCHEMA_TYPE_MAP: dict[str, type] = {
	'string': str,
	'integer': int,
	'number': float,
	'boolean': bool,
}


def schema_dict_to_pydantic_model(
	schema: dict[str, Any],
	model_name: str = 'DynamicExtractionModel',
) -> type[BaseModel]:
	"""Convert a JSON Schema dict to a runtime Pydantic model.

	Supports: object, array, string, integer, number, boolean types.
	Handles nested objects and arrays of objects/primitives.

	Args:
		schema: JSON Schema dictionary (must have "type": "object" at root or be treated as object).
		model_name: Name for the generated model class.

	Returns:
		A dynamically created Pydantic model class.

	Raises:
		ValueError: If the schema uses unsupported features or is malformed.
	"""
	assert isinstance(schema, dict), f'schema must be a dict, got {type(schema).__name__}'

	schema_type = schema.get('type', 'object')
	if schema_type != 'object':
		raise ValueError(
			f"Root schema must have type 'object', got '{schema_type}'. Wrap your schema in an object with properties."
		)

	properties = schema.get('properties')
	if not properties:
		raise ValueError("Schema must have 'properties' when type is 'object'.")

	required_fields = set(schema.get('required', []))
	field_definitions: dict[str, Any] = {}

	for field_name, field_schema in properties.items():
		python_type = _resolve_type(field_schema, parent_name=model_name, field_name=field_name)
		is_required = field_name in required_fields
		description = field_schema.get('description', '')
		default = ... if is_required else field_schema.get('default', None)

		if description:
			field_definitions[field_name] = (
				python_type if is_required else python_type | None,
				Field(default=default, description=description),
			)
		else:
			field_definitions[field_name] = (
				python_type if is_required else python_type | None,
				default,
			)

	# Create a base class with the desired config for Pydantic v2
	class _DynamicBase(BaseModel):
		model_config = ConfigDict(extra='forbid')

	model = create_model(
		model_name,
		__base__=_DynamicBase,
		**field_definitions,
	)
	return model


def _resolve_type(
	field_schema: dict[str, Any],
	parent_name: str,
	field_name: str,
) -> type:
	"""Resolve a JSON Schema field definition to a Python type.

	Handles primitives, nested objects, and arrays.
	"""
	schema_type = field_schema.get('type')

	if schema_type is None:
		# No type specified — fall back to Any via str
		logger.warning(f"No 'type' in schema for {parent_name}.{field_name}, defaulting to str")
		return str

	# Primitive types
	if schema_type in _JSON_SCHEMA_TYPE_MAP:
		return _JSON_SCHEMA_TYPE_MAP[schema_type]

	# Nested object
	if schema_type == 'object':
		nested_properties = field_schema.get('properties')
		if not nested_properties:
			# Object without properties — use dict[str, Any]
			return dict[str, Any]

		nested_model_name = f'{parent_name}_{field_name.title().replace("_", "")}'
		return schema_dict_to_pydantic_model(field_schema, model_name=nested_model_name)

	# Array
	if schema_type == 'array':
		items_schema = field_schema.get('items')
		if not items_schema:
			# Array without items schema — use list[Any]
			return list[Any]

		item_type = _resolve_type(
			items_schema,
			parent_name=parent_name,
			field_name=f'{field_name}_item',
		)
		return list[item_type]

	raise ValueError(
		f"Unsupported JSON Schema type '{schema_type}' for {parent_name}.{field_name}. "
		f'Supported types: {", ".join(list(_JSON_SCHEMA_TYPE_MAP.keys()) + ["object", "array"])}'
	)
