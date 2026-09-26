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


def _normalize_type(schema: dict) -> tuple[str, bool]:
	"""Return ``(json_type, nullable)`` for a schema node.

	JSON Schema allows ``"type"`` to be a list such as ``["string", "null"]``. A ``null``
	member means the field is nullable; exactly one concrete type must remain, otherwise
	the union is unsupported. The OpenAPI-style ``nullable: true`` keyword is honored too.
	"""
	json_type = schema.get('type', 'string')
	nullable = bool(schema.get('nullable', False))

	if isinstance(json_type, list):
		concrete = [t for t in json_type if t != 'null']
		if len(concrete) != 1:
			raise ValueError(f'Unsupported JSON Schema type union: {json_type}')
		nullable = nullable or len(concrete) != len(json_type)
		json_type = concrete[0]

	return json_type, nullable


def _resolve_type(schema: dict, name: str) -> Any:
	"""Recursively resolve a JSON Schema node to a Python type.

	Returns a Python type suitable for use as a field type in pydantic.create_model.
	"""
	_check_unsupported(schema)

	json_type, nullable = _normalize_type(schema)

	resolved: Any
	# Enums — constrain to str (Literal would be stricter but LLMs are flaky)
	if 'enum' in schema:
		resolved = str

	# Object with properties → nested pydantic model
	elif json_type == 'object':
		properties = schema.get('properties', {})
		resolved = _build_model(schema, name) if properties else dict

	# Array
	elif json_type == 'array':
		items_schema = schema.get('items')
		if items_schema:
			item_type = _resolve_type(items_schema, f'{name}_item')
			resolved = list[item_type]
		else:
			resolved = list

	# Primitive
	else:
		resolved = _PRIMITIVE_MAP.get(json_type, str)

	# Nullable
	if nullable:
		return resolved | None

	return resolved


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
		json_type, nullable = _normalize_type(prop_schema)

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
