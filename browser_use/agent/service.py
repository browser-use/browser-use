import asyncio
import gc
import inspect
import json
import logging
import re
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar
from urllib.parse import urlparse

from dotenv import load_dotenv

from browser_use.agent.cloud_events import (
	CreateAgentOutputFileEvent,
	CreateAgentSessionEvent,
	CreateAgentStepEvent,
	CreateAgentTaskEvent,
	UpdateAgentTaskEvent,
)
from browser_use.agent.message_manager.utils import save_conversation
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import BaseMessage, UserMessage
from browser_use.tokens.service import TokenCost

load_dotenv()

from bubus import EventBus
from pydantic import ValidationError
from uuid_extensions import uuid7str

# Lazy import for gif to avoid heavy agent.views import at startup
# from browser_use.agent.gif import create_history_gif
from browser_use.agent.message_manager.service import (
	MessageManager,
)
from browser_use.agent.prompts import SystemPrompt
from browser_use.agent.views import (
	ActionResult,
	AgentError,
	AgentHistory,
	AgentHistoryList,
	AgentOutput,
	AgentSettings,
	AgentState,
	AgentStepInfo,
	AgentStructuredOutput,
	BrowserStateHistory,
	StepMetadata,
)
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.session import DEFAULT_BROWSER_PROFILE
from browser_use.browser.views import BrowserStateSummary
from browser_use.config import CONFIG
from browser_use.controller.registry.views import ActionModel
from browser_use.controller.service import Controller
from browser_use.dom.views import DOMInteractedElement
from browser_use.filesystem.file_system import FileSystem
from browser_use.observability import observe, observe_debug
from browser_use.sync import CloudSync
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import AgentTelemetryEvent
from browser_use.utils import (
	_log_pretty_path,
	get_browser_use_version,
	get_git_info,
	time_execution_async,
	time_execution_sync,
)

logger = logging.getLogger(__name__)


def log_response(response: AgentOutput, registry=None, logger=None) -> None:
	"""Utility function to log the model's response."""

	# Use module logger if no logger provided
	if logger is None:
		logger = logging.getLogger(__name__)

	# Only log thinking if it's present
	if response.current_state.thinking:
		logger.info(f'💡 Thinking:\n{response.current_state.thinking}')

	# Only log evaluation if it's not empty
	eval_goal = response.current_state.evaluation_previous_goal
	if eval_goal:
		if 'success' in eval_goal.lower():
			emoji = '👍'
		elif 'failure' in eval_goal.lower():
			emoji = '⚠️'
		else:
			emoji = '❔'
		logger.info(f'{emoji} Eval: {eval_goal}')

	# Always log memory if present
	if response.current_state.memory:
		logger.info(f'🧠 Memory: {response.current_state.memory}')

	# Only log next goal if it's not empty
	next_goal = response.current_state.next_goal
	if next_goal:
		logger.info(f'🎯 Next goal: {next_goal}\n')
	else:
		logger.info('')  # Add empty line for spacing


Context = TypeVar('Context')


AgentHookFunc = Callable[['Agent'], Awaitable[None]]


