from browser_use.agent.views import AgentOutput
from browser_use.tools.service import Tools


def test_agent_output_dynamic_models_are_cached_per_action_model_and_mode() -> None:
	action_model = Tools().registry.create_action_model()

	thinking_model = AgentOutput.type_with_custom_actions(action_model)
	no_thinking_model = AgentOutput.type_with_custom_actions_no_thinking(action_model)
	flash_model = AgentOutput.type_with_custom_actions_flash_mode(action_model)

	assert AgentOutput.type_with_custom_actions(action_model) is thinking_model
	assert AgentOutput.type_with_custom_actions_no_thinking(action_model) is no_thinking_model
	assert AgentOutput.type_with_custom_actions_flash_mode(action_model) is flash_model
	assert len({thinking_model, no_thinking_model, flash_model}) == 3
