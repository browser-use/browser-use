def cap_text_length(text: str, max_length: int) -> str:
	"""Cap text length for display."""
	if len(text) <= max_length:
		return text
	return text[:max_length] + '...'


def generate_css_selector_for_element(enhanced_node) -> str | None:
	"""Generate a CSS selector using node properties from version 0.5.0 approach."""
	import re

	if not enhanced_node or not hasattr(enhanced_node, 'tag_name') or not enhanced_node.tag_name:
		return None

	# Get base selector from tag name (simplified since we don't have xpath in EnhancedDOMTreeNode)
	tag_name = enhanced_node.tag_name.lower().strip()
	if not tag_name or not re.match(r'^[a-zA-Z][a-zA-Z0-9-]*$', tag_name):
		return None

	css_selector = tag_name

	# Add ID if available (most specific)
	if enhanced_node.attributes and 'id' in enhanced_node.attributes:
		element_id = enhanced_node.attributes['id']
		if element_id and element_id.strip():
			element_id = element_id.strip()
			# Validate ID contains only valid characters for # selector
			if re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', element_id):
				return f'#{element_id}'
			else:
				# For IDs with special characters ($, ., :, etc.), use attribute selector
				# Escape quotes in the ID value
				escaped_id = element_id.replace('"', '\\"')
				return f'{tag_name}[id="{escaped_id}"]'

	# Handle class attributes (from version 0.5.0 approach)
	if enhanced_node.attributes and 'class' in enhanced_node.attributes and enhanced_node.attributes['class']:
		# Define a regex pattern for valid class names in CSS
		valid_class_name_pattern = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_-]*$')

		# Iterate through the class attribute values
		classes = enhanced_node.attributes['class'].split()
		for class_name in classes:
			# Skip empty class names
			if not class_name.strip():
				continue

			# Check if the class name is valid
			if valid_class_name_pattern.match(class_name):
				# Append the valid class name to the CSS selector
				css_selector += f'.{class_name}'

	# Expanded set of safe attributes that are stable and useful for selection (from v0.5.0)
	SAFE_ATTRIBUTES = {
		# Data attributes (if they're stable in your application)
		'id',
		# Standard HTML attributes
		'name',
		'type',
		'placeholder',
		# Accessibility attributes
		'aria-label',
		'aria-labelledby',
		'aria-describedby',
		'role',
		# Common form attributes
		'for',
		'autocomplete',
		'required',
		'readonly',
		# Media attributes
		'alt',
		'title',
		'src',
		# Custom stable attributes (add any application-specific ones)
		'href',
		'target',
	}

	# Always include dynamic attributes (include_dynamic_attributes=True equivalent)
	include_dynamic_attributes = True
	if include_dynamic_attributes:
		dynamic_attributes = {
			'data-id',
			'data-qa',
			'data-cy',
			'data-testid',
		}
		SAFE_ATTRIBUTES.update(dynamic_attributes)

	# Handle other attributes (from version 0.5.0 approach)
	if enhanced_node.attributes:
		for attribute, value in enhanced_node.attributes.items():
			if attribute == 'class':
				continue

			# Skip invalid attribute names
			if not attribute.strip():
				continue

			if attribute not in SAFE_ATTRIBUTES:
				continue

			# Escape special characters in attribute names
			safe_attribute = attribute.replace(':', r'\:')

			# Handle different value cases
			if value == '':
				css_selector += f'[{safe_attribute}]'
			elif any(char in value for char in '"\'<>`\n\r\t'):
				# Use contains for values with special characters
				# For newline-containing text, only use the part before the newline
				if '\n' in value:
					value = value.split('\n')[0]
				# Regex-substitute *any* whitespace with a single space, then strip.
				collapsed_value = re.sub(r'\s+', ' ', value).strip()
				# Escape embedded double-quotes.
				safe_value = collapsed_value.replace('"', '\\"')
				css_selector += f'[{safe_attribute}*="{safe_value}"]'
			else:
				css_selector += f'[{safe_attribute}="{value}"]'

	# Final validation: ensure the selector is safe and doesn't contain problematic characters
	# Note: quotes are allowed in attribute selectors like [name="value"]
	if css_selector and not any(char in css_selector for char in ['\n', '\r', '\t']):
		return css_selector

	# If we get here, the selector was problematic, return just the tag name as fallback
	return tag_name
