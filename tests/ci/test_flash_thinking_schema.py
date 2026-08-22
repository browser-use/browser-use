"""Flash mode reasoning-field variants.

Default flash mode emits {memory, action}. The opt-in variant swaps the conflated memory
field for a length-capped thinking field that is persisted into message history, so a small
local model reasons in structured output instead of via native reasoning tokens.
"""

from browser_use.agent.message_manager.views import HistoryItem
from browser_use.agent.views import ActionModel, AgentOutput
from browser_use.tools.service import Tools


def _flash_schema(**kwargs) -> dict:
	tools = Tools()
	action_model = tools.registry.create_action_model()
	return AgentOutput.type_with_custom_actions_flash_mode(action_model, **kwargs).model_json_schema()


class TestFlashSchemaVariants:
	def test_default_flash_mode_is_memory_and_action(self):
		"""Unchanged default: memory + action, no reasoning field."""
		schema = _flash_schema()

		assert schema['required'] == ['memory', 'action']
		assert 'thinking' not in schema['properties']
		assert 'memory' in schema['properties']
		assert 'evaluation_previous_goal' not in schema['properties']
		assert 'next_goal' not in schema['properties']

	def test_thinking_replaces_memory(self):
		"""Gregor's variant: a capped thinking field and no memory field."""
		schema = _flash_schema(include_thinking=True, include_memory=False)

		assert schema['required'] == ['thinking', 'action']
		assert 'thinking' in schema['properties']
		assert 'memory' not in schema['properties']

	def test_thinking_and_memory_can_coexist(self):
		"""Both fields, thinking ordered first so reasoning precedes the checkpoint."""
		schema = _flash_schema(include_thinking=True, include_memory=True)

		assert schema['required'] == ['thinking', 'memory', 'action']
		assert list(schema['properties']) == ['thinking', 'memory', 'action']

	def test_thinking_field_declares_a_length_cap(self):
		"""The cap is what keeps a chatty local model from spending its budget on prose."""
		schema = _flash_schema(include_thinking=True, include_memory=False)
		description = schema['properties']['thinking'].get('description', '')

		assert description, 'thinking field must carry a description telling the model what to write'
		assert 'words' in description.lower()

	def test_dropping_both_leaves_action_only(self):
		schema = _flash_schema(include_thinking=False, include_memory=False)

		assert schema['required'] == ['action']
		assert 'thinking' not in schema['properties']
		assert 'memory' not in schema['properties']

	def test_action_is_always_present(self):
		for kwargs in ({}, {'include_thinking': True}, {'include_thinking': True, 'include_memory': False}):
			schema = _flash_schema(**kwargs)
			assert 'action' in schema['properties']
			assert 'action' in schema['required']


class TestThinkingPersistence:
	def test_history_item_renders_thinking(self):
		"""Reasoning must survive into the next step's prompt, or it was wasted output."""
		item = HistoryItem(
			step_number=1, thinking='Search box is empty, typing the query next.', action_results='Clicked #search'
		)

		rendered = item.to_string()

		assert 'Search box is empty, typing the query next.' in rendered
		assert 'Clicked #search' in rendered

	def test_history_item_without_thinking_is_unchanged(self):
		item = HistoryItem(step_number=1, memory='Found 3 results', action_results='Clicked #search')

		rendered = item.to_string()

		assert 'Found 3 results' in rendered
		assert rendered.startswith('<step>')

	def test_thinking_precedes_memory(self):
		item = HistoryItem(step_number=2, thinking='Reasoned about it', memory='Remembered it')

		rendered = item.to_string()

		assert rendered.index('Reasoned about it') < rendered.index('Remembered it')


class TestWaitActionExclusion:
	def test_wait_is_registered_by_default(self):
		tools = Tools()
		assert 'wait' in tools.registry.registry.actions

	def test_wait_can_be_excluded(self):
		"""The wait action burns ~2s of wall clock whenever the model picks it."""
		tools = Tools(exclude_actions=['wait'])
		assert 'wait' not in tools.registry.registry.actions

	def test_excluding_wait_leaves_other_actions(self):
		tools = Tools(exclude_actions=['wait'])
		assert 'click' in tools.registry.registry.actions or 'click_element_by_index' in tools.registry.registry.actions
		assert 'done' in tools.registry.registry.actions


def test_agent_output_flash_variants_are_distinct_types():
	"""Each variant must be its own model so one agent's schema cannot leak into another's."""
	tools = Tools()
	action_model: type[ActionModel] = tools.registry.create_action_model()

	default = AgentOutput.type_with_custom_actions_flash_mode(action_model)
	thinking = AgentOutput.type_with_custom_actions_flash_mode(action_model, include_thinking=True, include_memory=False)

	assert default is not thinking
	assert default.model_json_schema()['required'] != thinking.model_json_schema()['required']


class TestAgentWiring:
	"""The settings must reach the schema, the prompt and the message manager together."""

	def _agent(self, **kwargs):
		from browser_use import Agent
		from tests.ci.conftest import create_mock_llm

		return Agent(task='test task', llm=create_mock_llm(), **kwargs)

	def test_flash_thinking_reaches_the_output_schema(self):
		agent = self._agent(flash_mode=True, flash_thinking=True, flash_memory=False)

		schema = agent.AgentOutput.model_json_schema()
		assert schema['required'] == ['thinking', 'action']
		assert agent.DoneAgentOutput.model_json_schema()['required'] == ['thinking', 'action']

	def test_flash_thinking_selects_the_matching_prompt(self):
		agent = self._agent(flash_mode=True, flash_thinking=True, flash_memory=False)

		prompt = agent._message_manager.system_prompt.text
		assert '"thinking"' in prompt
		assert '120 words' in prompt

	def test_flash_thinking_enables_history_persistence(self):
		agent = self._agent(flash_mode=True, flash_thinking=True, flash_memory=False)
		assert agent._message_manager.include_thinking_in_history is True

	def test_plain_flash_mode_is_untouched(self):
		"""Existing flash users must see exactly the previous schema, prompt and history."""
		agent = self._agent(flash_mode=True)

		assert agent.AgentOutput.model_json_schema()['required'] == ['memory', 'action']
		assert agent._message_manager.include_thinking_in_history is False
		assert '"memory"' in agent._message_manager.system_prompt.text

	def test_non_flash_mode_never_persists_thinking(self):
		"""Outside flash mode thinking is unbounded, so it must stay out of history."""
		agent = self._agent(flash_thinking=True)
		assert agent._message_manager.include_thinking_in_history is False
