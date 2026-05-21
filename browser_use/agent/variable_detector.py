"""Detect variables in agent history for reuse"""

import re

from browser_use.agent.views import AgentHistoryList, DetectedVariable
from browser_use.dom.views import DOMInteractedElement


def detect_variables_in_history(history: AgentHistoryList) -> dict[str, DetectedVariable]:
	"""
	Analyze agent history and detect reusable variables.

	Uses two strategies:
	1. Element attributes (id, name, type, placeholder, aria-label) - most reliable
	2. Value pattern matching (email, phone, date formats) - fallback

	Returns:
		Dictionary mapping variable names to DetectedVariable objects
	"""
	detected: dict[str, DetectedVariable] = {}
	detected_values: set[str] = set()  # Track which values we've already detected

	for step_idx, history_item in enumerate(history.history):
		if not history_item.model_output:
			continue

		for action_idx, action in enumerate(history_item.model_output.action):
			# Convert action to dict - handle both Pydantic models and dict-like objects
			if hasattr(action, 'model_dump'):
				action_dict = action.model_dump()
			elif isinstance(action, dict):
				action_dict = action
			else:
				# For SimpleNamespace or similar objects
				action_dict = vars(action)

			# Get the interacted element for this action (if available)
			element = None
			if history_item.state and history_item.state.interacted_element:
				if len(history_item.state.interacted_element) > action_idx:
					element = history_item.state.interacted_element[action_idx]

			# Detect variables in this action
			_detect_in_action(action_dict, element, detected, detected_values)

	return detected


def _detect_in_action(
	action_dict: dict,
	element: DOMInteractedElement | None,
	detected: dict[str, DetectedVariable],
	detected_values: set[str],
) -> None:
	"""Detect variables in a single action using element context"""

	# Extract action type and parameters
	for action_type, params in action_dict.items():
		if not isinstance(params, dict):
			continue

		# Check fields that commonly contain variables
		fields_to_check = ['text', 'query']

		for field in fields_to_check:
			if field not in params:
				continue

			value = params[field]
			if not isinstance(value, str) or not value.strip():
				continue

			# Skip if we already detected this exact value
			if value in detected_values:
				continue

			# Try to detect variable type (with element context)
			var_info = _detect_variable_type(value, element)
			if not var_info:
				continue

			var_name, var_format = var_info

			# Ensure unique variable name
			var_name = _ensure_unique_name(var_name, detected)

			# Add detected variable
			detected[var_name] = DetectedVariable(
				name=var_name,
				original_value=value,
				type='string',
				format=var_format,
			)

			detected_values.add(value)


def _detect_variable_type(
	value: str,
	element: DOMInteractedElement | None = None,
) -> tuple[str, str | None] | None:
	"""
	Detect if a value looks like a variable, using element context when available.

	Priority:
	1. Element attributes (id, name, type, placeholder, aria-label) - most reliable
	2. Value pattern matching (email, phone, date formats) - fallback

	Returns:
		(variable_name, format) or None if not detected
	"""

	# STRATEGY 1: Use element attributes (most reliable)
	if element and element.attributes:
		attr_detection = _detect_from_attributes(element.attributes)
		if attr_detection:
			return attr_detection

	# STRATEGY 2: Pattern matching on value (fallback)
	return _detect_from_value_pattern(value)


