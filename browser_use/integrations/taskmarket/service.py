import asyncio
import json
import math
import os
import re
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BASE_CHAIN_ID = 8453
DEFAULT_TASKMARKET_API_URL = 'https://api.taskmarket.dev'
TASKMARKET_TASK_URL = 'https://taskmarket.dev/tasks/{task_id}'
TASK_ID_RE = re.compile(r'^0x[a-fA-F0-9]{64}$')

CommandRunner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]


class TaskMarketTaskDraft(BaseModel):
	"""Validated Taskmarket requester task draft."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	description: str = Field(
		min_length=20,
		description='Exact requester-facing task description to publish.',
	)
	deliverables: str = Field(
		min_length=3,
		description='Exact deliverables and acceptance evidence the worker must submit.',
	)
	reward_usdc: Decimal = Field(gt=Decimal('0'), description='Task reward in USDC.')
	max_spend_usdc: Decimal = Field(gt=Decimal('0'), description='Maximum user-authorized spend in USDC.')
	deadline_iso: str = Field(description='Task deadline as an ISO-8601 timestamp.')
	network: Literal['base'] = Field(default='base', description='Taskmarket production tasks are funded on Base.')
	mode: Literal['bounty', 'claim', 'pitch', 'benchmark'] = Field(default='bounty')
	task_visibility: Literal['public', 'unlisted', 'private'] = Field(default='public')
	submission_visibility: Literal['public', 'reveal_all', 'winner_only', 'never'] = Field(default='public')
	tags: list[str] = Field(default_factory=list, max_length=8)

	@field_validator('reward_usdc', 'max_spend_usdc', mode='before')
	@classmethod
	def _parse_decimal(cls, value: Any) -> Decimal:
		try:
			return Decimal(str(value))
		except (InvalidOperation, ValueError) as exc:
			raise ValueError('Must be a decimal USDC amount') from exc

	@field_validator('tags')
	@classmethod
	def _clean_tags(cls, value: list[str]) -> list[str]:
		return [tag.strip() for tag in value if tag.strip()]

	@model_validator(mode='after')
	def _validate_spend_cap(self) -> 'TaskMarketTaskDraft':
		if self.max_spend_usdc < self.reward_usdc:
			raise ValueError('max_spend_usdc must be greater than or equal to reward_usdc')
		return self

	def deadline(self) -> datetime:
		value = self.deadline_iso
		if value.endswith('Z'):
			value = f'{value[:-1]}+00:00'
		try:
			parsed = datetime.fromisoformat(value)
		except ValueError as exc:
			raise ValueError('deadline_iso must be a valid ISO-8601 timestamp') from exc
		if parsed.tzinfo is None:
			raise ValueError('deadline_iso must include a timezone')
		return parsed.astimezone(UTC)

	def duration_hours(self, now: datetime | None = None) -> int:
		now = now or datetime.now(UTC)
		deadline = self.deadline()
		if deadline <= now:
			raise ValueError('deadline_iso must be in the future')
		return max(1, math.ceil((deadline - now).total_seconds() / 3600))

	def task_description(self) -> str:
		return f'{self.description.strip()}\n\nDeliverables:\n{self.deliverables.strip()}'


class TaskMarketPreview(BaseModel):
	"""Stored preview that must be confirmed before creating a task."""

	preview_id: str
	confirmation_token: str
	network: Literal['base']
	chain_id: int
	description: str
	deliverables: str
	reward_usdc: str
	max_spend_usdc: str
	deadline_iso: str
	duration_hours: int
	mode: str
	task_visibility: str
	submission_visibility: str
	tags: list[str]
	command_preview: list[str]
	approval_instruction: str


class TaskMarketCreatedTask(BaseModel):
	"""Result returned after the Taskmarket CLI creates and funds the task."""

	task_id: str
	task_url: str
	raw: dict[str, Any]


class TaskMarketService:
	"""Taskmarket requester client for browser-use integrations."""

	def __init__(
		self,
		api_url: str | None = None,
		cli_path: str = 'taskmarket',
		command_runner: CommandRunner | None = None,
		http_client: httpx.AsyncClient | None = None,
	):
		self.api_url = (api_url or os.environ.get('TASKMARKET_API_URL') or DEFAULT_TASKMARKET_API_URL).rstrip('/')
		self.cli_path = cli_path
		self._command_runner = command_runner or self._run_command
		self._http_client = http_client
		self._previews: dict[str, tuple[TaskMarketTaskDraft, TaskMarketPreview]] = {}

	async def prepare_task(self, draft: TaskMarketTaskDraft) -> TaskMarketPreview:
		duration_hours = draft.duration_hours()
		preview_id = secrets.token_urlsafe(8)
		confirmation_token = secrets.token_urlsafe(10)
		command_preview = self._build_create_command(draft, duration_hours)
		preview = TaskMarketPreview(
			preview_id=preview_id,
			confirmation_token=confirmation_token,
			network=draft.network,
			chain_id=BASE_CHAIN_ID,
			description=draft.description.strip(),
			deliverables=draft.deliverables.strip(),
			reward_usdc=self._format_decimal(draft.reward_usdc),
			max_spend_usdc=self._format_decimal(draft.max_spend_usdc),
			deadline_iso=draft.deadline().isoformat(),
			duration_hours=duration_hours,
			mode=draft.mode,
			task_visibility=draft.task_visibility,
			submission_visibility=draft.submission_visibility,
			tags=draft.tags,
			command_preview=command_preview,
			approval_instruction=(
				'Show this exact preview to the user. Create the task only after the user explicitly authorizes '
				f'Base spend up to {self._format_decimal(draft.max_spend_usdc)} USDC and provides the confirmation token.'
			),
		)
		self._previews[preview_id] = (draft, preview)
		return preview

	async def create_task(
		self,
		preview_id: str,
		confirmation_token: str,
		confirm_authorized: bool,
		max_spend_usdc: Decimal | str | None = None,
	) -> TaskMarketCreatedTask:
		if not confirm_authorized:
			raise ValueError('Fresh user authorization is required before creating or funding a Taskmarket task')
		if preview_id not in self._previews:
			raise ValueError('Unknown or expired Taskmarket preview_id')

		draft, preview = self._previews[preview_id]
		if not secrets.compare_digest(confirmation_token, preview.confirmation_token):
			raise ValueError('Taskmarket confirmation token does not match the preview')

		if max_spend_usdc is not None and Decimal(str(max_spend_usdc)) < draft.reward_usdc:
			raise ValueError('Authorized max_spend_usdc is lower than the task reward')

		duration_hours = draft.duration_hours()
		command = self._build_create_command(draft, duration_hours)
		returncode, stdout, stderr = await self._command_runner(command)
		if returncode != 0:
			raise RuntimeError(
				'Taskmarket task creation failed. The command was not retried because settlement status may be unknown. '
				f'stderr: {stderr.strip()}'
			)

		envelope = self._parse_cli_json(stdout)
		if not envelope.get('ok', False):
			raise RuntimeError(f'Taskmarket CLI returned an error: {envelope.get("error", "unknown error")}')

		data = envelope.get('data') or {}
		task_id = self._extract_task_id(data)
		if not task_id:
			raise RuntimeError('Taskmarket CLI succeeded but did not return a task id')
		return TaskMarketCreatedTask(task_id=task_id, task_url=TASKMARKET_TASK_URL.format(task_id=task_id), raw=data)

	async def get_task_status(self, task_id: str) -> dict[str, Any]:
		self._validate_task_id(task_id)
		return await self._get_json(f'/api/tasks/{task_id}')

	async def get_submissions(self, task_id: str) -> dict[str, Any]:
		self._validate_task_id(task_id)
		data = await self._get_json(f'/api/tasks/{task_id}/submissions')
		return {
			'task_id': task_id,
			'submissions': data if isinstance(data, list) else data.get('data', data),
			'review_note': 'Present these submissions for human review. This integration does not accept or reject work automatically.',
		}

	def _build_create_command(self, draft: TaskMarketTaskDraft, duration_hours: int) -> list[str]:
		command = [
			self.cli_path,
			'task',
			'create',
			'--description',
			draft.task_description(),
			'--reward',
			self._format_decimal(draft.reward_usdc),
			'--duration',
			str(duration_hours),
			'--mode',
			draft.mode,
			'--task-visibility',
			draft.task_visibility,
			'--submission-visibility',
			draft.submission_visibility,
		]
		if draft.tags:
			command.extend(['--tags', ','.join(draft.tags)])
		return command

	async def _run_command(self, command: list[str]) -> tuple[int, str, str]:
		process = await asyncio.create_subprocess_exec(
			*command,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
		)
		stdout, stderr = await process.communicate()
		return process.returncode or 1, stdout.decode(), stderr.decode()

	async def _get_json(self, path: str) -> dict[str, Any]:
		client = self._http_client
		close_client = client is None
		if client is None:
			client = httpx.AsyncClient(timeout=30)
		try:
			response = await client.get(f'{self.api_url}{path}')
			response.raise_for_status()
			payload = response.json()
			if isinstance(payload, dict) and payload.get('ok') is True and 'data' in payload:
				return payload['data']
			return payload
		finally:
			if close_client:
				await client.aclose()

	def _parse_cli_json(self, stdout: str) -> dict[str, Any]:
		try:
			payload = json.loads(stdout)
		except json.JSONDecodeError as exc:
			raise RuntimeError('Taskmarket CLI returned non-JSON output') from exc
		if not isinstance(payload, dict):
			raise RuntimeError('Taskmarket CLI returned an unexpected JSON shape')
		return payload

	def _extract_task_id(self, data: dict[str, Any]) -> str | None:
		candidates = [
			data.get('taskId'),
			data.get('id'),
			(data.get('task') or {}).get('id') if isinstance(data.get('task'), dict) else None,
		]
		for candidate in candidates:
			if isinstance(candidate, str) and TASK_ID_RE.match(candidate):
				return candidate
		return None

	def _validate_task_id(self, task_id: str) -> None:
		if not TASK_ID_RE.match(task_id):
			raise ValueError('Taskmarket task_id must be a 0x-prefixed 32-byte hex string')

	def _format_decimal(self, value: Decimal) -> str:
		return format(value.normalize(), 'f')
