"""Unit tests for variable detection in agent history"""

from browser_use.agent.variable_detector import (
	_detect_from_attributes,
	_detect_from_value_pattern,
	_detect_variable_type,
	_ensure_unique_name,
	detect_variables_in_history,
)
from browser_use.agent.views import DetectedVariable
from browser_use.dom.views import DOMInteractedElement, NodeType


def create_test_element(attributes: dict[str, str] | None = None) -> DOMInteractedElement:
	"""Helper to create a DOMInteractedElement for testing"""
	return DOMInteractedElement(
		node_id=1,
		backend_node_id=1,
		frame_id='frame1',
		node_type=NodeType.ELEMENT_NODE,
		node_value='',
		node_name='input',
		attributes=attributes or {},
		bounds=None,
		x_path='//*[@id="test"]',
		element_hash=12345,
	)


def create_mock_history(actions_with_elements: list[tuple[dict, DOMInteractedElement | None]]):
	"""Helper to create mock history for testing"""
	from types import SimpleNamespace

	history_items = []
	for action_dict, element in actions_with_elements:
		mock_action = SimpleNamespace(**action_dict)
		mock_output = SimpleNamespace(action=[mock_action])
		mock_state = SimpleNamespace(interacted_element=[element] if element else None)
		mock_history_item = SimpleNamespace(model_output=mock_output, state=mock_state)
		history_items.append(mock_history_item)

	return SimpleNamespace(history=history_items)


