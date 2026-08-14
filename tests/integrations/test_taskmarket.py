import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest

from browser_use.integrations.taskmarket import TaskMarketService, TaskMarketTaskDraft, register_taskmarket_actions

TASK_ID = '0x' + '1' * 64


def make_draft(**overrides):
	values: dict[str, Any] = {
		'description': 'Hire external workers to verify a browser automation benchmark.',
		'deliverables': 'Submit a Markdown report with reproduction steps, logs, and pass/fail evidence.',
		'reward_usdc': '2.5',
		'max_spend_usdc': '2.5',
		'deadline_iso': (datetime.now(UTC) + timedelta(hours=6)).isoformat(),
		'tags': ['browser-use', 'taskmarket'],
	}
	values.update(overrides)
	return TaskMarketTaskDraft(**values)


@pytest.mark.asyncio
async def test_prepare_task_preview_includes_required_authorization_details():
	service = TaskMarketService()
	preview = await service.prepare_task(make_draft())

	assert preview.network == 'base'
	assert preview.chain_id == 8453
	assert preview.reward_usdc == '2.5'
	assert preview.max_spend_usdc == '2.5'
	assert preview.confirmation_token
	assert '--description' in preview.command_preview
	assert '--reward' in preview.command_preview
	assert 'Show this exact preview to the user' in preview.approval_instruction


@pytest.mark.asyncio
async def test_create_task_requires_fresh_authorization():
	service = TaskMarketService()
	preview = await service.prepare_task(make_draft())

	with pytest.raises(ValueError, match='Fresh user authorization'):
		await service.create_task(preview.preview_id, preview.confirmation_token, confirm_authorized=False)


@pytest.mark.asyncio
async def test_create_task_uses_taskmarket_cli_once_without_shell():
	calls: list[list[str]] = []

	async def runner(command: list[str]):
		calls.append(command)
		return 0, json.dumps({'ok': True, 'data': {'taskId': TASK_ID}}), ''

	service = TaskMarketService(cli_path='taskmarket-test', command_runner=runner)
	preview = await service.prepare_task(make_draft())
	created = await service.create_task(
		preview.preview_id,
		preview.confirmation_token,
		confirm_authorized=True,
		max_spend_usdc='2.5',
	)

	assert created.task_id == TASK_ID
	assert created.task_url.endswith(TASK_ID)
	assert len(calls) == 1
	assert calls[0][0:3] == ['taskmarket-test', 'task', 'create']
	assert '--duration' in calls[0]
	assert all('\n' not in arg or arg.startswith('Hire external workers') for arg in calls[0])


@pytest.mark.asyncio
async def test_create_task_does_not_retry_when_cli_status_is_unknown():
	calls = 0

	async def runner(command: list[str]):
		nonlocal calls
		calls += 1
		return 1, '', '{"ok":false,"error":"network dropped"}'

	service = TaskMarketService(command_runner=runner)
	preview = await service.prepare_task(make_draft())

	with pytest.raises(RuntimeError, match='was not retried'):
		await service.create_task(preview.preview_id, preview.confirmation_token, confirm_authorized=True)
	assert calls == 1


@pytest.mark.asyncio
async def test_live_reads_use_public_api_and_present_submissions_for_review():
	def handler(request: httpx.Request) -> httpx.Response:
		if request.url.path.endswith('/submissions'):
			return httpx.Response(200, json={'ok': True, 'data': [{'workerAddress': '0xabc', 'id': 'sub_1'}]})
		return httpx.Response(200, json={'ok': True, 'data': {'id': TASK_ID, 'status': 'open'}})

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		service = TaskMarketService(api_url='https://taskmarket.test', http_client=client)
		status = await service.get_task_status(TASK_ID)
		submissions = await service.get_submissions(TASK_ID)

	assert status == {'id': TASK_ID, 'status': 'open'}
	assert submissions['submissions'] == [{'workerAddress': '0xabc', 'id': 'sub_1'}]
	assert 'does not accept or reject work automatically' in submissions['review_note']


@pytest.mark.asyncio
async def test_registered_actions_are_opt_in_and_do_not_register_review_writes():
	class FakeRegistry:
		def __init__(self):
			self.actions = {}

		def action(self, description, param_model=None):
			def decorator(func):
				self.actions[func.__name__] = {'description': description, 'param_model': param_model}
				return func

			return decorator

	class FakeTools:
		def __init__(self):
			self.registry = FakeRegistry()

	tools = FakeTools()
	register_taskmarket_actions(cast(Any, tools))

	actions = set(tools.registry.actions)
	assert {
		'taskmarket_prepare_task',
		'taskmarket_create_task',
		'taskmarket_get_task_status',
		'taskmarket_list_submissions',
	}.issubset(actions)
	assert 'taskmarket_accept_submission' not in actions
	assert 'taskmarket_reject_submission' not in actions
