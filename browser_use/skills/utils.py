"""Utilities for skill schema conversion"""

from typing import Any

from pydantic import BaseModel, Field, create_model

from browser_use.skills.views import ParameterSchema


def convert_parameters_to_pydantic(parameters: list[ParameterSchema], model_name: str = 'SkillParameters') -> type[BaseModel]:
	"""Convert a list of ParameterSchema to a pydantic model for structured output

	Args:
		parameters: List of parameter schemas from the skill API
		model_name: Name for the generated pydantic model

	Returns:
		A pydantic BaseModel class with fields matching the parameter schemas
	"""
	if not parameters:
		# Return empty model if no parameters
		return create_model(model_name, __base__=BaseModel)

	fields: dict[str, Any] = {}

	for param in parameters:
		# Map parameter type string to Python types
		python_type: Any = str  # default

		param_type = param.type

		if param_type == 'string':
			python_type = str
		elif param_type == 'number':
			python_type = float
		elif param_type == 'boolean':
			python_type = bool
		elif param_type == 'object':
			python_type = dict[str, Any]
		elif param_type == 'array':
			python_type = list[Any]
		elif param_type == 'cookie':
			python_type = str  # Treat cookies as strings

		# Check if parameter is required (defaults to True if not specified)
		is_required = param.required if param.required is not None else True

		# Make optional if not required
		if not is_required:
			python_type = python_type | None  # type: ignore

		# Create field with description
		field_kwargs = {}
		if param.description:
			field_kwargs['description'] = param.description

		if is_required:
			fields[param.name] = (python_type, Field(**field_kwargs))
		else:
			fields[param.name] = (python_type, Field(default=None, **field_kwargs))

	# Create and return the model
	return create_model(model_name, __base__=BaseModel, **fields)


def convert_json_schema_to_pydantic(schema: dict[str, Any], model_name: str = 'SkillOutput') -> type[BaseModel]:
	"""Convert a JSON schema to a pydantic model

	Args:
		schema: JSON schema dictionary (OpenAPI/JSON Schema format)
		model_name: Name for the generated pydantic model

	Returns:
		A pydantic BaseModel class matching the schema

	Note:
		This is a simplified converter that handles basic types.
		For complex nested schemas, consider using datamodel-code-generator.
	"""
	if not schema or 'properties' not in schema:
		# Return empty model if no schema
		return create_model(model_name, __base__=BaseModel)

	fields: dict[str, Any] = {}
	properties = schema.get('properties', {})
	required_fields = set(schema.get('required', []))

	for field_name, field_schema in properties.items():
		# Get the field type
		field_type_str = field_schema.get('type', 'string')
		field_description = field_schema.get('description')

		# Map JSON schema types to Python types
		python_type: Any = str  # default

		if field_type_str == 'string':
			python_type = str
		elif field_type_str == 'number':
			python_type = float
		elif field_type_str == 'integer':
			python_type = int
		elif field_type_str == 'boolean':
			python_type = bool
		elif field_type_str == 'object':
			python_type = dict[str, Any]
		elif field_type_str == 'array':
			# Check if items type is specified
			items_schema = field_schema.get('items', {})
			items_type = items_schema.get('type', 'string')

			if items_type == 'string':
				python_type = list[str]
			elif items_type == 'number':
				python_type = list[float]
			elif items_type == 'integer':
				python_type = list[int]
			elif items_type == 'boolean':
				python_type = list[bool]
			elif items_type == 'object':
				python_type = list[dict[str, Any]]
			else:
				python_type = list[Any]

		# Make optional if not required
		is_required = field_name in required_fields
		if not is_required:
			python_type = python_type | None  # type: ignore

		# Create field with description
		field_kwargs = {}
		if field_description:
			field_kwargs['description'] = field_description

		if is_required:
			fields[field_name] = (python_type, Field(**field_kwargs))
		else:
			fields[field_name] = (python_type, Field(default=None, **field_kwargs))

	# Create and return the model
	return create_model(model_name, __base__=BaseModel, **fields)