def test_detect_email_from_attributes():
	"""Test email detection via type='email' attribute"""
	attributes = {'type': 'email', 'id': 'email-input'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'email'
	assert var_format == 'email'


def test_detect_email_from_pattern():
	"""Test email detection via pattern matching"""
	result = _detect_from_value_pattern('test@example.com')

	assert result is not None
	var_name, var_format = result
	assert var_name == 'email'
	assert var_format == 'email'


def test_detect_phone_from_attributes():
	"""Test phone detection via type='tel' attribute"""
	attributes = {'type': 'tel', 'name': 'phone'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'phone'
	assert var_format == 'phone'


def test_detect_phone_from_pattern():
	"""Test phone detection via pattern matching"""
	result = _detect_from_value_pattern('+1 (555) 123-4567')

	assert result is not None
	var_name, var_format = result
	assert var_name == 'phone'
	assert var_format == 'phone'


def test_detect_date_from_attributes():
	"""Test date detection via type='date' attribute"""
	attributes = {'type': 'date', 'id': 'dob'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'date'
	assert var_format == 'date'


def test_detect_date_from_pattern():
	"""Test date detection via YYYY-MM-DD pattern"""
	result = _detect_from_value_pattern('1990-01-01')

	assert result is not None
	var_name, var_format = result
	assert var_name == 'date'
	assert var_format == 'date'


def test_detect_first_name_from_attributes():
	"""Test first name detection from element attributes"""
	attributes = {'name': 'first_name', 'placeholder': 'Enter your first name'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'first_name'
	assert var_format is None


def test_detect_first_name_from_pattern():
	"""Test first name detection from pattern (single capitalized word)"""
	result = _detect_from_value_pattern('John')

	assert result is not None
	var_name, var_format = result
	assert var_name == 'first_name'
	assert var_format is None


def test_detect_full_name_from_pattern():
	"""Test full name detection from pattern (two capitalized words)"""
	result = _detect_from_value_pattern('John Doe')

	assert result is not None
	var_name, var_format = result
	assert var_name == 'full_name'
	assert var_format is None


def test_detect_address_from_attributes():
	"""Test address detection from element attributes"""
	attributes = {'name': 'street_address', 'id': 'address-input'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'address'
	assert var_format is None


def test_detect_billing_address_from_attributes():
	"""Test billing address detection from element attributes"""
	attributes = {'name': 'billing_address', 'placeholder': 'Billing street address'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'billing_address'
	assert var_format is None


def test_detect_comment_from_attributes():
	"""Test comment detection from element attributes"""
	attributes = {'name': 'comment', 'placeholder': 'Enter your comment'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'comment'
	assert var_format is None


def test_detect_city_from_attributes():
	"""Test city detection from element attributes"""
	attributes = {'name': 'city', 'id': 'city-input'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'city'
	assert var_format is None


def test_detect_state_from_attributes():
	"""Test state detection from element attributes"""
	attributes = {'name': 'state', 'aria-label': 'State or Province'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'state'
	assert var_format is None


def test_detect_country_from_attributes():
	"""Test country detection from element attributes"""
	attributes = {'name': 'country', 'id': 'country-select'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'country'
	assert var_format is None


def test_detect_zip_code_from_attributes():
	"""Test zip code detection from element attributes"""
	attributes = {'name': 'zip_code', 'placeholder': 'Zip or postal code'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'zip_code'
	assert var_format == 'postal_code'


def test_detect_company_from_attributes():
	"""Test company detection from element attributes"""
	attributes = {'name': 'company', 'id': 'company-input'}
	result = _detect_from_attributes(attributes)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'company'
	assert var_format is None


def test_detect_number_from_pattern():
	"""Test number detection from pattern (pure digits)"""
	result = _detect_from_value_pattern('12345')

	assert result is not None
	var_name, var_format = result
	assert var_name == 'number'
	assert var_format == 'number'


def test_no_detection_for_random_text():
	"""Test that random text is not detected as a variable"""
	result = _detect_from_value_pattern('some random text that is not a variable')
	assert result is None


def test_no_detection_for_short_text():
	"""Test that very short text is not detected"""
	result = _detect_from_value_pattern('a')
	assert result is None


def test_element_attributes_take_priority_over_pattern():
	"""Test that element attributes are checked before pattern matching"""
	# A value that could match pattern (capitalized name)
	value = 'Test'

	# Element with explicit type="email"
	element = create_test_element(attributes={'type': 'email', 'id': 'email-input'})

	result = _detect_variable_type(value, element)

	assert result is not None
	var_name, var_format = result
	# Should detect as email (from attributes), not first_name (from pattern)
	assert var_name == 'email'
	assert var_format == 'email'


def test_pattern_matching_used_when_no_element():
	"""Test that pattern matching is used when element context is missing"""
	value = 'test@example.com'

	result = _detect_variable_type(value, element=None)

	assert result is not None
	var_name, var_format = result
	assert var_name == 'email'
	assert var_format == 'email'


def test_ensure_unique_name_no_conflict():
	"""Test unique name generation with no conflicts"""
	existing = {}
	result = _ensure_unique_name('email', existing)
	assert result == 'email'


def test_ensure_unique_name_with_conflict():
	"""Test unique name generation with conflicts"""
	existing = {
		'email': DetectedVariable(name='email', original_value='test1@example.com'),
	}
	result = _ensure_unique_name('email', existing)
	assert result == 'email_2'


def test_ensure_unique_name_with_multiple_conflicts():
	"""Test unique name generation with multiple conflicts"""
	existing = {
		'email': DetectedVariable(name='email', original_value='test1@example.com'),
		'email_2': DetectedVariable(name='email_2', original_value='test2@example.com'),
	}
	result = _ensure_unique_name('email', existing)
	assert result == 'email_3'


def test_detect_variables_in_empty_history():
	"""Test variable detection in empty history"""
	from types import SimpleNamespace

	history = SimpleNamespace(history=[])

	result = detect_variables_in_history(history)  # type: ignore[arg-type]

	assert result == {}


def test_detect_variables_in_history_with_input_action():
	"""Test variable detection in history with input action"""
	# Use mock objects to avoid Pydantic validation issues
	from types import SimpleNamespace

	# Create mock history structure
	element = create_test_element(attributes={'type': 'email', 'id': 'email-input'})

	mock_action = SimpleNamespace(**{'input': {'index': 1, 'text': 'test@example.com'}})
	mock_output = SimpleNamespace(action=[mock_action])
	mock_state = SimpleNamespace(interacted_element=[element])
	mock_history_item = SimpleNamespace(model_output=mock_output, state=mock_state)
	mock_history = SimpleNamespace(history=[mock_history_item])

	result = detect_variables_in_history(mock_history)  # type: ignore[arg-type]

	assert len(result) == 1
	assert 'email' in result
	assert result['email'].original_value == 'test@example.com'
	assert result['email'].format == 'email'


def test_detect_variables_skips_duplicate_values():
	"""Test that duplicate values are only detected once"""
	# Create history with same value entered twice
	element = create_test_element(attributes={'type': 'email'})
	history = create_mock_history(
		[
			({'input': {'index': 1, 'text': 'test@example.com'}}, element),
			({'input': {'index': 2, 'text': 'test@example.com'}}, element),
		]
	)

	result = detect_variables_in_history(history)  # type: ignore[arg-type]

	# Should only detect one variable, not two
	assert len(result) == 1
	assert 'email' in result


def test_detect_variables_handles_missing_state():
	"""Test that detection works when state is missing"""
	from types import SimpleNamespace

	# Create history with None state
	mock_action = SimpleNamespace(**{'input': {'index': 1, 'text': 'test@example.com'}})
	mock_output = SimpleNamespace(action=[mock_action])
	mock_history_item = SimpleNamespace(model_output=mock_output, state=None)
	history = SimpleNamespace(history=[mock_history_item])

	result = detect_variables_in_history(history)  # type: ignore[arg-type]

	# Should still detect via pattern matching
	assert len(result) == 1
	assert 'email' in result
	assert result['email'].original_value == 'test@example.com'


def test_detect_variables_handles_missing_interacted_element():
	"""Test that detection works when interacted_element is missing"""
	# Use None as element to test when interacted_element is None
	history = create_mock_history(
		[
			({'input': {'index': 1, 'text': 'test@example.com'}}, None),
		]
	)

	result = detect_variables_in_history(history)  # type: ignore[arg-type]

	# Should still detect via pattern matching
	assert len(result) == 1
	assert 'email' in result


def test_detect_variables_multiple_types():
	"""Test detection of multiple variable types in one history"""
	history = create_mock_history(
		[
			({'input': {'index': 1, 'text': 'test@example.com'}}, create_test_element(attributes={'type': 'email'})),
			({'input': {'index': 2, 'text': 'John'}}, create_test_element(attributes={'name': 'first_name'})),
			({'input': {'index': 3, 'text': '1990-01-01'}}, create_test_element(attributes={'type': 'date'})),
		]
	)

	result = detect_variables_in_history(history)  # type: ignore[arg-type]

	assert len(result) == 3
	assert 'email' in result
	assert 'first_name' in result
	assert 'date' in result

	assert result['email'].original_value == 'test@example.com'
	assert result['first_name'].original_value == 'John'
	assert result['date'].original_value == '1990-01-01'
