"""
Attribute compression utilities for reducing token usage in LLM prompts.

This module provides functions for compressing HTML attributes in a way that's both
compact and understandable by LLMs.
"""

# Attribute mapping: full_name -> short_code
ATTRIBUTE_MAP = {
	'type': 't',
	'placeholder': 'p',
	'aria-label': 'a',
	'role': 'r',
	'name': 'n',
	'id': 'i',
	'class': 'c',
	'value': 'v',
	'href': 'h',
	'target': 'tg',
	'title': 'ti',
	'alt': 'al',
}


def get_compression_documentation(include_attributes: list[str] | None = None) -> str:
	"""Generate documentation for the attribute compression format.

	Args:
	    include_attributes: List of attribute names to include in documentation.
	                     If None or empty, all available attributes will be included.

	Returns:
	    str: Formatted documentation string explaining the compression format.
	"""
	# Filter ATTRIBUTE_MAP to only include requested attributes
	attribute_items = ATTRIBUTE_MAP.items()
	if include_attributes:
		attribute_items = [(attr, code) for attr, code in attribute_items if attr in include_attributes]
	else:
		# no include_attributes so no need to provide description of attributes
		return ''

	# Get the longest code for alignment
	max_code_len = max(len(code) for _, code in attribute_items)

	# Build attribute mapping section with only included attributes
	mapping_lines = [f'- {code.ljust(max_code_len)} - {attr_name}' for attr_name, code in sorted(attribute_items)]

	# Build the full documentation
	lines = [
		'[ATTRIBUTE COMPRESSION ENABLED]',
		"Interactive element attributes are compressed to save tokens. Here's the format:",
		'- code - attribute_name',
		'',
		'Available attribute mappings:',
		*mapping_lines,
		'',
		'Examples:',
		"  <button type='submit' class='btn'> becomes [1] <button t='submit' c='btn'>",
		"  <a href='/login' title='Sign in'> becomes [2] <a h='/login' ti='Sign in'>",
	]

	return '\n'.join(lines)


def compress_attributes(attributes: dict[str, str]) -> str:
	"""Compress a dictionary of attributes into a space-separated string.

	Args:
	    attributes: Dictionary of attribute names and values

	Returns:
	    str: Compressed attribute string with values in single quotes (e.g., "t='submit' c='btn btn-primary'")
	"""
	if not attributes:
		return ''

	compressed = []
	for key, value in attributes.items():
		# Use mapped key or original key
		short_key = ATTRIBUTE_MAP.get(key, key)
		# Escape single quotes in the value
		escaped_value = str(value).replace("'", "\\'")
		# Add single quotes around the value
		compressed.append(f"{short_key}='{escaped_value}'")

	return ' '.join(compressed)
