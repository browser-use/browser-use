import json
import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def create_pydantic_model_from_schema(original_schema: dict | str, model_name: str = 'DynamicModel') -> type[BaseModel]:
	"""
	Convert JSON schema to Pydantic model class using datamodel-code-generator.

	Args:
		schema: JSON schema dictionary
		model_name: Name for the generated model class

	Returns:
		Pydantic model class that can be used with Controller(output_model=...)

	Example:
		schema = {
			"type": "object",
			"properties": {
				"name": {"type": "string"},
				"age": {"type": "integer"},
				"email": {"type": "string"}
			},
			"required": ["name", "age"]
		}
		PersonModel = create_pydantic_model_from_schema(schema, "Person")
		controller = Controller(output_model=PersonModel)
	"""
	try:
		import importlib.util
		import tempfile
		from pathlib import Path

		from datamodel_code_generator import DataModelType, generate  # type: ignore[import-untyped]

		# Handle case where schema might be a string (JSON)
		if isinstance(original_schema, str):
			schema: dict = json.loads(original_schema)
		else:
			schema: dict = original_schema

		logger.debug(f'Creating Pydantic model from schema: {schema}')

		# Initialize paths for cleanup
		schema_path = None
		model_path = None

		try:
			# Create temporary files for input schema and output model
			with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as schema_file:
				json.dump(schema, schema_file, indent=2)
				schema_path = Path(schema_file.name)

			with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as model_file:
				model_path = Path(model_file.name)

			# Generate Pydantic model code using datamodel-code-generator
			generate(
				input_=schema_path,
				output=model_path,
				output_model_type=DataModelType.PydanticV2BaseModel,
				class_name=model_name,
			)

			# Read the generated Python code
			generated_code = model_path.read_text()
			logger.debug(f'Generated Pydantic model code:\n{generated_code}')

			# Create a module and execute the generated code
			spec = importlib.util.spec_from_loader(f'dynamic_model_{model_name}', loader=None)
			if spec is None:
				raise ValueError('Failed to create module spec')

			module = importlib.util.module_from_spec(spec)

			# Add necessary imports to the module namespace before executing
			from typing import Any, Optional, Union

			from pydantic import BaseModel, Field

			module.__dict__.update(
				{
					'Optional': Optional,
					'Union': Union,
					'list': list,
					'dict': dict,
					'Any': Any,
					'BaseModel': BaseModel,
					'Field': Field,
					'str': str,
					'int': int,
					'float': float,
					'bool': bool,
				}
			)

			# Execute the generated code in the module's namespace
			exec(generated_code, module.__dict__)

			# Get the generated model class
			if hasattr(module, model_name):
				model_class = getattr(module, model_name)
				# Rebuild the model to resolve forward references and type annotations
				# Pass the module's namespace so it can resolve imports like Optional
				model_class.model_rebuild(_types_namespace=module.__dict__)
				logger.debug(f'Successfully created Pydantic model: {model_class}')
				return model_class
			else:
				# Fallback: look for any BaseModel subclass in the module
				for attr_name in dir(module):
					attr = getattr(module, attr_name)
					if isinstance(attr, type) and issubclass(attr, BaseModel) and attr != BaseModel:
						# Rebuild the model to resolve forward references and type annotations
						# Pass the module's namespace so it can resolve imports like Optional
						attr.model_rebuild(_types_namespace=module.__dict__)
						logger.debug(f'Using fallback model class: {attr}')
						return attr

				raise ValueError('No Pydantic model class found in generated code')

		finally:
			# Clean up temporary files safely
			if schema_path is not None:
				try:
					schema_path.unlink()
				except Exception as cleanup_error:
					logger.warning(f'Failed to cleanup schema file: {cleanup_error}')
			if model_path is not None:
				try:
					model_path.unlink()
				except Exception as cleanup_error:
					logger.warning(f'Failed to cleanup model file: {cleanup_error}')

	except ImportError as e:
		logger.error(f'datamodel-code-generator not available: {e}')
		logger.error('Falling back to basic schema conversion')

		try:
			# Fallback to basic implementation if datamodel-code-generator is not available
			from typing import Any, Optional

			from pydantic import create_model

			def json_type_to_python_type(json_type):
				"""Map JSON schema types to Python types"""
				# Handle union types (arrays of types)
				if isinstance(json_type, list):
					# Handle union types like ["string", "null"]
					types = []
					for t in json_type:
						if t == 'null':
							continue  # We'll handle null separately
						types.append(json_type_to_python_type(t))

					if len(types) == 0:
						return Any
					elif len(types) == 1:
						return types[0]
					else:
						# len(types) >= 2 - create Union dynamically
						from typing import Union

						# For 2 types, use Union[type1, type2]
						if len(types) == 2:
							return Union[types[0], types[1]]
						# For more types, we need to use a different approach
						# Since Union doesn't support unpacking, we'll just use the first type
						# This is a limitation of the fallback implementation
						return types[0]

				# Handle single types
				if json_type == 'string':
					return str
				elif json_type == 'integer':
					return int
				elif json_type == 'number':
					return float
				elif json_type == 'boolean':
					return bool
				elif json_type == 'array':
					return list[Any]
				elif json_type == 'object':
					return dict[str, Any]
				else:
					return Any

			# Handle case where schema might be a string (JSON)
			if isinstance(schema, str):
				schema = json.loads(schema)

			# Extract properties and required fields from schema
			properties = schema.get('properties', {})
			required_fields = schema.get('required', [])

			# Build field definitions for create_model
			field_definitions = {}

			for field_name, field_schema in properties.items():
				json_type = field_schema.get('type')
				field_type = json_type_to_python_type(json_type)

				# Check if the field allows null (either not required or explicitly allows null)
				allows_null = field_name not in required_fields or (isinstance(json_type, list) and 'null' in json_type)

				# Handle required vs optional fields
				if field_name in required_fields and not allows_null:
					field_definitions[field_name] = (field_type, ...)  # Required field
				else:
					optional_type = Optional[field_type]  # Use Optional instead of Union[T, None]
					field_definitions[field_name] = (optional_type, None)  # Optional field with default None

			# Create the dynamic model using create_model
			return create_model(model_name, **field_definitions)

		except Exception as fallback_error:
			logger.error(f'Fallback schema conversion also failed: {fallback_error}')
			raise ValueError(f'Both primary and fallback schema conversion failed: {fallback_error}') from fallback_error

	except Exception as e:
		logger.error(f'Failed to create Pydantic model from schema: {e}')
		logger.error(f'Schema: {schema}')
		raise ValueError(f'Invalid JSON schema: {e}') from e
