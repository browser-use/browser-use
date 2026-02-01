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

	raw_required = schema.get('required', [])
	required_fields = {r for r in raw_required if isinstance(r, str)} if isinstance(raw_required, list) else set()
	field_definitions: dict[str, Any] = {}

	for field_name, field_schema in properties.items():
		if not isinstance(field_name, str):
			logger.warning(f'Skipping non-string property key: {field_name!r}')
			continue
		if not isinstance(field_schema, dict):
			logger.warning(f'Skipping non-dict field schema for {field_name!r}: {type(field_schema).__name__}')
			continue
		python_type = _resolve_type(field_schema, parent_name=model_name, field_name=field_name)
		is_required = field_name in required_fields
		description = field_schema.get('description', '')
		raw_default = field_schema.get('default', None)
		# Mutable defaults (list, dict) must use default_factory in Pydantic
		if is_required:
			default = ...
		elif isinstance(raw_default, (list, dict)):
			default = None
		else:
			default = raw_default

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
) -> Any:
	"""Resolve a JSON Schema field definition to a Python type.

	Handles primitives, nested objects, and arrays.
	"""
	schema_type = field_schema.get('type')

	if schema_type is None:
		# No type specified — fall back to Any via str
		logger.warning(f"No 'type' in schema for {parent_name}.{field_name}, defaulting to str")
		return str

	# JSON Schema union types: "type": ["string", "null"]
	# Extract the non-null type and resolve it; include None if "null" is present
	if isinstance(schema_type, list):
		has_null = 'null' in schema_type
		non_null_types = [t for t in schema_type if t != 'null']
		if len(non_null_types) == 1:
			# Common case: ["string", "null"] → str | None
			field_schema_copy = {**field_schema, 'type': non_null_types[0]}
			resolved = _resolve_type(field_schema_copy, parent_name, field_name)
			return resolved | None if has_null else resolved
		elif len(non_null_types) == 0:
			return str | None if has_null else str
		else:
			logger.warning(f'Multi-type union {schema_type} for {parent_name}.{field_name}, defaulting to str')
			return str | None if has_null else str

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
