"""Agent setup and configuration helpers."""

import json
import logging
from pathlib import Path
from typing import Any

from browser_use import BrowserProfile, BrowserSession
from browser_use.agent.runtime.model_context import ModelContextManager
from browser_use.agent.views import AgentOutput, AgentSettings, AgentStructuredOutput
from browser_use.config import CONFIG
from browser_use.tools.service import Tools
from browser_use.utils import get_browser_use_version


class AgentConfigurationMixin:
	browser_session: BrowserSession | None
	llm: Any
	settings: AgentSettings
	source: str
	task_id: str | None
	tools: Tools[Any]
	version: str
	_using_fallback_llm: bool
	_message_manager: ModelContextManager

	def _enhance_task_with_schema(self, task: str, output_model_schema: type[AgentStructuredOutput] | None) -> str:
		"""Enhance task description with output schema information if provided."""
		if output_model_schema is None:
			return task

		try:
			schema = output_model_schema.model_json_schema()
			schema_json = json.dumps(schema, indent=2)
			enhancement = f'\nExpected output format: {output_model_schema.__name__}\n{schema_json}'
			return task + enhancement
		except Exception as e:
			self.logger.debug(f'Could not parse output schema: {e}')

		return task

	@property
	def logger(self) -> logging.Logger:
		"""Get instance-specific logger with task ID in the name."""
		_task_id = task_id[-4:] if (task_id := getattr(self, 'task_id', None)) else '----'
		_browser_session_id = browser_session.id[-4:] if (browser_session := getattr(self, 'browser_session', None)) else '----'
		_current_target_id = (
			browser_session.agent_focus_target_id[-2:]
			if (browser_session := getattr(self, 'browser_session', None)) and browser_session.agent_focus_target_id
			else '--'
		)
		return logging.getLogger(f'browser_use.Agent🅰 {_task_id} ⇢ 🅑 {_browser_session_id} 🅣 {_current_target_id}')

	@property
	def browser_profile(self) -> BrowserProfile:
		assert self.browser_session is not None, 'BrowserSession is not set up'
		return self.browser_session.browser_profile

	@property
	def is_using_fallback_llm(self) -> bool:
		"""Check if the agent is currently using the fallback LLM."""
		return self._using_fallback_llm

	@property
	def current_llm_model(self) -> str:
		"""Get the model name of the currently active LLM."""
		return self.llm.model if hasattr(self.llm, 'model') else 'unknown'

	def _set_browser_use_version_and_source(self, source_override: str | None = None) -> None:
		"""Get the package version and source."""
		version = get_browser_use_version()

		try:
			package_root = Path(__file__).parent.parent.parent
			repo_files = ['.git', 'README.md', 'docs', 'examples']
			if all(Path(package_root / file).exists() for file in repo_files):
				source = 'git'
			else:
				source = 'pip'
		except Exception as e:
			self.logger.debug(f'Error determining source: {e}')
			source = 'unknown'

		if source_override is not None:
			source = source_override
		self.version = version
		self.source = source

	def _setup_action_models(self) -> None:
		"""Setup dynamic action models from tools registry."""
		self.ActionModel = self.tools.registry.create_action_model()
		if self.settings.flash_mode:
			self.AgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.ActionModel)
		elif self.settings.use_thinking:
			self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)
		else:
			self.AgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.ActionModel)

		self.DoneActionModel = self.tools.registry.create_action_model(include_actions=['done'])
		if self.settings.flash_mode:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.DoneActionModel)
		elif self.settings.use_thinking:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions(self.DoneActionModel)
		else:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.DoneActionModel)

	def _verify_and_setup_llm(self) -> bool | None:
		"""Verify that the LLM API keys are set up when verification is enabled."""
		if getattr(self.llm, '_verified_api_keys', None) is True or CONFIG.SKIP_LLM_API_KEY_VERIFICATION:
			setattr(self.llm, '_verified_api_keys', True)
			return True
		return None

	@property
	def message_manager(self) -> ModelContextManager:
		return self._message_manager

	async def _update_action_models_for_page(self, page_url: str) -> None:
		"""Update action models with page-specific actions."""
		self.ActionModel = self.tools.registry.create_action_model(page_url=page_url)
		if self.settings.flash_mode:
			self.AgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.ActionModel)
		elif self.settings.use_thinking:
			self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)
		else:
			self.AgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.ActionModel)

		self.DoneActionModel = self.tools.registry.create_action_model(include_actions=['done'], page_url=page_url)
		if self.settings.flash_mode:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.DoneActionModel)
		elif self.settings.use_thinking:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions(self.DoneActionModel)
		else:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.DoneActionModel)
