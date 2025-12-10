import asyncio
import gc
import inspect
import json
import logging
import re
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, cast
from urllib.parse import urlparse

if TYPE_CHECKING:
	from browser_use.skills.views import Skill

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
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage, ContentPartImageParam, ContentPartTextParam, UserMessage
from browser_use.tokens.service import TokenCost

load_dotenv()

from bubus import EventBus
from pydantic import BaseModel, ValidationError
from uuid_extensions import uuid7str

from browser_use import Browser, BrowserProfile, BrowserSession
from browser_use.agent.judge import construct_judge_messages

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
	DetectedVariable,
	JudgementResult,
	StepMetadata,
)
from browser_use.browser.session import DEFAULT_BROWSER_PROFILE
from browser_use.browser.views import BrowserStateSummary
from browser_use.config import CONFIG
from browser_use.dom.views import DOMInteractedElement
from browser_use.filesystem.file_system import FileSystem
from browser_use.observability import observe, observe_debug
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import AgentTelemetryEvent
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.utils import (
	URL_PATTERN,
	_log_pretty_path,
	check_latest_browser_use_version,
	get_browser_use_version,
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
		logger.debug(f'💡 Thinking:\n{response.current_state.thinking}')

	# Only log evaluation if it's not empty
	eval_goal = response.current_state.evaluation_previous_goal
	if eval_goal:
		if 'success' in eval_goal.lower():
			emoji = '👍'
			# Green color for success
			logger.info(f'  \033[32m{emoji} Eval: {eval_goal}\033[0m')
		elif 'failure' in eval_goal.lower():
			emoji = '⚠️'
			# Red color for failure
			logger.info(f'  \033[31m{emoji} Eval: {eval_goal}\033[0m')
		else:
			emoji = '❔'
			# No color for unknown/neutral
			logger.info(f'  {emoji} Eval: {eval_goal}')

	# Always log memory if present
	if response.current_state.memory:
		logger.info(f'  🧠 Memory: {response.current_state.memory}')

	# Only log next goal if it's not empty
	next_goal = response.current_state.next_goal
	if next_goal:
		# Blue color for next goal
		logger.info(f'  \033[34m🎯 Next goal: {next_goal}\033[0m')


Context = TypeVar('Context')


AgentHookFunc = Callable[['Agent'], Awaitable[None]]


class Agent(Generic[Context, AgentStructuredOutput]):
	@time_execution_sync('--init')
	def __init__(
		self,
		task: str,
		llm: BaseChatModel | None = None,
		# Optional parameters
		browser_profile: BrowserProfile | None = None,
		browser_session: BrowserSession | None = None,
		browser: Browser | None = None,  # Alias for browser_session
		tools: Tools[Context] | None = None,
		controller: Tools[Context] | None = None,  # Alias for tools
		# Skills integration
		skill_ids: list[str | Literal['*']] | None = None,
		skills: list[str | Literal['*']] | None = None,  # Alias for skill_ids
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
		register_should_stop_callback: Callable[[], Awaitable[bool]] | None = None,
		# Agent settings
		output_model_schema: type[AgentStructuredOutput] | None = None,
		use_vision: bool | Literal['auto'] = True,
		save_conversation_path: str | Path | None = None,
		save_conversation_path_encoding: str | None = 'utf-8',
		max_failures: int = 3,
		override_system_message: str | None = None,
		extend_system_message: str | None = None,
		generate_gif: bool | str = False,
		available_file_paths: list[str] | None = None,
		include_attributes: list[str] | None = None,
		max_actions_per_step: int = 3,
		use_thinking: bool = True,
		flash_mode: bool = False,
		demo_mode: bool | None = None,
		max_history_items: int | None = None,
		page_extraction_llm: BaseChatModel | None = None,
		fallback_llm: BaseChatModel | None = None,
		use_judge: bool = True,
		ground_truth: str | None = None,
		judge_llm: BaseChatModel | None = None,
		injected_agent_state: AgentState | None = None,
		source: str | None = None,
		file_system_path: str | None = None,
		task_id: str | None = None,
		calculate_cost: bool = False,
		display_files_in_done_text: bool = True,
		include_tool_call_examples: bool = False,
		vision_detail_level: Literal['auto', 'low', 'high'] = 'auto',
		llm_timeout: int | None = None,
		step_timeout: int = 120,
		directly_open_url: bool = True,
		include_recent_events: bool = False,
		sample_images: list[ContentPartTextParam | ContentPartImageParam] | None = None,
		final_response_after_failure: bool = True,
		llm_screenshot_size: tuple[int, int] | None = None,
		_url_shortening_limit: int = 25,
		**kwargs,
	):
		# Validate llm_screenshot_size
		if llm_screenshot_size is not None:
			if not isinstance(llm_screenshot_size, tuple) or len(llm_screenshot_size) != 2:
				raise ValueError('llm_screenshot_size must be a tuple of (width, height)')
			width, height = llm_screenshot_size
			if not isinstance(width, int) or not isinstance(height, int):
				raise ValueError('llm_screenshot_size dimensions must be integers')
			if width < 100 or height < 100:
				raise ValueError('llm_screenshot_size dimensions must be at least 100 pixels')
			self.logger.info(f'🖼️  LLM screenshot resizing enabled: {width}x{height}')
		if llm is None:
			default_llm_name = CONFIG.DEFAULT_LLM
			if default_llm_name:
				from browser_use.llm.models import get_llm_by_name

				llm = get_llm_by_name(default_llm_name)
			else:
				# No default LLM specified, use the original default
				from browser_use import ChatBrowserUse

				llm = ChatBrowserUse()

		# set flashmode = True if llm is ChatBrowserUse
		if llm.provider == 'browser-use':
			flash_mode = True

		# Auto-configure llm_screenshot_size for Claude Sonnet models
		if llm_screenshot_size is None:
			model_name = getattr(llm, 'model', '')
			if isinstance(model_name, str) and model_name.startswith('claude-sonnet'):
				llm_screenshot_size = (1400, 850)
				logger.info('🖼️  Auto-configured LLM screenshot size for Claude Sonnet: 1400x850')

		if page_extraction_llm is None:
			page_extraction_llm = llm
		if judge_llm is None:
			judge_llm = llm
		if available_file_paths is None:
			available_file_paths = []

		# Set timeout based on model name if not explicitly provided
		if llm_timeout is None:

			def _get_model_timeout(llm_model: BaseChatModel) -> int:
				"""Determine timeout based on model name"""
				model_name = getattr(llm_model, 'model', '').lower()
				if 'gemini' in model_name:
					if '3-pro' in model_name:
						return 90
					return 45
				elif 'groq' in model_name:
					return 30
				elif 'o3' in model_name or 'claude' in model_name or 'sonnet' in model_name or 'deepseek' in model_name:
					return 90
				else:
					return 60  # Default timeout

			llm_timeout = _get_model_timeout(llm)

		self.id = task_id or uuid7str()
		self.task_id: str = self.id
		self.session_id: str = uuid7str()

		base_profile = browser_profile or DEFAULT_BROWSER_PROFILE
		if base_profile is DEFAULT_BROWSER_PROFILE:
			base_profile = base_profile.model_copy()
		if demo_mode is not None and base_profile.demo_mode != demo_mode:
			base_profile = base_profile.model_copy(update={'demo_mode': demo_mode})
		browser_profile = base_profile

		# Handle browser vs browser_session parameter (browser takes precedence)
		if browser and browser_session:
			raise ValueError('Cannot specify both "browser" and "browser_session" parameters. Use "browser" for the cleaner API.')
		browser_session = browser or browser_session

		if browser_session is not None and demo_mode is not None and browser_session.browser_profile.demo_mode != demo_mode:
			browser_session.browser_profile = browser_session.browser_profile.model_copy(update={'demo_mode': demo_mode})

		self.browser_session = browser_session or BrowserSession(
			browser_profile=browser_profile,
			id=uuid7str()[:-4] + self.id[-4:],  # re-use the same 4-char suffix so they show up together in logs
		)

		self._demo_mode_enabled: bool = bool(self.browser_profile.demo_mode) if self.browser_session else False
		if self._demo_mode_enabled and getattr(self.browser_profile, 'headless', False):
			self.logger.warning(
				'Demo mode is enabled but the browser is headless=True; set headless=False to view the in-browser panel.'
			)

		# Initialize available file paths as direct attribute
		self.available_file_paths = available_file_paths

		# Set up tools first (needed to detect output_model_schema)
		if tools is not None:
			self.tools = tools
		elif controller is not None:
			self.tools = controller
		else:
			# Exclude screenshot tool when use_vision is not auto
			exclude_actions = ['screenshot'] if use_vision != 'auto' else []
			self.tools = Tools(exclude_actions=exclude_actions, display_files_in_done_text=display_files_in_done_text)

		# Enforce screenshot exclusion when use_vision != 'auto', even if user passed custom tools
		if use_vision != 'auto':
			self.tools.exclude_action('screenshot')

		# Handle skills vs skill_ids parameter (skills takes precedence)
		if skills and skill_ids:
			raise ValueError('Cannot specify both "skills" and "skill_ids" parameters. Use "skills" for the cleaner API.')
		skill_ids = skills or skill_ids

		# Skills integration
		self.skill_service = None
		self._skills_registered = False
		if skill_ids:
			from browser_use.skills import SkillService

			self.skill_service = SkillService(skill_ids=skill_ids)

		# Structured output - use explicit param or detect from tools
		tools_output_model = self.tools.get_output_model()
		if output_model_schema is not None and tools_output_model is not None:
			# Both provided - warn if they differ
			if output_model_schema is not tools_output_model:
				logger.warning(
					f'output_model_schema ({output_model_schema.__name__}) differs from Tools output_model '
					f'({tools_output_model.__name__}). Using Agent output_model_schema.'
				)
		elif output_model_schema is None and tools_output_model is not None:
			# Only tools has it - use that (cast is safe: both are BaseModel subclasses)
			output_model_schema = cast(type[AgentStructuredOutput], tools_output_model)
		self.output_model_schema = output_model_schema
		if self.output_model_schema is not None:
			self.tools.use_structured_output_action(self.output_model_schema)

		# Core components - task enhancement now has access to output_model_schema from tools
		self.task = self._enhance_task_with_schema(task, output_model_schema)
		self.llm = llm
		self.judge_llm = judge_llm

		# Fallback LLM configuration
		self._fallback_llm: BaseChatModel | None = fallback_llm
		self._using_fallback_llm: bool = False
		self._original_llm: BaseChatModel = llm  # Store original for reference
		self.directly_open_url = directly_open_url
		self.include_recent_events = include_recent_events
		self._url_shortening_limit = _url_shortening_limit

		self.sensitive_data = sensitive_data

		self.sample_images = sample_images

		self.settings = AgentSettings(
			use_vision=use_vision,
			vision_detail_level=vision_detail_level,
			save_conversation_path=save_conversation_path,
			save_conversation_path_encoding=save_conversation_path_encoding,
			max_failures=max_failures,
			override_system_message=override_system_message,
			extend_system_message=extend_system_message,
			generate_gif=generate_gif,
			include_attributes=include_attributes,
			max_actions_per_step=max_actions_per_step,
			use_thinking=use_thinking,
			flash_mode=flash_mode,
			max_history_items=max_history_items,
			page_extraction_llm=page_extraction_llm,
			calculate_cost=calculate_cost,
			include_tool_call_examples=include_tool_call_examples,
			llm_timeout=llm_timeout,
			step_timeout=step_timeout,
			final_response_after_failure=final_response_after_failure,
			use_judge=use_judge,
			ground_truth=ground_truth,
		)

		# Token cost service
		self.token_cost_service = TokenCost(include_cost=calculate_cost)
		self.token_cost_service.register_llm(llm)
		self.token_cost_service.register_llm(page_extraction_llm)
		self.token_cost_service.register_llm(judge_llm)

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

		initial_url = None

		# only load url if no initial actions are provided
		if self.directly_open_url and not self.state.follow_up_task and not initial_actions:
			initial_url = self._extract_start_url(self.task)
			if initial_url:
				self.logger.info(f'🔗 Found URL in task: {initial_url}, adding as initial action...')
				initial_actions = [{'navigate': {'url': initial_url, 'new_tab': False}}]

		self.initial_url = initial_url

		self.initial_actions = self._convert_initial_actions(initial_actions) if initial_actions else None
		# Verify we can connect to the model
		self._verify_and_setup_llm()

		# TODO: move this logic to the LLMs
		# Handle users trying to use use_vision=True with DeepSeek models
		if 'deepseek' in self.llm.model.lower():
			self.logger.warning('⚠️ DeepSeek models do not support use_vision=True yet. Setting use_vision=False for now...')
			self.settings.use_vision = False

		# Handle users trying to use use_vision=True with XAI models
		if 'grok' in self.llm.model.lower():
			self.logger.warning('⚠️ XAI models do not support use_vision=True yet. Setting use_vision=False for now...')
			self.settings.use_vision = False

		logger.debug(
			f'{" +vision" if self.settings.use_vision else ""}'
			f' extraction_model={self.settings.page_extraction_llm.model if self.settings.page_extraction_llm else "Unknown"}'
			f'{" +file_system" if self.file_system else ""}'
		)

		# Store llm_screenshot_size in browser_session so tools can access it
		self.browser_session.llm_screenshot_size = llm_screenshot_size

		# Check if LLM is ChatAnthropic instance
		from browser_use.llm.anthropic.chat import ChatAnthropic

		is_anthropic = isinstance(self.llm, ChatAnthropic)

		# Initialize message manager with state
		# Initial system prompt with all actions - will be updated during each step
		self._message_manager = MessageManager(
			task=self.task,
			system_message=SystemPrompt(
				max_actions_per_step=self.settings.max_actions_per_step,
				override_system_message=override_system_message,
				extend_system_message=extend_system_message,
				use_thinking=self.settings.use_thinking,
				flash_mode=self.settings.flash_mode,
				is_anthropic=is_anthropic,
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
			sample_images=self.sample_images,
			llm_screenshot_size=llm_screenshot_size,
		)

		if self.sensitive_data:
			# Check if sensitive_data has domain-specific credentials
			has_domain_specific_credentials = any(isinstance(v, dict) for v in self.sensitive_data.values())

			# If no allowed_domains are configured, show a security warning
			if not self.browser_profile.allowed_domains:
				self.logger.warning(
					'⚠️ Agent(sensitive_data=••••••••) was provided but Browser(allowed_domains=[...]) is not locked down! ⚠️\n'
					'          ☠️ If the agent visits a malicious website and encounters a prompt-injection attack, your sensitive_data may be exposed!\n\n'
					'   \n'
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
		self.register_should_stop_callback = register_should_stop_callback
		self.register_external_agent_status_raise_error_callback = register_external_agent_status_raise_error_callback

		# Telemetry
		self.telemetry = ProductTelemetry()

		# Event bus with WAL persistence
		# Default to ~/.config/browseruse/events/{agent_session_id}.jsonl
		# wal_path = CONFIG.BROWSER_USE_CONFIG_DIR / 'events' / f'{self.session_id}.jsonl'
		self.eventbus = EventBus(name=f'Agent_{str(self.id)[-4:]}')

		if self.settings.save_conversation_path:
			self.settings.save_conversation_path = Path(self.settings.save_conversation_path).expanduser().resolve()
			self.logger.info(f'💬 Saving conversation to {_log_pretty_path(self.settings.save_conversation_path)}')

		# Initialize download tracking
		assert self.browser_session is not None, 'BrowserSession is not set up'
		self.has_downloads_path = self.browser_session.browser_profile.downloads_path is not None
		if self.has_downloads_path:
			self._last_known_downloads: list[str] = []
			self.logger.debug('📁 Initialized download tracking for agent')

		# Event-based pause control (kept out of AgentState for serialization)
		self._external_pause_event = asyncio.Event()
		self._external_pause_event.set()

	def _enhance_task_with_schema(self, task: str, output_model_schema: type[AgentStructuredOutput] | None) -> str:
		"""Enhance task description with output schema information if provided."""
		if output_model_schema is None:
			return task

		try:
			schema = output_model_schema.model_json_schema()
			import json

			schema_json = json.dumps(schema, indent=2)

			enhancement = f'\nExpected output format: {output_model_schema.__name__}\n{schema_json}'
			return task + enhancement
		except Exception as e:
			self.logger.debug(f'Could not parse output schema: {e}')

		return task

	@property
	def logger(self) -> logging.Logger:
		"""Get instance-specific logger with task ID in the name"""
		# logger may be called in __init__ so we don't assume self.* attributes have been initialized
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
			self.logger.debug(f'📁 No new downloads detected (tracking {len(current_files)} files)')

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
				self.logger.debug(f'💾 File system restored from state to: {self.file_system_path}')
				return
			except Exception as e:
				self.logger.error(f'💾 Failed to restore file system from state: {e}')
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
			self.logger.error(f'💾 Failed to initialize file system: {e}.')
			raise e

		# Save file system state to agent state
		self.state.file_system_state = self.file_system.get_state()

		self.logger.debug(f'💾 File system path: {self.file_system_path}')

	def _set_screenshot_service(self) -> None:
		"""Initialize screenshot service using agent directory"""
		try:
			from browser_use.screenshots.service import ScreenshotService

			self.screenshot_service = ScreenshotService(self.agent_directory)
			self.logger.debug(f'📸 Screenshot service initialized in: {self.agent_directory}/screenshots')
		except Exception as e:
			self.logger.error(f'📸 Failed to initialize screenshot service: {e}.')
			raise e

	def save_file_system_state(self) -> None:
		"""Save current file system state to agent state"""
		if self.file_system:
			self.state.file_system_state = self.file_system.get_state()
		else:
			self.logger.error('💾 File system is not set up. Cannot save state.')
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

	def _setup_action_models(self) -> None:
		"""Setup dynamic action models from tools registry"""
		# Initially only include actions with no filters
		self.ActionModel = self.tools.registry.create_action_model()
		# Create output model with the dynamic actions
		if self.settings.flash_mode:
			self.AgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.ActionModel)
		elif self.settings.use_thinking:
			self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)
		else:
			self.AgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.ActionModel)

		# used to force the done action when max_steps is reached
		self.DoneActionModel = self.tools.registry.create_action_model(include_actions=['done'])
		if self.settings.flash_mode:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.DoneActionModel)
		elif self.settings.use_thinking:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions(self.DoneActionModel)
		else:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.DoneActionModel)

	def _get_skill_slug(self, skill: 'Skill', all_skills: list['Skill']) -> str:
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
		import re

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

	def add_new_task(self, new_task: str) -> None:
		"""Add a new task to the agent, keeping the same task_id as tasks are continuous"""
		# Simply delegate to message manager - no need for new task_id or events
		# The task continues with new instructions, it doesn't end and start a new one
		self.task = new_task
		self._message_manager.add_new_task(new_task)
		# Mark as follow-up task and recreate eventbus (gets shut down after each run)
		self.state.follow_up_task = True
		# Reset control flags so agent can continue
		self.state.stopped = False
		self.state.paused = False
		agent_id_suffix = str(self.id)[-4:].replace('-', '_')
		if agent_id_suffix and agent_id_suffix[0].isdigit():
			agent_id_suffix = 'a' + agent_id_suffix
		self.eventbus = EventBus(name=f'Agent_{agent_id_suffix}')

	async def _check_stop_or_pause(self) -> None:
		"""Check if the agent should stop or pause, and handle accordingly."""

		# Check new should_stop_callback - sets stopped state cleanly without raising
		if self.register_should_stop_callback:
			if await self.register_should_stop_callback():
				self.logger.info('External callback requested stop')
				self.state.stopped = True
				raise InterruptedError

		if self.register_external_agent_status_raise_error_callback:
			if await self.register_external_agent_status_raise_error_callback():
				raise InterruptedError

		if self.state.stopped:
			raise InterruptedError

		if self.state.paused:
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
		self.logger.debug('📸 Requesting browser state with include_screenshot=True')
		browser_state_summary = await self.browser_session.get_browser_state_summary(
			include_screenshot=True,  # always capture even if use_vision=False so that cloud sync is useful (it's fast now anyway)
			include_recent_events=self.include_recent_events,
		)
		if browser_state_summary.screenshot:
			self.logger.debug(f'📸 Got browser state WITH screenshot, length: {len(browser_state_summary.screenshot)}')
		else:
			self.logger.debug('📸 Got browser state WITHOUT screenshot')

		# Check for new downloads after getting browser state (catches PDF auto-downloads and previous step downloads)
		await self._check_and_update_downloads(f'Step {self.state.n_steps}: after getting browser state')

		self._log_step_context(browser_state_summary)
		await self._check_stop_or_pause()

		# Update action models with page-specific actions
		self.logger.debug(f'📝 Step {self.state.n_steps}: Updating action models...')
		await self._update_action_models_for_page(browser_state_summary.url)

		# Get page-specific filtered actions
		page_filtered_actions = self.tools.registry.get_prompt_description(browser_state_summary.url)

		# Page-specific actions will be included directly in the browser_state message
		self.logger.debug(f'💬 Step {self.state.n_steps}: Creating state messages for context...')

		# Get unavailable skills info if skills service is enabled
		unavailable_skills_info = None
		if self.skill_service is not None:
			unavailable_skills_info = await self._get_unavailable_skills_info()

		self._message_manager.create_state_messages(
			browser_state_summary=browser_state_summary,
			model_output=self.state.last_model_output,
			result=self.state.last_result,
			step_info=step_info,
			use_vision=self.settings.use_vision,
			page_filtered_actions=page_filtered_actions if page_filtered_actions else None,
			sensitive_data=self.sensitive_data,
			available_file_paths=self.available_file_paths,  # Always pass current available_file_paths
			unavailable_skills_info=unavailable_skills_info,
		)

		await self._force_done_after_last_step(step_info)
		await self._force_done_after_failure()
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
		await self._check_stop_or_pause()

		# Handle callbacks and conversation saving
		await self._handle_post_llm_processing(browser_state_summary, input_messages)

		# check again if Ctrl+C was pressed before we commit the output to history
		await self._check_stop_or_pause()

	async def _execute_actions(self) -> None:
		"""Execute the actions from model output"""
		if self.state.last_model_output is None:
			raise ValueError('No model output to execute actions from')

		result = await self.multi_act(self.state.last_model_output.action)
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

		if self.state.consecutive_failures > 0:
			self.state.consecutive_failures = 0
			self.logger.debug(f'🔄 Step {self.state.n_steps}: Consecutive failures reset to: {self.state.consecutive_failures}')

		# Log completion results
		if self.state.last_result and len(self.state.last_result) > 0 and self.state.last_result[-1].is_done:
			success = self.state.last_result[-1].success
			if success:
				# Green color for success
				self.logger.info(f'\n📄 \033[32m Final Result:\033[0m \n{self.state.last_result[-1].extracted_content}\n\n')
			else:
				# Red color for failure
				self.logger.info(f'\n📄 \033[31m Final Result:\033[0m \n{self.state.last_result[-1].extracted_content}\n\n')
			if self.state.last_result[-1].attachments:
				total_attachments = len(self.state.last_result[-1].attachments)
				for i, file_path in enumerate(self.state.last_result[-1].attachments):
					self.logger.info(f'👉 Attachment {i + 1 if total_attachments > 1 else ""}: {file_path}')

	async def _handle_step_error(self, error: Exception) -> None:
		"""Handle all types of errors that can occur during a step"""

		# Handle InterruptedError specially
		if isinstance(error, InterruptedError):
			error_msg = 'The agent was interrupted mid-step' + (f' - {str(error)}' if str(error) else '')
			# NOTE: This is not an error, it's a normal part of the execution when the user interrupts the agent
			self.logger.warning(f'{error_msg}')
			return

		# Handle all other exceptions
		include_trace = self.logger.isEnabledFor(logging.DEBUG)
		error_msg = AgentError.format_error(error, include_trace=include_trace)
		max_total_failures = self.settings.max_failures + int(self.settings.final_response_after_failure)
		prefix = f'❌ Result failed {self.state.consecutive_failures + 1}/{max_total_failures} times: '
		self.state.consecutive_failures += 1

		# Use WARNING for partial failures, ERROR only when max failures reached
		is_final_failure = self.state.consecutive_failures >= max_total_failures
		log_level = logging.ERROR if is_final_failure else logging.WARNING

		if 'Could not parse response' in error_msg or 'tool_use_failed' in error_msg:
			# give model a hint how output should look like
			self.logger.log(log_level, f'Model: {self.llm.model} failed')
			self.logger.log(log_level, f'{prefix}{error_msg}')
		else:
			self.logger.log(log_level, f'{prefix}{error_msg}')

		await self._demo_mode_log(f'Step error: {error_msg}', 'error', {'step': self.state.n_steps})
		self.state.last_result = [ActionResult(error=error_msg)]
		return None

	async def _finalize(self, browser_state_summary: BrowserStateSummary | None) -> None:
		"""Finalize the step with history, logging, and events"""
		step_end_time = time.time()
		if not self.state.last_result:
			return

		if browser_state_summary:
			step_interval = None
			if len(self.history.history) > 0:
				last_history_item = self.history.history[-1]

				if last_history_item.metadata:
					previous_end_time = last_history_item.metadata.step_end_time
					previous_start_time = last_history_item.metadata.step_start_time
					step_interval = max(0, previous_end_time - previous_start_time)
			metadata = StepMetadata(
				step_number=self.state.n_steps,
				step_start_time=self.step_start_time,
				step_end_time=step_end_time,
				step_interval=step_interval,
			)

			# Use _make_history_item like main branch
			await self._make_history_item(
				self.state.last_model_output,
				browser_state_summary,
				self.state.last_result,
				metadata,
				state_message=self._message_manager.last_state_message_text,
			)

		# Log step completion summary
		summary_message = self._log_step_completion_summary(self.step_start_time, self.state.last_result)
		if summary_message:
			await self._demo_mode_log(summary_message, 'info', {'step': self.state.n_steps})

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

	async def _force_done_after_last_step(self, step_info: AgentStepInfo | None = None) -> None:
		"""Handle special processing for the last step"""
		if step_info and step_info.is_last_step():
			# Add last step warning if needed
			msg = 'You reached max_steps - this is your last step. Your only tool available is the "done" tool. No other tool is available. All other tools which you see in history or examples are not available.'
			msg += '\nIf the task is not yet fully finished as requested by the user, set success in "done" to false! E.g. if not all steps are fully completed. Else success to true.'
			msg += '\nInclude everything you found out for the ultimate task in the done text.'
			self.logger.debug('Last step finishing up')
			self._message_manager._add_context_message(UserMessage(content=msg))
			self.AgentOutput = self.DoneAgentOutput

	async def _force_done_after_failure(self) -> None:
		"""Force done after failure"""
		# Create recovery message
		if self.state.consecutive_failures >= self.settings.max_failures and self.settings.final_response_after_failure:
			msg = f'You failed {self.settings.max_failures} times. Therefore we terminate the agent.'
			msg += '\nYour only tool available is the "done" tool. No other tool is available. All other tools which you see in history or examples are not available.'
			msg += '\nIf the task is not yet fully finished as requested by the user, set success in "done" to false! E.g. if not all steps are fully completed. Else success to true.'
			msg += '\nInclude everything you found out for the ultimate task in the done text.'

			self.logger.debug('Force done action, because we reached max_failures.')
			self._message_manager._add_context_message(UserMessage(content=msg))
			self.AgentOutput = self.DoneAgentOutput

	@observe(ignore_input=True, ignore_output=False)
	async def _judge_trace(self) -> JudgementResult | None:
		"""Judge the trace of the agent"""
		task = self.task
		final_result = self.history.final_result() or ''
		agent_steps = self.history.agent_steps()
		screenshot_paths = [p for p in self.history.screenshot_paths() if p is not None]

		# Construct input messages for judge evaluation
		input_messages = construct_judge_messages(
			task=task,
			final_result=final_result,
			agent_steps=agent_steps,
			screenshot_paths=screenshot_paths,
			max_images=10,
			ground_truth=self.settings.ground_truth,
		)

		# Call LLM with JudgementResult as output format
		kwargs: dict = {'output_format': JudgementResult}

		# Only pass request_type for ChatBrowserUse (other providers don't support it)
		if self.judge_llm.provider == 'browser-use':
			kwargs['request_type'] = 'judge'

		try:
			response = await self.judge_llm.ainvoke(input_messages, **kwargs)
			judgement: JudgementResult = response.completion  # type: ignore[assignment]
			return judgement
		except Exception as e:
			self.logger.error(f'Judge trace failed: {e}')
			# Return a default judgement on failure
			return None

	async def _judge_and_log(self) -> None:
		"""Run judge evaluation and log the verdict"""
		judgement = await self._judge_trace()

		# Attach judgement to last action result
		if self.history.history[-1].result[-1].is_done:
			last_result = self.history.history[-1].result[-1]
			last_result.judgement = judgement

			# Get self-reported success
			self_reported_success = last_result.success

			# Log the verdict based on self-reported success and judge verdict
			if judgement:
				# If both self-reported and judge agree on success, don't log
				if self_reported_success is True and judgement.verdict is True:
					return

				judge_log = '\n'
				# If agent reported success but judge thinks it failed, show warning
				if self_reported_success is True and judgement.verdict is False:
					judge_log += '⚠️  \033[33mAgent reported success but judge thinks task failed\033[0m\n'

				# Otherwise, show full judge result
				verdict_color = '\033[32m' if judgement.verdict else '\033[31m'
				verdict_text = '✅ PASS' if judgement.verdict else '❌ FAIL'
				judge_log += f'⚖️  {verdict_color}Judge Verdict: {verdict_text}\033[0m\n'
				if judgement.failure_reason:
					judge_log += f'   Failure Reason: {judgement.failure_reason}\n'
				if judgement.reached_captcha:
					judge_log += '   🤖 Captcha Detected: Agent encountered captcha challenges\n'
					judge_log += '   👉 🥷 Use Browser Use Cloud for the most stealth browser infra: https://docs.browser-use.com/customize/browser/remote\n'
				judge_log += f'   {judgement.reasoning}\n'
				self.logger.info(judge_log)

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
				content='You forgot to return an action. Please respond with a valid JSON action according to the expected schema with your assessment and next actions.'
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
		state_message: str | None = None,
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
			state_message=state_message,
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

	# region - URL replacement
	def _replace_urls_in_text(self, text: str) -> tuple[str, dict[str, str]]:
		"""Replace URLs in a text string"""

		replaced_urls: dict[str, str] = {}

		def replace_url(match: re.Match) -> str:
			"""Url can only have 1 query and 1 fragment"""
			import hashlib

			original_url = match.group(0)

			# Find where the query/fragment starts
			query_start = original_url.find('?')
			fragment_start = original_url.find('#')

			# Find the earliest position of query or fragment
			after_path_start = len(original_url)  # Default: no query/fragment
			if query_start != -1:
				after_path_start = min(after_path_start, query_start)
			if fragment_start != -1:
				after_path_start = min(after_path_start, fragment_start)

			# Split URL into base (up to path) and after_path (query + fragment)
			base_url = original_url[:after_path_start]
			after_path = original_url[after_path_start:]

			# If after_path is within the limit, don't shorten
			if len(after_path) <= self._url_shortening_limit:
				return original_url

			# If after_path is too long, truncate and add hash
			if after_path:
				truncated_after_path = after_path[: self._url_shortening_limit]
				# Create a short hash of the full after_path content
				hash_obj = hashlib.md5(after_path.encode('utf-8'))
				short_hash = hash_obj.hexdigest()[:7]
				# Create shortened URL
				shortened = f'{base_url}{truncated_after_path}...{short_hash}'
				# Only use shortened URL if it's actually shorter than the original
				if len(shortened) < len(original_url):
					replaced_urls[shortened] = original_url
					return shortened

			return original_url

		return URL_PATTERN.sub(replace_url, text), replaced_urls

	def _process_messsages_and_replace_long_urls_shorter_ones(self, input_messages: list[BaseMessage]) -> dict[str, str]:
		"""Replace long URLs with shorter ones
		? @dev edits input_messages in place

		returns:
			tuple[filtered_input_messages, urls we replaced {shorter_url: original_url}]
		"""
		from browser_use.llm.messages import AssistantMessage, UserMessage

		urls_replaced: dict[str, str] = {}

		# Process each message, in place
		for message in input_messages:
			# no need to process SystemMessage, we have control over that anyway
			if isinstance(message, (UserMessage, AssistantMessage)):
				if isinstance(message.content, str):
					# Simple string content
					message.content, replaced_urls = self._replace_urls_in_text(message.content)
					urls_replaced.update(replaced_urls)

				elif isinstance(message.content, list):
					# List of content parts
					for part in message.content:
						if isinstance(part, ContentPartTextParam):
							part.text, replaced_urls = self._replace_urls_in_text(part.text)
							urls_replaced.update(replaced_urls)

		return urls_replaced

	@staticmethod
	def _recursive_process_all_strings_inside_pydantic_model(model: BaseModel, url_replacements: dict[str, str]) -> None:
		"""Recursively process all strings inside a Pydantic model, replacing shortened URLs with originals in place."""
		for field_name, field_value in model.__dict__.items():
			if isinstance(field_value, str):
				# Replace shortened URLs with original URLs in string
				processed_string = Agent._replace_shortened_urls_in_string(field_value, url_replacements)
				setattr(model, field_name, processed_string)
			elif isinstance(field_value, BaseModel):
				# Recursively process nested Pydantic models
				Agent._recursive_process_all_strings_inside_pydantic_model(field_value, url_replacements)
			elif isinstance(field_value, dict):
				# Process dictionary values in place
				Agent._recursive_process_dict(field_value, url_replacements)
			elif isinstance(field_value, (list, tuple)):
				processed_value = Agent._recursive_process_list_or_tuple(field_value, url_replacements)
				setattr(model, field_name, processed_value)

	@staticmethod
	def _recursive_process_dict(dictionary: dict, url_replacements: dict[str, str]) -> None:
		"""Helper method to process dictionaries."""
		for k, v in dictionary.items():
			if isinstance(v, str):
				dictionary[k] = Agent._replace_shortened_urls_in_string(v, url_replacements)
			elif isinstance(v, BaseModel):
				Agent._recursive_process_all_strings_inside_pydantic_model(v, url_replacements)
			elif isinstance(v, dict):
				Agent._recursive_process_dict(v, url_replacements)
			elif isinstance(v, (list, tuple)):
				dictionary[k] = Agent._recursive_process_list_or_tuple(v, url_replacements)

	@staticmethod
	def _recursive_process_list_or_tuple(container: list | tuple, url_replacements: dict[str, str]) -> list | tuple:
		"""Helper method to process lists and tuples."""
		if isinstance(container, tuple):
			# For tuples, create a new tuple with processed items
			processed_items = []
			for item in container:
				if isinstance(item, str):
					processed_items.append(Agent._replace_shortened_urls_in_string(item, url_replacements))
				elif isinstance(item, BaseModel):
					Agent._recursive_process_all_strings_inside_pydantic_model(item, url_replacements)
					processed_items.append(item)
				elif isinstance(item, dict):
					Agent._recursive_process_dict(item, url_replacements)
					processed_items.append(item)
				elif isinstance(item, (list, tuple)):
					processed_items.append(Agent._recursive_process_list_or_tuple(item, url_replacements))
				else:
					processed_items.append(item)
			return tuple(processed_items)
		else:
			# For lists, modify in place
			for i, item in enumerate(container):
				if isinstance(item, str):
					container[i] = Agent._replace_shortened_urls_in_string(item, url_replacements)
				elif isinstance(item, BaseModel):
					Agent._recursive_process_all_strings_inside_pydantic_model(item, url_replacements)
				elif isinstance(item, dict):
					Agent._recursive_process_dict(item, url_replacements)
				elif isinstance(item, (list, tuple)):
					container[i] = Agent._recursive_process_list_or_tuple(item, url_replacements)
			return container

	@staticmethod
	def _replace_shortened_urls_in_string(text: str, url_replacements: dict[str, str]) -> str:
		"""Replace all shortened URLs in a string with their original URLs."""
		result = text
		for shortened_url, original_url in url_replacements.items():
			result = result.replace(shortened_url, original_url)
		return result

	# endregion - URL replacement

	@time_execution_async('--get_next_action')
	@observe_debug(ignore_input=True, ignore_output=True, name='get_model_output')
	async def get_model_output(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get next action from LLM based on current state"""

		urls_replaced = self._process_messsages_and_replace_long_urls_shorter_ones(input_messages)

		# Build kwargs for ainvoke
		# Note: ChatBrowserUse will automatically generate action descriptions from output_format schema
		kwargs: dict = {'output_format': self.AgentOutput}

		try:
			response = await self.llm.ainvoke(input_messages, **kwargs)
			parsed: AgentOutput = response.completion  # type: ignore[assignment]

			# Replace any shortened URLs in the LLM response back to original URLs
			if urls_replaced:
				self._recursive_process_all_strings_inside_pydantic_model(parsed, urls_replaced)

			# cut the number of actions to max_actions_per_step if needed
			if len(parsed.action) > self.settings.max_actions_per_step:
				parsed.action = parsed.action[: self.settings.max_actions_per_step]

			if not (hasattr(self.state, 'paused') and (self.state.paused or self.state.stopped)):
				log_response(parsed, self.tools.registry.registry, self.logger)
				await self._broadcast_model_state(parsed)

			self._log_next_action_summary(parsed)
			return parsed
		except ValidationError:
			# Just re-raise - Pydantic's validation errors are already descriptive
			raise
		except (ModelRateLimitError, ModelProviderError) as e:
			# Check if we can switch to a fallback LLM
			if not self._try_switch_to_fallback_llm(e):
				# No fallback available, re-raise the original error
				raise
			# Retry with the fallback LLM
			return await self.get_model_output(input_messages)

	def _try_switch_to_fallback_llm(self, error: ModelRateLimitError | ModelProviderError) -> bool:
		"""
		Attempt to switch to a fallback LLM after a rate limit or provider error.

		Returns True if successfully switched to a fallback, False if no fallback available.
		Once switched, the agent will use the fallback LLM for the rest of the run.
		"""
		# Already using fallback - can't switch again
		if self._using_fallback_llm:
			self.logger.warning(
				f'⚠️ Fallback LLM also failed ({type(error).__name__}: {error.message}), no more fallbacks available'
			)
			return False

		# Check if error is retryable (rate limit, auth errors, or server errors)
		# 401: API key invalid/expired - fallback to different provider
		# 402: Insufficient credits/payment required - fallback to different provider
		# 429: Rate limit exceeded
		# 500, 502, 503, 504: Server errors
		retryable_status_codes = {401, 402, 429, 500, 502, 503, 504}
		is_retryable = isinstance(error, ModelRateLimitError) or (
			hasattr(error, 'status_code') and error.status_code in retryable_status_codes
		)

		if not is_retryable:
			return False

		# Check if we have a fallback LLM configured
		if self._fallback_llm is None:
			self.logger.warning(f'⚠️ LLM error ({type(error).__name__}: {error.message}) but no fallback_llm configured')
			return False

		self._log_fallback_switch(error, self._fallback_llm)

		# Switch to the fallback LLM
		self.llm = self._fallback_llm
		self._using_fallback_llm = True

		# Register the fallback LLM for token cost tracking
		self.token_cost_service.register_llm(self._fallback_llm)

		return True

	def _log_fallback_switch(self, error: ModelRateLimitError | ModelProviderError, fallback: BaseChatModel) -> None:
		"""Log when switching to a fallback LLM."""
		original_model = self._original_llm.model if hasattr(self._original_llm, 'model') else 'unknown'
		fallback_model = fallback.model if hasattr(fallback, 'model') else 'unknown'
		error_type = type(error).__name__
		status_code = getattr(error, 'status_code', 'N/A')

		self.logger.warning(
			f'⚠️ Primary LLM ({original_model}) failed with {error_type} (status={status_code}), '
			f'switching to fallback LLM ({fallback_model})'
		)

	async def _log_agent_run(self) -> None:
		"""Log the agent run"""
		# Blue color for task
		self.logger.info(f'\033[34m🎯 Task: {self.task}\033[0m')

		self.logger.debug(f'🤖 Browser-Use Library Version {self.version} ({self.source})')

		# Check for latest version and log upgrade message if needed
		if CONFIG.BROWSER_USE_VERSION_CHECK:
			latest_version = await check_latest_browser_use_version()
			if latest_version and latest_version != self.version:
				self.logger.info(
					f'📦 Newer version available: {latest_version} (current: {self.version}). Upgrade with: uv add browser-use=={latest_version}'
				)

	def _log_first_step_startup(self) -> None:
		"""Log startup message only on the first step"""
		if len(self.history.history) == 0:
			self.logger.info(
				f'Starting a browser-use agent with version {self.version}, with provider={self.llm.provider} and model={self.llm.model}'
			)

	def _log_step_context(self, browser_state_summary: BrowserStateSummary) -> None:
		"""Log step context information"""
		url = browser_state_summary.url if browser_state_summary else ''
		url_short = url[:50] + '...' if len(url) > 50 else url
		interactive_count = len(browser_state_summary.dom_state.selector_map) if browser_state_summary else 0
		self.logger.info('\n')
		self.logger.info(f'📍 Step {self.state.n_steps}:')
		self.logger.debug(f'Evaluating page with {interactive_count} interactive elements on: {url_short}')

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

	def _prepare_demo_message(self, message: str, limit: int = 600) -> str:
		# Previously truncated long entries; keep full text for better context in demo panel
		return message.strip()

	async def _demo_mode_log(self, message: str, level: str = 'info', metadata: dict[str, Any] | None = None) -> None:
		if not self._demo_mode_enabled or not message or self.browser_session is None:
			return
		try:
			await self.browser_session.send_demo_mode_log(
				message=self._prepare_demo_message(message),
				level=level,
				metadata=metadata or {},
			)
		except Exception as exc:
			self.logger.debug(f'[DemoMode] Failed to send overlay log: {exc}')

	async def _broadcast_model_state(self, parsed: 'AgentOutput') -> None:
		if not self._demo_mode_enabled:
			return

		state = parsed.current_state
		step_meta = {'step': self.state.n_steps}

		if state.thinking:
			await self._demo_mode_log(state.thinking, 'thought', step_meta)

		if state.evaluation_previous_goal:
			eval_text = state.evaluation_previous_goal
			level = 'success' if 'success' in eval_text.lower() else 'warning' if 'failure' in eval_text.lower() else 'info'
			await self._demo_mode_log(eval_text, level, step_meta)

		if state.memory:
			await self._demo_mode_log(f'Memory: {state.memory}', 'info', step_meta)

		if state.next_goal:
			await self._demo_mode_log(f'Next goal: {state.next_goal}', 'info', step_meta)

	def _log_step_completion_summary(self, step_start_time: float, result: list[ActionResult]) -> str | None:
		"""Log step completion summary with action count, timing, and success/failure stats"""
		if not result:
			return None

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

		message = (
			f'📍 Step {self.state.n_steps}: Ran {action_count} action{"" if action_count == 1 else "s"} '
			f'in {step_duration:.2f}s: {status_str}'
		)
		self.logger.debug(message)
		return message

	def _log_final_outcome_messages(self) -> None:
		"""Log helpful messages to user based on agent run outcome"""
		# Check if agent failed
		is_successful = self.history.is_successful()

		if is_successful is False or is_successful is None:
			# Get final result to check for specific failure reasons
			final_result = self.history.final_result()
			final_result_str = str(final_result).lower() if final_result else ''

			# Check for captcha/cloudflare related failures
			captcha_keywords = ['captcha', 'cloudflare', 'recaptcha', 'challenge', 'bot detection', 'access denied']
			has_captcha_issue = any(keyword in final_result_str for keyword in captcha_keywords)

			if has_captcha_issue:
				# Suggest use_cloud=True for captcha/cloudflare issues
				task_preview = self.task[:10] if len(self.task) > 10 else self.task
				self.logger.info('')
				self.logger.info('Failed because of CAPTCHA? For better browser stealth, try:')
				self.logger.info(f'   agent = Agent(task="{task_preview}...", browser=Browser(use_cloud=True))')

			# General failure message
			self.logger.info('')
			self.logger.info('Did the Agent not work as expected? Let us fix this!')
			self.logger.info('   Open a short issue on GitHub: https://github.com/browser-use/browser-use/issues')

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

		# Extract judgement data if available
		judgement_data = self.history.judgement()
		judge_verdict = judgement_data.get('verdict') if judgement_data else None
		judge_reasoning = judgement_data.get('reasoning') if judgement_data else None
		judge_failure_reason = judgement_data.get('failure_reason') if judgement_data else None
		judge_reached_captcha = judgement_data.get('reached_captcha') if judgement_data else None
		judge_impossible_task = judgement_data.get('impossible_task') if judgement_data else None

		self.telemetry.capture(
			AgentTelemetryEvent(
				task=self.task,
				model=self.llm.model,
				model_provider=self.llm.provider,
				max_steps=max_steps,
				max_actions_per_step=self.settings.max_actions_per_step,
				use_vision=self.settings.use_vision,
				version=self.version,
				source=self.source,
				cdp_url=urlparse(self.browser_session.cdp_url).hostname
				if self.browser_session and self.browser_session.cdp_url
				else None,
				agent_type=None,  # Regular Agent (not code-use)
				action_errors=self.history.errors(),
				action_history=action_history_data,
				urls_visited=self.history.urls(),
				steps=self.state.n_steps,
				total_input_tokens=token_summary.prompt_tokens,
				total_output_tokens=token_summary.completion_tokens,
				prompt_cached_tokens=token_summary.prompt_cached_tokens,
				total_tokens=token_summary.total_tokens,
				total_duration_seconds=self.history.total_duration_seconds(),
				success=self.history.is_successful(),
				final_result_response=final_result_str,
				error_message=agent_run_error,
				judge_verdict=judge_verdict,
				judge_reasoning=judge_reasoning,
				judge_failure_reason=judge_failure_reason,
				judge_reached_captcha=judge_reached_captcha,
				judge_impossible_task=judge_impossible_task,
			)
		)

	async def take_step(self, step_info: AgentStepInfo | None = None) -> tuple[bool, bool]:
		"""Take a step

		Returns:
		        Tuple[bool, bool]: (is_done, is_valid)
		"""
		if step_info is not None and step_info.step_number == 0:
			# First step
			self._log_first_step_startup()
			# Normally there was no try catch here but the callback can raise an InterruptedError which we skip
			try:
				await self._execute_initial_actions()
			except InterruptedError:
				pass
			except Exception as e:
				raise e

		await self.step(step_info)

		if self.history.is_done():
			await self.log_completion()

			# Run judge before done callback if enabled
			if self.settings.use_judge:
				await self._judge_and_log()

			if self.register_done_callback:
				if inspect.iscoroutinefunction(self.register_done_callback):
					await self.register_done_callback(self.history)
				else:
					self.register_done_callback(self.history)
			return True, True

		return False, False

	def _extract_start_url(self, task: str) -> str | None:
		"""Extract URL from task string using naive pattern matching."""

		import re

		# Remove email addresses from task before looking for URLs
		task_without_emails = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', task)

		# Look for common URL patterns
		patterns = [
			r'https?://[^\s<>"\']+',  # Full URLs with http/https
			r'(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}(?:/[^\s<>"\']*)?',  # Domain names with subdomains and optional paths
		]

		# File extensions that should be excluded from URL detection
		# These are likely files rather than web pages to navigate to
		excluded_extensions = {
			# Documents
			'pdf',
			'doc',
			'docx',
			'xls',
			'xlsx',
			'ppt',
			'pptx',
			'odt',
			'ods',
			'odp',
			# Text files
			'txt',
			'md',
			'csv',
			'json',
			'xml',
			'yaml',
			'yml',
			# Archives
			'zip',
			'rar',
			'7z',
			'tar',
			'gz',
			'bz2',
			'xz',
			# Images
			'jpg',
			'jpeg',
			'png',
			'gif',
			'bmp',
			'svg',
			'webp',
			'ico',
			# Audio/Video
			'mp3',
			'mp4',
			'avi',
			'mkv',
			'mov',
			'wav',
			'flac',
			'ogg',
			# Code/Data
			'py',
			'js',
			'css',
			'java',
			'cpp',
			# Academic/Research
			'bib',
			'bibtex',
			'tex',
			'latex',
			'cls',
			'sty',
			# Other common file types
			'exe',
			'msi',
			'dmg',
			'pkg',
			'deb',
			'rpm',
			'iso',
			# GitHub/Project paths
			'polynomial',
		}

		excluded_words = {
			'never',
			'dont',
			'not',
			"don't",
		}

		found_urls = []
		for pattern in patterns:
			matches = re.finditer(pattern, task_without_emails)
			for match in matches:
				url = match.group(0)
				original_position = match.start()  # Store original position before URL modification

				# Remove trailing punctuation that's not part of URLs
				url = re.sub(r'[.,;:!?()\[\]]+$', '', url)

				# Check if URL ends with a file extension that should be excluded
				url_lower = url.lower()
				should_exclude = False
				for ext in excluded_extensions:
					if f'.{ext}' in url_lower:
						should_exclude = True
						break

				if should_exclude:
					self.logger.debug(f'Excluding URL with file extension from auto-navigation: {url}')
					continue

				# If in the 20 characters before the url position is a word in excluded_words skip to avoid "Never go to this url"
				context_start = max(0, original_position - 20)
				context_text = task_without_emails[context_start:original_position]
				if any(word.lower() in context_text.lower() for word in excluded_words):
					self.logger.debug(
						f'Excluding URL with word in excluded words from auto-navigation: {url} (context: "{context_text.strip()}")'
					)
					continue

				# Add https:// if missing (after excluded words check to avoid position calculation issues)
				if not url.startswith(('http://', 'https://')):
					url = 'https://' + url

				found_urls.append(url)

		unique_urls = list(set(found_urls))
		# If multiple URLs found, skip directly_open_urling
		if len(unique_urls) > 1:
			self.logger.debug(f'Multiple URLs found ({len(found_urls)}), skipping directly_open_url to avoid ambiguity')
			return None

		# If exactly one URL found, return it
		if len(unique_urls) == 1:
			return unique_urls[0]

		return None

	async def _execute_step(
		self,
		step: int,
		max_steps: int,
		step_info: AgentStepInfo,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> bool:
		"""
		Execute a single step with timeout.

		Returns:
			bool: True if task is done, False otherwise
		"""
		if on_step_start is not None:
			await on_step_start(self)

		await self._demo_mode_log(
			f'Starting step {step + 1}/{max_steps}',
			'info',
			{'step': step + 1, 'total_steps': max_steps},
		)

		self.logger.debug(f'🚶 Starting step {step + 1}/{max_steps}...')

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
			await self._demo_mode_log(error_msg, 'error', {'step': step + 1})
			self.state.consecutive_failures += 1
			self.state.last_result = [ActionResult(error=error_msg)]

		if on_step_end is not None:
			await on_step_end(self)

		if self.history.is_done():
			await self.log_completion()

			# Run judge before done callback if enabled
			if self.settings.use_judge:
				await self._judge_and_log()

			if self.register_done_callback:
				if inspect.iscoroutinefunction(self.register_done_callback):
					await self.register_done_callback(self.history)
				else:
					self.register_done_callback(self.history)

			return True

		return False

	@observe(name='agent.run', ignore_input=True, ignore_output=True)
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
		should_delay_close = False

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
			await self._log_agent_run()

			self.logger.debug(
				f'🔧 Agent setup: Agent Session ID {self.session_id[-4:]}, Task ID {self.task_id[-4:]}, Browser Session ID {self.browser_session.id[-4:] if self.browser_session else "None"} {"(connecting via CDP)" if (self.browser_session and self.browser_session.cdp_url) else "(launching local browser)"}'
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

			# Log startup message on first step (only if we haven't already done steps)
			self._log_first_step_startup()
			# Start browser session and attach watchdogs
			await self.browser_session.start()
			if self._demo_mode_enabled:
				await self._demo_mode_log(f'Started task: {self.task}', 'info', {'tag': 'task'})
				await self._demo_mode_log(
					'Demo mode active - follow the side panel for live thoughts and actions.',
					'info',
					{'tag': 'status'},
				)

			# Register skills as actions if SkillService is configured
			await self._register_skills_as_actions()

			# Normally there was no try catch here but the callback can raise an InterruptedError
			try:
				await self._execute_initial_actions()
			except InterruptedError:
				pass
			except Exception as e:
				raise e

			self.logger.debug(
				f'🔄 Starting main execution loop with max {max_steps} steps (currently at step {self.state.n_steps})...'
			)
			while self.state.n_steps <= max_steps:
				current_step = self.state.n_steps - 1  # Convert to 0-indexed for step_info

				# Use the consolidated pause state management
				if self.state.paused:
					self.logger.debug(f'⏸️ Step {self.state.n_steps}: Agent paused, waiting to resume...')
					await self._external_pause_event.wait()
					signal_handler.reset()

				# Check if we should stop due to too many failures, if final_response_after_failure is True, we try one last time
				if (self.state.consecutive_failures) >= self.settings.max_failures + int(
					self.settings.final_response_after_failure
				):
					self.logger.error(f'❌ Stopping due to {self.settings.max_failures} consecutive failures')
					agent_run_error = f'Stopped due to {self.settings.max_failures} consecutive failures'
					break

				# Check control flags before each step
				if self.state.stopped:
					self.logger.info('🛑 Agent stopped')
					agent_run_error = 'Agent stopped programmatically'
					break

				step_info = AgentStepInfo(step_number=current_step, max_steps=max_steps)
				is_done = await self._execute_step(current_step, max_steps, step_info, on_step_start, on_step_end)

				if is_done:
					# Agent has marked the task as done
					if self._demo_mode_enabled and self.history.history:
						final_result_text = self.history.final_result() or 'Task completed'
						await self._demo_mode_log(f'Final Result: {final_result_text}', 'success', {'tag': 'task'})

					should_delay_close = True
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

			self.history.usage = await self.token_cost_service.get_usage_summary()

			# set the model output schema and call it on the fly
			if self.history._output_model_schema is None and self.output_model_schema is not None:
				self.history._output_model_schema = self.output_model_schema

			return self.history

		except KeyboardInterrupt:
			# Already handled by our signal handler, but catch any direct KeyboardInterrupt as well
			self.logger.debug('Got KeyboardInterrupt during execution, returning current history')
			agent_run_error = 'KeyboardInterrupt'

			self.history.usage = await self.token_cost_service.get_usage_summary()

			return self.history

		except Exception as e:
			self.logger.error(f'Agent run failed with exception: {e}', exc_info=True)
			agent_run_error = str(e)
			raise e

		finally:
			if should_delay_close and self._demo_mode_enabled and agent_run_error is None:
				await asyncio.sleep(30)
			if agent_run_error:
				await self._demo_mode_log(f'Agent stopped: {agent_run_error}', 'error', {'tag': 'run'})
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
				self.logger.debug('Telemetry for force exit (SIGINT) was logged by custom exit callback.')

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

			# Log final messages to user based on outcome
			self._log_final_outcome_messages()

			# Stop the event bus gracefully, waiting for all events to be processed
			# Use longer timeout to avoid deadlocks in tests with multiple agents
			await self.eventbus.stop(timeout=3.0)

			await self.close()

	@observe_debug(ignore_input=True, ignore_output=True)
	@time_execution_async('--multi_act')
	async def multi_act(self, actions: list[ActionModel]) -> list[ActionResult]:
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
				cached_selector_map = dict(self.browser_session._cached_browser_state_summary.dom_state.selector_map)
				cached_element_hashes = {e.parent_branch_hash() for e in cached_selector_map.values()}
			else:
				cached_selector_map = {}
				cached_element_hashes = set()
		except Exception as e:
			self.logger.error(f'Error getting cached selector map: {e}')
			cached_selector_map = {}
			cached_element_hashes = set()

		for i, action in enumerate(actions):
			if i > 0:
				# ONLY ALLOW TO CALL `done` IF IT IS A SINGLE ACTION
				if action.model_dump(exclude_unset=True).get('done') is not None:
					msg = f'Done action is allowed only as a single action - stopped after action {i} / {total_actions}.'
					self.logger.debug(msg)
					break

			# wait between actions (only after first action)
			if i > 0:
				self.logger.debug(f'Waiting {self.browser_profile.wait_between_actions} seconds between actions')
				await asyncio.sleep(self.browser_profile.wait_between_actions)

			try:
				await self._check_stop_or_pause()
				# Get action name from the action model
				action_data = action.model_dump(exclude_unset=True)
				action_name = next(iter(action_data.keys())) if action_data else 'unknown'

				# Log action before execution
				await self._log_action(action, action_name, i + 1, total_actions)

				time_start = time.time()

				result = await self.tools.act(
					action=action,
					browser_session=self.browser_session,
					file_system=self.file_system,
					page_extraction_llm=self.settings.page_extraction_llm,
					sensitive_data=self.sensitive_data,
					available_file_paths=self.available_file_paths,
				)

				time_end = time.time()
				time_elapsed = time_end - time_start

				if result.error:
					await self._demo_mode_log(
						f'Action "{action_name}" failed: {result.error}',
						'error',
						{'action': action_name, 'step': self.state.n_steps},
					)
				elif result.is_done:
					completion_text = result.long_term_memory or result.extracted_content or 'Task marked as done.'
					level = 'success' if result.success is not False else 'warning'
					await self._demo_mode_log(
						completion_text,
						level,
						{'action': action_name, 'step': self.state.n_steps},
					)

				results.append(result)

				if results[-1].is_done or results[-1].error or i == total_actions - 1:
					break

			except Exception as e:
				# Handle any exceptions during action execution
				self.logger.error(f'❌ Executing action {i + 1} failed -> {type(e).__name__}: {e}')
				await self._demo_mode_log(
					f'Action "{action_name}" raised {type(e).__name__}: {e}',
					'error',
					{'action': action_name, 'step': self.state.n_steps},
				)
				raise e

		return results

	async def _log_action(self, action, action_name: str, action_num: int, total_actions: int) -> None:
		"""Log the action before execution with colored formatting"""
		# Color definitions
		blue = '\033[34m'  # Action name
		magenta = '\033[35m'  # Parameter names
		reset = '\033[0m'

		# Format action number and name
		if total_actions > 1:
			action_header = f'▶️  [{action_num}/{total_actions}] {blue}{action_name}{reset}:'
			plain_header = f'▶️  [{action_num}/{total_actions}] {action_name}:'
		else:
			action_header = f'▶️   {blue}{action_name}{reset}:'
			plain_header = f'▶️  {action_name}:'

		# Get action parameters
		action_data = action.model_dump(exclude_unset=True)
		params = action_data.get(action_name, {})

		# Build parameter parts with colored formatting
		param_parts = []
		plain_param_parts = []

		if params and isinstance(params, dict):
			for param_name, value in params.items():
				# Truncate long values for readability
				if isinstance(value, str) and len(value) > 150:
					display_value = value[:150] + '...'
				elif isinstance(value, list) and len(str(value)) > 200:
					display_value = str(value)[:200] + '...'
				else:
					display_value = value

				param_parts.append(f'{magenta}{param_name}{reset}: {display_value}')
				plain_param_parts.append(f'{param_name}: {display_value}')

		# Join all parts
		if param_parts:
			params_string = ', '.join(param_parts)
			self.logger.info(f'  {action_header} {params_string}')
		else:
			self.logger.info(f'  {action_header}')

		if self._demo_mode_enabled:
			panel_message = plain_header
			if plain_param_parts:
				panel_message = f'{panel_message} {", ".join(plain_param_parts)}'
			await self._demo_mode_log(panel_message.strip(), 'action', {'action': action_name, 'step': self.state.n_steps})

	async def log_completion(self) -> None:
		"""Log the completion of the task"""
		# self._task_end_time = time.time()
		# self._task_duration = self._task_end_time - self._task_start_time TODO: this is not working when using take_step
		if self.history.is_successful():
			self.logger.info('✅ Task completed successfully')
			await self._demo_mode_log('Task completed successfully', 'success', {'tag': 'task'})

	async def _generate_rerun_summary(
		self, original_task: str, results: list[ActionResult], summary_llm: BaseChatModel | None = None
	) -> ActionResult:
		"""Generate AI summary of rerun completion using screenshot and last step info"""
		from browser_use.agent.views import RerunSummaryAction

		# Get current screenshot
		screenshot_b64 = None
		try:
			screenshot = await self.browser_session.take_screenshot(full_page=False)
			if screenshot:
				import base64

				screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
		except Exception as e:
			self.logger.warning(f'Failed to capture screenshot for rerun summary: {e}')

		# Build summary prompt and message
		error_count = sum(1 for r in results if r.error)
		success_count = len(results) - error_count

		from browser_use.agent.prompts import get_rerun_summary_message, get_rerun_summary_prompt

		prompt = get_rerun_summary_prompt(
			original_task=original_task,
			total_steps=len(results),
			success_count=success_count,
			error_count=error_count,
		)

		# Use provided LLM, agent's LLM, or fall back to OpenAI with structured output
		try:
			# Determine which LLM to use
			if summary_llm is None:
				# Try to use the agent's LLM first
				summary_llm = self.llm
				self.logger.debug('Using agent LLM for rerun summary')
			else:
				self.logger.debug(f'Using provided LLM for rerun summary: {summary_llm.model}')

			# Build message with prompt and optional screenshot
			from browser_use.llm.messages import BaseMessage

			message = get_rerun_summary_message(prompt, screenshot_b64)
			messages: list[BaseMessage] = [message]  # type: ignore[list-item]

			# Try calling with structured output first
			self.logger.debug(f'Calling LLM for rerun summary with {len(messages)} message(s)')
			try:
				kwargs: dict = {'output_format': RerunSummaryAction}
				response = await summary_llm.ainvoke(messages, **kwargs)
				summary: RerunSummaryAction = response.completion  # type: ignore[assignment]
				self.logger.debug(f'LLM response type: {type(summary)}')
				self.logger.debug(f'LLM response: {summary}')
			except Exception as structured_error:
				# If structured output fails (e.g., Browser-Use LLM doesn't support it for this type),
				# fall back to text response without parsing
				self.logger.debug(f'Structured output failed: {structured_error}, falling back to text response')

				response = await summary_llm.ainvoke(messages, None)
				response_text = response.completion
				self.logger.debug(f'LLM text response: {response_text}')

				# Use the text response directly as the summary
				summary = RerunSummaryAction(
					summary=response_text if isinstance(response_text, str) else str(response_text),
					success=error_count == 0,
					completion_status='complete' if error_count == 0 else ('partial' if success_count > 0 else 'failed'),
				)

			self.logger.info(f'📊 Rerun Summary: {summary.summary}')
			self.logger.info(f'📊 Status: {summary.completion_status} (success={summary.success})')

			return ActionResult(
				is_done=True,
				success=summary.success,
				extracted_content=summary.summary,
				long_term_memory=f'Rerun completed with status: {summary.completion_status}. {summary.summary[:100]}',
			)

		except Exception as e:
			self.logger.warning(f'Failed to generate AI summary: {e.__class__.__name__}: {e}')
			self.logger.debug('Full error traceback:', exc_info=True)
			# Fallback to simple summary
			return ActionResult(
				is_done=True,
				success=error_count == 0,
				extracted_content=f'Rerun completed: {success_count}/{len(results)} steps succeeded',
				long_term_memory=f'Rerun completed: {success_count} steps succeeded, {error_count} errors',
			)

	async def _execute_ai_step(
		self,
		query: str,
		include_screenshot: bool = False,
		extract_links: bool = False,
		ai_step_llm: BaseChatModel | None = None,
	) -> ActionResult:
		"""
		Execute an AI step during rerun to re-evaluate extract actions.
		Analyzes full page DOM/markdown + optional screenshot.

		Args:
			query: What to analyze or extract from the current page
			include_screenshot: Whether to include screenshot in analysis
			extract_links: Whether to include links in markdown extraction
			ai_step_llm: Optional LLM to use. If not provided, uses agent's LLM

		Returns:
			ActionResult with extracted content
		"""
		from browser_use.agent.prompts import get_ai_step_system_prompt, get_ai_step_user_prompt, get_rerun_summary_message
		from browser_use.llm.messages import SystemMessage, UserMessage
		from browser_use.utils import sanitize_surrogates

		# Use provided LLM or agent's LLM
		llm = ai_step_llm or self.llm
		self.logger.debug(f'Using LLM for AI step: {llm.model}')

		# Extract clean markdown
		try:
			from browser_use.dom.markdown_extractor import extract_clean_markdown

			content, content_stats = await extract_clean_markdown(
				browser_session=self.browser_session, extract_links=extract_links
			)
		except Exception as e:
			return ActionResult(error=f'Could not extract clean markdown: {type(e).__name__}: {e}')

		# Get screenshot if requested
		screenshot_b64 = None
		if include_screenshot:
			try:
				screenshot = await self.browser_session.take_screenshot(full_page=False)
				if screenshot:
					import base64

					screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
			except Exception as e:
				self.logger.warning(f'Failed to capture screenshot for ai_step: {e}')

		# Build prompt with content stats
		original_html_length = content_stats['original_html_chars']
		initial_markdown_length = content_stats['initial_markdown_chars']
		final_filtered_length = content_stats['final_filtered_chars']
		chars_filtered = content_stats['filtered_chars_removed']

		stats_summary = f"""Content processed: {original_html_length:,} HTML chars → {initial_markdown_length:,} initial markdown → {final_filtered_length:,} filtered markdown"""
		if chars_filtered > 0:
			stats_summary += f' (filtered {chars_filtered:,} chars of noise)'

		# Sanitize content
		content = sanitize_surrogates(content)
		query = sanitize_surrogates(query)

		# Get prompts from prompts.py
		system_prompt = get_ai_step_system_prompt()
		prompt_text = get_ai_step_user_prompt(query, stats_summary, content)

		# Build user message with optional screenshot
		if screenshot_b64:
			user_message = get_rerun_summary_message(prompt_text, screenshot_b64)
		else:
			user_message = UserMessage(content=prompt_text)

		try:
			import asyncio

			response = await asyncio.wait_for(llm.ainvoke([SystemMessage(content=system_prompt), user_message]), timeout=120.0)

			current_url = await self.browser_session.get_current_page_url()
			extracted_content = (
				f'<url>\n{current_url}\n</url>\n<query>\n{query}\n</query>\n<result>\n{response.completion}\n</result>'
			)

			# Simple memory handling
			MAX_MEMORY_LENGTH = 1000
			if len(extracted_content) < MAX_MEMORY_LENGTH:
				memory = extracted_content
				include_extracted_content_only_once = False
			else:
				file_name = await self.file_system.save_extracted_content(extracted_content)
				memory = f'Query: {query}\nContent in {file_name} and once in <read_state>.'
				include_extracted_content_only_once = True

			self.logger.info(f'🤖 AI Step: {memory}')
			return ActionResult(
				extracted_content=extracted_content,
				include_extracted_content_only_once=include_extracted_content_only_once,
				long_term_memory=memory,
			)
		except Exception as e:
			self.logger.warning(f'Failed to execute AI step: {e.__class__.__name__}: {e}')
			self.logger.debug('Full error traceback:', exc_info=True)
			return ActionResult(error=f'AI step failed: {e}')

	async def rerun_history(
		self,
		history: AgentHistoryList,
		max_retries: int = 3,
		skip_failures: bool = True,
		delay_between_actions: float = 2.0,
		summary_llm: BaseChatModel | None = None,
		ai_step_llm: BaseChatModel | None = None,
	) -> list[ActionResult]:
		"""
		Rerun a saved history of actions with error handling and retry logic.

		Args:
		                history: The history to replay
		                max_retries: Maximum number of retries per action
		                skip_failures: Whether to skip failed actions or stop execution
		                delay_between_actions: Delay between actions in seconds
		                summary_llm: Optional LLM to use for generating the final summary. If not provided, uses the agent's LLM
		                ai_step_llm: Optional LLM to use for AI steps (extract actions). If not provided, uses the agent's LLM

		Returns:
		                List of action results (including AI summary as the final result)
		"""
		# Skip cloud sync session events for rerunning (we're replaying, not starting new)
		self.state.session_initialized = True

		# Initialize browser session
		await self.browser_session.start()

		results = []

		for i, history_item in enumerate(history.history):
			goal = history_item.model_output.current_state.next_goal if history_item.model_output else ''
			step_num = history_item.metadata.step_number if history_item.metadata else i
			step_name = 'Initial actions' if step_num == 0 else f'Step {step_num}'

			# Determine step delay
			if history_item.metadata and history_item.metadata.step_interval is not None:
				step_delay = history_item.metadata.step_interval
				# Format delay nicely - show ms for values < 1s, otherwise show seconds
				if step_delay < 1.0:
					delay_str = f'{step_delay * 1000:.0f}ms'
				else:
					delay_str = f'{step_delay:.1f}s'
				delay_source = f'using saved step_interval={delay_str}'
			else:
				step_delay = delay_between_actions
				if step_delay < 1.0:
					delay_str = f'{step_delay * 1000:.0f}ms'
				else:
					delay_str = f'{step_delay:.1f}s'
				delay_source = f'using default delay={delay_str}'

			self.logger.info(f'Replaying {step_name} ({i + 1}/{len(history.history)}) [{delay_source}]: {goal}')

			if (
				not history_item.model_output
				or not history_item.model_output.action
				or history_item.model_output.action == [None]
			):
				self.logger.warning(f'{step_name}: No action to replay, skipping')
				results.append(ActionResult(error='No action to replay'))
				continue

			retry_count = 0
			while retry_count < max_retries:
				try:
					result = await self._execute_history_step(history_item, step_delay, ai_step_llm)
					results.extend(result)
					break

				except Exception as e:
					retry_count += 1
					if retry_count == max_retries:
						error_msg = f'{step_name} failed after {max_retries} attempts: {str(e)}'
						self.logger.error(error_msg)
						if not skip_failures:
							results.append(ActionResult(error=error_msg))
							raise RuntimeError(error_msg)
					else:
						self.logger.warning(f'{step_name} failed (attempt {retry_count}/{max_retries}), retrying...')
						await asyncio.sleep(delay_between_actions)

		# Generate AI summary of rerun completion
		self.logger.info('🤖 Generating AI summary of rerun completion...')
		summary_result = await self._generate_rerun_summary(self.task, results, summary_llm)
		results.append(summary_result)

		await self.close()
		return results

	async def _execute_initial_actions(self) -> None:
		# Execute initial actions if provided
		if self.initial_actions and not self.state.follow_up_task:
			self.logger.debug(f'⚡ Executing {len(self.initial_actions)} initial actions...')
			result = await self.multi_act(self.initial_actions)
			# update result 1 to mention that its was automatically loaded
			if result and self.initial_url and result[0].long_term_memory:
				result[0].long_term_memory = f'Found initial url and automatically loaded it. {result[0].long_term_memory}'
			self.state.last_result = result

			# Save initial actions to history as step 0 for rerun capability
			# Skip browser state capture for initial actions (usually just URL navigation)
			if self.settings.flash_mode:
				model_output = self.AgentOutput(
					evaluation_previous_goal=None,
					memory='Initial navigation',
					next_goal=None,
					action=self.initial_actions,
				)
			else:
				model_output = self.AgentOutput(
					evaluation_previous_goal='Start',
					memory=None,
					next_goal='Initial navigation',
					action=self.initial_actions,
				)

			metadata = StepMetadata(step_number=0, step_start_time=time.time(), step_end_time=time.time(), step_interval=None)

			# Create minimal browser state history for initial actions
			state_history = BrowserStateHistory(
				url=self.initial_url or '',
				title='Initial Actions',
				tabs=[],
				interacted_element=[None] * len(self.initial_actions),  # No DOM elements needed
				screenshot_path=None,
			)

			history_item = AgentHistory(
				model_output=model_output,
				result=result,
				state=state_history,
				metadata=metadata,
			)

			self.history.add_item(history_item)
			self.logger.debug('📝 Saved initial actions to history as step 0')
			self.logger.debug('Initial actions completed')

	async def _execute_history_step(
		self, history_item: AgentHistory, delay: float, ai_step_llm: BaseChatModel | None = None
	) -> list[ActionResult]:
		"""Execute a single step from history with element validation.

		For extract actions, uses AI to re-evaluate the content since page content may have changed.
		"""
		assert self.browser_session is not None, 'BrowserSession is not set up'

		await asyncio.sleep(delay)
		state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
		if not state or not history_item.model_output:
			raise ValueError('Invalid state or model output')

		results = []
		pending_actions = []

		for i, action in enumerate(history_item.model_output.action):
			# Check if this is an extract action - use AI step instead
			action_data = action.model_dump(exclude_unset=True)
			action_name = next(iter(action_data.keys()), None)

			if action_name == 'extract':
				# Execute any pending actions first to maintain correct order
				# (e.g., if step is [click, extract], click must happen before extract)
				if pending_actions:
					batch_results = await self.multi_act(pending_actions)
					results.extend(batch_results)
					pending_actions = []

				# Now execute AI step for extract action
				extract_params = action_data['extract']
				query = extract_params.get('query', '')
				extract_links = extract_params.get('extract_links', False)

				self.logger.info(f'🤖 Using AI step for extract action: {query[:50]}...')
				ai_result = await self._execute_ai_step(
					query=query,
					include_screenshot=False,  # Match original extract behavior
					extract_links=extract_links,
					ai_step_llm=ai_step_llm,
				)
				results.append(ai_result)
			else:
				# For non-extract actions, update indices and collect for batch execution
				updated_action = await self._update_action_indices(
					history_item.state.interacted_element[i],
					action,
					state,
				)
				if updated_action is None:
					raise ValueError(f'Could not find matching element {i} in current page')
				pending_actions.append(updated_action)

		# Execute any remaining pending actions
		if pending_actions:
			batch_results = await self.multi_act(pending_actions)
			results.extend(batch_results)

		return results

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

	async def load_and_rerun(
		self,
		history_file: str | Path | None = None,
		variables: dict[str, str] | None = None,
		**kwargs,
	) -> list[ActionResult]:
		"""
		Load history from file and rerun it, optionally substituting variables.

		Args:
			history_file: Path to the history file
			variables: Optional dict mapping variable names to new values (e.g. {'email': 'new@example.com'})
			**kwargs: Additional arguments passed to rerun_history
		"""
		if not history_file:
			history_file = 'AgentHistory.json'
		history = AgentHistoryList.load_from_file(history_file, self.AgentOutput)

		# Substitute variables if provided
		if variables:
			history = self._substitute_variables_in_history(history, variables)

		return await self.rerun_history(history, **kwargs)

	def save_history(self, file_path: str | Path | None = None) -> None:
		"""Save the history to a file with sensitive data filtering"""
		if not file_path:
			file_path = 'AgentHistory.json'
		self.history.save_to_file(file_path, sensitive_data=self.sensitive_data)

	def pause(self) -> None:
		"""Pause the agent before the next step"""
		print('\n\n⏸️ Paused the agent and left the browser open.\n\tPress [Enter] to resume or [Ctrl+C] again to quit.')
		self.state.paused = True
		self._external_pause_event.clear()

	def resume(self) -> None:
		"""Resume the agent"""
		# TODO: Locally the browser got closed
		print('----------------------------------------------------------------------')
		print('▶️  Resuming agent execution where it left off...\n')
		self.state.paused = False
		self._external_pause_event.set()

	def stop(self) -> None:
		"""Stop the agent"""
		self.logger.info('⏹️ Agent stopping')
		self.state.stopped = True

		# Signal pause event to unblock any waiting code so it can check the stopped state
		self._external_pause_event.set()

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
			action_info = self.tools.registry.registry.actions[action_name]
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

			# Close skill service if configured
			if self.skill_service is not None:
				await self.skill_service.close()

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

		except Exception as e:
			self.logger.error(f'Error during cleanup: {e}')

	async def _update_action_models_for_page(self, page_url: str) -> None:
		"""Update action models with page-specific actions"""
		# Create new action model with current page's filtered actions
		self.ActionModel = self.tools.registry.create_action_model(page_url=page_url)
		# Update output model with the new actions
		if self.settings.flash_mode:
			self.AgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.ActionModel)
		elif self.settings.use_thinking:
			self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)
		else:
			self.AgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.ActionModel)

		# Update done action model too
		self.DoneActionModel = self.tools.registry.create_action_model(include_actions=['done'], page_url=page_url)
		if self.settings.flash_mode:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.DoneActionModel)
		elif self.settings.use_thinking:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions(self.DoneActionModel)
		else:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.DoneActionModel)

	async def authenticate_cloud_sync(self, show_instructions: bool = True) -> bool:
		"""
		Authenticate with cloud service for future runs.

		This is useful when users want to authenticate after a task has completed
		so that future runs will sync to the cloud.

		Args:
			show_instructions: Whether to show authentication instructions to user

		Returns:
			bool: True if authentication was successful
		"""
		self.logger.warning('Cloud sync has been removed and is no longer available')
		return False

	def run_sync(
		self,
		max_steps: int = 100,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		"""Synchronous wrapper around the async run method for easier usage without asyncio."""
		import asyncio

		return asyncio.run(self.run(max_steps=max_steps, on_step_start=on_step_start, on_step_end=on_step_end))

	def detect_variables(self) -> dict[str, DetectedVariable]:
		"""Detect reusable variables in agent history"""
		from browser_use.agent.variable_detector import detect_variables_in_history

		return detect_variables_in_history(self.history)

	def _substitute_variables_in_history(self, history: AgentHistoryList, variables: dict[str, str]) -> AgentHistoryList:
		"""Substitute variables in history with new values for rerunning with different data"""
		from browser_use.agent.variable_detector import detect_variables_in_history

		# Detect variables in the history
		detected_vars = detect_variables_in_history(history)

		# Build a mapping of original values to new values
		value_replacements: dict[str, str] = {}
		for var_name, new_value in variables.items():
			if var_name in detected_vars:
				old_value = detected_vars[var_name].original_value
				value_replacements[old_value] = new_value
			else:
				self.logger.warning(f'Variable "{var_name}" not found in history, skipping substitution')

		if not value_replacements:
			self.logger.info('No variables to substitute')
			return history

		# Create a deep copy of history to avoid modifying the original
		import copy

		modified_history = copy.deepcopy(history)

		# Substitute values in all actions
		substitution_count = 0
		for history_item in modified_history.history:
			if not history_item.model_output or not history_item.model_output.action:
				continue

			for action in history_item.model_output.action:
				# Handle both Pydantic models and dicts
				if hasattr(action, 'model_dump'):
					action_dict = action.model_dump()
				elif isinstance(action, dict):
					action_dict = action
				else:
					action_dict = vars(action) if hasattr(action, '__dict__') else {}

				# Substitute in all string fields
				substitution_count += self._substitute_in_dict(action_dict, value_replacements)

				# Update the action with modified values
				if hasattr(action, 'model_dump'):
					# For Pydantic RootModel, we need to recreate from the modified dict
					if hasattr(action, 'root'):
						# This is a RootModel - recreate it from the modified dict
						new_action = type(action).model_validate(action_dict)
						# Replace the root field in-place using object.__setattr__ to bypass Pydantic's immutability
						object.__setattr__(action, 'root', getattr(new_action, 'root'))
					else:
						# Regular Pydantic model - update fields in-place
						for key, val in action_dict.items():
							if hasattr(action, key):
								setattr(action, key, val)
				elif isinstance(action, dict):
					action.update(action_dict)

		self.logger.info(f'Substituted {substitution_count} value(s) in {len(value_replacements)} variable type(s) in history')
		return modified_history

	def _substitute_in_dict(self, data: dict, replacements: dict[str, str]) -> int:
		"""Recursively substitute values in a dictionary, returns count of substitutions made"""
		count = 0
		for key, value in data.items():
			if isinstance(value, str):
				# Replace if exact match
				if value in replacements:
					data[key] = replacements[value]
					count += 1
			elif isinstance(value, dict):
				# Recurse into nested dicts
				count += self._substitute_in_dict(value, replacements)
			elif isinstance(value, list):
				# Handle lists
				for i, item in enumerate(value):
					if isinstance(item, str) and item in replacements:
						value[i] = replacements[item]
						count += 1
					elif isinstance(item, dict):
						count += self._substitute_in_dict(item, replacements)
		return count