def _detect_from_attributes(attributes: dict[str, str]) -> tuple[str, str | None] | None:
	"""
	Detect variable from element attributes.

	Check attributes in priority order:
	1. type attribute (HTML5 input types - most specific)
	2. id, name, placeholder, aria-label (semantic hints)
	"""

	# Check 'type' attribute first (HTML5 input types)
	input_type = attributes.get('type', '').lower()
	if input_type == 'email':
		return ('email', 'email')
	elif input_type == 'tel':
		return ('phone', 'phone')
	elif input_type == 'date':
		return ('date', 'date')
	elif input_type == 'number':
		return ('number', 'number')
	elif input_type == 'url':
		return ('url', 'url')

	# Combine semantic attributes for keyword matching
	semantic_attrs = [
		attributes.get('id', ''),
		attributes.get('name', ''),
		attributes.get('placeholder', ''),
		attributes.get('aria-label', ''),
	]

	combined_text = ' '.join(semantic_attrs).lower()

	# Address detection
	if any(keyword in combined_text for keyword in ['address', 'street', 'addr']):
		if 'billing' in combined_text:
			return ('billing_address', None)
		elif 'shipping' in combined_text:
			return ('shipping_address', None)
		else:
			return ('address', None)

	# Comment/Note detection
	if any(keyword in combined_text for keyword in ['comment', 'note', 'message', 'description']):
		return ('comment', None)

	# Email detection
	if 'email' in combined_text or 'e-mail' in combined_text:
		return ('email', 'email')

	# Phone detection
	if any(keyword in combined_text for keyword in ['phone', 'tel', 'mobile', 'cell']):
		return ('phone', 'phone')

	# Name detection (order matters - check specific before general)
	if 'first' in combined_text and 'name' in combined_text:
		return ('first_name', None)
	elif 'last' in combined_text and 'name' in combined_text:
		return ('last_name', None)
	elif 'full' in combined_text and 'name' in combined_text:
		return ('full_name', None)
	elif 'name' in combined_text:
		return ('name', None)

	# Date detection
	if any(keyword in combined_text for keyword in ['date', 'dob', 'birth']):
		return ('date', 'date')

	# City detection
	if 'city' in combined_text:
		return ('city', None)

	# State/Province detection
	if 'state' in combined_text or 'province' in combined_text:
		return ('state', None)

	# Country detection
	if 'country' in combined_text:
		return ('country', None)

	# Zip code detection
	if any(keyword in combined_text for keyword in ['zip', 'postal', 'postcode']):
		return ('zip_code', 'postal_code')

	# Company detection
	if 'company' in combined_text or 'organization' in combined_text:
		return ('company', None)

	return None


def _detect_from_value_pattern(value: str) -> tuple[str, str | None] | None:
	"""
	Detect variable type from value pattern (fallback when no element context).

	Patterns:
	- Email: contains @ and . with valid format
	- Phone: digits with separators, 10+ chars
	- Date: YYYY-MM-DD format
	- Name: Capitalized word(s), 2-30 chars, letters only
	- Number: Pure digits, 1-9 chars
	"""

	# Email detection - most specific first
	if '@' in value and '.' in value:
		# Basic email validation
		if re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', value):
			return ('email', 'email')

	# Phone detection (digits with separators, 10+ chars)
	if re.match(r'^[\d\s\-\(\)\+]+$', value):
		# Remove separators and check length
		digits_only = re.sub(r'[\s\-\(\)\+]', '', value)
		if len(digits_only) >= 10:
			return ('phone', 'phone')

	# Date detection (YYYY-MM-DD or similar)
	if re.match(r'^\d{4}-\d{2}-\d{2}$', value):
		return ('date', 'date')

	# Name detection (capitalized, only letters/spaces, 2-30 chars)
	if value and value[0].isupper() and value.replace(' ', '').replace('-', '').isalpha() and 2 <= len(value) <= 30:
		words = value.split()
		if len(words) == 1:
			return ('first_name', None)
		elif len(words) == 2:
			return ('full_name', None)
		else:
			return ('name', None)

	# Number detection (pure digits, not phone length)
	if value.isdigit() and 1 <= len(value) <= 9:
		return ('number', 'number')

	return None


def _ensure_unique_name(base_name: str, existing: dict[str, DetectedVariable]) -> str:
	"""
	Ensure variable name is unique by adding suffix if needed.

	Examples:
		first_name → first_name
		first_name (exists) → first_name_2
		first_name_2 (exists) → first_name_3
	"""
	if base_name not in existing:
		return base_name

	# Add numeric suffix
	counter = 2
	while f'{base_name}_{counter}' in existing:
		counter += 1

	return f'{base_name}_{counter}'
