from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, field_validator

from .service import TaskMarketService, TaskMarketTaskDraft

if TYPE_CHECKING:
	from browser_use.tools.service import Tools


class PrepareTaskMarketTaskParams(TaskMarketTaskDraft):
	"""Parameters for preparing a Taskmarket requester task preview."""


class CreateTaskMarketTaskParams(BaseModel):
	"""Parameters for creating a previously previewed Taskmarket task."""

	preview_id: str = Field(description='Preview id returned by taskmarket_prepare_task.')
	confirmation_token: str = Field(description='Confirmation token returned in the preview after the user authorizes it.')
	confirm_authorized: bool = Field(
		default=False,
		description='Set true only after the user explicitly authorizes creating and funding this exact Taskmarket task.',
	)
	max_spend_usdc: Decimal | None = Field(
		default=None,
		description='Optional fresh user-authorized spend cap. Must be at least the previewed reward.',
	)

	@field_validator('max_spend_usdc', mode='before')
	@classmethod
	def _parse_decimal(cls, value: Any) -> Decimal | None:
		if value is None:
			return None
		try:
			return Decimal(str(value))
		except (InvalidOperation, ValueError) as exc:
			raise ValueError('max_spend_usdc must be a decimal USDC amount') from exc


class TaskMarketTaskIdParams(BaseModel):
	"""Parameters for Taskmarket read-only task lookups."""

	task_id: str = Field(description='0x-prefixed 32-byte Taskmarket task id.')


def register_taskmarket_actions(
	tools: Tools,
	taskmarket_service: TaskMarketService | None = None,
	api_url: str | None = None,
	cli_path: str = 'taskmarket',
) -> Tools:
	"""Register opt-in Taskmarket requester workflow actions."""

	service = taskmarket_service or TaskMarketService(api_url=api_url, cli_path=cli_path)

	@tools.registry.action(
		description=(
			'Prepare a Taskmarket requester task preview. This does not create or fund anything. '
			'Show the exact description, deliverables, reward, deadline, Base network, maximum spend, and confirmation token to the user.'
		),
		param_model=PrepareTaskMarketTaskParams,
	)
	async def taskmarket_prepare_task(params: PrepareTaskMarketTaskParams) -> Any:
		from browser_use.agent.views import ActionResult

		try:
			preview = await service.prepare_task(params)
			content = json.dumps(preview.model_dump(), indent=2)
			return ActionResult(
				extracted_content=content,
				long_term_memory=f'Prepared Taskmarket preview {preview.preview_id}; user authorization is still required.',
			)
		except Exception as exc:
			return ActionResult(error=f'Failed to prepare Taskmarket task: {exc}')

	@tools.registry.action(
		description=(
			'Create and fund a previously previewed Taskmarket task using the first-party taskmarket CLI. '
			'Only call after fresh explicit user authorization for this exact preview; never retry automatically after failure.'
		),
		param_model=CreateTaskMarketTaskParams,
	)
	async def taskmarket_create_task(params: CreateTaskMarketTaskParams) -> Any:
		from browser_use.agent.views import ActionResult

		try:
			created = await service.create_task(
				preview_id=params.preview_id,
				confirmation_token=params.confirmation_token,
				confirm_authorized=params.confirm_authorized,
				max_spend_usdc=params.max_spend_usdc,
			)
			content = json.dumps(created.model_dump(), indent=2)
			return ActionResult(
				extracted_content=content,
				long_term_memory=f'Created Taskmarket task {created.task_id}.',
			)
		except Exception as exc:
			return ActionResult(error=f'Failed to create Taskmarket task: {exc}')

	@tools.registry.action(
		description='Retrieve live Taskmarket task status by id. This is read-only and does not use wallet authority.',
		param_model=TaskMarketTaskIdParams,
	)
	async def taskmarket_get_task_status(params: TaskMarketTaskIdParams) -> Any:
		from browser_use.agent.views import ActionResult

		try:
			status = await service.get_task_status(params.task_id)
			return ActionResult(extracted_content=json.dumps(status, indent=2))
		except Exception as exc:
			return ActionResult(error=f'Failed to retrieve Taskmarket task status: {exc}')

	@tools.registry.action(
		description=(
			'Retrieve Taskmarket submissions for human review. This is read-only and never accepts, rejects, rates, or pays workers.'
		),
		param_model=TaskMarketTaskIdParams,
	)
	async def taskmarket_list_submissions(params: TaskMarketTaskIdParams) -> Any:
		from browser_use.agent.views import ActionResult

		try:
			submissions = await service.get_submissions(params.task_id)
			return ActionResult(extracted_content=json.dumps(submissions, indent=2))
		except Exception as exc:
			return ActionResult(error=f'Failed to retrieve Taskmarket submissions: {exc}')

	return tools
