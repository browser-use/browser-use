import logging
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.skills.views import Skill
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools


class AgentSkillMixin:
	skill_service: Any | None
	_skills_registered: bool
	tools: Tools[Any]
	browser_session: BrowserSession
	initial_actions: list[ActionModel] | None
	logger: logging.Logger
	_setup_action_models: Callable[[], None]
	_convert_initial_actions: Callable[[list[dict[str, dict[str, Any]]]], list[ActionModel]]

	def _get_skill_slug(self, skill: Skill, all_skills: list[Skill]) -> str:
		"""Generate a clean slug from skill title for action names

		Converts title to lowercase, removes special characters, replaces spaces with underscores.
		Adds UUID suffix if there are duplicate slugs.

		Args:
			skill: The skill to get slug for
			all_skills: List of all skills to check for duplicates

		Returns:
			Slug like "cloned_github_stars_tracker" or "get_weather_data_a1b2" if duplicate

		Examples:
			"[Cloned] Github Stars Tracker" -> "cloned_github_stars_tracker"
			"Get Weather Data" -> "get_weather_data"
		"""
		# Remove special characters and convert to lowercase
		slug = re.sub(r'[^\w\s]', '', skill.title.lower())
		# Replace whitespace and hyphens with underscores
		slug = re.sub(r'[\s\-]+', '_', slug)
		# Remove leading/trailing underscores
		slug = slug.strip('_')

		# Check for duplicates and add UUID suffix if needed
		same_slug_count = sum(
			1 for s in all_skills if re.sub(r'[\s\-]+', '_', re.sub(r'[^\w\s]', '', s.title.lower()).strip('_')) == slug
		)
		if same_slug_count > 1:
			return f'{slug}_{skill.id[:4]}'
		else:
			return slug

	async def _register_skills_as_actions(self) -> None:
		"""Register each skill as a separate action using slug as action name"""
		if not self.skill_service or self._skills_registered:
			return

		self.logger.info('🔧 Registering skill actions...')

		# Fetch all skills (auto-initializes if needed)
		skills = await self.skill_service.get_all_skills()

		if not skills:
			self.logger.warning('No skills loaded from SkillService')
			return

		# Register each skill as its own action
		for skill in skills:
			slug = self._get_skill_slug(skill, skills)
			param_model = skill.parameters_pydantic(exclude_cookies=True)

			# Create description with skill title in quotes
			description = f'{skill.description} (Skill: "{skill.title}")'

			# Create handler for this specific skill
			def make_skill_handler(skill_id: str):
				async def skill_handler(params: BaseModel) -> ActionResult:
					"""Execute a specific skill"""
					assert self.skill_service is not None, 'SkillService not initialized'

					# Convert parameters to dict
					if isinstance(params, BaseModel):
						skill_params = params.model_dump()
					elif isinstance(params, dict):
						skill_params = params
					else:
						return ActionResult(extracted_content=None, error=f'Invalid parameters type: {type(params)}')

					# Get cookies from browser
					_cookies = await self.browser_session.cookies()

					try:
						result = await self.skill_service.execute_skill(
							skill_id=skill_id, parameters=skill_params, cookies=_cookies
						)

						if result.success:
							return ActionResult(
								extracted_content=str(result.result) if result.result else None,
								error=None,
							)
						else:
							return ActionResult(extracted_content=None, error=result.error or 'Skill execution failed')
					except Exception as e:
						# Check if it's a MissingCookieException
						if type(e).__name__ == 'MissingCookieException':
							# Format: "Missing cookies (name): description"
							cookie_name = getattr(e, 'cookie_name', 'unknown')
							cookie_description = getattr(e, 'cookie_description', str(e))
							error_msg = f'Missing cookies ({cookie_name}): {cookie_description}'
							return ActionResult(extracted_content=None, error=error_msg)
						return ActionResult(extracted_content=None, error=f'Skill execution error: {type(e).__name__}: {e}')

				return skill_handler

			# Create the handler for this skill
			handler = make_skill_handler(skill.id)
			handler.__name__ = slug

			# Register the action with the slug as the action name
			self.tools.registry.action(description=description, param_model=param_model)(handler)

		# Mark as registered
		self._skills_registered = True

		# Rebuild action models to include the new skill actions
		self._setup_action_models()

		# Reconvert initial actions with the new ActionModel type if they exist
		if self.initial_actions:
			# Convert back to dict form first
			initial_actions_dict = []
			for action in self.initial_actions:
				action_dump = action.model_dump(exclude_unset=True)
				initial_actions_dict.append(action_dump)
			# Reconvert using new ActionModel
			self.initial_actions = self._convert_initial_actions(initial_actions_dict)

		self.logger.info(f'✓ Registered {len(skills)} skill actions')

	async def _get_unavailable_skills_info(self) -> str:
		"""Get information about skills that are unavailable due to missing cookies

		Returns:
			Formatted string describing unavailable skills and how to make them available
		"""
		if not self.skill_service:
			return ''

		try:
			# Get all skills
			skills = await self.skill_service.get_all_skills()
			if not skills:
				return ''

			# Get current cookies
			current_cookies = await self.browser_session.cookies()
			cookie_dict = {cookie['name']: cookie['value'] for cookie in current_cookies}

			# Check each skill for missing required cookies
			unavailable_skills: list[dict[str, Any]] = []

			for skill in skills:
				# Get cookie parameters for this skill
				cookie_params = [p for p in skill.parameters if p.type == 'cookie']

				if not cookie_params:
					# No cookies needed, skip
					continue

				# Check for missing required cookies
				missing_cookies: list[dict[str, str]] = []
				for cookie_param in cookie_params:
					is_required = cookie_param.required if cookie_param.required is not None else True

					if is_required and cookie_param.name not in cookie_dict:
						missing_cookies.append(
							{'name': cookie_param.name, 'description': cookie_param.description or 'No description provided'}
						)

				if missing_cookies:
					unavailable_skills.append(
						{
							'id': skill.id,
							'title': skill.title,
							'description': skill.description,
							'missing_cookies': missing_cookies,
						}
					)

			if not unavailable_skills:
				return ''

			# Format the unavailable skills info with slugs
			lines = ['Unavailable Skills (missing required cookies):']
			for skill_info in unavailable_skills:
				# Get the full skill object to use the slug helper
				skill_obj = next((s for s in skills if s.id == skill_info['id']), None)
				slug = self._get_skill_slug(skill_obj, skills) if skill_obj else skill_info['title']
				title = skill_info['title']

				lines.append(f'\n  • {slug} ("{title}")')
				lines.append(f'    Description: {skill_info["description"]}')
				lines.append('    Missing cookies:')
				for cookie in skill_info['missing_cookies']:
					lines.append(f'      - {cookie["name"]}: {cookie["description"]}')

			return '\n'.join(lines)

		except Exception as e:
			self.logger.error(f'Error getting unavailable skills info: {type(e).__name__}: {e}')
			return ''
