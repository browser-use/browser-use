from unittest.mock import AsyncMock

from browser_use import Agent, AgentConfig
from browser_use.llm.base import BaseChatModel


def _mock_llm() -> BaseChatModel:
	llm = AsyncMock(spec=BaseChatModel)
	llm.provider = 'mock'
	llm.model = 'mock-model'
	llm.name = 'mock-model'
	llm._verified_api_keys = True
	return llm


def test_agent_from_config_applies_grouped_settings() -> None:
	agent = Agent.from_config(
		'config smoke',
		llm=_mock_llm(),
		config=AgentConfig(
			use_vision=False,
			use_judge=False,
			directly_open_url=False,
			max_actions_per_step=2,
			available_file_paths=['/tmp/input.csv'],
			use_native_tool_calls=True,
		),
	)

	assert agent.settings.use_vision is False
	assert agent.settings.use_judge is False
	assert agent.directly_open_url is False
	assert agent.settings.max_actions_per_step == 2
	assert agent.available_file_paths == ['/tmp/input.csv']
	assert agent.settings.use_native_tool_calls is True


def test_agent_from_config_accepts_dict_and_overrides() -> None:
	agent = Agent.from_config(
		'config dict smoke',
		llm=_mock_llm(),
		config={'use_judge': True, 'directly_open_url': True, 'max_actions_per_step': 4},
		use_judge=False,
		directly_open_url=False,
	)

	assert agent.settings.use_judge is False
	assert agent.directly_open_url is False
	assert agent.settings.max_actions_per_step == 4


def test_agent_config_only_emits_explicit_fields() -> None:
	config = AgentConfig(use_judge=False)

	assert config.to_agent_kwargs() == {'use_judge': False}
