"""Converts a JSON Schema dict to a runtime Pydantic model for structured extraction."""

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

logger = logging.getLogger(__name__)

# Keywords that indicate composition/reference patterns we don't support
_UNSUPPORTED_KEYWORDS = frozenset(
	{
		'$ref',
		'allOf',
		'anyOf',
		'oneOf',
		'not',
		'$defs',
		'definitions',
		'if',
		'then',
		'else',
		'dependentSchemas',
		'dependentRequired',
	}
)

# Primitive JSON Schema type → Python type
_PRIMITIVE_MAP: dict[str, type] = {
	'string': str,
	'number': float,
	'integer': int,
	'boolean': bool,
	'null': type(None),
}


class _StrictBase(BaseModel):
	model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True)


def _check_unsupported(schema: dict) -> None:
	"""Raise ValueError if the schema uses unsupported composition keywords."""
	for kw in _UNSUPPORTED_KEYWORDS:
		if kw in schema:
			raise ValueError(f'Unsupported JSON Schema keyword: {kw}')


def _resolve_type(schema: dict, name: str) -> Any:
	"""Recursively resolve a JSON Schema node to a Python type.

	Returns a Python type suitable for use as a field type in pydantic.create_model.
	"""
	_check_unsupported(schema)

	json_type = schema.get('type', 'string')

	# Enums — constrain to str (Literal would be stricter but LLMs are flaky)
	if 'enum' in schema:
		return str

	# JSON Schema type arrays (e.g. ["string", "null"]) — standard nullable-union form.
	# Resolve each member type, then join them into a union ("null" contributes NoneType).
	if isinstance(json_type, list):
		non_null = [t for t in json_type if t != 'null']
		nullable = 'null' in json_type or bool(schema.get('nullable', False))
		if not non_null:
			return type(None)
		members = [_resolve_type({**schema, 'type': t, 'nullable': False}, name) for t in non_null]
		if nullable:
			members.append(type(None))
		resolved = members[0]
		for member in members[1:]:
			resolved = resolved | member
		return resolved

	# Object with properties → nested pydantic model
	if json_type == 'object':
		properties = schema.get('properties', {})
		if properties:
			return _build_model(schema, name)
		return dict

	# Array
	if json_type == 'array':
		items_schema = schema.get('items')
		if items_schema:
			item_type = _resolve_type(items_schema, f'{name}_item')
			return list[item_type]
		return list

	# Primitive
	base = _PRIMITIVE_MAP.get(json_type, str)

	# Nullable
	if schema.get('nullable', False):
		return base | None

	return base


_PRIMITIVE_DEFAULTS: dict[str, Any] = {
	'string': '',
	'number': 0.0,
	'integer': 0,
	'boolean': False,
}


def _build_model(schema: dict, name: str) -> type[BaseModel]:
	"""Build a pydantic model from an object-type JSON Schema node."""
	_check_unsupported(schema)

	properties = schema.get('properties', {})
	required_fields = set(schema.get('required', []))
	fields: dict[str, Any] = {}

	for prop_name, prop_schema in properties.items():
		prop_type = _resolve_type(prop_schema, f'{name}_{prop_name}')

		# Normalize JSON Schema type arrays (e.g. ["string", "null"]) so the
		# default-selection logic below can treat them like the proprietary
		# nullable flag instead of choking on the list.
		raw_type = prop_schema.get('type', 'string')
		nullable = bool(prop_schema.get('nullable', False)) or (isinstance(raw_type, list) and 'null' in raw_type)
		json_type = next((t for t in raw_type if t != 'null'), 'string') if isinstance(raw_type, list) else raw_type

		if prop_name in required_fields:
			default = ...
		elif 'default' in prop_schema:
			default = prop_schema['default']
		elif nullable:
			# _resolve_type already made the type include None
			default = None
		else:
			# Non-required, non-nullable, no explicit default.
			# Use a type-appropriate zero value for primitives/arrays;
			# fall back to None (with | None) for enums and nested objects
			# where no in-set or constructible default exists.
			if 'enum' in prop_schema:
				# Can't pick an arbitrary enum member as default — use None
				# so absent fields serialize as null, not an out-of-set value.
				prop_type = prop_type | None
				default = None
			elif json_type in _PRIMITIVE_DEFAULTS:
				default = _PRIMITIVE_DEFAULTS[json_type]
			elif json_type == 'array':
				default = []
			else:
				# Nested object or unknown — must allow None as sentinel
				prop_type = prop_type | None
				default = None

		field_kwargs: dict[str, Any] = {}
		if 'description' in prop_schema:
			field_kwargs['description'] = prop_schema['description']

		if isinstance(default, list) and not default:
			fields[prop_name] = (prop_type, Field(default_factory=list, **field_kwargs))
		else:
			fields[prop_name] = (prop_type, Field(default, **field_kwargs))

	return create_model(name, __base__=_StrictBase, **fields)


def schema_dict_to_pydantic_model(schema: dict) -> type[BaseModel]:
	"""Convert a JSON Schema dict to a runtime Pydantic model.

	The schema must be ``{"type": "object", "properties": {...}, ...}``.
	Unsupported keywords ($ref, allOf, anyOf, oneOf, etc.) raise ValueError.

	Returns:
		A dynamically-created Pydantic BaseModel subclass.

	Raises:
		ValueError: If the schema is invalid or uses unsupported features.
	"""
	_check_unsupported(schema)

	top_type = schema.get('type')
	if top_type != 'object':
		raise ValueError(f'Top-level schema must have type "object", got {top_type!r}')

	properties = schema.get('properties')
	if not properties:
		raise ValueError('Top-level schema must have at least one property')

	model_name = schema.get('title', 'DynamicExtractionModel')
	return _build_model(schema, model_name)