class Agent(Generic[Context, AgentStructuredOutput]):
	browser_session: BrowserSession | None = None
	_logger: logging.Logger | None = None

	@time_execution_sync('--init')
	def __init__(
		self,
		task: str,
		llm: BaseChatModel,
		# Optional parameters
		browser_profile: BrowserProfile | None = None,
		browser_session: BrowserSession | None = None,
		controller: Controller[Context] | None = None,
		# Initial agent run parameters
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		initial_actions: list[dict[str, dict[str, Any]]] | None = None,
		# Cloud Callbacks
		register_new_step_callback: (
			Callable[['BrowserStateSummary', 'AgentOutput', int], None]  # Sync callback
			| Callable[['BrowserStateSummary', 'AgentOutput', int], Awaitable[None]]  # Async callback
			| None
		) = None,
		register_done_callback: (
			Callable[['AgentHistoryList'], Awaitable[None]]  # Async Callback
			| Callable[['AgentHistoryList'], None]  # Sync Callback
			| None
		) = None,
		register_external_agent_status_raise_error_callback: Callable[[], Awaitable[bool]] | None = None,
		# Agent settings
		output_model_schema: type[AgentStructuredOutput] | None = None,
		use_vision: bool = True,
		use_vision_for_planner: bool = False,  # Deprecated
		save_conversation_path: str | Path | None = None,
		save_conversation_path_encoding: str | None = 'utf-8',
		max_failures: int = 3,
		retry_delay: int = 10,
		override_system_message: str | None = None,
		extend_system_message: str | None = None,
		validate_output: bool = False,
		generate_gif: bool | str = False,
		available_file_paths: list[str] | None = None,
		include_attributes: list[str] | None = None,
		max_actions_per_step: int = 10,
		use_thinking: bool = True,
		flash_mode: bool = False,
		max_history_items: int | None = None,
		page_extraction_llm: BaseChatModel | None = None,
		planner_llm: BaseChatModel | None = None,  # Deprecated
		planner_interval: int = 1,  # Deprecated
		is_planner_reasoning: bool = False,  # Deprecated
		extend_planner_system_message: str | None = None,  # Deprecated
		injected_agent_state: AgentState | None = None,
		context: Context | None = None,
		source: str | None = None,
		file_system_path: str | None = None,
		task_id: str | None = None,
		cloud_sync: CloudSync | None = None,
		calculate_cost: bool = False,
		display_files_in_done_text: bool = True,
		include_tool_call_examples: bool = False,
		vision_detail_level: Literal['auto', 'low', 'high'] = 'auto',
		llm_timeout: int = 60,
		step_timeout: int = 120,
		preload: bool = True,
		include_recent_events: bool = False,
		**kwargs,
	):
		if not isinstance(llm, BaseChatModel):
			raise ValueError('invalid llm, must be from browser_use.llm')
		# Check for deprecated planner parameters
		planner_params = [
			planner_llm,
			use_vision_for_planner,
			is_planner_reasoning,
			extend_planner_system_message,
		]
		if any(param is not None and param is not False for param in planner_params) or planner_interval != 1:
			logger.warning(
				'⚠️ Planner functionality has been removed in browser-use v0.3.3+. '
				'The planner_llm, use_vision_for_planner, planner_interval, is_planner_reasoning, '
				'and extend_planner_system_message parameters are deprecated and will be ignored. '
				'Please remove these parameters from your Agent() initialization.'
			)

		# Check for deprecated memory parameters
		if kwargs.get('enable_memory', False) or kwargs.get('memory_config') is not None:
			logger.warning(
				'Memory support has been removed as of version 0.3.2. '
				'The agent context for memory is significantly improved and no longer requires the old memory system. '
				"Please remove the 'enable_memory' and 'memory_config' parameters."
			)
			kwargs['enable_memory'] = False
			kwargs['memory_config'] = None

		if page_extraction_llm is None:
			page_extraction_llm = llm
		if available_file_paths is None:
			available_file_paths = []

		self.id = task_id or uuid7str()
		self.task_id: str = self.id
		self.session_id: str = uuid7str()

		# Initialize available file paths as direct attribute
		self.available_file_paths = available_file_paths

		# Create instance-specific logger
		self._logger = logging.getLogger(f'browser_use.Agent[{self.task_id[-3:]}]')

		# Core components
		self.task = task
		self.llm = llm
		self.preload = preload
		self.include_recent_events = include_recent_events
		self.controller = (
			controller if controller is not None else Controller(display_files_in_done_text=display_files_in_done_text)
		)

		# Structured output
		self.output_model_schema = output_model_schema
		if self.output_model_schema is not None:
			self.controller.use_structured_output_action(self.output_model_schema)

		self.sensitive_data = sensitive_data

		self.settings = AgentSettings(
			use_vision=use_vision,
			vision_detail_level=vision_detail_level,
			use_vision_for_planner=False,  # Always False now (deprecated)
			save_conversation_path=save_conversation_path,
			save_conversation_path_encoding=save_conversation_path_encoding,
			max_failures=max_failures,
			retry_delay=retry_delay,
			override_system_message=override_system_message,
			extend_system_message=extend_system_message,
			validate_output=validate_output,
			generate_gif=generate_gif,
			include_attributes=include_attributes,
			max_actions_per_step=max_actions_per_step,
			use_thinking=use_thinking,
			flash_mode=flash_mode,
			max_history_items=max_history_items,
			page_extraction_llm=page_extraction_llm,
			planner_llm=None,  # Always None now (deprecated)
			planner_interval=1,  # Always 1 now (deprecated)
			is_planner_reasoning=False,  # Always False now (deprecated)
			extend_planner_system_message=None,  # Always None now (deprecated)
			calculate_cost=calculate_cost,
			include_tool_call_examples=include_tool_call_examples,
			llm_timeout=llm_timeout,
			step_timeout=step_timeout,
		)

		# Token cost service
		self.token_cost_service = TokenCost(include_cost=calculate_cost)
		self.token_cost_service.register_llm(llm)
		self.token_cost_service.register_llm(page_extraction_llm)
		# Note: No longer registering planner_llm (deprecated)

		# Initialize state
		self.state = injected_agent_state or AgentState()

		# Initialize history
		self.history = AgentHistoryList(history=[], usage=None)

		# Initialize agent directory
		import time

		timestamp = int(time.time())
		base_tmp = Path(tempfile.gettempdir())
		self.agent_directory = base_tmp / f'browser_use_agent_{self.id}_{timestamp}'

		# Initialize file system and screenshot service
		self._set_file_system(file_system_path)
		self._set_screenshot_service()

		# Action setup
		self._setup_action_models()
		self._set_browser_use_version_and_source(source)
		self.initial_actions = self._convert_initial_actions(initial_actions) if initial_actions else None

		# Verify we can connect to the model
		self._verify_and_setup_llm()

		# TODO: move this logic to the LLMs
		# Handle users trying to use use_vision=True with DeepSeek models
		if 'deepseek' in self.llm.model.lower():
			self.logger.warning('⚠️ DeepSeek models do not support use_vision=True yet. Setting use_vision=False for now...')
			self.settings.use_vision = False
		# Note: No longer checking planner_llm for DeepSeek (deprecated)

		# Handle users trying to use use_vision=True with XAI models
		if 'grok' in self.llm.model.lower():
			self.logger.warning('⚠️ XAI models do not support use_vision=True yet. Setting use_vision=False for now...')
			self.settings.use_vision = False
		# Note: No longer checking planner_llm for XAI models (deprecated)

		self.logger.info(
			f'🧠 Starting a browser-use agent {self.version} with base_model={self.llm.model}'
			f'{" +vision" if self.settings.use_vision else ""}'
			f' extraction_model={self.settings.page_extraction_llm.model if self.settings.page_extraction_llm else "Unknown"}'
			# Note: No longer logging planner_model (deprecated)
			f'{" +file_system" if self.file_system else ""}'
		)

		# Initialize available actions for system prompt (only non-filtered actions)
		# These will be used for the system prompt to maintain caching
		self.unfiltered_actions = self.controller.registry.get_prompt_description()

		# Initialize message manager with state
		# Initial system prompt with all actions - will be updated during each step
		self._message_manager = MessageManager(
			task=task,
			system_message=SystemPrompt(
				action_description=self.unfiltered_actions,
				max_actions_per_step=self.settings.max_actions_per_step,
				override_system_message=override_system_message,
				extend_system_message=extend_system_message,
				use_thinking=self.settings.use_thinking,
				flash_mode=self.settings.flash_mode,
			).get_system_message(),
			file_system=self.file_system,
			state=self.state.message_manager_state,
			use_thinking=self.settings.use_thinking,
			# Settings that were previously in MessageManagerSettings
			include_attributes=self.settings.include_attributes,
			sensitive_data=sensitive_data,
			max_history_items=self.settings.max_history_items,
			vision_detail_level=self.settings.vision_detail_level,
			include_tool_call_examples=self.settings.include_tool_call_examples,
			include_recent_events=self.include_recent_events,
		)

		browser_profile = browser_profile or DEFAULT_BROWSER_PROFILE

		self.browser_session = browser_session or BrowserSession(
			browser_profile=browser_profile,
			id=uuid7str()[:-4] + self.id[-4:],  # re-use the same 4-char suffix so they show up together in logs
		)

		if self.sensitive_data:
			# Check if sensitive_data has domain-specific credentials
			has_domain_specific_credentials = any(isinstance(v, dict) for v in self.sensitive_data.values())

			# If no allowed_domains are configured, show a security warning
			if not self.browser_profile.allowed_domains:
				self.logger.error(
					'⚠️⚠️⚠️ Agent(sensitive_data=••••••••) was provided but BrowserSession(allowed_domains=[...]) is not locked down! ⚠️⚠️⚠️\n'
					'          ☠️ If the agent visits a malicious website and encounters a prompt-injection attack, your sensitive_data may be exposed!\n\n'
					'             https://docs.browser-use.com/customize/browser-settings#restrict-urls\n'
					'Waiting 10 seconds before continuing... Press [Ctrl+C] to abort.'
				)
				if sys.stdin.isatty():
					try:
						time.sleep(10)
					except KeyboardInterrupt:
						print(
							'\n\n 🛑 Exiting now... set BrowserSession(allowed_domains=["example.com", "example.org"]) to only domains you trust to see your sensitive_data.'
						)
						sys.exit(0)
				else:
					pass  # no point waiting if we're not in an interactive shell
				self.logger.warning(
					'‼️ Continuing with insecure settings for now... but this will become a hard error in the future!'
				)

			# If we're using domain-specific credentials, validate domain patterns
			elif has_domain_specific_credentials:
				# For domain-specific format, ensure all domain patterns are included in allowed_domains
				domain_patterns = [k for k, v in self.sensitive_data.items() if isinstance(v, dict)]

				# Validate each domain pattern against allowed_domains
				for domain_pattern in domain_patterns:
					is_allowed = False
					for allowed_domain in self.browser_profile.allowed_domains:
						# Special cases that don't require URL matching
						if domain_pattern == allowed_domain or allowed_domain == '*':
							is_allowed = True
							break

						# Need to create example URLs to compare the patterns
						# Extract the domain parts, ignoring scheme
						pattern_domain = domain_pattern.split('://')[-1] if '://' in domain_pattern else domain_pattern
						allowed_domain_part = allowed_domain.split('://')[-1] if '://' in allowed_domain else allowed_domain

						# Check if pattern is covered by an allowed domain
						# Example: "google.com" is covered by "*.google.com"
						if pattern_domain == allowed_domain_part or (
							allowed_domain_part.startswith('*.')
							and (
								pattern_domain == allowed_domain_part[2:]
								or pattern_domain.endswith('.' + allowed_domain_part[2:])
							)
						):
							is_allowed = True
							break

					if not is_allowed:
						self.logger.warning(
							f'⚠️ Domain pattern "{domain_pattern}" in sensitive_data is not covered by any pattern in allowed_domains={self.browser_profile.allowed_domains}\n'
							f'   This may be a security risk as credentials could be used on unintended domains.'
						)

		# Callbacks
		self.register_new_step_callback = register_new_step_callback
		self.register_done_callback = register_done_callback
		self.register_external_agent_status_raise_error_callback = register_external_agent_status_raise_error_callback

		# Context
		self.context: Context | None = context

		# Telemetry
		self.telemetry = ProductTelemetry()

		# Event bus with WAL persistence
		# Default to ~/.config/browseruse/events/{agent_session_id}.jsonl
		# wal_path = CONFIG.BROWSER_USE_CONFIG_DIR / 'events' / f'{self.session_id}.jsonl'
		self.eventbus = EventBus(name=f'Agent_{str(self.id)[-4:]}')

		# Cloud sync service
		self.enable_cloud_sync = CONFIG.BROWSER_USE_CLOUD_SYNC
		if self.enable_cloud_sync or cloud_sync is not None:
			self.cloud_sync = cloud_sync or CloudSync()
			# Register cloud sync handler
			self.eventbus.on('*', self.cloud_sync.handle_event)

		if self.settings.save_conversation_path:
			self.settings.save_conversation_path = Path(self.settings.save_conversation_path).expanduser().resolve()
			self.logger.info(f'💬 Saving conversation to {_log_pretty_path(self.settings.save_conversation_path)}')

		# Initialize download tracking
		assert self.browser_session is not None, 'BrowserSession is not set up'
		self.has_downloads_path = self.browser_session.browser_profile.downloads_path is not None
		if self.has_downloads_path:
			self._last_known_downloads: list[str] = []
			self.logger.info('📁 Initialized download tracking for agent')

		self._external_pause_event = asyncio.Event()
		self._external_pause_event.set()

	@property
	def logger(self) -> logging.Logger:
		"""Get instance-specific logger with task ID in the name"""

		_browser_session_id = self.browser_session.id if self.browser_session else self.id
		_current_page_id = (
			self.browser_session.agent_focus.target_id[-2:]
			if self.browser_session and self.browser_session.agent_focus and self.browser_session.agent_focus.target_id
			else '--'
		)
		return logging.getLogger(f'browser_use.Agent🅰 {self.task_id[-4:]} on 🆂 {_browser_session_id[-4:]} 🅟 {_current_page_id}')

	@property
	def browser_profile(self) -> BrowserProfile:
		assert self.browser_session is not None, 'BrowserSession is not set up'
		return self.browser_session.browser_profile

	async def _check_and_update_downloads(self, context: str = '') -> None:
		"""Check for new downloads and update available file paths."""
		if not self.has_downloads_path:
			return

		assert self.browser_session is not None, 'BrowserSession is not set up'

		try:
			current_downloads = self.browser_session.downloaded_files
			if current_downloads != self._last_known_downloads:
				self._update_available_file_paths(current_downloads)
				self._last_known_downloads = current_downloads
				if context:
					self.logger.debug(f'📁 {context}: Updated available files')
		except Exception as e:
			error_context = f' {context}' if context else ''
			self.logger.debug(f'📁 Failed to check for downloads{error_context}: {type(e).__name__}: {e}')

	def _update_available_file_paths(self, downloads: list[str]) -> None:
		"""Update available_file_paths with downloaded files."""
		if not self.has_downloads_path:
			return

		current_files = set(self.available_file_paths or [])
		new_files = set(downloads) - current_files

		if new_files:
			self.available_file_paths = list(current_files | new_files)

			self.logger.info(
				f'📁 Added {len(new_files)} downloaded files to available_file_paths (total: {len(self.available_file_paths)} files)'
			)
			for file_path in new_files:
				self.logger.info(f'📄 New file available: {file_path}')
		else:
			self.logger.info(f'📁 No new downloads detected (tracking {len(current_files)} files)')

	def _set_file_system(self, file_system_path: str | None = None) -> None:
		# Check for conflicting parameters
		if self.state.file_system_state and file_system_path:
			raise ValueError(
				'Cannot provide both file_system_state (from agent state) and file_system_path. '
				'Either restore from existing state or create new file system at specified path, not both.'
			)

		# Check if we should restore from existing state first
		if self.state.file_system_state:
			try:
				# Restore file system from state at the exact same location
				self.file_system = FileSystem.from_state(self.state.file_system_state)
				# The parent directory of base_dir is the original file_system_path
				self.file_system_path = str(self.file_system.base_dir)
				logger.info(f'💾 File system restored from state to: {self.file_system_path}')
				return
			except Exception as e:
				logger.error(f'💾 Failed to restore file system from state: {e}')
				raise e

		# Initialize new file system
		try:
			if file_system_path:
				self.file_system = FileSystem(file_system_path)
				self.file_system_path = file_system_path
			else:
				# Use the agent directory for file system
				self.file_system = FileSystem(self.agent_directory)
				self.file_system_path = str(self.agent_directory)
		except Exception as e:
			logger.error(f'💾 Failed to initialize file system: {e}.')
			raise e

		# Save file system state to agent state
		self.state.file_system_state = self.file_system.get_state()

		logger.info(f'💾 File system path: {self.file_system_path}')

	def _set_screenshot_service(self) -> None:
		"""Initialize screenshot service using agent directory"""
		try:
			from browser_use.screenshots.service import ScreenshotService

			self.screenshot_service = ScreenshotService(self.agent_directory)
			logger.info(f'📸 Screenshot service initialized in: {self.agent_directory}/screenshots')
		except Exception as e:
			logger.error(f'📸 Failed to initialize screenshot service: {e}.')
			raise e

	def save_file_system_state(self) -> None:
		"""Save current file system state to agent state"""
		if self.file_system:
			self.state.file_system_state = self.file_system.get_state()
		else:
			logger.error('💾 File system is not set up. Cannot save state.')
			raise ValueError('File system is not set up. Cannot save state.')

	def _set_browser_use_version_and_source(self, source_override: str | None = None) -> None:
		"""Get the version from pyproject.toml and determine the source of the browser-use package"""
		# Use the helper function for version detection
		version = get_browser_use_version()

		# Determine source
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
		# self.logger.debug(f'Version: {version}, Source: {source}')  # moved later to _log_agent_run so that people are more likely to include it in copy-pasted support ticket logs
		self.version = version
		self.source = source

	# def _set_model_names(self) -> None:
	# 	self.chat_model_library = self.llm.provider
	# 	self.model_name = self.llm.model

	# 	if self.settings.planner_llm:
	# 		if hasattr(self.settings.planner_llm, 'model_name'):
	# 			self.planner_model_name = self.settings.planner_llm.model_name  # type: ignore
	# 		elif hasattr(self.settings.planner_llm, 'model'):
	# 			self.planner_model_name = self.settings.planner_llm.model  # type: ignore
	# 		else:
	# 			self.planner_model_name = 'Unknown'
	# 	else:
	# 		self.planner_model_name = None

	def _setup_action_models(self) -> None:
		"""Setup dynamic action models from controller's registry"""
		# Initially only include actions with no filters
		self.ActionModel = self.controller.registry.create_action_model()
		# Create output model with the dynamic actions
		if self.settings.flash_mode:
			self.AgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.ActionModel)
		elif self.settings.use_thinking:
			self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)
		else:
			self.AgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.ActionModel)

		# used to force the done action when max_steps is reached
		self.DoneActionModel = self.controller.registry.create_action_model(include_actions=['done'])
		if self.settings.flash_mode:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.DoneActionModel)
		elif self.settings.use_thinking:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions(self.DoneActionModel)
		else:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.DoneActionModel)

	def add_new_task(self, new_task: str) -> None:
		"""Add a new task to the agent, keeping the same task_id as tasks are continuous"""
		# Simply delegate to message manager - no need for new task_id or events
		# The task continues with new instructions, it doesn't end and start a new one
		self.task = new_task
		self._message_manager.add_new_task(new_task)

	@observe_debug(ignore_input=True, ignore_output=True, name='_raise_if_stopped_or_paused')
	async def _raise_if_stopped_or_paused(self) -> None:
		"""Utility function that raises an InterruptedError if the agent is stopped or paused."""

		if self.register_external_agent_status_raise_error_callback:
			if await self.register_external_agent_status_raise_error_callback():
				raise InterruptedError

		if self.state.stopped or self.state.paused:
			# self.logger.debug('Agent paused after getting state')
			raise InterruptedError

	@observe(name='agent.step', ignore_output=True, ignore_input=True)
	@time_execution_async('--step')
	async def step(self, step_info: AgentStepInfo | None = None) -> None:
		"""Execute one step of the task"""
		# Initialize timing first, before any exceptions can occur
		self.step_start_time = time.time()

		browser_state_summary = None

		try:
			# Phase 1: Prepare context and timing
			browser_state_summary = await self._prepare_context(step_info)

			# Phase 2: Get model output and execute actions
			await self._get_next_action(browser_state_summary)
			await self._execute_actions()

			# Phase 3: Post-processing
			await self._post_process()

		except Exception as e:
			# Handle ALL exceptions in one place
			await self._handle_step_error(e)

		finally:
			await self._finalize(browser_state_summary)

	async def _prepare_context(self, step_info: AgentStepInfo | None = None) -> BrowserStateSummary:
		"""Prepare the context for the step: browser state, action models, page actions"""
		# step_start_time is now set in step() method

		assert self.browser_session is not None, 'BrowserSession is not set up'

		self.logger.debug(f'🌐 Step {self.state.n_steps}: Getting browser state...')
		# Always take screenshots for all steps
		# Use caching based on preload setting - if preload is False, don't use cached state
		is_first_step = self.state.n_steps in (0, 1)
		use_cache = is_first_step and self.preload
		self.logger.debug(f'📸 Requesting browser state with include_screenshot=True, cached={use_cache}')
		browser_state_summary = await self.browser_session.get_browser_state_summary(
			cache_clickable_elements_hashes=True,
			include_screenshot=True,  # always capture even if use_vision=False so that cloud sync is useful (it's fast now anyway)
			cached=use_cache,
			include_recent_events=self.include_recent_events,
		)
		if browser_state_summary.screenshot:
			self.logger.debug(f'📸 Got browser state WITH screenshot, length: {len(browser_state_summary.screenshot)}')
		else:
			self.logger.debug('📸 Got browser state WITHOUT screenshot')

		# Check for new downloads after getting browser state (catches PDF auto-downloads and previous step downloads)
		await self._check_and_update_downloads(f'Step {self.state.n_steps}: after getting browser state')

		self._log_step_context(browser_state_summary)
		await self._raise_if_stopped_or_paused()

		# Update action models with page-specific actions
		self.logger.debug(f'📝 Step {self.state.n_steps}: Updating action models...')
		await self._update_action_models_for_page(browser_state_summary.url)

		# Get page-specific filtered actions
		page_filtered_actions = self.controller.registry.get_prompt_description(browser_state_summary.url)

		# Page-specific actions will be included directly in the browser_state message
		self.logger.debug(f'💬 Step {self.state.n_steps}: Creating state messages for context...')
		self._message_manager.create_state_messages(
			browser_state_summary=browser_state_summary,
			model_output=self.state.last_model_output,
			result=self.state.last_result,
			step_info=step_info,
			use_vision=self.settings.use_vision,
			page_filtered_actions=page_filtered_actions if page_filtered_actions else None,
			sensitive_data=self.sensitive_data,
			available_file_paths=self.available_file_paths,  # Always pass current available_file_paths
		)

		await self._handle_final_step(step_info)
		return browser_state_summary

	@observe_debug(ignore_input=True, name='get_next_action')
	async def _get_next_action(self, browser_state_summary: BrowserStateSummary) -> None:
		"""Execute LLM interaction with retry logic and handle callbacks"""
		input_messages = self._message_manager.get_messages()
		self.logger.debug(
			f'🤖 Step {self.state.n_steps}: Calling LLM with {len(input_messages)} messages (model: {self.llm.model})...'
		)

		try:
			model_output = await asyncio.wait_for(
				self._get_model_output_with_retry(input_messages), timeout=self.settings.llm_timeout
			)
		except TimeoutError:

			@observe(name='_llm_call_timed_out_with_input')
			async def _log_model_input_to_lmnr(input_messages: list[BaseMessage]) -> None:
				"""Log the model input"""
				pass

			await _log_model_input_to_lmnr(input_messages)

			raise TimeoutError(
				f'LLM call timed out after {self.settings.llm_timeout} seconds. Keep your thinking and output short.'
			)

		self.state.last_model_output = model_output

		# Check again for paused/stopped state after getting model output
		await self._raise_if_stopped_or_paused()

		# Handle callbacks and conversation saving
		await self._handle_post_llm_processing(browser_state_summary, input_messages)

		# check again if Ctrl+C was pressed before we commit the output to history
		await self._raise_if_stopped_or_paused()

	async def _execute_actions(self) -> None:
		"""Execute the actions from model output"""
		if self.state.last_model_output is None:
			raise ValueError('No model output to execute actions from')

		self.logger.debug(f'⚡ Step {self.state.n_steps}: Executing {len(self.state.last_model_output.action)} actions...')
		result = await self.multi_act(self.state.last_model_output.action)
		self.logger.debug(f'✅ Step {self.state.n_steps}: Actions completed')

		self.state.last_result = result

	async def _post_process(self) -> None:
		"""Handle post-action processing like download tracking and result logging"""
		assert self.browser_session is not None, 'BrowserSession is not set up'

		# Check for new downloads after executing actions
		await self._check_and_update_downloads('after executing actions')

		# check for action errors  and len more than 1
		if self.state.last_result and len(self.state.last_result) == 1 and self.state.last_result[-1].error:
			self.state.consecutive_failures += 1
			self.logger.debug(f'🔄 Step {self.state.n_steps}: Consecutive failures: {self.state.consecutive_failures}')
			return

		self.state.consecutive_failures = 0
		self.logger.debug(f'🔄 Step {self.state.n_steps}: Consecutive failures reset to: {self.state.consecutive_failures}')

		# Log completion results
		if self.state.last_result and len(self.state.last_result) > 0 and self.state.last_result[-1].is_done:
			self.logger.info(f'📄 Result: {self.state.last_result[-1].extracted_content}')
			if self.state.last_result[-1].attachments:
				self.logger.info('📎 Click links below to access the attachments:')
				for file_path in self.state.last_result[-1].attachments:
					self.logger.info(f'👉 {file_path}')

	async def _handle_step_error(self, error: Exception) -> None:
		"""Handle all types of errors that can occur during a step"""

		# Handle all other exceptions
		include_trace = self.logger.isEnabledFor(logging.DEBUG)
		error_msg = AgentError.format_error(error, include_trace=include_trace)
		prefix = f'❌ Result failed {self.state.consecutive_failures + 1}/{self.settings.max_failures} times:\n '
		self.state.consecutive_failures += 1

		# TODO: figure out what to do here
		if isinstance(error, (ValidationError, ValueError)):
			self.logger.error(f'{prefix}{error_msg}')
			# Add context message to help model fix validation errors
			validation_hint = 'Your output format was invalid. Please follow the exact schema structure required for actions.'
			# self._message_manager._add_context_message(UserMessage(content=validation_hint))

			if 'Max token limit reached' in error_msg:
				token_hint = 'Your response was too long. Keep your thinking and output concise.'
				# self._message_manager._add_context_message(UserMessage(content=token_hint))
		# Handle InterruptedError specially
		elif isinstance(error, InterruptedError):
			error_msg = 'The agent was interrupted mid-step' + (f' - {error}' if error else '')
			self.logger.error(f'{prefix}{error_msg}')
		elif 'Could not parse response' in error_msg or 'tool_use_failed' in error_msg:
			# give model a hint how output should look like
			logger.debug(f'Model: {self.llm.model} failed')
			error_msg += '\n\nReturn a valid JSON object with the required fields.'
			logger.error(f'{prefix}{error_msg}')
			# Add context message to help model fix parsing errors
			parse_hint = 'Your response could not be parsed. Return a valid JSON object with the required fields.'
			# self._message_manager._add_context_message(UserMessage(content=parse_hint))
		else:
			from anthropic import RateLimitError as AnthropicRateLimitError
			from google.api_core.exceptions import ResourceExhausted
			from openai import RateLimitError

			# Define a tuple of rate limit error types for easier maintenance
			RATE_LIMIT_ERRORS = (
				RateLimitError,  # OpenAI
				ResourceExhausted,  # Google
				AnthropicRateLimitError,  # Anthropic
			)

			if isinstance(error, RATE_LIMIT_ERRORS) or 'on tokens per minute (TPM): Limit' in error_msg:
				logger.warning(f'{prefix}{error_msg}')
				await asyncio.sleep(self.settings.retry_delay)
			else:
				self.logger.error(f'{prefix}{error_msg}')

		self.state.last_result = [ActionResult(error=error_msg)]
		return None

	async def _finalize(self, browser_state_summary: BrowserStateSummary | None) -> None:
		"""Finalize the step with history, logging, and events"""
		step_end_time = time.time()
		if not self.state.last_result:
			return

		if browser_state_summary:
			metadata = StepMetadata(
				step_number=self.state.n_steps,
				step_start_time=self.step_start_time,
				step_end_time=step_end_time,
			)

			# Use _make_history_item like main branch
			await self._make_history_item(self.state.last_model_output, browser_state_summary, self.state.last_result, metadata)

		# Log step completion summary
		self._log_step_completion_summary(self.step_start_time, self.state.last_result)

		# Save file system state after step completion
		self.save_file_system_state()

		# Emit both step created and executed events
		if browser_state_summary and self.state.last_model_output:
			# Extract key step data for the event
			actions_data = []
			if self.state.last_model_output.action:
				for action in self.state.last_model_output.action:
					action_dict = action.model_dump() if hasattr(action, 'model_dump') else {}
					actions_data.append(action_dict)

			# Emit CreateAgentStepEvent
			step_event = CreateAgentStepEvent.from_agent_step(
				self,
				self.state.last_model_output,
				self.state.last_result,
				actions_data,
				browser_state_summary,
			)
			self.eventbus.dispatch(step_event)

		# Increment step counter after step is fully completed
		self.state.n_steps += 1

	async def _handle_final_step(self, step_info: AgentStepInfo | None = None) -> None:
		"""Handle special processing for the last step"""
		if step_info and step_info.is_last_step():
			# Add last step warning if needed
			msg = 'Now comes your last step. Use only the "done" action now. No other actions - so here your action sequence must have length 1.'
			msg += '\nIf the task is not yet fully finished as requested by the user, set success in "done" to false! E.g. if not all steps are fully completed.'
			msg += '\nIf the task is fully finished, set success in "done" to true.'
			msg += '\nInclude everything you found out for the ultimate task in the done text.'
			self.logger.info('Last step finishing up')
			self._message_manager._add_context_message(UserMessage(content=msg))
			self.AgentOutput = self.DoneAgentOutput

	async def _get_model_output_with_retry(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get model output with retry logic for empty actions"""
		model_output = await self.get_model_output(input_messages)
		self.logger.debug(
			f'✅ Step {self.state.n_steps}: Got LLM response with {len(model_output.action) if model_output.action else 0} actions'
		)

		if (
			not model_output.action
			or not isinstance(model_output.action, list)
			or all(action.model_dump() == {} for action in model_output.action)
		):
			self.logger.warning('Model returned empty action. Retrying...')

			clarification_message = UserMessage(
				content='You forgot to return an action. Please respond only with a valid JSON action according to the expected format.'
			)

			retry_messages = input_messages + [clarification_message]
			model_output = await self.get_model_output(retry_messages)

			if not model_output.action or all(action.model_dump() == {} for action in model_output.action):
				self.logger.warning('Model still returned empty after retry. Inserting safe noop action.')
				action_instance = self.ActionModel()
				setattr(
					action_instance,
					'done',
					{
						'success': False,
						'text': 'No next action returned by LLM!',
					},
				)
				model_output.action = [action_instance]

		return model_output

	async def _handle_post_llm_processing(
		self,
		browser_state_summary: BrowserStateSummary,
		input_messages: list[BaseMessage],
	) -> None:
		"""Handle callbacks and conversation saving after LLM interaction"""
		if self.register_new_step_callback and self.state.last_model_output:
			if inspect.iscoroutinefunction(self.register_new_step_callback):
				await self.register_new_step_callback(
					browser_state_summary,
					self.state.last_model_output,
					self.state.n_steps,
				)
			else:
				self.register_new_step_callback(
					browser_state_summary,
					self.state.last_model_output,
					self.state.n_steps,
				)

		if self.settings.save_conversation_path and self.state.last_model_output:
			# Treat save_conversation_path as a directory (consistent with other recording paths)
			conversation_dir = Path(self.settings.save_conversation_path)
			conversation_filename = f'conversation_{self.id}_{self.state.n_steps}.txt'
			target = conversation_dir / conversation_filename
			await save_conversation(
				input_messages,
				self.state.last_model_output,
				target,
				self.settings.save_conversation_path_encoding,
			)

	async def _make_history_item(
		self,
		model_output: AgentOutput | None,
		browser_state_summary: BrowserStateSummary,
		result: list[ActionResult],
		metadata: StepMetadata | None = None,
	) -> None:
		"""Create and store history item"""

		if model_output:
			interacted_elements = AgentHistory.get_interacted_element(model_output, browser_state_summary.dom_state.selector_map)
		else:
			interacted_elements = [None]

		# Store screenshot and get path
		screenshot_path = None
		if browser_state_summary.screenshot:
			self.logger.debug(
				f'📸 Storing screenshot for step {self.state.n_steps}, screenshot length: {len(browser_state_summary.screenshot)}'
			)
			screenshot_path = await self.screenshot_service.store_screenshot(browser_state_summary.screenshot, self.state.n_steps)
			self.logger.debug(f'📸 Screenshot stored at: {screenshot_path}')
		else:
			self.logger.debug(f'📸 No screenshot in browser_state_summary for step {self.state.n_steps}')

		state_history = BrowserStateHistory(
			url=browser_state_summary.url,
			title=browser_state_summary.title,
			tabs=browser_state_summary.tabs,
			interacted_element=interacted_elements,
			screenshot_path=screenshot_path,
		)

		history_item = AgentHistory(
			model_output=model_output,
			result=result,
			state=state_history,
			metadata=metadata,
		)

		self.history.add_item(history_item)

	def _remove_think_tags(self, text: str) -> str:
		THINK_TAGS = re.compile(r'<think>.*?</think>', re.DOTALL)
		STRAY_CLOSE_TAG = re.compile(r'.*?</think>', re.DOTALL)
		# Step 1: Remove well-formed <think>...</think>
		text = re.sub(THINK_TAGS, '', text)
		# Step 2: If there's an unmatched closing tag </think>,
		#         remove everything up to and including that.
		text = re.sub(STRAY_CLOSE_TAG, '', text)
		return text.strip()

	@time_execution_async('--get_next_action')
	@observe_debug(ignore_input=True, ignore_output=True, name='get_model_output')
	async def get_model_output(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get next action from LLM based on current state"""

		try:
			response = await self.llm.ainvoke(input_messages, output_format=self.AgentOutput)
			parsed = response.completion

			# cut the number of actions to max_actions_per_step if needed
			if len(parsed.action) > self.settings.max_actions_per_step:
				parsed.action = parsed.action[: self.settings.max_actions_per_step]

			if not (hasattr(self.state, 'paused') and (self.state.paused or self.state.stopped)):
				log_response(parsed, self.controller.registry.registry, self.logger)

			self._log_next_action_summary(parsed)
			return parsed
		except ValidationError:
			# Just re-raise - Pydantic's validation errors are already descriptive
			raise

	def _log_agent_run(self) -> None:
		"""Log the agent run"""
		self.logger.info(f'🚀 Starting task: {self.task}')

		self.logger.debug(f'🤖 Browser-Use Library Version {self.version} ({self.source})')

	def _log_step_context(self, browser_state_summary: BrowserStateSummary) -> None:
		"""Log step context information"""
		url = browser_state_summary.url if browser_state_summary else ''
		url_short = url[:50] + '...' if len(url) > 50 else url
		interactive_count = len(browser_state_summary.dom_state.selector_map) if browser_state_summary else 0
		self.logger.info(
			f'📍 Step {self.state.n_steps}: Evaluating page with {interactive_count} interactive elements on: {url_short}'
		)

	def _log_next_action_summary(self, parsed: 'AgentOutput') -> None:
		"""Log a comprehensive summary of the next action(s)"""
		if not (self.logger.isEnabledFor(logging.DEBUG) and parsed.action):
			return

		action_count = len(parsed.action)

		# Collect action details
		action_details = []
		for i, action in enumerate(parsed.action):
			action_data = action.model_dump(exclude_unset=True)
			action_name = next(iter(action_data.keys())) if action_data else 'unknown'
			action_params = action_data.get(action_name, {}) if action_data else {}

			# Format key parameters concisely
			param_summary = []
			if isinstance(action_params, dict):
				for key, value in action_params.items():
					if key == 'index':
						param_summary.append(f'#{value}')
					elif key == 'text' and isinstance(value, str):
						text_preview = value[:30] + '...' if len(value) > 30 else value
						param_summary.append(f'text="{text_preview}"')
					elif key == 'url':
						param_summary.append(f'url="{value}"')
					elif key == 'success':
						param_summary.append(f'success={value}')
					elif isinstance(value, (str, int, bool)):
						val_str = str(value)[:30] + '...' if len(str(value)) > 30 else str(value)
						param_summary.append(f'{key}={val_str}')

			param_str = f'({", ".join(param_summary)})' if param_summary else ''
			action_details.append(f'{action_name}{param_str}')

		# Create summary based on single vs multi-action
		if action_count == 1:
			self.logger.info(f'☝️ Decided next action: {action_name}{param_str}')
		else:
			summary_lines = [f'✌️ Decided next {action_count} multi-actions:']
			for i, detail in enumerate(action_details):
				summary_lines.append(f'          {i + 1}. {detail}')
			self.logger.info('\n'.join(summary_lines))

	def _log_step_completion_summary(self, step_start_time: float, result: list[ActionResult]) -> None:
		"""Log step completion summary with action count, timing, and success/failure stats"""
		if not result:
			return

		step_duration = time.time() - step_start_time
		action_count = len(result)

		# Count success and failures
		success_count = sum(1 for r in result if not r.error)
		failure_count = action_count - success_count

		# Format success/failure indicators
		success_indicator = f'✅ {success_count}' if success_count > 0 else ''
		failure_indicator = f'❌ {failure_count}' if failure_count > 0 else ''
		status_parts = [part for part in [success_indicator, failure_indicator] if part]
		status_str = ' | '.join(status_parts) if status_parts else '✅ 0'

		self.logger.info(f'📍 Step {self.state.n_steps}: Ran {action_count} actions in {step_duration:.2f}s: {status_str}')

	def _log_agent_event(self, max_steps: int, agent_run_error: str | None = None) -> None:
		"""Sent the agent event for this run to telemetry"""

		token_summary = self.token_cost_service.get_usage_tokens_for_model(self.llm.model)

		# Prepare action_history data correctly
		action_history_data = []
		for item in self.history.history:
			if item.model_output and item.model_output.action:
				# Convert each ActionModel in the step to its dictionary representation
				step_actions = [
					action.model_dump(exclude_unset=True)
					for action in item.model_output.action
					if action  # Ensure action is not None if list allows it
				]
				action_history_data.append(step_actions)
			else:
				# Append None or [] if a step had no actions or no model output
				action_history_data.append(None)

		final_res = self.history.final_result()
		final_result_str = json.dumps(final_res) if final_res is not None else None

		self.telemetry.capture(
			AgentTelemetryEvent(
				task=self.task,
				model=self.llm.model,
				model_provider=self.llm.provider,
				planner_llm=self.settings.planner_llm.model if self.settings.planner_llm else None,
				max_steps=max_steps,
				max_actions_per_step=self.settings.max_actions_per_step,
				use_vision=self.settings.use_vision,
				use_validation=self.settings.validate_output,
				version=self.version,
				source=self.source,
				cdp_url=urlparse(self.browser_session.cdp_url).hostname
				if self.browser_session and self.browser_session.cdp_url
				else None,
				action_errors=self.history.errors(),
				action_history=action_history_data,
				urls_visited=self.history.urls(),
				steps=self.state.n_steps,
				total_input_tokens=token_summary.prompt_tokens,
				total_duration_seconds=self.history.total_duration_seconds(),
				success=self.history.is_successful(),
				final_result_response=final_result_str,
				error_message=agent_run_error,
			)
		)

	async def take_step(self, step_info: AgentStepInfo | None = None) -> tuple[bool, bool]:
		"""Take a step

		Returns:
		        Tuple[bool, bool]: (is_done, is_valid)
		"""
		await self.step(step_info)

		if self.history.is_done():
			await self.log_completion()
			if self.register_done_callback:
				if inspect.iscoroutinefunction(self.register_done_callback):
					await self.register_done_callback(self.history)
				else:
					self.register_done_callback(self.history)
			return True, True

		return False, False

	def _extract_url_from_task(self, task: str) -> str | None:
		"""Extract URL from task string using naive pattern matching."""
		import re

		# Look for common URL patterns
		patterns = [
			r'https?://[^\s<>"\']+',  # Full URLs with http/https
			r'(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}(?:/[^\s<>"\']*)?',  # Domain names with subdomains and optional paths
		]

		for pattern in patterns:
			match = re.search(pattern, task)
			if match:
				url = match.group(0)
				# Add https:// if missing
				if not url.startswith(('http://', 'https://')):
					url = 'https://' + url
				return url

		# If no URL found, check if task mentions Google or search
		task_lower = task.lower()
		if 'google' in task_lower or 'search' in task_lower:
			self.logger.debug('📍 Task mentions "google" or "search", defaulting to https://google.com')
			return 'https://google.com'

		return None

	@observe(name='agent.run', metadata={'task': '{{task}}', 'debug': '{{debug}}'})
	@time_execution_async('--run')
	async def run(
		self,
		max_steps: int = 100,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		"""Execute the task with maximum number of steps"""

		loop = asyncio.get_event_loop()
		agent_run_error: str | None = None  # Initialize error tracking variable
		self._force_exit_telemetry_logged = False  # ADDED: Flag for custom telemetry on force exit

		# Set up the  signal handler with callbacks specific to this agent
		from browser_use.utils import SignalHandler

		# Define the custom exit callback function for second CTRL+C
		def on_force_exit_log_telemetry():
			self._log_agent_event(max_steps=max_steps, agent_run_error='SIGINT: Cancelled by user')
			# NEW: Call the flush method on the telemetry instance
			if hasattr(self, 'telemetry') and self.telemetry:
				self.telemetry.flush()
			self._force_exit_telemetry_logged = True  # Set the flag

		signal_handler = SignalHandler(
			loop=loop,
			pause_callback=self.pause,
			resume_callback=self.resume,
			custom_exit_callback=on_force_exit_log_telemetry,  # Pass the new telemetrycallback
			exit_on_second_int=True,
		)
		signal_handler.register()

		try:
			self._log_agent_run()

			self.logger.debug(
				f'🔧 Agent setup: Task ID {self.task_id[-4:]}, Session ID {self.session_id[-4:]}, Browser Session ID {self.browser_session.id[-4:] if self.browser_session else "None"}'
			)

			# Initialize timing for session and task
			self._session_start_time = time.time()
			self._task_start_time = self._session_start_time  # Initialize task start time

			# Only dispatch session events if this is the first run
			if not self.state.session_initialized:
				self.logger.debug('📡 Dispatching CreateAgentSessionEvent...')
				# Emit CreateAgentSessionEvent at the START of run()
				self.eventbus.dispatch(CreateAgentSessionEvent.from_agent(self))

				self.state.session_initialized = True

			self.logger.debug('📡 Dispatching CreateAgentTaskEvent...')
			# Emit CreateAgentTaskEvent at the START of run()
			self.eventbus.dispatch(CreateAgentTaskEvent.from_agent(self))

			# Start browser session and attach watchdogs
			assert self.browser_session is not None, 'Browser session must be initialized before starting'
			self.logger.debug('🌐 Starting browser session...')
			from browser_use.browser.events import BrowserStartEvent

			event = self.browser_session.event_bus.dispatch(BrowserStartEvent())
			await event

			self.logger.debug('🔧 Browser session started with watchdogs attached')

			# Check if task contains a URL and add it as an initial action (only if preload is enabled)
			if self.preload:
				initial_url = self._extract_url_from_task(self.task)
				if initial_url:
					self.logger.info(f'🔗 Found URL in task: {initial_url}, adding as initial action...')

					# Create a go_to_url action for the initial URL
					go_to_url_action = {
						'go_to_url': {
							'url': initial_url,
							'new_tab': False,  # Navigate in current tab
						}
					}

					# Add to initial_actions or create new list if none exist
					if self.initial_actions:
						# Convert back to dict format, prepend URL navigation, then convert back
						initial_actions_dicts = []
						for action in self.initial_actions:
							action_data = action.model_dump(exclude_unset=True)
							initial_actions_dicts.append(action_data)

						# Prepend the go_to_url action
						initial_actions_dicts = [go_to_url_action] + initial_actions_dicts

						# Convert back to ActionModel instances
						self.initial_actions = self._convert_initial_actions(initial_actions_dicts)
					else:
						# Create new initial_actions with just the go_to_url
						self.initial_actions = self._convert_initial_actions([go_to_url_action])

					self.logger.debug(f'✅ Added navigation to {initial_url} as initial action')

			# Execute initial actions if provided
			if self.initial_actions:
				self.logger.debug(f'⚡ Executing {len(self.initial_actions)} initial actions...')
				result = await self.multi_act(self.initial_actions, check_for_new_elements=False)
				self.state.last_result = result
				self.logger.debug('✅ Initial actions completed')

			self.logger.debug(f'🔄 Starting main execution loop with max {max_steps} steps...')
			for step in range(max_steps):
				# Replace the polling with clean pause-wait
				if self.state.paused:
					self.logger.debug(f'⏸️ Step {step}: Agent paused, waiting to resume...')
					await self.wait_until_resumed()
					signal_handler.reset()

				# Check if we should stop due to too many failures
				if self.state.consecutive_failures >= self.settings.max_failures:
					self.logger.error(f'❌ Stopping due to {self.settings.max_failures} consecutive failures')
					agent_run_error = f'Stopped due to {self.settings.max_failures} consecutive failures'
					break

				# Check control flags before each step
				if self.state.stopped:
					self.logger.info('🛑 Agent stopped')
					agent_run_error = 'Agent stopped programmatically'
					break

				while self.state.paused:
					await asyncio.sleep(0.2)  # Small delay to prevent CPU spinning
					if self.state.stopped:  # Allow stopping while paused
						agent_run_error = 'Agent stopped programmatically while paused'
						break

				if on_step_start is not None:
					await on_step_start(self)

				self.logger.debug(f'🚶 Starting step {step + 1}/{max_steps}...')
				step_info = AgentStepInfo(step_number=step, max_steps=max_steps)

				try:
					await asyncio.wait_for(
						self.step(step_info),
						timeout=self.settings.step_timeout,
					)
					self.logger.debug(f'✅ Completed step {step + 1}/{max_steps}')
				except TimeoutError:
					# Handle step timeout gracefully
					error_msg = f'Step {step + 1} timed out after {self.settings.step_timeout} seconds'
					self.logger.error(f'⏰ {error_msg}')
					self.state.consecutive_failures += 1
					self.state.last_result = [ActionResult(error=error_msg)]

				if on_step_end is not None:
					await on_step_end(self)

				if self.history.is_done():
					self.logger.debug(f'🎯 Task completed after {step + 1} steps!')
					await self.log_completion()

					if self.register_done_callback:
						if inspect.iscoroutinefunction(self.register_done_callback):
							await self.register_done_callback(self.history)
						else:
							self.register_done_callback(self.history)

					# Task completed
					break
			else:
				agent_run_error = 'Failed to complete task in maximum steps'

				self.history.add_item(
					AgentHistory(
						model_output=None,
						result=[ActionResult(error=agent_run_error, include_in_memory=True)],
						state=BrowserStateHistory(
							url='',
							title='',
							tabs=[],
							interacted_element=[],
							screenshot_path=None,
						),
						metadata=None,
					)
				)

				self.logger.info(f'❌ {agent_run_error}')

			self.logger.debug('📊 Collecting usage summary...')
			self.history.usage = await self.token_cost_service.get_usage_summary()

			# set the model output schema and call it on the fly
			if self.history._output_model_schema is None and self.output_model_schema is not None:
				self.history._output_model_schema = self.output_model_schema

			self.logger.debug('🏁 Agent.run() completed successfully')
			return self.history

		except KeyboardInterrupt:
			# Already handled by our signal handler, but catch any direct KeyboardInterrupt as well
			self.logger.info('Got KeyboardInterrupt during execution, returning current history')
			agent_run_error = 'KeyboardInterrupt'

			self.history.usage = await self.token_cost_service.get_usage_summary()

			return self.history

		except Exception as e:
			self.logger.error(f'Agent run failed with exception: {e}', exc_info=True)
			agent_run_error = str(e)
			raise e

		finally:
			# Log token usage summary
			await self.token_cost_service.log_usage_summary()

			# Unregister signal handlers before cleanup
			signal_handler.unregister()

			if not self._force_exit_telemetry_logged:  # MODIFIED: Check the flag
				try:
					self._log_agent_event(max_steps=max_steps, agent_run_error=agent_run_error)
				except Exception as log_e:  # Catch potential errors during logging itself
					self.logger.error(f'Failed to log telemetry event: {log_e}', exc_info=True)
			else:
				# ADDED: Info message when custom telemetry for SIGINT was already logged
				self.logger.info('Telemetry for force exit (SIGINT) was logged by custom exit callback.')

			# NOTE: CreateAgentSessionEvent and CreateAgentTaskEvent are now emitted at the START of run()
			# to match backend requirements for CREATE events to be fired when entities are created,
			# not when they are completed

			# Emit UpdateAgentTaskEvent at the END of run() with final task state
			self.eventbus.dispatch(UpdateAgentTaskEvent.from_agent(self))

			# Generate GIF if needed before stopping event bus
			if self.settings.generate_gif:
				output_path: str = 'agent_history.gif'
				if isinstance(self.settings.generate_gif, str):
					output_path = self.settings.generate_gif

				# Lazy import gif module to avoid heavy startup cost
				from browser_use.agent.gif import create_history_gif

				create_history_gif(task=self.task, history=self.history, output_path=output_path)

				# Only emit output file event if GIF was actually created
				if Path(output_path).exists():
					output_event = await CreateAgentOutputFileEvent.from_agent_and_file(self, output_path)
					self.eventbus.dispatch(output_event)

			# Wait briefly for cloud auth to start and print the URL, but don't block for completion
			if self.enable_cloud_sync and hasattr(self, 'cloud_sync'):
				if self.cloud_sync.auth_task and not self.cloud_sync.auth_task.done():
					try:
						# Wait up to 1 second for auth to start and print URL
						await asyncio.wait_for(self.cloud_sync.auth_task, timeout=1.0)
					except TimeoutError:
						logger.info('Cloud authentication started - continuing in background')
					except Exception as e:
						logger.debug(f'Cloud authentication error: {e}')

			# Stop the event bus gracefully, waiting for all events to be processed
			# Use longer timeout to avoid deadlocks in tests with multiple agents
			await self.eventbus.stop(timeout=10.0)

			await self.close()

	@observe_debug(ignore_input=True, ignore_output=True)
	@time_execution_async('--multi_act')
	async def multi_act(
		self,
		actions: list[ActionModel],
		check_for_new_elements: bool = True,
	) -> list[ActionResult]:
		"""Execute multiple actions"""
		results: list[ActionResult] = []
		time_elapsed = 0
		total_actions = len(actions)

		assert self.browser_session is not None, 'BrowserSession is not set up'
		try:
			if (
				self.browser_session._cached_browser_state_summary is not None
				and self.browser_session._cached_browser_state_summary.dom_state is not None
			):
				cached_selector_map = self.browser_session._cached_browser_state_summary.dom_state.selector_map
				cached_element_hashes = {e.parent_branch_hash() for e in cached_selector_map.values()}
			else:
				cached_selector_map = {}
				cached_element_hashes = set()
		except Exception as e:
			self.logger.error(f'Error getting cached selector map: {e}')
			cached_selector_map = {}
			cached_element_hashes = set()

		# await self.browser_session.remove_highlights()

		for i, action in enumerate(actions):
			if i > 0:
				# ONLY ALLOW TO CALL `done` IF IT IS A SINGLE ACTION
				if action.model_dump(exclude_unset=True).get('done') is not None:
					msg = f'Done action is allowed only as a single action - stopped after action {i} / {total_actions}.'
					logger.info(msg)
					break

			# DOM synchronization check - verify element indexes are still valid AFTER first action
			# This prevents stale element detection but doesn't refresh before execution
			if action.get_index() is not None and i != 0:
				new_browser_state_summary = await self.browser_session.get_browser_state_summary(
					cache_clickable_elements_hashes=False,
					include_screenshot=False,
				)
				new_selector_map = new_browser_state_summary.dom_state.selector_map

				# Detect index change after previous action
				orig_target = cached_selector_map.get(action.get_index())
				orig_target_hash = orig_target.parent_branch_hash() if orig_target else None

				new_target = new_selector_map.get(action.get_index())  # type: ignore
				new_target_hash = new_target.parent_branch_hash() if new_target else None

				if orig_target_hash != new_target_hash:
					msg = f'Element index changed after action {i} / {total_actions}, because page changed.'
					logger.info(msg)
					results.append(
						ActionResult(
							extracted_content=msg,
							include_in_memory=True,
							long_term_memory=msg,
						)
					)
					break

				# Check for new elements that appeared
				new_element_hashes = {e.parent_branch_hash() for e in new_selector_map.values()}
				if check_for_new_elements and not new_element_hashes.issubset(cached_element_hashes):
					# next action requires index but there are new elements on the page
					msg = f'Something new appeared after action {i} / {total_actions}, following actions are NOT executed and should be retried.'
					logger.info(msg)
					results.append(
						ActionResult(
							extracted_content=msg,
							include_in_memory=True,
							long_term_memory=msg,
						)
					)
					break

			# wait between actions (only after first action)
			if i > 0:
				await asyncio.sleep(self.browser_profile.wait_between_actions)

			red = '\033[91m'
			green = '\033[92m'
			cyan = '\033[96m'
			reset = '\033[0m'

			try:
				await self._raise_if_stopped_or_paused()
				# Get action name from the action model
				action_data = action.model_dump(exclude_unset=True)
				action_name = next(iter(action_data.keys())) if action_data else 'unknown'
				action_params = getattr(action, action_name, '') or str(action.model_dump(mode='json'))[:140].replace(
					'"', ''
				).replace('{', '').replace('}', '').replace("'", '').strip().strip(',')
				# Ensure action_params is always a string before checking length
				action_params = str(action_params)
				action_params = f'{action_params[:122]}...' if len(action_params) > 128 else action_params
				time_start = time.time()

				self.logger.info(f'🦾 {cyan}[ACTION {i + 1}/{total_actions}] {action_name}({action_params})... {reset}')

				result = await self.controller.act(
					action=action,
					browser_session=self.browser_session,
					file_system=self.file_system,
					page_extraction_llm=self.settings.page_extraction_llm,
					sensitive_data=self.sensitive_data,
					available_file_paths=self.available_file_paths,
					context=self.context,
				)

				time_end = time.time()
				time_elapsed = time_end - time_start
				results.append(result)

				self.logger.info(
					f'☑️ Executed action {i + 1}/{total_actions}: {green}{action_name}({action_params}){reset} in {time_elapsed:.2f}s'
				)
				if results[-1].is_done or results[-1].error or i == total_actions - 1:
					break

			except Exception as e:
				# Handle any exceptions during action execution
				self.logger.error(
					f'❌ Executing action {i + 1} failed in {time_elapsed:.2f}s {red}{action_name}({action_params}) -> {type(e).__name__}: {e}{reset}'
				)
				raise e

		return results

	async def log_completion(self) -> None:
		"""Log the completion of the task"""
		if self.history.is_successful():
			self.logger.info('✅ Task completed successfully')
		else:
			self.logger.info('❌ Task completed without success')

	async def rerun_history(
		self,
		history: AgentHistoryList,
		max_retries: int = 3,
		skip_failures: bool = True,
		delay_between_actions: float = 2.0,
	) -> list[ActionResult]:
		"""
		Rerun a saved history of actions with error handling and retry logic.

		Args:
		                history: The history to replay
		                max_retries: Maximum number of retries per action
		                skip_failures: Whether to skip failed actions or stop execution
		                delay_between_actions: Delay between actions in seconds

		Returns:
		                List of action results
		"""
		# Execute initial actions if provided
		if self.initial_actions:
			result = await self.multi_act(self.initial_actions)
			self.state.last_result = result

		results = []

		for i, history_item in enumerate(history.history):
			goal = history_item.model_output.current_state.next_goal if history_item.model_output else ''
			self.logger.info(f'Replaying step {i + 1}/{len(history.history)}: goal: {goal}')

			if (
				not history_item.model_output
				or not history_item.model_output.action
				or history_item.model_output.action == [None]
			):
				self.logger.warning(f'Step {i + 1}: No action to replay, skipping')
				results.append(ActionResult(error='No action to replay'))
				continue

			retry_count = 0
			while retry_count < max_retries:
				try:
					result = await self._execute_history_step(history_item, delay_between_actions)
					results.extend(result)
					break

				except Exception as e:
					retry_count += 1
					if retry_count == max_retries:
						error_msg = f'Step {i + 1} failed after {max_retries} attempts: {str(e)}'
						self.logger.error(error_msg)
						if not skip_failures:
							results.append(ActionResult(error=error_msg))
							raise RuntimeError(error_msg)
					else:
						self.logger.warning(f'Step {i + 1} failed (attempt {retry_count}/{max_retries}), retrying...')
						await asyncio.sleep(delay_between_actions)

		return results

	async def _execute_history_step(self, history_item: AgentHistory, delay: float) -> list[ActionResult]:
		"""Execute a single step from history with element validation"""
		assert self.browser_session is not None, 'BrowserSession is not set up'
		state = await self.browser_session.get_browser_state_summary(
			cache_clickable_elements_hashes=False, include_screenshot=False
		)
		if not state or not history_item.model_output:
			raise ValueError('Invalid state or model output')
		updated_actions = []
		for i, action in enumerate(history_item.model_output.action):
			updated_action = await self._update_action_indices(
				history_item.state.interacted_element[i],
				action,
				state,
			)
			updated_actions.append(updated_action)

			if updated_action is None:
				raise ValueError(f'Could not find matching element {i} in current page')

		result = await self.multi_act(updated_actions)

		await asyncio.sleep(delay)
		return result

	async def _update_action_indices(
		self,
		historical_element: DOMInteractedElement | None,
		action: ActionModel,  # Type this properly based on your action model
		browser_state_summary: BrowserStateSummary,
	) -> ActionModel | None:
		"""
		Update action indices based on current page state.
		Returns updated action or None if element cannot be found.
		"""
		if not historical_element or not browser_state_summary.dom_state.selector_map:
			return action

		# selector_hash_map = {hash(e): e for e in browser_state_summary.dom_state.selector_map.values()}

		highlight_index, current_element = next(
			(
				(highlight_index, element)
				for highlight_index, element in browser_state_summary.dom_state.selector_map.items()
				if element.element_hash == historical_element.element_hash
			),
			(None, None),
		)

		if not current_element or highlight_index is None:
			return None

		old_index = action.get_index()
		if old_index != highlight_index:
			action.set_index(highlight_index)
			self.logger.info(f'Element moved in DOM, updated index from {old_index} to {highlight_index}')

		return action

	async def load_and_rerun(self, history_file: str | Path | None = None, **kwargs) -> list[ActionResult]:
		"""
		Load history from file and rerun it.

		Args:
		                history_file: Path to the history file
		                **kwargs: Additional arguments passed to rerun_history
		"""
		if not history_file:
			history_file = 'AgentHistory.json'
		history = AgentHistoryList.load_from_file(history_file, self.AgentOutput)
		return await self.rerun_history(history, **kwargs)

	def save_history(self, file_path: str | Path | None = None) -> None:
		"""Save the history to a file"""
		if not file_path:
			file_path = 'AgentHistory.json'
		self.history.save_to_file(file_path)

	async def wait_until_resumed(self):
		await self._external_pause_event.wait()

	def pause(self) -> None:
		"""Pause the agent before the next step"""
		print(
			'\n\n⏸️  Got [Ctrl+C], paused the agent and left the browser open.\n\tPress [Enter] to resume or [Ctrl+C] again to quit.'
		)
		self.state.paused = True
		self._external_pause_event.clear()

		# Task paused

		# The signal handler will handle the asyncio pause logic for us
		# No need to duplicate the code here

	def resume(self) -> None:
		"""Resume the agent"""
		print('----------------------------------------------------------------------')
		print('▶️  Got Enter, resuming agent execution where it left off...\n')
		self.state.paused = False
		self._external_pause_event.set()

		# Task resumed

		# The signal handler should have already reset the flags
		# through its reset() method when called from run()

	def stop(self) -> None:
		"""Stop the agent"""
		self.logger.info('⏹️ Agent stopping')
		self.state.stopped = True

		# Task stopped

	def _convert_initial_actions(self, actions: list[dict[str, dict[str, Any]]]) -> list[ActionModel]:
		"""Convert dictionary-based actions to ActionModel instances"""
		converted_actions = []
		action_model = self.ActionModel
		for action_dict in actions:
			# Each action_dict should have a single key-value pair
			action_name = next(iter(action_dict))
			params = action_dict[action_name]

			# Get the parameter model for this action from registry
			action_info = self.controller.registry.registry.actions[action_name]
			param_model = action_info.param_model

			# Create validated parameters using the appropriate param model
			validated_params = param_model(**params)

			# Create ActionModel instance with the validated parameters
			action_model = self.ActionModel(**{action_name: validated_params})
			converted_actions.append(action_model)

		return converted_actions

	def _verify_and_setup_llm(self):
		"""
		Verify that the LLM API keys are setup and the LLM API is responding properly.
		Also handles tool calling method detection if in auto mode.
		"""

		# Skip verification if already done
		if getattr(self.llm, '_verified_api_keys', None) is True or CONFIG.SKIP_LLM_API_KEY_VERIFICATION:
			setattr(self.llm, '_verified_api_keys', True)
			return True

	@property
	def message_manager(self) -> MessageManager:
		return self._message_manager

	async def close(self):
		"""Close all resources"""
		try:
			# Only close browser if keep_alive is False (or not set)
			if self.browser_session is not None:
				if not self.browser_session.browser_profile.keep_alive:
					# Kill the browser session - this dispatches BrowserStopEvent,
					# stops the EventBus with clear=True, and recreates a fresh EventBus
					await self.browser_session.kill()

			# Force garbage collection
			gc.collect()

			# Debug: Log remaining threads and asyncio tasks
			import threading

			threads = threading.enumerate()
			self.logger.debug(f'🧵 Remaining threads ({len(threads)}): {[t.name for t in threads]}')

			# Get all asyncio tasks
			tasks = asyncio.all_tasks(asyncio.get_event_loop())
			# Filter out the current task (this close() coroutine)
			other_tasks = [t for t in tasks if t != asyncio.current_task()]
			if other_tasks:
				self.logger.debug(f'⚡ Remaining asyncio tasks ({len(other_tasks)}):')
				for task in other_tasks[:10]:  # Limit to first 10 to avoid spam
					self.logger.debug(f'  - {task.get_name()}: {task}')
			else:
				self.logger.debug('⚡ No remaining asyncio tasks')

		except Exception as e:
			self.logger.error(f'Error during cleanup: {e}')

	async def _update_action_models_for_page(self, page_url: str) -> None:
		"""Update action models with page-specific actions"""
		# Create new action model with current page's filtered actions
		self.ActionModel = self.controller.registry.create_action_model(page_url=page_url)
		# Update output model with the new actions
		if self.settings.flash_mode:
			self.AgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.ActionModel)
		elif self.settings.use_thinking:
			self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)
		else:
			self.AgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.ActionModel)

		# Update done action model too
		self.DoneActionModel = self.controller.registry.create_action_model(include_actions=['done'], page_url=page_url)
		if self.settings.flash_mode:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.DoneActionModel)
		elif self.settings.use_thinking:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions(self.DoneActionModel)
		else:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.DoneActionModel)

	def get_trace_object(self) -> dict[str, Any]:
		"""Get the trace and trace_details objects for the agent"""

		def extract_task_website(task_text: str) -> str | None:
			url_pattern = r'https?://[^\s<>"\']+|www\.[^\s<>"\']+|[^\s<>"\']+\.[a-z]{2,}(?:/[^\s<>"\']*)?'
			match = re.search(url_pattern, task_text, re.IGNORECASE)
			return match.group(0) if match else None

		def _get_complete_history_without_screenshots(history_data: dict[str, Any]) -> str:
			if 'history' in history_data:
				for item in history_data['history']:
					if 'state' in item and 'screenshot' in item['state']:
						item['state']['screenshot'] = None

			return json.dumps(history_data)

		# Generate autogenerated fields
		trace_id = uuid7str()
		timestamp = datetime.now().isoformat()

		# Only declare variables that are used multiple times
		structured_output = self.history.structured_output
		structured_output_json = json.dumps(structured_output.model_dump()) if structured_output else None
		final_result = self.history.final_result()
		git_info = get_git_info()
		action_history = self.history.action_history()
		action_errors = self.history.errors()
		urls = self.history.urls()
		usage = self.history.usage

		return {
			'trace': {
				# Autogenerated fields
				'trace_id': trace_id,
				'timestamp': timestamp,
				'browser_use_version': get_browser_use_version(),
				'git_info': json.dumps(git_info) if git_info else None,
				# Direct agent properties
				'model': self.llm.model,
				'settings': json.dumps(self.settings.model_dump()) if self.settings else None,
				'task_id': self.task_id,
				'task_truncated': self.task[:20000] if len(self.task) > 20000 else self.task,
				'task_website': extract_task_website(self.task),
				# AgentHistoryList methods
				'structured_output_truncated': (
					structured_output_json[:20000]
					if structured_output_json and len(structured_output_json) > 20000
					else structured_output_json
				),
				'action_history_truncated': json.dumps(action_history) if action_history else None,
				'action_errors': json.dumps(action_errors) if action_errors else None,
				'urls': json.dumps(urls) if urls else None,
				'final_result_response_truncated': (
					final_result[:20000] if final_result and len(final_result) > 20000 else final_result
				),
				'self_report_completed': 1 if self.history.is_done() else 0,
				'self_report_success': 1 if self.history.is_successful() else 0,
				'duration': self.history.total_duration_seconds(),
				'steps_taken': self.history.number_of_steps(),
				'usage': json.dumps(usage.model_dump()) if usage else None,
			},
			'trace_details': {
				# Autogenerated fields (ensure same as trace)
				'trace_id': trace_id,
				'timestamp': timestamp,
				# Direct agent properties
				'task': self.task,
				# AgentHistoryList methods
				'structured_output': structured_output_json,
				'final_result_response': final_result,
				'complete_history': _get_complete_history_without_screenshots(self.history.model_dump()),
			},
		}
