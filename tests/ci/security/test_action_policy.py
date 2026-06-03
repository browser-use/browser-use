import pytest
from pydantic import BaseModel

from browser_use.agent.views import ActionResult
from browser_use.tools.policy import ActionPolicy
from browser_use.tools.registry.service import Registry
from browser_use.tools.service import Tools


class TextParams(BaseModel):
	text: str


class NavigateParams(BaseModel):
	url: str
	new_tab: bool = False


class UploadParams(BaseModel):
	path: str


@pytest.mark.asyncio
async def test_read_only_policy_blocks_interactive_actions_before_execution():
	executed = False
	registry = Registry(action_policy=ActionPolicy(read_only=True))

	@registry.action('', param_model=TextParams)
	async def input(params: TextParams):
		nonlocal executed
		executed = True
		return ActionResult(extracted_content=params.text)

	with pytest.raises(RuntimeError, match='Action policy blocked input'):
		await registry.execute_action('input', {'text': 'hello'})

	assert executed is False


@pytest.mark.asyncio
async def test_action_policy_blocks_navigation_target_outside_allowed_domains():
	executed = False
	registry = Registry(action_policy=ActionPolicy(allowed_domains=['example.com'], block_transactional=False))

	@registry.action('', param_model=NavigateParams)
	async def navigate(params: NavigateParams):
		nonlocal executed
		executed = True
		return ActionResult(extracted_content=f'Navigated to {params.url}')

	with pytest.raises(RuntimeError, match='Policy does not allow target_url domain'):
		await registry.execute_action('navigate', {'url': 'https://evil.com/phish', 'new_tab': False})

	assert executed is False

	result = await registry.execute_action('navigate', {'url': 'https://example.com/docs', 'new_tab': False})
	assert result.extracted_content == 'Navigated to https://example.com/docs'
	assert executed is True


@pytest.mark.asyncio
async def test_transactional_actions_are_blocked_by_default():
	executed = False
	registry = Registry(action_policy=ActionPolicy())

	@registry.action('', param_model=UploadParams)
	async def upload_file(params: UploadParams):
		nonlocal executed
		executed = True
		return ActionResult(extracted_content=f'Uploaded {params.path}')

	with pytest.raises(RuntimeError, match='Policy blocks transactional actions'):
		await registry.execute_action('upload_file', {'path': '/tmp/report.pdf'})

	assert executed is False


@pytest.mark.asyncio
async def test_tools_passes_action_policy_to_default_registry():
	tools = Tools(action_policy=ActionPolicy(read_only=True))

	with pytest.raises(RuntimeError, match='Action policy blocked navigate'):
		await tools.registry.execute_action('navigate', {'url': 'https://example.com', 'new_tab': False})
