"""Skills service for fetching and executing skills from the Browser Use API"""

import logging
import os
from typing import Any, Literal

from browser_use_sdk import AsyncBrowserUse
from browser_use_sdk.types.execute_skill_response import ExecuteSkillResponse
from browser_use_sdk.types.skill_list_response import SkillListResponse
from cdp_use.cdp.network import Cookie
from pydantic import BaseModel, ValidationError

from browser_use.skills.views import (
	MissingCookieException,
	Skill,
)

logger = logging.getLogger(__name__)


class SkillService:
	"""Service for managing and executing skills from the Browser Use API"""

	def __init__(self, skill_ids: list[str | Literal['*']], api_key: str | None = None):
		"""Initialize the skills service

		Args:
			skill_ids: List of skill IDs to fetch and cache, or ['*'] to fetch all available skills
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
		"""Async initialization to fetch all skills at once

		This should be called after __init__ to fetch and cache all skills.
		Fetches all available skills in one API call and filters based on skill_ids.
		"""
		if self._initialized:
			logger.debug('SkillService already initialized')
			return

		# Create the SDK client
		self._client = AsyncBrowserUse(api_key=self.api_key)

		try:
			# Fetch skills from API
			logger.info('Fetching skills from Browser Use API...')
			use_wildcard = '*' in self.skill_ids
			page_size = 100
			requested_ids: set[str] = set() if use_wildcard else {s for s in self.skill_ids if s != '*'}

			if use_wildcard:
				# Wildcard: fetch only first page (max 100 skills) to avoid LLM tool overload
				skills_response: SkillListResponse = await self._client.skills.list_skills(
					page_size=page_size,
					page_number=1,
					is_enabled=True,
				)
				all_items = list(skills_response.items)

				if len(all_items) >= page_size:
					logger.warning(
						f'Wildcard "*" limited to first {page_size} skills. '
						f'Specify explicit skill IDs if you need specific skills beyond this limit.'
					)

				logger.debug(f'Fetched {len(all_items)} skills (wildcard mode, single page)')
			else:
				# Explicit IDs: paginate until all requested IDs found
				all_items = []
				page = 1
				max_pages = 5  # Safety limit

				while page <= max_pages:
					skills_response = await self._client.skills.list_skills(
						page_size=page_size,
						page_number=page,
						is_enabled=True,
					)
					all_items.extend(skills_response.items)

					# Check if we've found all requested skills
					found_ids = {s.id for s in all_items if s.id in requested_ids}
					if found_ids == requested_ids:
						break

					# Stop if we got fewer items than page_size (last page)
					if len(skills_response.items) < page_size:
						break
					page += 1

				if page > max_pages:
					logger.warning(f'Reached pagination limit ({max_pages} pages) before finding all requested skills')

				logger.debug(f'Fetched {len(all_items)} skills across {page} page(s)')

			# Filter to only finished skills (is_enabled already filtered by API)
			all_available_skills = [skill for skill in all_items if skill.status == 'finished']

			logger.info(f'Found {len(all_available_skills)} available skills from API')

			# Determine which skills to load
			if use_wildcard:
				logger.info('Wildcard "*" detected, loading first 100 skills')
				skills_to_load = all_available_skills
			else:
				# Load only the requested skill IDs
				skills_to_load = [skill for skill in all_available_skills if skill.id in requested_ids]

				# Warn about any requested skills that weren't found
				found_ids = {skill.id for skill in skills_to_load}
				missing_ids = requested_ids - found_ids
				if missing_ids:
					logger.warning(f'Requested skills not found or not available: {missing_ids}')

			# Convert SDK SkillResponse objects to our Skill models and cache them
			for skill_response in skills_to_load:
				try:
					skill = Skill.from_skill_response(skill_response)
					self._skills[skill.id] = skill
					logger.debug(f'Cached skill: {skill.title} ({skill.id})')
				except Exception as e:
					logger.error(f'Failed to convert skill {skill_response.id}: {type(e).__name__}: {e}')

			logger.info(f'Successfully loaded {len(self._skills)} skills')
			self._initialized = True

		except Exception as e:
			logger.error(f'Error during skill initialization: {type(e).__name__}: {e}')
			self._initialized = True  # Mark as initialized even on failure to avoid retry loops
			raise

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

	async def execute_skill(
		self, skill_id: str, parameters: dict[str, Any] | BaseModel, cookies: list[Cookie]
	) -> ExecuteSkillResponse:
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

		# Extract cookie parameters from the skill
		cookie_params = [p for p in skill.parameters if p.type == 'cookie']

		# Build a dict of cookies from the provided cookie list
		cookie_dict: dict[str, str] = {cookie['name']: cookie['value'] for cookie in cookies}

		# Check for missing required cookies and fill cookie values
		if cookie_params:
			for cookie_param in cookie_params:
				is_required = cookie_param.required if cookie_param.required is not None else True

				if is_required and cookie_param.name not in cookie_dict:
					# Required cookie is missing - raise exception with description
					raise MissingCookieException(
						cookie_name=cookie_param.name, cookie_description=cookie_param.description or 'No description provided'
					)

			# Fill in cookie values into parameters
			# Convert parameters to dict first if it's a BaseModel
			if isinstance(parameters, BaseModel):
				params_dict = parameters.model_dump()
			else:
				params_dict = dict(parameters)

			# Add cookie values to parameters
			for cookie_param in cookie_params:
				if cookie_param.name in cookie_dict:
					params_dict[cookie_param.name] = cookie_dict[cookie_param.name]

			# Replace parameters with the updated dict
			parameters = params_dict

		# Get the skill's pydantic model for parameter validation
		ParameterModel = skill.parameters_pydantic(exclude_cookies=False)

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
