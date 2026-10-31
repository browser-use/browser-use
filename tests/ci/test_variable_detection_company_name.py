"""Regression test: company/organization fields must not fall through to the generic `name` variable.

`company_name` and `organization_name` contain the substring `name`, so the generic name branch used to
run before the company branch and classified the value as a personal name.
"""

import pytest
from pydantic import create_model

from browser_use.agent.variable_detector import detect_variables_in_history
from browser_use.agent.views import AgentHistory, AgentHistoryList, AgentOutput
from browser_use.browser.views import BrowserStateHistory
from browser_use.dom.views import DOMInteractedElement, NodeType
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.views import InputTextAction


def _history_with_field(attribute_name: str, value: str, placeholder: str) -> AgentHistoryList:
	action_model = create_model(
		'InputActionModel',
		__base__=ActionModel,
		input=(InputTextAction | None, None),
	)
	output_model = AgentOutput.type_with_custom_actions(action_model)

	element = DOMInteractedElement(
		node_id=1,
		backend_node_id=1,
		frame_id='frame1',
		node_type=NodeType.ELEMENT_NODE,
		node_value='',
		node_name='input',
		attributes={'name': attribute_name, 'placeholder': placeholder},
		bounds=None,
		x_path=f'//*[@name="{attribute_name}"]',
		element_hash=12345,
	)
	action = action_model(**{'input': InputTextAction(index=1, text=value)})

	return AgentHistoryList(
		history=[
			AgentHistory(
				model_output=output_model(
					evaluation_previous_goal='ok',
					memory='ok',
					next_goal='done',
					action=[action],
				),
				result=[],
				state=BrowserStateHistory(
					url='https://example.com/signup',
					title='Create account',
					tabs=[],
					interacted_element=[element],
				),
			)
		]
	)


@pytest.mark.parametrize('attribute_name', ['company', 'organization', 'company_name', 'organization_name'])
def test_company_field_is_detected_as_company(attribute_name: str) -> None:
	result = detect_variables_in_history(_history_with_field(attribute_name, 'OpenAI', 'Company or organization'))

	assert list(result) == ['company']
	assert result['company'].original_value == 'OpenAI'


@pytest.mark.parametrize(
	'attribute_name, expected',
	[('first_name', 'first_name'), ('last_name', 'last_name'), ('full_name', 'full_name'), ('name', 'name')],
)
def test_personal_name_fields_keep_their_classification(attribute_name: str, expected: str) -> None:
	result = detect_variables_in_history(_history_with_field(attribute_name, 'Ada Lovelace', 'Your name'))

	assert list(result) == [expected]
	assert result[expected].original_value == 'Ada Lovelace'
