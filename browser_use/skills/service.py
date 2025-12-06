"""Skills service for fetching and executing skills from the Browser Use API"""

import asyncio
import logging
import os
from typing import Any

from browser_use_sdk import AsyncBrowserUse
from pydantic import BaseModel, ValidationError

from browser_use.skills.views import ExecuteSkillResponse, Skill, SkillResponse

logger = logging.getLogger(__name__)


class SkillService:
	"""Service for managing and executing skills from the Browser Use API"""

	def __init__(self, skill_ids: list[str], api_key: str | None = None):
		"""Initialize the skills service

		Args:
			skill_ids: List of skill IDs to fetch and cache
			api_key: Browser Use API key (optional, will use env var if not provided)
		"""
		self.skill_ids = skill_ids
		self.api_key = api_key or os.getenv('BROWSER_USE_API_KEY') or ''

		if not self.api_key:
			raise ValueError('BROWSER_USE_API_KEY environment variable is not set')

		self._skills: dict[str, Skill] = {}
		self._client: AsyncBrowserUse | None = None
		self._initialized = False

	async def async_init(self) -> None:
		"""Async initialization to fetch all skills concurrently

		This should be called after __init__ to fetch and cache all skills.
		"""
		if self._initialized:
			logger.debug('SkillService already initialized')
			return

		# Create the SDK client
		self._client = AsyncBrowserUse(api_key=self.api_key)

		# Fetch all skills concurrently
		logger.info(f'Fetching {len(self.skill_ids)} skills from Browser Use API...')

		fetch_tasks = [self._fetch_skill(skill_id) for skill_id in self.skill_ids]
		results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

		# Process results
		for skill_id, result in zip(self.skill_ids, results):
			if isinstance(result, Exception):
				logger.error(f'Failed to fetch skill {skill_id}: {result}')
			elif isinstance(result, Skill):
				self._skills[skill_id] = result
				logger.debug(f'Cached skill: {result.title} ({skill_id})')

		logger.info(f'Successfully loaded {len(self._skills)}/{len(self.skill_ids)} skills')
		self._initialized = True

	async def _fetch_skill(self, skill_id: str) -> Skill | None:
		"""Fetch a single skill from the API and convert to Skill model

		Args:
			skill_id: The UUID of the skill to fetch

		Returns:
			Skill model or None if fetch failed
		"""
		assert self._client is not None, 'Client not initialized - call async_init() first'

		try:
			# Fetch skill details from API (returns SkillResponse from SDK)
			skill_response: SkillResponse = await self._client.skills.get_skill(skill_id=skill_id)

			# Check if skill is finished and enabled
			if skill_response.status != 'finished':
				logger.warning(f'Skill {skill_id} is not finished (status: {skill_response.status})')
				return None

			if not skill_response.is_enabled:
				logger.warning(f'Skill {skill_id} is not enabled')
				return None

			# Convert SDK SkillResponse to our Skill model with helper properties
			skill = Skill.from_skill_response(skill_response)

			return skill

		except Exception as e:
			logger.error(f'Error fetching skill {skill_id}: {type(e).__name__}: {e}')
			return None

	async def get_skill(self, skill_id: str) -> Skill | None:
		"""Get a cached skill by ID. Auto-initializes if not already initialized.

		Args:
			skill_id: The UUID of the skill

		Returns:
			Skill model or None if not found in cache
		"""
		if not self._initialized:
			await self.async_init()

		return self._skills.get(skill_id)

	async def get_all_skills(self) -> list[Skill]:
		"""Get all cached skills. Auto-initializes if not already initialized.

		Returns:
			List of all successfully loaded skills
		"""
		if not self._initialized:
			await self.async_init()

		return list(self._skills.values())

	async def execute_skill(self, skill_id: str, parameters: dict[str, Any] | BaseModel) -> ExecuteSkillResponse:
		"""Execute a skill with the provided parameters. Auto-initializes if not already initialized.

		Parameters are validated against the skill's Pydantic schema before execution.

		Args:
			skill_id: The UUID of the skill to execute
			parameters: Either a dictionary or BaseModel instance matching the skill's parameter schema

		Returns:
			ExecuteSkillResponse with execution results

		Raises:
			ValueError: If skill not found in cache or parameter validation fails
			Exception: If API call fails
		"""
		# Auto-initialize if needed
		if not self._initialized:
			await self.async_init()

		assert self._client is not None, 'Client not initialized'

		# Check if skill exists in cache
		skill = await self.get_skill(skill_id)
		if skill is None:
			raise ValueError(f'Skill {skill_id} not found in cache. Available skills: {list(self._skills.keys())}')

		# Get the skill's pydantic model for parameter validation
		ParameterModel = skill.parameters_pydantic

		# Validate and convert parameters to dict
		validated_params_dict: dict[str, Any]

		try:
			if isinstance(parameters, BaseModel):
				# Already a pydantic model - validate it matches the skill's schema
				# by converting to dict and re-validating with the skill's model
				params_dict = parameters.model_dump()
				validated_model = ParameterModel(**params_dict)
				validated_params_dict = validated_model.model_dump()
			else:
				# Dict provided - validate with the skill's pydantic model
				validated_model = ParameterModel(**parameters)
				validated_params_dict = validated_model.model_dump()

		except ValidationError as e:
			# Pydantic validation failed
			error_msg = f'Parameter validation failed for skill {skill.title}:\n'
			for error in e.errors():
				field = '.'.join(str(x) for x in error['loc'])
				error_msg += f'  - {field}: {error["msg"]}\n'
			raise ValueError(error_msg) from e
		except Exception as e:
			raise ValueError(f'Failed to validate parameters for skill {skill.title}: {type(e).__name__}: {e}') from e

		# Execute skill via API
		try:
			logger.info(f'Executing skill: {skill.title} ({skill_id})')
			result: ExecuteSkillResponse = await self._client.skills.execute_skill(
				skill_id=skill_id, parameters=validated_params_dict
			)

			if result.success:
				logger.info(f'Skill {skill.title} executed successfully (latency: {result.latency_ms}ms)')
			else:
				logger.error(f'Skill {skill.title} execution failed: {result.error}')

			return result

		except Exception as e:
			logger.error(f'Error executing skill {skill_id}: {type(e).__name__}: {e}')
			# Return error response
			return ExecuteSkillResponse(
				success=False,
				error=f'Failed to execute skill: {type(e).__name__}: {str(e)}',
			)

	async def close(self) -> None:
		"""Close the SDK client and cleanup resources"""
		if self._client is not None:
			# AsyncBrowserUse client cleanup if needed
			# The SDK doesn't currently have a close method, but we set to None for cleanup
			self._client = None
		self._initialized = False
