from dataclasses import dataclass

from browser_use.agent.service import Agent
from browser_use.agent.views import ActionResult
from browser_use.tools.registry.service import Registry
from browser_use.tools.service import Tools
from tests.ci.conftest import create_mock_llm


@dataclass
class RuntimeContext:
	value: str


async def test_registry_injects_constructor_context_and_allows_per_call_override():
	registry = Registry[RuntimeContext](context=RuntimeContext('registry-context'))

	@registry.action('Read runtime context')
	async def read_context(context: RuntimeContext):
		return ActionResult(extracted_content=context.value)

	result = await registry.execute_action('read_context', {})

	assert result.extracted_content == 'registry-context'

	result = await registry.execute_action('read_context', {}, context=RuntimeContext('override-context'))

	assert result.extracted_content == 'override-context'


async def test_tools_act_threads_context_to_registered_actions():
	tools = Tools[RuntimeContext](context=RuntimeContext('tools-context'))

	@tools.registry.action('Read runtime context through tools')
	async def read_context(context: RuntimeContext):
		return ActionResult(extracted_content=context.value)

	ActionModel = tools.registry.create_action_model(include_actions=['read_context'])

	result = await tools.act(ActionModel(**{'read_context': {}}), browser_session=None)  # type: ignore[arg-type]

	assert result.extracted_content == 'tools-context'

	result = await tools.act(
		ActionModel(**{'read_context': {}}),
		browser_session=None,  # type: ignore[arg-type]
		context=RuntimeContext('act-context'),
	)

	assert result.extracted_content == 'act-context'


async def test_tools_direct_action_helper_threads_context():
	tools = Tools[RuntimeContext](context=RuntimeContext('tools-context'))

	@tools.registry.action('Read runtime context through direct helper')
	async def read_context(context: RuntimeContext):
		return ActionResult(extracted_content=context.value)

	result = await tools.read_context()

	assert result.extracted_content == 'tools-context'

	result = await tools.read_context(context=RuntimeContext('helper-context'))

	assert result.extracted_content == 'helper-context'


def test_agent_threads_context_to_default_tools():
	context = RuntimeContext('agent-context')

	agent = Agent(task='Use context.', llm=create_mock_llm(), context=context)

	assert agent.context is context
	assert agent.tools.context is context
	assert agent.tools.registry.context is context


def test_agent_threads_context_to_custom_tools():
	initial_context = RuntimeContext('initial-context')
	context = RuntimeContext('agent-context')
	tools = Tools[RuntimeContext](context=initial_context)

	agent = Agent(task='Use custom tools context.', llm=create_mock_llm(), tools=tools, context=context)

	assert agent.tools is tools
	assert tools.context is context
	assert tools.registry.context is context
