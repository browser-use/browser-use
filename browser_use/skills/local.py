"""Local filesystem-backed skills service."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from browser_use_sdk import ExecuteSkillResponse
from cdp_use.cdp.network import Cookie
from pydantic import BaseModel, ConfigDict, Field

from browser_use.skills.views import Skill

logger = logging.getLogger(__name__)


class LocalSkillMetadata(BaseModel):
	"""Metadata parsed from a local SKILL.md frontmatter block."""

	model_config = ConfigDict(extra='ignore')

	name: str = Field(min_length=1)
	description: str = Field(min_length=1)
	id: str | None = Field(default=None, min_length=1)
	title: str | None = Field(default=None, min_length=1)


class _LocalSkillRecord(BaseModel):
	"""Cached local skill contents."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	skill: Skill
	name: str
	body: str
	path: Path


class LocalSkillService:
	"""Load Markdown skills from the local filesystem.

	The service implements the same async interface Agent expects from SkillService:
	``get_all_skills()``, ``execute_skill()``, and ``close()``. Each local
	``SKILL.md`` file becomes a no-argument skill action whose execution returns
	the Markdown body as instructions for the agent.
	"""

	def __init__(self, skills_path: str | Path, skill_ids: list[str | Literal['*']] | None = None):
		"""Initialize a local skill service.

		Args:
			skills_path: A directory containing */SKILL.md files, or a direct SKILL.md path.
			skill_ids: Optional list of local skill IDs/names to load, or ['*'] for all.
		"""
		self.skills_path = Path(skills_path).expanduser()
		self.skill_ids = skill_ids if skill_ids is not None else ['*']
		self._skills: dict[str, _LocalSkillRecord] = {}
		self._initialized = False

	async def async_init(self) -> None:
		"""Load and cache all matching local skills."""
		if self._initialized:
			return

		if not self.skills_path.exists():
			raise FileNotFoundError(f'Local skills path does not exist: {self.skills_path}')

		records: dict[str, _LocalSkillRecord] = {}
		use_wildcard = '*' in self.skill_ids
		requested_ids = {skill_id for skill_id in self.skill_ids if skill_id != '*'}

		for skill_file in self._skill_files():
			try:
				record = self._load_skill_file(skill_file)
			except ValueError as e:
				if self.skills_path.is_file():
					raise ValueError(f'Invalid local skill {skill_file}: {e}') from e
				logger.warning(f'Skipping invalid local skill {skill_file}: {e}')
				continue

			if not use_wildcard and requested_ids.isdisjoint(self._skill_aliases(record)):
				continue

			skill = record.skill
			if skill.id in records:
				existing_path = records[skill.id].path
				raise ValueError(f'Duplicate local skill id "{skill.id}" in {existing_path} and {skill_file}')

			records[skill.id] = record

		if not use_wildcard:
			found_aliases: set[str] = set()
			for record in records.values():
				found_aliases.update(self._skill_aliases(record))
			missing = requested_ids - found_aliases
			if missing:
				logger.warning(f'Requested local skills not found: {missing}')

		self._skills = records
		self._initialized = True
		logger.info(f'Loaded {len(self._skills)} local skill(s) from {self.skills_path}')

	def _skill_files(self) -> list[Path]:
		if self.skills_path.is_file():
			return [self.skills_path]
		return sorted(self.skills_path.glob('*/SKILL.md'))

	def _load_skill_file(self, skill_file: Path) -> _LocalSkillRecord:
		metadata, body = self._parse_skill_file(skill_file)
		skill_id = metadata.id or metadata.name
		title = metadata.title or metadata.name
		return _LocalSkillRecord(
			skill=Skill(
				id=skill_id,
				title=title,
				description=metadata.description,
				parameters=[],
				output_schema={},
			),
			name=metadata.name,
			body=body,
			path=skill_file,
		)

	@staticmethod
	def _skill_aliases(record: _LocalSkillRecord) -> set[str]:
		return {record.skill.id, record.skill.title, record.name}

	@classmethod
	def _parse_skill_file(cls, skill_file: Path) -> tuple[LocalSkillMetadata, str]:
		text = skill_file.read_text(encoding='utf-8').replace('\r\n', '\n')
		if not text.startswith('---\n'):
			raise ValueError('missing YAML frontmatter')

		content = text.removeprefix('---\n')
		delimiter_index = content.find('\n---')
		if delimiter_index == -1:
			raise ValueError('unterminated YAML frontmatter')

		frontmatter = content[:delimiter_index]
		body = content[delimiter_index + len('\n---') :]
		if body.startswith('\n'):
			body = body.removeprefix('\n')
		elif body:
			raise ValueError('unterminated YAML frontmatter')

		data: dict[str, str] = {}
		for raw_line in frontmatter.splitlines():
			line = raw_line.strip()
			if not line or line.startswith('#'):
				continue
			if ':' not in line:
				continue

			key, value = line.split(':', 1)
			key = key.strip()
			if key in LocalSkillMetadata.model_fields:
				data[key] = cls._parse_frontmatter_scalar(value)

		return LocalSkillMetadata.model_validate(data), body

	@staticmethod
	def _parse_frontmatter_scalar(value: str) -> str:
		value = value.strip()
		if value in {'|', '>'} or value.startswith('|') or value.startswith('>'):
			raise ValueError('YAML block scalars are not supported in local skill frontmatter')
		if not value:
			return value

		quote = value[0]
		if quote in {'"', "'"}:
			if len(value) < 2 or value[-1] != quote:
				raise ValueError('unterminated quoted scalar')
			if quote == "'":
				return value[1:-1].replace("''", "'")

			try:
				parsed = json.loads(value)
			except json.JSONDecodeError as e:
				raise ValueError('invalid double-quoted scalar; use JSON-compatible escapes') from e
			if isinstance(parsed, str):
				return parsed
			raise ValueError('quoted scalar must parse to a string')
		return value

	async def get_skill(self, skill_id: str) -> Skill | None:
		"""Get a cached local skill by ID."""
		if not self._initialized:
			await self.async_init()

		record = self._skills.get(skill_id)
		return record.skill if record else None

	async def get_all_skills(self) -> list[Skill]:
		"""Get all loaded local skills."""
		if not self._initialized:
			await self.async_init()

		return [record.skill for record in self._skills.values()]

	async def execute_skill(
		self, skill_id: str, parameters: dict[str, Any] | BaseModel, cookies: list[Cookie]
	) -> ExecuteSkillResponse:
		"""Return the Markdown body for a local skill."""
		if not self._initialized:
			await self.async_init()

		record = self._skills.get(skill_id)
		if record is None:
			return ExecuteSkillResponse(
				success=False,
				result=None,
				error=f'Local skill {skill_id} not found. Available skills: {list(self._skills.keys())}',
				stderr=None,
				latencyMs=0,
			)

		return ExecuteSkillResponse(success=True, result=record.body, error=None, stderr=None, latencyMs=0)

	async def close(self) -> None:
		"""Clear cached local skills."""
		self._skills = {}
		self._initialized = False
