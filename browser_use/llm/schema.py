"""
Utilities for creating optimized Pydantic schemas for LLM usage.
"""

from typing import Any

from pydantic import BaseModel


class SchemaOptimizer:
	@staticmethod
	def create_optimized_json_schema(model: type[BaseModel]) -> dict[str, Any]:
		"""
		Create the most optimized schema by flattening all $ref/$defs while preserving
		FULL descriptions and ALL action definitions. Also ensures OpenAI strict mode compatibility.

		Args:
			model: The Pydantic model to optimize

		Returns:
			Optimized schema with all $refs resolved and strict mode compatibility
		"""
		# Generate original schema
		original_schema = model.model_json_schema()

		# Extract $defs for reference resolution, then flatten everything
		defs_lookup = original_schema.get('$defs', {})

		def optimize_schema(
			obj: Any,
			defs_lookup: dict[str, Any] | None = None,
			*,
			in_properties: bool = False,  # NEW: track context
		) -> Any:
			"""Apply all optimization techniques including flattening all $ref/$defs"""
			if isinstance(obj, dict):
				optimized: dict[str, Any] = {}
				flattened_ref: dict[str, Any] | None = None

				# Skip unnecessary fields AND $defs (we'll inline everything)
				skip_fields = ['additionalProperties', '$defs']

				for key, value in obj.items():
					if key in skip_fields:
						continue

					# Skip metadata "title" unless we're iterating inside an actual `properties` map
					if key == 'title' and not in_properties:
						continue

					# Preserve FULL descriptions without truncation
					elif key == 'description':
						optimized[key] = value

					# Handle type field
					elif key == 'type':
						optimized[key] = value

					# FLATTEN: Resolve $ref by inlining the actual definition
					elif key == '$ref' and defs_lookup:
						ref_path = value.split('/')[-1]  # Get the definition name from "#/$defs/SomeName"
						if ref_path in defs_lookup:
							# Get the referenced definition and flatten it
							referenced_def = defs_lookup[ref_path]
							flattened_ref = optimize_schema(referenced_def, defs_lookup)

					# Keep all anyOf structures (action unions) and resolve any $refs within
					elif key == 'anyOf' and isinstance(value, list):
						optimized[key] = [optimize_schema(item, defs_lookup) for item in value]

					# Recursively optimize nested structures
					elif key in ['properties', 'items']:
						optimized[key] = optimize_schema(
							value,
							defs_lookup,
							in_properties=(key == 'properties'),
						)

					# Keep essential validation fields
					elif key in ['type', 'required', 'minimum', 'maximum', 'minItems', 'maxItems', 'pattern', 'default']:
						optimized[key] = value if not isinstance(value, (dict, list)) else optimize_schema(value, defs_lookup)

					# Recursively process all other fields
					else:
						optimized[key] = optimize_schema(value, defs_lookup) if isinstance(value, (dict, list)) else value

				# If we have a flattened reference, merge it with the optimized properties
				if flattened_ref is not None and isinstance(flattened_ref, dict):
					# Start with the flattened reference as the base
					result = flattened_ref.copy()

					# Merge in any sibling properties that were processed
					for key, value in optimized.items():
						# Preserve descriptions from the original object if they exist
						if key == 'description' and 'description' not in result:
							result[key] = value
						elif key != 'description':  # Don't overwrite description from flattened ref
							result[key] = value

					return result
				else:
					# No $ref, just return the optimized object
					# CRITICAL: Add additionalProperties: false to ALL objects for OpenAI strict mode
					if optimized.get('type') == 'object':
						optimized['additionalProperties'] = False

					return optimized

			elif isinstance(obj, list):
				return [optimize_schema(item, defs_lookup, in_properties=in_properties) for item in obj]
			return obj

		# Create optimized schema with flattening
		optimized_result = optimize_schema(original_schema, defs_lookup)

		# Ensure we have a dictionary (should always be the case for schema root)
		if not isinstance(optimized_result, dict):
			raise ValueError('Optimized schema result is not a dictionary')

		optimized_schema: dict[str, Any] = optimized_result

		# Additional pass to ensure ALL objects have additionalProperties: false
		def ensure_additional_properties_false(obj: Any) -> None:
			"""Ensure all objects have additionalProperties: false"""
			if isinstance(obj, dict):
				# If it's an object type, ensure additionalProperties is false
				if obj.get('type') == 'object':
					obj['additionalProperties'] = False

				# Recursively apply to all values
				for value in obj.values():
					if isinstance(value, (dict, list)):
						ensure_additional_properties_false(value)
			elif isinstance(obj, list):
				for item in obj:
					if isinstance(item, (dict, list)):
						ensure_additional_properties_false(item)

		ensure_additional_properties_false(optimized_schema)
		SchemaOptimizer._make_strict_compatible(optimized_schema)

		return optimized_schema

	@staticmethod
	def _make_strict_compatible(schema: dict[str, Any] | list[Any]) -> None:
		"""Ensure all properties are required for OpenAI strict mode"""
		if isinstance(schema, dict):
			# First recursively apply to nested objects
			for key, value in schema.items():
				if isinstance(value, (dict, list)) and key != 'required':
					SchemaOptimizer._make_strict_compatible(value)

			# Then update required for this level
			if 'properties' in schema and 'type' in schema and schema['type'] == 'object':
				# Add all properties to required array
				all_props = list(schema['properties'].keys())
				schema['required'] = all_props  # Set all properties as required

		elif isinstance(schema, list):
			for item in schema:
				SchemaOptimizer._make_strict_compatible(item)
