import asyncio
import gc
import logging
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar, cast

from dotenv import load_dotenv

from browser_use.agent.cloud_events import (
	CreateAgentStepEvent,
)
from browser_use.agent.message_manager.utils import save_conversation
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import BaseMessage, ContentPartImageParam, ContentPartTextParam, UserMessage
from browser_use.tokens.service import TokenCost

load_dotenv()

from bubus import EventBus
from uuid_extensions import uuid7str

from browser_use import Browser, BrowserProfile, BrowserSession
from browser_use.agent.files import AgentFileSystemMixin
from browser_use.agent.judge import construct_judge_messages

# Lazy import for gif to avoid heavy agent.views import at startup
# from browser_use.agent.gif import create_history_gif
from browser_use.agent.message_manager.service import (
	MessageManager,
)
from browser_use.agent.model_io import AgentModelIOMixin
from browser_use.agent.planning import AgentPlanningMixin
from browser_use.agent.prompts import SystemPrompt
from browser_use.agent.run_logging import AgentRunLoggingMixin
from browser_use.agent.runtime import (
	AgentRuntimeEventBridge,
	BrowserAgentSession,
	BrowserRunConfig,
	BrowserRuntimeEventTypes,
	BrowserSkill,
	BrowserSkillRegistry,
	ModelCapabilities,
)
from browser_use.agent.skills import AgentSkillMixin
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
	MessageCompactionSettings,
	StepMetadata,
)
from browser_use.browser.events import _get_timeout
from browser_use.browser.session import DEFAULT_BROWSER_PROFILE
from browser_use.browser.views import BrowserStateSummary
from browser_use.config import CONFIG
from browser_use.dom.views import DOMInteractedElement, MatchLevel
from browser_use.observability import observe, observe_debug
from browser_use.telemetry.service import ProductTelemetry
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.utils import (
	_log_pretty_path,
	get_browser_use_version,
	time_execution_async,
	time_execution_sync,
)

logger = logging.getLogger(__name__)


Context = TypeVar('Context')


AgentHookFunc = Callable[['Agent'], Awaitable[None]]


