"""Parser for unstructured plain text output from Gemini models.

This parser converts the plain text format:
<memory>
free form text
</memory>
<action>
navigate(url_value)
click(1)
</action>

Into structured AgentOutput format.
"""

import re
from typing import Any

from pydantic import BaseModel, ValidationError


class UnstructuredOutputParser:
	"""Parser for unstructured plain text output format"""

	@staticmethod
	def parse(text: str, output_format: type[BaseModel]) -> dict[str, Any]:
		"""
		Parse plain text output into structured format.

		Args:
			text: The plain text output from the model
			output_format: The AgentOutput class (not ActionModel)

		Returns:
			Dictionary with 'memory' and 'action' keys

		Raises:
			ValueError: If parsing fails
		"""
		# Extract memory section
		memory_match = re.search(r'<memory>(.*?)</memory>', text, re.DOTALL | re.IGNORECASE)
		if not memory_match:
			raise ValueError('No <memory> section found in output')

		memory = memory_match.group(1).strip()

		# Extract action section
		action_match = re.search(r'<action>(.*?)</action>', text, re.DOTALL | re.IGNORECASE)
		if not action_match:
			raise ValueError('No <action> section found in output')

		action_text = action_match.group(1).strip()

		# Parse actions
		actions = UnstructuredOutputParser._parse_actions(action_text, output_format)

		if not actions:
			raise ValueError('No valid actions parsed from action section')

		return {'memory': memory, 'action': actions}

	@staticmethod
	def _parse_actions(action_text: str, output_format: type[BaseModel]) -> list[BaseModel]:
		"""
		Parse action function calls from text.

		Expects format like:
		navigate("https://example.com")
		click(1)
		input(5, "hello", true)

		Args:
			action_text: Text containing action calls
			output_format: The AgentOutput class (not ActionModel)

		Returns:
			List of action model instances
		"""
		actions = []

		# Get the action field from AgentOutput to find the ActionModel type
		output_fields = output_format.model_fields
		if 'action' not in output_fields:
			raise ValueError('output_format must have an "action" field')

		action_field = output_fields['action']
		# Extract the item type from list[ActionModel]
		import typing
		if hasattr(typing, 'get_args'):
			action_types = typing.get_args(action_field.annotation)
			if action_types and len(action_types) > 0:
				action_model = action_types[0]
			else:
				raise ValueError('Could not determine ActionModel type from output_format')
		else:
			raise ValueError('Python version does not support typing.get_args')

		# Get all available action fields from the ActionModel
		# The ActionModel uses a discriminated union with anyOf structure
		# Each action is defined in $defs and referenced via anyOf
		# We need to extract action names from the $defs
		schema = action_model.model_json_schema()
		action_schemas = {}

		if '$defs' in schema:
			# Extract action names and their schemas from $defs
			for def_name, def_schema in schema['$defs'].items():
				# Each def like 'DoneActionModel' has properties that contain the action
				# e.g., {'properties': {'done': {...}}}
				if 'properties' in def_schema:
					for prop_name, prop_schema in def_schema['properties'].items():
						# Store the action name and its parameter structure
						action_schemas[prop_name] = prop_schema

		# Pattern to match function calls: name(args)
		# This matches function_name(...) including nested parentheses
		pattern = r'(\w+)\s*\(((?:[^()]|\([^()]*\))*)\)'

		for match in re.finditer(pattern, action_text):
			action_name = match.group(1)
			args_str = match.group(2).strip()

			try:
				# Check if this action exists in the model
				if action_name not in action_schemas:
					# Try to find it with common variations
					continue

				# Get the schema for this action
				action_schema = action_schemas[action_name]

				# Parse the arguments
				if args_str:
					# Try to parse as JSON-like format first
					params = UnstructuredOutputParser._parse_args_for_action(args_str, action_name, action_schema)
				else:
					# No parameters - use empty dict or None
					params = {}

				# Create the action instance
				action_data = {action_name: params}
				action_instance = action_model.model_validate(action_data)
				actions.append(action_instance)

			except (ValueError, ValidationError):
				# Log but don't fail on individual action parsing errors
				# The LLM might have included invalid actions
				continue

		return actions

	@staticmethod
	def _parse_args_for_action(args_str: str, _action_name: str, param_type: Any) -> dict[str, Any] | None:
		"""
		Parse function arguments for a specific action.

		Args:
			args_str: String containing arguments
			action_name: Name of the action being parsed
			param_type: The expected parameter type

		Returns:
			Dictionary of parsed arguments
		"""
		if not args_str:
			return None

		# Try to parse as JSON object first (handles both valid JSON and object literal syntax)
		if args_str.strip().startswith('{'):
			try:
				import json

				return json.loads(args_str)
			except json.JSONDecodeError:
				# Try to handle object literal syntax like {text: "value", success: True}
				# Convert it to valid JSON by adding quotes around unquoted keys
				try:
					# Replace unquoted keys with quoted keys
					# Pattern: find word characters followed by colon (but not inside quotes)
					import re

					fixed_str = args_str
					# Find all potential unquoted keys (word at start or after comma/brace, followed by colon)
					pattern = r'([,{]\s*)([a-zA-Z_]\w*)(\s*:)'
					fixed_str = re.sub(pattern, r'\1"\2"\3', fixed_str)
					# Also handle keys at the very start
					if not fixed_str.strip().startswith('{'):
						fixed_str = '{' + fixed_str
					if not fixed_str.strip().endswith('}'):
						fixed_str = fixed_str + '}'
					# Try one more time with the start of string
					pattern_start = r'^(\s*)([a-zA-Z_]\w*)(\s*:)'
					fixed_str = re.sub(pattern_start, r'\1"\2"\3', fixed_str)

					# Convert Python boolean literals to JSON (True -> true, False -> false, None -> null)
					# Only replace when they appear as values (after : or ,)
					fixed_str = re.sub(r':\s*True\b', ': true', fixed_str)
					fixed_str = re.sub(r':\s*False\b', ': false', fixed_str)
					fixed_str = re.sub(r':\s*None\b', ': null', fixed_str)

					return json.loads(fixed_str)
				except (json.JSONDecodeError, Exception):
					# If that also fails, fall through to other parsing methods
					pass

		# Check if we have named arguments (key=value format)
		if '=' in args_str:
			# Parse as key=value pairs
			params = {}
			args_list = UnstructuredOutputParser._split_args(args_str)
			for arg in args_list:
				if '=' in arg:
					key, value = arg.split('=', 1)
					params[key.strip()] = UnstructuredOutputParser._parse_value(value.strip())
			return params if params else None

		# Otherwise parse as positional args and map to known param names
		args_list = UnstructuredOutputParser._split_args(args_str)

		# Extract parameter names from the schema
		param_names: list[str] = []
		if isinstance(param_type, dict):
			# param_type is a schema dict with 'properties'
			if 'properties' in param_type:
				param_names = list(param_type['properties'].keys())
			elif 'anyOf' in param_type:
				# Handle anyOf schemas by taking the first option's properties
				for option in param_type['anyOf']:
					if isinstance(option, dict) and 'properties' in option:
						param_names = list(option['properties'].keys())
						break

		params: dict[str, Any] = {}

		# Map positional arguments to parameter names
		for i, arg in enumerate(args_list):
			if i < len(param_names):
				param_name = param_names[i]
				params[param_name] = UnstructuredOutputParser._parse_value(arg.strip())
			else:
				# Extra args beyond expected - try to include them
				params[f'arg_{i}'] = UnstructuredOutputParser._parse_value(arg.strip())

		return params if params else None

	@staticmethod
	def _split_args(args_str: str) -> list[str]:
		"""Split arguments by comma, respecting quotes and nesting."""
		args = []
		current = []
		depth = 0
		in_quotes = False
		quote_char = None

		for char in args_str:
			if char in ('"', "'") and (not in_quotes or char == quote_char):
				in_quotes = not in_quotes
				quote_char = char if in_quotes else None
				current.append(char)
			elif char in ('(', '[', '{') and not in_quotes:
				depth += 1
				current.append(char)
			elif char in (')', ']', '}') and not in_quotes:
				depth -= 1
				current.append(char)
			elif char == ',' and depth == 0 and not in_quotes:
				args.append(''.join(current).strip())
				current = []
			else:
				current.append(char)

		if current:
			args.append(''.join(current).strip())

		return args

	@staticmethod
	def _parse_value(value_str: str) -> Any:
		"""Parse a single value from string."""
		value_str = value_str.strip()

		# Handle quoted strings
		if (value_str.startswith('"') and value_str.endswith('"')) or (
			value_str.startswith("'") and value_str.endswith("'")
		):
			return value_str[1:-1]

		# Handle booleans
		if value_str.lower() in ('true', '1', 'yes'):
			return True
		if value_str.lower() in ('false', '0', 'no'):
			return False

		# Handle None/null
		if value_str.lower() in ('none', 'null'):
			return None

		# Try integer
		try:
			return int(value_str)
		except ValueError:
			pass

		# Try float
		try:
			return float(value_str)
		except ValueError:
			pass

		# Return as string
		return value_str
