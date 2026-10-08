"""The "at least one action" constraint must survive as standard JSON Schema.

`AgentOutput.action` used to be declared with `json_schema_extra={'min_items': 1}` and the
inline comment "Ensure at least one action is provided". `min_items` is the Pydantic v1
spelling of this keyword; Pydantic v2 and JSON Schema (draft 2020-12, §10.2.1) name it
`minItems`, and consumers must ignore keywords they do not recognise. Every provider
path here forwards the schema through `SchemaOptimizer.create_optimized_json_schema()`,
which keeps the key verbatim but never renames it, so the constraint was invisible to
`ChatOpenAI`, `ChatGroq`, `ChatOpenRouter`, `ChatGoogle` (via
`create_gemini_optimized_schema`) and the Browser Use cloud endpoint by default
(`remove_min_items_from_schema=False`).

The fix is schema-only on purpose: an empty `action` list is still handled gracefully at
runtime (`Agent._get_next_action` / `AgentHistoryList.last_action`), so this test also
pins that behaviour to make the scope unambiguous.
"""

from pydantic import ValidationError

from browser_use.agent.views import AgentOutput
from browser_use.llm.schema import SchemaOptimizer
from browser_use.tools.service import Tools


def _custom_action_model() -> type[AgentOutput]:
	"""Build the dynamic AgentOutput subclass an Agent uses at runtime."""
	ActionModel = Tools().registry.create_action_model()
	return AgentOutput.type_with_custom_actions(ActionModel)


def test_raw_agent_output_schema_uses_standard_min_items_keyword():
	schema = AgentOutput.model_json_schema()
	action_schema = schema['properties']['action']

	assert 'min_items' not in action_schema, 'min_items is the Pydantic v1 keyword and is not valid JSON Schema'
	assert action_schema.get('minItems') == 1, 'action array must declare minItems=1 for schema consumers'


def test_every_agent_output_variant_declares_min_items():
	for label, model in (
		('base', AgentOutput),
		('custom_actions', _custom_action_model()),
		('no_thinking', AgentOutput.type_with_custom_actions_no_thinking(Tools().registry.create_action_model())),
		('flash_mode', AgentOutput.type_with_custom_actions_flash_mode(Tools().registry.create_action_model())),
	):
		action_schema = SchemaOptimizer.create_optimized_json_schema(model)['properties']['action']

		assert 'min_items' not in action_schema, f'{label}: non-standard min_items leaked into the provider payload'
		assert action_schema.get('minItems') == 1, f'{label}: minItems=1 missing from the provider payload'


def test_empty_action_list_is_still_accepted_at_runtime():
	"""Schema-only fix: the agent keeps handling `action: []` itself instead of raising."""
	assert AgentOutput.model_validate({'memory': 'm', 'action': []}).action == []

	try:
		_custom_action_model().model_validate({'memory': 'm', 'action': []})
	except ValidationError as e:
		raise AssertionError('runtime validation of action=[] must not change with this schema fix') from e