class Agent(
	AgentFileSystemMixin,
	AgentModelIOMixin,
	AgentRunLoggingMixin,
	AgentSkillMixin,
	AgentPlanningMixin,
	Generic[Context, AgentStructuredOutput],
):
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
		skill_service: Any | None = None,
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
		extraction_schema: dict | None = None,
		use_vision: bool | Literal['auto'] = True,
		save_conversation_path: str | Path | None = None,
		save_conversation_path_encoding: str | None = 'utf-8',
		max_failures: int = 5,
		override_system_message: str | None = None,
		extend_system_message: str | None = None,
		generate_gif: bool | str = False,
		available_file_paths: list[str] | None = None,
		include_attributes: list[str] | None = None,
		max_actions_per_step: int = 5,
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
		pricing_url: str | None = None,
		display_files_in_done_text: bool = True,
		include_tool_call_examples: bool = False,
		use_native_tool_calls: bool = False,
		vision_detail_level: Literal['auto', 'low', 'high'] = 'auto',
		llm_timeout: int | None = None,
		step_timeout: int = 180,
		directly_open_url: bool = True,
		include_recent_events: bool = False,
		sample_images: list[ContentPartTextParam | ContentPartImageParam] | None = None,
		final_response_after_failure: bool = True,
		enable_planning: bool = True,
		planning_replan_on_stall: int = 3,
		planning_exploration_limit: int = 5,
		loop_detection_window: int = 20,
		loop_detection_enabled: bool = True,
		llm_screenshot_size: tuple[int, int] | None = None,
		message_compaction: MessageCompactionSettings | bool | None = True,
		max_clickable_elements_length: int = 40000,
		_url_shortening_limit: int = 25,
		enable_signal_handler: bool = True,
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

		self.model_capabilities = ModelCapabilities.from_llm(llm)

		# set flashmode = True if llm is ChatBrowserUse
		if self.model_capabilities.prefers_flash_mode:
			flash_mode = True

		# Flash mode strips plan fields from the output schema, so planning is structurally impossible
		if flash_mode:
			enable_planning = False

		# Auto-configure llm_screenshot_size for Claude Sonnet models
		if llm_screenshot_size is None and self.model_capabilities.recommended_screenshot_size is not None:
			llm_screenshot_size = self.model_capabilities.recommended_screenshot_size
			logger.info(f'🖼️  Auto-configured LLM screenshot size: {llm_screenshot_size[0]}x{llm_screenshot_size[1]}')

		if page_extraction_llm is None:
			page_extraction_llm = llm
		if judge_llm is None:
			judge_llm = llm
		if available_file_paths is None:
			available_file_paths = []

		# Set timeout based on model name if not explicitly provided
		if llm_timeout is None:
			llm_timeout = self.model_capabilities.default_timeout_s

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

		# Enable coordinate clicking for models that support it
		if self.model_capabilities.supports_coordinate_clicking:
			self.tools.set_coordinate_clicking(True)

		# Handle skills vs skill_ids parameter (skills takes precedence)
		if skills and skill_ids:
			raise ValueError('Cannot specify both "skills" and "skill_ids" parameters. Use "skills" for the cleaner API.')
		skill_ids = skills or skill_ids

		# Skills integration - use injected service or create from skill_ids
		self.skill_service = None
		self._skills_registered = False
		self.runtime_skill_registry = BrowserSkillRegistry.default()
		if skill_service is not None:
			self.skill_service = skill_service
		elif skill_ids:
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

		# Extraction schema: explicit param takes priority, otherwise auto-bridge from output_model_schema
		self.extraction_schema = extraction_schema
		if self.extraction_schema is None and self.output_model_schema is not None:
			self.extraction_schema = self.output_model_schema.model_json_schema()

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

		if isinstance(message_compaction, bool):
			message_compaction = MessageCompactionSettings(enabled=message_compaction)

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
			use_native_tool_calls=use_native_tool_calls,
			llm_timeout=llm_timeout,
			step_timeout=step_timeout,
			final_response_after_failure=final_response_after_failure,
			use_judge=use_judge,
			ground_truth=ground_truth,
			enable_planning=enable_planning,
			planning_replan_on_stall=planning_replan_on_stall,
			planning_exploration_limit=planning_exploration_limit,
			loop_detection_window=loop_detection_window,
			loop_detection_enabled=loop_detection_enabled,
			message_compaction=message_compaction,
			max_clickable_elements_length=max_clickable_elements_length,
		)

		# Token cost service
		self.token_cost_service = TokenCost(include_cost=calculate_cost, pricing_url=pricing_url)
		self.token_cost_service.register_llm(llm)
		self.token_cost_service.register_llm(page_extraction_llm)
		self.token_cost_service.register_llm(judge_llm)
		if self.settings.message_compaction and self.settings.message_compaction.compaction_llm:
			self.token_cost_service.register_llm(self.settings.message_compaction.compaction_llm)

		# Store signal handler setting (not part of AgentSettings as it's runtime behavior)
		self.enable_signal_handler = enable_signal_handler

		# Initialize state
		self.state = injected_agent_state or AgentState()

		# Configure loop detector window size from settings
		self.state.loop_detector.window_size = self.settings.loop_detection_window

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

		if self.model_capabilities.unsupported_vision_reason:
			self.logger.warning(f'⚠️ {self.model_capabilities.unsupported_vision_reason} Setting use_vision=False for now...')
			self.settings.use_vision = False

		logger.debug(
			f'{" +vision" if self.settings.use_vision else ""}'
			f' extraction_model={self.settings.page_extraction_llm.model if self.settings.page_extraction_llm else "Unknown"}'
			f'{" +file_system" if self.file_system else ""}'
		)

		# Store llm_screenshot_size in browser_session so tools can access it
		self.browser_session.llm_screenshot_size = llm_screenshot_size

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
				is_anthropic=self.model_capabilities.is_anthropic,
				is_browser_use_model=self.model_capabilities.uses_browser_use_prompt,
				is_anthropic_4_5=self.model_capabilities.is_anthropic_4_5,
				model_name=self.model_capabilities.model_name,
				use_native_tool_calls=self.settings.use_native_tool_calls,
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
			max_clickable_elements_length=self.settings.max_clickable_elements_length,
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
		self.runtime_session = BrowserAgentSession.create(
			task=self.task,
			llm=self.llm,
			config=BrowserRunConfig(
				run_id=self.session_id,
				max_actions_per_step=self.settings.max_actions_per_step,
				runtime_mode='legacy',
				use_native_tool_calls=self.settings.use_native_tool_calls,
				stream_events=True,
			),
			metadata={'agent_id': self.id, 'task_id': self.task_id},
		)
		self.runtime_events = AgentRuntimeEventBridge(agent=self, runtime_session=self.runtime_session)
		self.runtime_events.attach()
		self.last_typed_context = None

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

	def add_new_task(self, new_task: str) -> None:
		"""Add a new task to the agent, keeping the same task_id as tasks are continuous"""
		# Simply delegate to message manager - no need for new task_id or events
		# The task continues with new instructions, it doesn't end and start a new one
		self.task = new_task
		self._message_manager.add_new_task(new_task)
		# Mark as follow-up task and recreate eventbus (gets shut down after each run)
		self.state.follow_up_task = True
		self.runtime_session.task = new_task
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
			if self.browser_session:
				try:
					captcha_wait = await self.browser_session.wait_if_captcha_solving()
					if captcha_wait and captcha_wait.waited:
						# Reset step timing to exclude the captcha wait from step duration metrics
						self.step_start_time = time.time()
						duration_s = captcha_wait.duration_ms / 1000
						outcome = captcha_wait.result  # 'success' | 'failed' | 'timeout'
						msg = f'Waited {duration_s:.1f}s for {captcha_wait.vendor} CAPTCHA to be solved. Result: {outcome}.'
						self.logger.info(f'🔒 {msg}')
						# Inject the outcome so the LLM sees what happened
						captcha_result = ActionResult(long_term_memory=msg)
						if self.state.last_result:
							self.state.last_result.append(captcha_result)
						else:
							self.state.last_result = [captcha_result]
				except Exception as e:
					self.logger.warning(f'Phase 0 captcha wait failed (non-fatal): {e}')

			# Phase 1: Prepare context and timing
			browser_state_summary = await self._prepare_context(step_info)

			# Clear previous step state after context preparation (which needs
			# them for the "previous action result" prompt) but before the LLM
			# call, so a timeout during _get_next_action or _execute_actions
			# won't leave stale data from the previous step.
			self.state.last_model_output = None
			self.state.last_result = None

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

		selected_runtime_skills = self._select_runtime_skills(browser_state_summary)

		# Render plan description for injection into agent context
		plan_description = self._render_plan_description()

		self._message_manager.prepare_step_state(
			browser_state_summary=browser_state_summary,
			model_output=self.state.last_model_output,
			result=self.state.last_result,
			step_info=step_info,
			sensitive_data=self.sensitive_data,
		)

		await self._maybe_compact_messages(step_info)

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
			selected_runtime_skills=selected_runtime_skills,
			plan_description=plan_description,
			skip_state_update=True,
		)
		self.last_typed_context = self._message_manager.last_typed_context
		if self.last_typed_context is None:
			raise RuntimeError('MessageManager did not build typed context for the current step.')
		rendered_typed_context = self.last_typed_context.render()
		await self.runtime_events.emit_runtime_event(
			BrowserRuntimeEventTypes.CONTEXT_BUILT,
			payload={
				'step': self.state.n_steps,
				'item_count': len(self.last_typed_context.items),
				'rendered_chars': len(rendered_typed_context),
				'legacy_message_count': len(self._message_manager.state.history.get_messages()),
				'runtime_skill_count': len(selected_runtime_skills),
			},
		)

		await self._inject_budget_warning(step_info)
		self._inject_replan_nudge()
		self._inject_exploration_nudge()
		self._update_loop_detector_page_state(browser_state_summary)
		self._inject_loop_detection_nudge()
		await self._force_done_after_last_step(step_info)
		await self._force_done_after_failure()
		return browser_state_summary

	def _select_runtime_skills(self, browser_state_summary: BrowserStateSummary) -> list[BrowserSkill]:
		recent_failures = [
			result.error for result in self.state.last_result or [] if result.error is not None and result.error.strip()
		]
		return self.runtime_skill_registry.select(
			task=self.task,
			url=browser_state_summary.url,
			recent_failures=recent_failures,
		)

	async def _maybe_compact_messages(self, step_info: AgentStepInfo | None = None) -> None:
		"""Optionally compact message history to keep prompts small."""
		settings = self.settings.message_compaction
		if not settings or not settings.enabled:
			return

		compaction_llm = settings.compaction_llm or self.settings.page_extraction_llm or self.llm
		await self._message_manager.maybe_compact_messages(
			llm=compaction_llm,
			settings=settings,
			step_info=step_info,
		)

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

		# Update plan state from model output
		if self.state.last_model_output is not None:
			self._update_plan_from_model_output(self.state.last_model_output)

		# Record executed actions for loop detection
		self._update_loop_detector_actions()

		# check for action errors - only count single-action steps toward consecutive failures;
		# multi-action steps with errors are handled by loop detection and replan nudges instead
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

		# Handle browser closed/disconnected errors
		if self._is_connection_like_error(error):
			# If reconnection is in progress, wait for it instead of stopping
			if self.browser_session.is_reconnecting:
				wait_timeout = self.browser_session.RECONNECT_WAIT_TIMEOUT
				self.logger.warning(
					f'🔄 Connection error during reconnection, waiting up to {wait_timeout}s for reconnect: {error}'
				)
				try:
					await asyncio.wait_for(self.browser_session._reconnect_event.wait(), timeout=wait_timeout)
				except TimeoutError:
					pass

				# Check if reconnection succeeded
				if self.browser_session.is_cdp_connected:
					self.logger.info('🔄 Reconnection succeeded, retrying step...')
					self.state.last_result = [ActionResult(error=f'Connection lost and recovered: {error}')]
					return

			# Not reconnecting or reconnection failed — check if truly terminal
			if self._is_browser_closed_error(error):
				self.logger.warning(f'🛑 Browser closed or disconnected: {error}')
				self.state.stopped = True
				self._external_pause_event.set()
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

	def _is_connection_like_error(self, error: Exception) -> bool:
		"""Check if the error looks like a CDP/WebSocket connection failure.

		Unlike _is_browser_closed_error(), this does NOT check if the CDP client is None
		or if reconnection is in progress — it purely looks at the error signature.
		"""
		error_str = str(error).lower()
		return (
			isinstance(error, ConnectionError)
			or 'websocket connection closed' in error_str
			or 'connection closed' in error_str
			or 'browser has been closed' in error_str
			or 'browser closed' in error_str
			or 'no browser' in error_str
		)

	def _is_browser_closed_error(self, error: Exception) -> bool:
		"""Check if the browser has been closed or disconnected.

		Only returns True when the error itself is a CDP/WebSocket connection failure
		AND the CDP client is gone AND we're not actively reconnecting.
		Avoids false positives on unrelated errors (element not found, timeouts,
		parse errors) that happen to coincide with a transient None state during
		reconnects or resets.
		"""
		# During reconnection, don't treat connection errors as terminal
		if self.browser_session.is_reconnecting:
			return False

		error_str = str(error).lower()
		is_connection_error = (
			isinstance(error, ConnectionError)
			or 'websocket connection closed' in error_str
			or 'connection closed' in error_str
			or 'browser has been closed' in error_str
			or 'browser closed' in error_str
			or 'no browser' in error_str
		)
		return is_connection_error and self.browser_session._cdp_client_root is None

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
			await self.runtime_events.emit_runtime_event(
				BrowserRuntimeEventTypes.TURN_COMPLETED,
				payload={
					'step': self.state.n_steps,
					'actions': actions_data,
					'legacy_step_event': step_event,
				},
			)

		# Increment step counter after step is fully completed
		self.state.n_steps += 1

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
			use_vision=self.settings.use_vision,
		)

		# Call LLM with JudgementResult as output format
		kwargs: dict = {'output_format': JudgementResult}

		# Only pass request_type for ChatBrowserUse (other providers don't support it)
		if self.judge_llm.provider == 'browser-use':
			kwargs['request_type'] = 'judge'
			kwargs['session_id'] = self.session_id

		try:
			response = await self.judge_llm.ainvoke(input_messages, **kwargs)
			judgement: JudgementResult = response.completion  # type: ignore[assignment]
			return judgement
		except Exception as e:
			self.logger.error(f'Judge trace failed: {e}')
			# Return a default judgement on failure
			return None

	async def _judge_and_log(self) -> None:
		"""Run judge evaluation and log the verdict.

		The judge verdict is attached to the action result but does NOT override
		last_result.success — that stays as the agent's self-report. Telemetry
		sends both values so the eval platform can compare agent vs judge.
		"""
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
					self.logger.warning(
						'Agent was blocked by a captcha. Cloud browsers include stealth fingerprinting and proxy rotation to avoid this.\n'
						'         Try: Browser(use_cloud=True)  |  Get an API key: https://cloud.browser-use.com?utm_source=oss&utm_medium=captcha_nudge'
					)
				judge_log += f'   {judgement.reasoning}\n'
				self.logger.info(judge_log)

	async def _handle_post_llm_processing(
		self,
		browser_state_summary: BrowserStateSummary,
		input_messages: list[BaseMessage],
	) -> None:
		"""Handle callbacks and conversation saving after LLM interaction"""
		if self.state.last_model_output:
			await self.runtime_events.emit_runtime_event(
				BrowserRuntimeEventTypes.MODEL_DELTA,
				payload={
					'browser_state_summary': browser_state_summary,
					'model_output': self.state.last_model_output,
					'step': self.state.n_steps,
					'input_message_count': len(input_messages),
				},
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

			# Run full judge before done callback if enabled
			if self.settings.use_judge:
				await self._judge_and_log()

			await self.runtime_events.emit_terminal_event(
				max_steps=step_info.max_steps if step_info is not None else self.state.n_steps,
				agent_run_error=None,
				skip_telemetry=True,
				skip_cloud_events=True,
				skip_gif=True,
			)
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
			# Ensure step counter advances on timeout — _finalize() may have
			# been skipped or returned early due to the cancellation.
			if self.state.n_steps == step + 1:
				self.state.n_steps += 1

		if on_step_end is not None:
			await on_step_end(self)

		if self.history.is_done():
			await self.log_completion()

			# Run full judge before done callback if enabled
			if self.settings.use_judge:
				await self._judge_and_log()

			return True

		return False

	@observe(name='agent.run', ignore_input=True, ignore_output=True)
	@time_execution_async('--run')
	async def run(
		self,
		max_steps: int = 500,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		"""Execute the task with maximum number of steps"""

		loop = asyncio.get_event_loop()
		agent_run_error: str | None = None  # Initialize error tracking variable
		self._force_exit_telemetry_logged = False  # ADDED: Flag for custom telemetry on force exit
		should_delay_close = False
		self.runtime_session.config.max_steps = max_steps

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
			disabled=not self.enable_signal_handler,
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

			await self.runtime_events.emit_runtime_event(BrowserRuntimeEventTypes.RUN_STARTED, payload={'max_steps': max_steps})

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

			# Normally there was no try catch here but the callback can raise an InterruptedError.
			# Wrap with step_timeout so initial actions (usually a single URL navigate) can't
			# hang indefinitely on a silent CDP WebSocket — without this the agent would take
			# zero steps and return with an empty history while any outer watchdog waits.
			try:
				await asyncio.wait_for(
					self._execute_initial_actions(),
					timeout=self.settings.step_timeout,
				)
			except InterruptedError:
				pass
			except TimeoutError:
				initial_timeout_msg = (
					f'Initial actions timed out after {self.settings.step_timeout}s '
					f'(browser may be unresponsive). Proceeding to main execution loop.'
				)
				self.logger.error(f'⏰ {initial_timeout_msg}')
				self.state.last_result = [ActionResult(error=initial_timeout_msg)]
				self.state.consecutive_failures += 1
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

			if self._force_exit_telemetry_logged:
				# ADDED: Info message when custom telemetry for SIGINT was already logged
				self.logger.debug('Telemetry for force exit (SIGINT) was logged by custom exit callback.')

			await self.runtime_events.emit_terminal_event(
				max_steps=max_steps,
				agent_run_error=agent_run_error,
				skip_telemetry=self._force_exit_telemetry_logged,
			)

			# Log final messages to user based on outcome
			self._log_final_outcome_messages()

			# Stop the event bus gracefully, waiting for all events to be processed
			# Configurable via TIMEOUT_AgentEventBusStop env var (default: 3.0s)
			await self.eventbus.stop(clear=True, timeout=_get_timeout('TIMEOUT_AgentEventBusStop', 3.0))

			await self.close()

	@observe_debug(ignore_input=True, ignore_output=True)
	@time_execution_async('--multi_act')
	async def multi_act(self, actions: list[ActionModel]) -> list[ActionResult]:
		"""Execute multiple actions with page-change guards.

		Two layers of protection prevent executing actions against stale DOM:
		  1. Static flag: actions tagged with terminates_sequence=True (navigate, search, go_back, switch)
		     automatically abort remaining queued actions.
		  2. Runtime detection: after every action, the current URL and focused target are compared
		     to pre-action values. Any change aborts the remaining queue.
		"""
		results: list[ActionResult] = []
		total_actions = len(actions)

		assert self.browser_session is not None, 'BrowserSession is not set up'
		try:
			if (
				self.browser_session._cached_browser_state_summary is not None
				and self.browser_session._cached_browser_state_summary.dom_state is not None
			):
				cached_selector_map = dict(self.browser_session._cached_browser_state_summary.dom_state.selector_map)
			else:
				cached_selector_map = {}
		except Exception as e:
			self.logger.error(f'Error getting cached selector map: {e}')
			cached_selector_map = {}

		for i, action in enumerate(actions):
			# Get action name from the action model BEFORE try block to ensure it's always available in except
			action_data = action.model_dump(exclude_unset=True)
			action_name = next(iter(action_data.keys())) if action_data else 'unknown'

			if i > 0:
				# ONLY ALLOW TO CALL `done` IF IT IS A SINGLE ACTION
				if action_data.get('done') is not None:
					msg = f'Done action is allowed only as a single action - stopped after action {i} / {total_actions}.'
					self.logger.debug(msg)
					break

			# wait between actions (only after first action)
			if i > 0:
				self.logger.debug(f'Waiting {self.browser_profile.wait_between_actions} seconds between actions')
				await asyncio.sleep(self.browser_profile.wait_between_actions)

			try:
				await self._check_stop_or_pause()

				# Log action before execution
				await self._log_action(action, action_name, i + 1, total_actions)

				# Capture pre-action state for runtime page-change detection
				pre_action_url = await self.browser_session.get_current_page_url()
				pre_action_focus = self.browser_session.agent_focus_target_id

				result = await self.tools.act(
					action=action,
					browser_session=self.browser_session,
					file_system=self.file_system,
					page_extraction_llm=self.settings.page_extraction_llm,
					sensitive_data=self.sensitive_data,
					available_file_paths=self.available_file_paths,
					extraction_schema=self.extraction_schema,
				)

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

				# --- Page-change guards (only when more actions remain) ---

				# Layer 1: Static flag — action metadata declares it changes the page
				registered_action = self.tools.registry.registry.actions.get(action_name)
				if registered_action and registered_action.terminates_sequence:
					self.logger.info(
						f'Action "{action_name}" terminates sequence — skipping {total_actions - i - 1} remaining action(s)'
					)
					break

				# Layer 2: Runtime detection — URL or focus target changed
				post_action_url = await self.browser_session.get_current_page_url()
				post_action_focus = self.browser_session.agent_focus_target_id

				if post_action_url != pre_action_url or post_action_focus != pre_action_focus:
					self.logger.info(f'Page changed after "{action_name}" — skipping {total_actions - i - 1} remaining action(s)')
					break

			except Exception as e:
				# Re-raise InterruptedError so _check_stop_or_pause's stop/pause signal still propagates
				if isinstance(e, InterruptedError):
					raise
				# Re-raise browser/connection errors so _handle_step_error can handle reconnect/shutdown
				if self._is_connection_like_error(e):
					raise
				# Handle any exceptions during action execution
				self.logger.error(f'❌ Executing action {i + 1} failed -> {type(e).__name__}: {e}')
				await self._demo_mode_log(
					f'Action "{action_name}" raised {type(e).__name__}: {e}',
					'error',
					{'action': action_name, 'step': self.state.n_steps},
				)
				# Preserve partial results so the agent knows which actions succeeded before the failure
				results.append(ActionResult(error=f'{type(e).__name__}: {e}'))
				return results

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
		from browser_use.llm.messages import SystemMessage
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
		skip_failures: bool = False,
		delay_between_actions: float = 2.0,
		max_step_interval: float = 45.0,
		summary_llm: BaseChatModel | None = None,
		ai_step_llm: BaseChatModel | None = None,
		wait_for_elements: bool = False,
	) -> list[ActionResult]:
		"""
		Rerun a saved history of actions with error handling and retry logic.

		Args:
		                history: The history to replay
		                max_retries: Maximum number of retries per action
		                skip_failures: Whether to skip failed actions or stop execution. When True, also skips
		                               steps that had errors in the original run (e.g., modal close buttons that
		                               auto-dismissed, or elements that became non-interactable)
		                delay_between_actions: Delay between actions in seconds (used when no saved interval)
		                max_step_interval: Maximum delay from saved step_interval (caps LLM time from original run)
		                summary_llm: Optional LLM to use for generating the final summary. If not provided, uses the agent's LLM
		                ai_step_llm: Optional LLM to use for AI steps (extract actions). If not provided, uses the agent's LLM
		                wait_for_elements: If True, wait for minimum number of elements before attempting element
		                               matching. Useful for SPA pages where shadow DOM content loads dynamically.
		                               Default is False.

		Returns:
		                List of action results (including AI summary as the final result)
		"""
		# Skip cloud sync session events for rerunning (we're replaying, not starting new)
		self.state.session_initialized = True

		# Initialize browser session
		await self.browser_session.start()

		results = []

		# Track previous step for redundant retry detection
		previous_item: AgentHistory | None = None
		previous_step_succeeded: bool = False

		try:
			for i, history_item in enumerate(history.history):
				goal = history_item.model_output.current_state.next_goal if history_item.model_output else ''
				step_num = history_item.metadata.step_number if history_item.metadata else i
				step_name = 'Initial actions' if step_num == 0 else f'Step {step_num}'

				# Determine step delay
				if history_item.metadata and history_item.metadata.step_interval is not None:
					# Cap the saved interval to max_step_interval (saved interval includes LLM time)
					step_delay = min(history_item.metadata.step_interval, max_step_interval)
					# Format delay nicely - show ms for values < 1s, otherwise show seconds
					if step_delay < 1.0:
						delay_str = f'{step_delay * 1000:.0f}ms'
					else:
						delay_str = f'{step_delay:.1f}s'
					if history_item.metadata.step_interval > max_step_interval:
						delay_source = f'capped to {delay_str} (saved was {history_item.metadata.step_interval:.1f}s)'
					else:
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

				# Check if the original step had errors - skip if skip_failures is enabled
				original_had_error = any(r.error for r in history_item.result if r.error)
				if original_had_error and skip_failures:
					error_msgs = [r.error for r in history_item.result if r.error]
					self.logger.warning(
						f'{step_name}: Original step had error(s), skipping (skip_failures=True): {error_msgs[0][:100] if error_msgs else "unknown"}'
					)
					results.append(
						ActionResult(
							error=f'Skipped - original step had error: {error_msgs[0][:100] if error_msgs else "unknown"}'
						)
					)
					continue

				# Check if this step is a redundant retry of the previous step
				# This handles cases where original run needed to click same element multiple times
				# due to slow page response, but during replay the first click already worked
				if self._is_redundant_retry_step(history_item, previous_item, previous_step_succeeded):
					self.logger.info(f'{step_name}: Skipping redundant retry (previous step already succeeded with same element)')
					results.append(
						ActionResult(
							extracted_content='Skipped - redundant retry of previous step',
							include_in_memory=False,
						)
					)
					# Don't update previous_item/previous_step_succeeded - keep tracking the original step
					continue

				retry_count = 0
				step_succeeded = False
				menu_reopened = False  # Track if we've already tried reopening the menu
				# Exponential backoff: 5s base, doubling each retry, capped at 30s
				base_retry_delay = 5.0
				max_retry_delay = 30.0
				while retry_count < max_retries:
					try:
						result = await self._execute_history_step(history_item, step_delay, ai_step_llm, wait_for_elements)
						results.extend(result)
						step_succeeded = True
						break

					except Exception as e:
						error_str = str(e)
						retry_count += 1

						# Check if this is a "Could not find matching element" error for a menu item
						# If so, try to re-open the dropdown from the previous step before retrying
						if (
							not menu_reopened
							and 'Could not find matching element' in error_str
							and previous_item is not None
							and self._is_menu_opener_step(previous_item)
						):
							# Check if current step targets a menu item element
							curr_elements = history_item.state.interacted_element if history_item.state else []
							curr_elem = curr_elements[0] if curr_elements else None
							if self._is_menu_item_element(curr_elem):
								self.logger.info(
									'🔄 Dropdown may have closed. Attempting to re-open by re-executing previous step...'
								)
								reopened = await self._reexecute_menu_opener(previous_item, ai_step_llm)
								if reopened:
									menu_reopened = True
									# Don't increment retry_count for the menu reopen attempt
									# Retry immediately with minimal delay
									retry_count -= 1
									step_delay = 0.5  # Use short delay after reopening
									self.logger.info('🔄 Dropdown re-opened, retrying element match...')
									continue

						if retry_count == max_retries:
							error_msg = f'{step_name} failed after {max_retries} attempts: {error_str}'
							self.logger.error(error_msg)
							# Always record the error in results so AI summary counts it correctly
							results.append(ActionResult(error=error_msg))
							if not skip_failures:
								raise RuntimeError(error_msg)
							# With skip_failures=True, continue to next step
						else:
							# Exponential backoff: 5s, 10s, 20s, ... capped at 30s
							retry_delay = min(base_retry_delay * (2 ** (retry_count - 1)), max_retry_delay)
							self.logger.warning(
								f'{step_name} failed (attempt {retry_count}/{max_retries}), retrying in {retry_delay}s...'
							)
							await asyncio.sleep(retry_delay)

				# Update tracking for redundant retry detection
				previous_item = history_item
				previous_step_succeeded = step_succeeded

			# Generate AI summary of rerun completion
			self.logger.info('🤖 Generating AI summary of rerun completion...')
			summary_result = await self._generate_rerun_summary(self.task, results, summary_llm)
			results.append(summary_result)

			return results
		finally:
			# Always close resources, even on failure
			await self.close()

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

	async def _wait_for_minimum_elements(
		self,
		min_elements: int,
		timeout: float = 30.0,
		poll_interval: float = 1.0,
	) -> BrowserStateSummary | None:
		"""Wait for the page to have at least min_elements interactive elements.

		This helps handle SPA pages where shadow DOM and dynamic content
		may not be immediately available even when document.readyState is 'complete'.

		Args:
			min_elements: Minimum number of interactive elements to wait for
			timeout: Maximum time to wait in seconds
			poll_interval: Time between polling attempts in seconds

		Returns:
			BrowserStateSummary if minimum elements found, None if timeout
		"""
		assert self.browser_session is not None, 'BrowserSession is not set up'

		start_time = time.time()
		last_count = 0

		while (time.time() - start_time) < timeout:
			state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
			if state and state.dom_state.selector_map:
				current_count = len(state.dom_state.selector_map)
				if current_count >= min_elements:
					self.logger.debug(f'✅ Page has {current_count} elements (needed {min_elements}), proceeding with action')
					return state
				if current_count != last_count:
					self.logger.debug(
						f'⏳ Waiting for elements: {current_count}/{min_elements} '
						f'(timeout in {timeout - (time.time() - start_time):.1f}s)'
					)
					last_count = current_count
			await asyncio.sleep(poll_interval)

		# Return last state even if we didn't reach min_elements
		self.logger.warning(f'⚠️ Timeout waiting for {min_elements} elements, proceeding with {last_count} elements')
		return await self.browser_session.get_browser_state_summary(include_screenshot=False)

	def _count_expected_elements_from_history(self, history_item: AgentHistory) -> int:
		"""Estimate the minimum number of elements expected based on history.

		Uses the action indices from the history to determine the minimum
		number of elements the page should have. If an action targets index N,
		the page needs at least N+1 elements in the selector_map.
		"""
		if not history_item.model_output or not history_item.model_output.action:
			return 0

		max_index = -1  # Use -1 to indicate no index found yet
		for action in history_item.model_output.action:
			# Get the element index this action targets
			index = action.get_index()
			if index is not None:
				max_index = max(max_index, index)

		# Need at least max_index + 1 elements (indices are 0-based)
		# Cap at 50 to avoid waiting forever for very high indices
		# max_index >= 0 means we found at least one action with an index
		return min(max_index + 1, 50) if max_index >= 0 else 0

	async def _execute_history_step(
		self,
		history_item: AgentHistory,
		delay: float,
		ai_step_llm: BaseChatModel | None = None,
		wait_for_elements: bool = False,
	) -> list[ActionResult]:
		"""Execute a single step from history with element validation.

		For extract actions, uses AI to re-evaluate the content since page content may have changed.

		Args:
			history_item: The history step to execute
			delay: Delay before executing the step
			ai_step_llm: Optional LLM to use for AI steps
			wait_for_elements: If True, wait for minimum elements before element matching
		"""
		assert self.browser_session is not None, 'BrowserSession is not set up'

		await asyncio.sleep(delay)

		# Optionally wait for minimum elements before element matching (useful for SPAs)
		if wait_for_elements:
			# Determine if we need to wait for elements (actions that interact with DOM elements)
			needs_element_matching = False
			if history_item.model_output:
				for i, action in enumerate(history_item.model_output.action):
					action_data = action.model_dump(exclude_unset=True)
					action_name = next(iter(action_data.keys()), None)
					# Actions that need element matching
					if action_name in ('click', 'input', 'hover', 'select_option', 'drag_and_drop'):
						historical_elem = (
							history_item.state.interacted_element[i] if i < len(history_item.state.interacted_element) else None
						)
						if historical_elem is not None:
							needs_element_matching = True
							break

			# If we need element matching, wait for minimum elements before proceeding
			if needs_element_matching:
				min_elements = self._count_expected_elements_from_history(history_item)
				if min_elements > 0:
					state = await self._wait_for_minimum_elements(min_elements, timeout=15.0, poll_interval=1.0)
				else:
					state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
			else:
				state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
		else:
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
				historical_elem = history_item.state.interacted_element[i]
				updated_action = await self._update_action_indices(
					historical_elem,
					action,
					state,
				)
				if updated_action is None:
					# Build informative error message with diagnostic info
					elem_info = self._format_element_for_error(historical_elem)
					selector_map = state.dom_state.selector_map or {}
					selector_count = len(selector_map)

					# Find elements with same node_name for diagnostics
					hist_node = historical_elem.node_name.lower() if historical_elem else ''
					similar_elements = []
					if historical_elem and historical_elem.attributes:
						for idx, elem in selector_map.items():
							if elem.node_name.lower() == hist_node and elem.attributes:
								elem_aria = elem.attributes.get('aria-label', '')
								if elem_aria:
									similar_elements.append(f'{idx}:{elem_aria[:30]}')
									if len(similar_elements) >= 5:
										break

					diagnostic = ''
					if similar_elements:
						diagnostic = f'\n  Available <{hist_node.upper()}> with aria-label: {similar_elements}'
					elif hist_node:
						same_node_count = sum(1 for e in selector_map.values() if e.node_name.lower() == hist_node)
						diagnostic = (
							f'\n  Found {same_node_count} <{hist_node.upper()}> elements (none with matching identifiers)'
						)

					raise ValueError(
						f'Could not find matching element for action {i} in current page.\n'
						f'  Looking for: {elem_info}\n'
						f'  Page has {selector_count} interactive elements.{diagnostic}\n'
						f'  Tried: EXACT hash → STABLE hash → XPATH → AX_NAME → ATTRIBUTE matching'
					)
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

		Cascading matching strategy (tries each level in order):
		1. EXACT: Full element_hash match (includes all attributes + ax_name)
		2. STABLE: Hash with dynamic CSS classes filtered out (focus, hover, animation, etc.)
		3. XPATH: XPath string match (structural position in DOM)
		4. AX_NAME: Accessible name match from accessibility tree (robust for dynamic menus)
		5. ATTRIBUTE: Unique attribute match (name, id, aria-label) for old history files
		"""
		if not historical_element or not browser_state_summary.dom_state.selector_map:
			return action

		selector_map = browser_state_summary.dom_state.selector_map
		highlight_index: int | None = None
		match_level: MatchLevel | None = None

		# Debug: log what we're looking for and what's available
		self.logger.info(
			f'🔍 Searching for element: <{historical_element.node_name}> '
			f'hash={historical_element.element_hash} stable_hash={historical_element.stable_hash}'
		)
		# Log what elements are in selector_map for debugging
		if historical_element.node_name:
			hist_name = historical_element.node_name.lower()
			matching_nodes = [
				(idx, elem.node_name, elem.attributes.get('name') if elem.attributes else None)
				for idx, elem in selector_map.items()
				if elem.node_name.lower() == hist_name
			]
			self.logger.info(
				f'🔍 Selector map has {len(selector_map)} elements, '
				f'{len(matching_nodes)} are <{hist_name.upper()}>: {matching_nodes}'
			)

		# Level 1: EXACT hash match
		for idx, elem in selector_map.items():
			if elem.element_hash == historical_element.element_hash:
				highlight_index = idx
				match_level = MatchLevel.EXACT
				break

		if highlight_index is None:
			self.logger.debug(f'EXACT hash match failed (checked {len(selector_map)} elements)')

		# Level 2: STABLE hash match (dynamic classes filtered)
		# Use stored stable_hash (computed at save time from EnhancedDOMTreeNode - single source of truth)
		if highlight_index is None and historical_element.stable_hash is not None:
			for idx, elem in selector_map.items():
				if elem.compute_stable_hash() == historical_element.stable_hash:
					highlight_index = idx
					match_level = MatchLevel.STABLE
					self.logger.info('Element matched at STABLE level (dynamic classes filtered)')
					break
			if highlight_index is None:
				self.logger.debug('STABLE hash match failed')
		elif highlight_index is None:
			self.logger.debug('STABLE hash match skipped (no stable_hash in history)')

		# Level 3: XPATH match
		if highlight_index is None and historical_element.x_path:
			for idx, elem in selector_map.items():
				if elem.xpath == historical_element.x_path:
					highlight_index = idx
					match_level = MatchLevel.XPATH
					self.logger.info(f'Element matched at XPATH level: {historical_element.x_path}')
					break
			if highlight_index is None:
				self.logger.debug(f'XPATH match failed for: {historical_element.x_path[-60:]}')

		# Level 4: ax_name (accessible name) match - robust for dynamic SPAs with menus
		# This uses the accessible name from the accessibility tree which is stable
		# even when DOM structure changes (e.g., dynamically generated menu items)
		if highlight_index is None and historical_element.ax_name:
			hist_name = historical_element.node_name.lower()
			hist_ax_name = historical_element.ax_name
			for idx, elem in selector_map.items():
				# Match by node type and accessible name
				elem_ax_name = elem.ax_node.name if elem.ax_node else None
				if elem.node_name.lower() == hist_name and elem_ax_name == hist_ax_name:
					highlight_index = idx
					match_level = MatchLevel.AX_NAME
					self.logger.info(f'Element matched at AX_NAME level: "{hist_ax_name}"')
					break
			if highlight_index is None:
				# Log available ax_names for debugging
				same_type_ax_names = [
					(idx, elem.ax_node.name if elem.ax_node else None)
					for idx, elem in selector_map.items()
					if elem.node_name.lower() == hist_name and elem.ax_node and elem.ax_node.name
				]
				self.logger.debug(
					f'AX_NAME match failed for <{hist_name.upper()}> ax_name="{hist_ax_name}". '
					f'Page has {len(same_type_ax_names)} <{hist_name.upper()}> with ax_names: '
					f'{same_type_ax_names[:5]}{"..." if len(same_type_ax_names) > 5 else ""}'
				)

		# Level 5: Unique attribute fallback (for old history files without stable_hash)
		if highlight_index is None and historical_element.attributes:
			hist_attrs = historical_element.attributes
			hist_name = historical_element.node_name.lower()

			# Try matching by unique identifiers: name, id, or aria-label
			for attr_key in ['name', 'id', 'aria-label']:
				if attr_key in hist_attrs and hist_attrs[attr_key]:
					for idx, elem in selector_map.items():
						if (
							elem.node_name.lower() == hist_name
							and elem.attributes
							and elem.attributes.get(attr_key) == hist_attrs[attr_key]
						):
							highlight_index = idx
							match_level = MatchLevel.ATTRIBUTE
							self.logger.info(f'Element matched via {attr_key} attribute: {hist_attrs[attr_key]}')
							break
					if highlight_index is not None:
						break

			if highlight_index is None:
				tried_attrs = [k for k in ['name', 'id', 'aria-label'] if k in hist_attrs and hist_attrs[k]]
				# Log what was tried and what's available on the page for debugging
				same_node_elements = [
					(idx, elem.attributes.get('aria-label') or elem.attributes.get('id') or elem.attributes.get('name'))
					for idx, elem in selector_map.items()
					if elem.node_name.lower() == hist_name and elem.attributes
				]
				self.logger.info(
					f'🔍 ATTRIBUTE match failed for <{hist_name.upper()}> '
					f'(tried: {tried_attrs}, looking for: {[hist_attrs.get(k) for k in tried_attrs]}). '
					f'Page has {len(same_node_elements)} <{hist_name.upper()}> elements with identifiers: '
					f'{same_node_elements[:5]}{"..." if len(same_node_elements) > 5 else ""}'
				)

		if highlight_index is None:
			return None

		old_index = action.get_index()
		if old_index != highlight_index:
			action.set_index(highlight_index)
			level_name = match_level.name if match_level else 'UNKNOWN'
			self.logger.info(f'Element index updated {old_index} → {highlight_index} (matched at {level_name} level)')

		return action

	def _format_element_for_error(self, elem: DOMInteractedElement | None) -> str:
		"""Format element info for error messages during history rerun."""
		if elem is None:
			return '<no element recorded>'

		parts = [f'<{elem.node_name}>']

		# Add key identifying attributes
		if elem.attributes:
			for key in ['name', 'id', 'aria-label', 'type']:
				if key in elem.attributes and elem.attributes[key]:
					parts.append(f'{key}="{elem.attributes[key]}"')

		# Add hash info
		parts.append(f'hash={elem.element_hash}')
		if elem.stable_hash:
			parts.append(f'stable_hash={elem.stable_hash}')

		# Add xpath (truncated)
		if elem.x_path:
			xpath_short = elem.x_path if len(elem.x_path) <= 60 else f'...{elem.x_path[-57:]}'
			parts.append(f'xpath="{xpath_short}"')

		return ' '.join(parts)

	def _is_redundant_retry_step(
		self,
		current_item: AgentHistory,
		previous_item: AgentHistory | None,
		previous_step_succeeded: bool,
	) -> bool:
		"""
		Detect if current step is a redundant retry of the previous step.

		This handles cases where the original run needed to click the same element multiple
		times due to slow page response, but during replay the first click already succeeded.
		When the page has already navigated, subsequent retry clicks on the same element
		would fail because that element no longer exists.

		Returns True if:
		- Previous step succeeded
		- Both steps target the same element (by element_hash, stable_hash, or xpath)
		- Both steps perform the same action type (e.g., both are clicks)
		"""
		if not previous_item or not previous_step_succeeded:
			return False

		# Get interacted elements from both steps (first action in each)
		curr_elements = current_item.state.interacted_element
		prev_elements = previous_item.state.interacted_element

		if not curr_elements or not prev_elements:
			return False

		curr_elem = curr_elements[0] if curr_elements else None
		prev_elem = prev_elements[0] if prev_elements else None

		if not curr_elem or not prev_elem:
			return False

		# Check if same element by various matching strategies
		same_by_hash = curr_elem.element_hash == prev_elem.element_hash
		same_by_stable_hash = (
			curr_elem.stable_hash is not None
			and prev_elem.stable_hash is not None
			and curr_elem.stable_hash == prev_elem.stable_hash
		)
		same_by_xpath = curr_elem.x_path == prev_elem.x_path

		if not (same_by_hash or same_by_stable_hash or same_by_xpath):
			return False

		# Check if same action type
		curr_actions = current_item.model_output.action if current_item.model_output else []
		prev_actions = previous_item.model_output.action if previous_item.model_output else []

		if not curr_actions or not prev_actions:
			return False

		# Get the action type (first key in the action dict)
		curr_action_data = curr_actions[0].model_dump(exclude_unset=True)
		prev_action_data = prev_actions[0].model_dump(exclude_unset=True)

		curr_action_type = next(iter(curr_action_data.keys()), None)
		prev_action_type = next(iter(prev_action_data.keys()), None)

		if curr_action_type != prev_action_type:
			return False

		self.logger.debug(
			f'🔄 Detected redundant retry: both steps target same element '
			f'<{curr_elem.node_name}> with action "{curr_action_type}"'
		)

		return True

	def _is_menu_opener_step(self, history_item: AgentHistory | None) -> bool:
		"""
		Detect if a step opens a dropdown/menu.

		Checks for common patterns indicating a menu opener:
		- Element has aria-haspopup attribute
		- Element has data-gw-click="toggleSubMenu" (Guidewire pattern)
		- Element has expand-button in class name
		- Element role is "menuitem" with aria-expanded

		Returns True if the step appears to open a dropdown/submenu.
		"""
		if not history_item or not history_item.state or not history_item.state.interacted_element:
			return False

		elem = history_item.state.interacted_element[0] if history_item.state.interacted_element else None
		if not elem:
			return False

		attrs = elem.attributes or {}

		# Check for common menu opener indicators
		if attrs.get('aria-haspopup') in ('true', 'menu', 'listbox'):
			return True
		if attrs.get('data-gw-click') == 'toggleSubMenu':
			return True
		if 'expand-button' in attrs.get('class', ''):
			return True
		if attrs.get('role') == 'menuitem' and attrs.get('aria-expanded') in ('false', 'true'):
			return True
		if attrs.get('role') == 'button' and attrs.get('aria-expanded') in ('false', 'true'):
			return True

		return False

	def _is_menu_item_element(self, elem: 'DOMInteractedElement | None') -> bool:
		"""
		Detect if an element is a menu item that appears inside a dropdown/menu.

		Checks for:
		- role="menuitem", "option", "menuitemcheckbox", "menuitemradio"
		- Element is inside a menu structure (has menu-related parent indicators)
		- ax_name is set (menu items typically have accessible names)

		Returns True if the element appears to be a menu item.
		"""
		if not elem:
			return False

		attrs = elem.attributes or {}

		# Check for menu item roles
		role = attrs.get('role', '')
		if role in ('menuitem', 'option', 'menuitemcheckbox', 'menuitemradio', 'treeitem'):
			return True

		# Elements in Guidewire menus have these patterns
		if 'gw-action--inner' in attrs.get('class', ''):
			return True
		if 'menuitem' in attrs.get('class', '').lower():
			return True

		# If element has an ax_name and looks like it could be in a menu
		# This is a softer check - only used if the previous step was a menu opener
		if elem.ax_name and elem.ax_name not in ('', None):
			# Common menu container classes
			elem_class = attrs.get('class', '').lower()
			if any(x in elem_class for x in ['dropdown', 'popup', 'menu', 'submenu', 'action']):
				return True

		return False

	async def _reexecute_menu_opener(
		self,
		opener_item: AgentHistory,
		ai_step_llm: 'BaseChatModel | None' = None,
	) -> bool:
		"""
		Re-execute a menu opener step to re-open a closed dropdown.

		This is used when a menu item can't be found because the dropdown
		closed during the wait between steps.

		Returns True if re-execution succeeded, False otherwise.
		"""
		try:
			self.logger.info('🔄 Re-opening dropdown/menu by re-executing previous step...')
			# Use a minimal delay - we want to quickly re-open the menu
			await self._execute_history_step(opener_item, delay=0.5, ai_step_llm=ai_step_llm, wait_for_elements=False)
			# Small delay to let the menu render
			await asyncio.sleep(0.3)
			return True
		except Exception as e:
			self.logger.warning(f'Failed to re-open dropdown: {e}')
			return False

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
			**kwargs: Additional arguments passed to rerun_history:
				- max_retries: Maximum retries per action (default: 3)
				- skip_failures: Continue on failure (default: True)
				- delay_between_actions: Delay when no saved interval (default: 2.0s)
				- max_step_interval: Cap on saved step_interval (default: 45.0s)
				- summary_llm: Custom LLM for final summary
				- ai_step_llm: Custom LLM for extract re-evaluation
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
				else:
					# keep_alive=True sessions shouldn't keep the event loop alive after agent.run()
					await self.browser_session.event_bus.stop(
						clear=False,
						timeout=_get_timeout('TIMEOUT_BrowserSessionEventBusStopOnAgentClose', 1.0),
					)
					try:
						self.browser_session.event_bus.event_queue = None
						self.browser_session.event_bus._on_idle = None
					except Exception:
						pass

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
		max_steps: int = 500,
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
