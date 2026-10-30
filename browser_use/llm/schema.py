"""
Utilities for creating optimized Pydantic schemas for LLM usage.
"""

from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

# Keywords whose values are JSON instances (data), not schemas. Their contents must
# be copied as-is: keys like "title" or "type" inside them are data, not keywords.
_INSTANCE_KEYWORDS = frozenset({'default', 'const', 'enum', 'examples'})


class SchemaOptimizer:
	@staticmethod
	def create_optimized_json_schema(
		model: type[BaseModel],
		*,
		remove_min_items: bool = False,
		remove_defaults: bool = False,
	) -> dict[str, Any]:
		"""
		Create the most optimized schema by flattening all $ref/$defs while preserving
		FULL descriptions and ALL action definitions. Also ensures OpenAI strict mode compatibility.

		Args:
			model: The Pydantic model to optimize
			remove_min_items: If True, remove minItems from the schema
			remove_defaults: If True, remove default values from the schema

		Returns:
			Optimized schema with all $refs resolved and strict mode compatibility
		"""
		# Generate original schema
		original_schema = model.model_json_schema()

		# Extract $defs for reference resolution, then flatten everything
		defs_lookup = original_schema.get('$defs', {})

		# Create optimized schema with flattening
		# Pass flags to optimize_schema via closure
		def optimize_schema(obj: Any, defs_lookup: dict[str, Any] | None = None, *, in_properties: bool = False) -> Any:
			"""Apply all optimization techniques including flattening all $ref/$defs"""
			if isinstance(obj, dict):
				optimized: dict[str, Any] = {}
				flattened_ref: dict[str, Any] | None = None

				# Skip unnecessary fields AND $defs (we'll inline everything)
				skip_fields = ['additionalProperties', '$defs']

				for key, value in obj.items():
					# Keys inside `properties` are user field names, not schema keywords.
					if in_properties:
						optimized[key] = optimize_schema(value, defs_lookup)
						continue

					if key in skip_fields:
						continue

					# Skip metadata "title"
					if key == 'title':
						continue

					# Preserve FULL descriptions without truncation, skip empty ones
					elif key == 'description':
						if value:  # Only include non-empty descriptions
							optimized[key] = value

					# Handle type field - must recursively process in case value contains $ref
					elif key == 'type':
						optimized[key] = value if not isinstance(value, (dict, list)) else optimize_schema(value, defs_lookup)

					# FLATTEN: Resolve $ref by inlining the actual definition
					elif key == '$ref' and defs_lookup:
						ref_path = value.split('/')[-1]  # Get the definition name from "#/$defs/SomeName"
						if ref_path in defs_lookup:
							# Get the referenced definition and flatten it
							referenced_def = defs_lookup[ref_path]
							flattened_ref = optimize_schema(referenced_def, defs_lookup)

					# Skip minItems/min_items and default if requested (check BEFORE processing)
					elif key in ('minItems', 'min_items') and remove_min_items:
						continue  # Skip minItems/min_items
					elif key == 'default' and remove_defaults:
						continue  # Skip default values

					# Keep instance values (default, const, enum, examples) unchanged
					elif key in _INSTANCE_KEYWORDS:
						optimized[key] = value

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
					elif key in [
						'required',
						'minimum',
						'maximum',
						'minItems',
						'min_items',
						'maxItems',
						'pattern',
					]:
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

		optimized_result = optimize_schema(original_schema, defs_lookup)

		# Ensure we have a dictionary (should always be the case for schema root)
		if not isinstance(optimized_result, dict):
			raise ValueError('Optimized schema result is not a dictionary')

		optimized_schema: dict[str, Any] = optimized_result

		# Additional pass to ensure ALL objects have additionalProperties: false
		for sub_schema in SchemaOptimizer._iter_schemas(optimized_schema):
			if sub_schema.get('type') == 'object':
				sub_schema['additionalProperties'] = False

		SchemaOptimizer._make_strict_compatible(optimized_schema)

		# Final pass to remove minItems/min_items and default values if requested
		if remove_min_items or remove_defaults:
			for sub_schema in SchemaOptimizer._iter_schemas(optimized_schema):
				if remove_min_items:
					sub_schema.pop('minItems', None)
					sub_schema.pop('min_items', None)
				if remove_defaults:
					sub_schema.pop('default', None)

		return optimized_schema

	@staticmethod
	def _iter_schemas(obj: Any) -> Iterator[dict[str, Any]]:
		"""Yield every schema object in obj.

		Keys of a `properties` map are field names, so the map itself is not yielded, only
		the schemas it holds. Instance values (default, const, enum, examples) are data and
		are not walked. A caller may add or remove keys on each yielded schema.
		"""
		if isinstance(obj, list):
			for item in obj:
				yield from SchemaOptimizer._iter_schemas(item)
		elif isinstance(obj, dict):
			yield obj
			for key, value in list(obj.items()):
				if key in _INSTANCE_KEYWORDS:
					continue
				if key == 'properties' and isinstance(value, dict):
					for prop_schema in value.values():
						yield from SchemaOptimizer._iter_schemas(prop_schema)
				else:
					yield from SchemaOptimizer._iter_schemas(value)

	@staticmethod
	def _make_strict_compatible(schema: dict[str, Any] | list[Any]) -> None:
		"""Ensure all properties are required for OpenAI strict mode"""
		for sub_schema in SchemaOptimizer._iter_schemas(schema):
			if sub_schema.get('type') == 'object' and isinstance(sub_schema.get('properties'), dict):
				# Add all properties to required array
				sub_schema['required'] = list(sub_schema['properties'].keys())

	@staticmethod
	def create_gemini_optimized_schema(model: type[BaseModel]) -> dict[str, Any]:
		"""
		Create Gemini-optimized schema, preserving explicit `required` arrays so Gemini
		respects mandatory fields defined by the caller.

		Args:
			model: The Pydantic model to optimize

		Returns:
			Optimized schema suitable for Gemini structured output
		"""
		return SchemaOptimizer.create_optimized_json_schema(model)
