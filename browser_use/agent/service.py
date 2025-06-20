import asyncio
import gc
import inspect
import json
import logging
import os
import re
import shutil
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Generic, TypeVar

from dotenv import load_dotenv

from browser_use.agent.cloud_events import (
	CreateAgentOutputFileEvent,
	CreateAgentSessionEvent,
	CreateAgentStepEvent,
	CreateAgentTaskEvent,
	UpdateAgentTaskEvent,
)

load_dotenv()

# from lmnr.sdk.decorators import observe
from bubus import EventBus
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
	BaseMessage,
	HumanMessage,
	SystemMessage,
)
from pydantic import BaseModel, ValidationError
from uuid_extensions import uuid7str

from browser_use.agent.gif import create_history_gif
from browser_use.agent.llm_manager import LLMManager
from browser_use.agent.memory import Memory, MemoryConfig
from browser_use.agent.message_manager.service import MessageManager, MessageManagerSettings
from browser_use.agent.message_manager.utils import (
	convert_input_messages,
	extract_json_from_model_output,
	is_model_without_tool_support,
	save_conversation,
)
from browser_use.agent.prompts import AgentMessagePrompt, PlannerPrompt, SystemPrompt
from browser_use.agent.views import (
	ActionResult,
	AgentBrain,
	AgentError,
	AgentHistory,
	AgentHistoryList,
	AgentOutput,
	AgentSettings,
	AgentState,
	AgentStepInfo,
	BrowserStateHistory,
	StepMetadata,
	ToolCallingMethod,
)
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.session import DEFAULT_BROWSER_PROFILE
from browser_use.browser.types import Browser, BrowserContext, Page
from browser_use.browser.views import BrowserStateSummary
from browser_use.controller.registry.views import ActionModel
from browser_use.controller.service import Controller
from browser_use.dom.history_tree_processor.service import DOMHistoryElement, HistoryTreeProcessor
from browser_use.exceptions import LLMException
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import AgentTelemetryEvent
from browser_use.utils import _log_pretty_path, get_browser_use_version, time_execution_async, time_execution_sync

logger = logging.getLogger(__name__)

SKIP_LLM_API_KEY_VERIFICATION = os.environ.get('SKIP_LLM_API_KEY_VERIFICATION', 'false').lower()[0] in 'ty1'


def log_response(response: AgentOutput, registry=None, logger=None) -> None:
	"""Utility function to log the model's response."""

	# Use module logger if no logger provided
	if logger is None:
		logger = logging.getLogger(__name__)

	if 'Success' in response.current_state.evaluation_previous_goal:
		emoji = '👍'
	elif 'Failed' in response.current_state.evaluation_previous_goal:
		emoji = '⚠️'
	else:
		emoji = '❓'

	logger.info(f'{emoji} Eval: {response.current_state.evaluation_previous_goal}')
	logger.info(f'🧠 Memory: {response.current_state.memory}')
	logger.info(f'🎯 Next goal: {response.current_state.next_goal}\n')


Context = TypeVar('Context')

AgentHookFunc = Callable[['Agent'], Awaitable[None]]


class Agent(Generic[Context]):
	browser_session: BrowserSession | None = None
	_logger: logging.Logger | None = None

	@time_execution_sync('--init')
	def __init__(
		self,
		task: str,
		llm: BaseChatModel,
		# Optional parameters
		page: Page | None = None,
		browser: Browser | BrowserSession | None = None,
		browser_context: BrowserContext | None = None,
		browser_profile: BrowserProfile | None = None,
		browser_session: BrowserSession | None = None,
		controller: Controller[Context] = Controller(),
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
		use_vision: bool = True,
		use_vision_for_planner: bool = False,
		save_conversation_path: str | Path | None = None,
		save_conversation_path_encoding: str | None = 'utf-8',
		max_failures: int = 3,
		retry_delay: int = 10,
		override_system_message: str | None = None,
		extend_system_message: str | None = None,
		max_input_tokens: int = 128000,
		validate_output: bool = False,
		message_context: str | None = None,
		generate_gif: bool | str = False,
		available_file_paths: list[str] | None = None,
		include_attributes: list[str] = [
			'title',
			'type',
			'name',
			'role',
			'aria-label',
			'placeholder',
			'value',
			'alt',
			'aria-expanded',
			'data-date-format',
			'checked',
			'data-state',
			'aria-checked',
		],
		max_actions_per_step: int = 10,
		tool_calling_method: ToolCallingMethod | None = 'auto',
		page_extraction_llm: BaseChatModel | None = None,
		planner_llm: BaseChatModel | None = None,
		planner_interval: int = 1,  # Run planner every N steps
		is_planner_reasoning: bool = False,
		extend_planner_system_message: str | None = None,
		injected_agent_state: AgentState | None = None,
		context: Context | None = None,
		enable_memory: bool = True,
		memory_config: MemoryConfig | None = None,
		source: str | None = None,
		task_id: str | None = None,
	):
		if page_extraction_llm is None:
			page_extraction_llm = llm

		self.id = task_id or uuid7str()
		self.task_id: str = self.id
		self.session_id: str = uuid7str()

		# Create instance-specific logger
		self._logger = logging.getLogger(f'browser_use.Agent[{self.task_id[-3:]}]')

		# Core components
		self.task = task
		self.llm = llm
		self.controller = controller
		self.sensitive_data = sensitive_data

		self.settings = AgentSettings(
			use_vision=use_vision,
			use_vision_for_planner=use_vision_for_planner,
			save_conversation_path=save_conversation_path,
			save_conversation_path_encoding=save_conversation_path_encoding,
			max_failures=max_failures,
			retry_delay=retry_delay,
			override_system_message=override_system_message,
			extend_system_message=extend_system_message,
			max_input_tokens=max_input_tokens,
			validate_output=validate_output,
			message_context=message_context,
			generate_gif=generate_gif,
			available_file_paths=available_file_paths,
			include_attributes=include_attributes,
			max_actions_per_step=max_actions_per_step,
			tool_calling_method=tool_calling_method,
			page_extraction_llm=page_extraction_llm,
			planner_llm=planner_llm,
			planner_interval=planner_interval,
			is_planner_reasoning=is_planner_reasoning,
			extend_planner_system_message=extend_planner_system_message,
		)

		# Memory settings
		self.enable_memory = enable_memory
		self.memory_config = memory_config

		# Initialize state
		self.state = injected_agent_state or AgentState()

		# Action setup
		self._setup_action_models()
		self._set_browser_use_version_and_source(source)
		self.initial_actions = self._convert_initial_actions(initial_actions) if initial_actions else None

		# Model setup
		self._set_model_names()

		# Verify we can connect to the LLM and setup the tool calling method
		llm_manager = LLMManager(self.llm, self.logger, self.settings)
		self.tool_calling_method = llm_manager.verify_and_setup_llm()

		# Handle users trying to use use_vision=True with DeepSeek models
		if 'deepseek' in self.model_name.lower():
			self.logger.warning('⚠️ DeepSeek models do not support use_vision=True yet. Setting use_vision=False for now...')
			self.settings.use_vision = False
		if 'deepseek' in (self.planner_model_name or '').lower():
			self.logger.warning(
				'⚠️ DeepSeek models do not support use_vision=True yet. Setting use_vision_for_planner=False for now...'
			)
			self.settings.use_vision_for_planner = False
		# Handle users trying to use use_vision=True with XAI models
		if 'grok' in self.model_name.lower():
			self.logger.warning('⚠️ XAI models do not support use_vision=True yet. Setting use_vision=False for now...')
			self.settings.use_vision = False
		if 'grok' in (self.planner_model_name or '').lower():
			self.logger.warning(
				'⚠️ XAI models do not support use_vision=True yet. Setting use_vision_for_planner=False for now...'
			)
			self.settings.use_vision_for_planner = False

		self.logger.info(
			f'🧠 Starting a browser-use agent {self.version} with base_model={self.model_name}'
			f'{" +tools" if self.tool_calling_method == "function_calling" else ""}'
			f'{" +rawtools" if self.tool_calling_method == "raw" else ""}'
			f'{" +vision" if self.settings.use_vision else ""}'
			f'{" +memory" if self.enable_memory else ""}'
			f' extraction_model={getattr(self.settings.page_extraction_llm, "model_name", None)}'
			f'{f" planner_model={self.planner_model_name}" if self.planner_model_name else ""}'
			f'{" +reasoning" if self.settings.is_planner_reasoning else ""}'
			f'{" +vision" if self.settings.use_vision_for_planner else ""} '
		)

		# Initialize available actions for system prompt (only non-filtered actions)
		# These will be used for the system prompt to maintain caching
		self.unfiltered_actions = self.controller.registry.get_prompt_description()

		self.settings.message_context = self._set_message_context()

		# Initialize message manager with state
		# Initial system prompt with all actions - will be updated during each step
		self._message_manager = MessageManager(
			task=task,
			system_message=SystemPrompt(
				action_description=self.unfiltered_actions,
				max_actions_per_step=self.settings.max_actions_per_step,
				override_system_message=override_system_message,
				extend_system_message=extend_system_message,
			).get_system_message(),
			settings=MessageManagerSettings(
				max_input_tokens=self.settings.max_input_tokens,
				include_attributes=self.settings.include_attributes,
				message_context=self.settings.message_context,
				sensitive_data=sensitive_data,
				available_file_paths=self.settings.available_file_paths,
			),
			state=self.state.message_manager_state,
		)

		if self.enable_memory:
			try:
				# Initialize memory
				self.memory = Memory(
					message_manager=self._message_manager,
					llm=self.llm,
					config=self.memory_config,
				)
			except ImportError:
				self.logger.warning(
					'⚠️ Agent(enable_memory=True) is set but missing some required packages, install and re-run to use memory features: pip install browser-use[memory]'
				)
				self.memory = None
				self.enable_memory = False
		else:
			self.memory = None

		if isinstance(browser, BrowserSession):
			browser_session = browser_session or browser

		browser_context = page.context if page else browser_context
		browser_profile = browser_profile or DEFAULT_BROWSER_PROFILE

		if browser_session:
			# Check if user is trying to reuse an uninitialized session
			if browser_session.browser_profile.keep_alive and not browser_session.initialized:
				self.logger.error(
					'❌ Passed a BrowserSession with keep_alive=True that is not initialized. '
					'Call await browser_session.start() before passing it to Agent() to reuse the same browser. '
					'Otherwise, each agent will launch its own browser instance.'
				)
				raise ValueError(
					'BrowserSession with keep_alive=True must be initialized before passing to Agent. '
					'Call: await browser_session.start()'
				)

			# always copy sessions that are passed in to avoid agents overwriting each other's agent_current_page and human_current_page by accident
			self.browser_session = browser_session.model_copy()
		else:
			if browser is not None:
				assert isinstance(browser, Browser), 'Browser is not set up'
			self.browser_session = BrowserSession(
				browser_profile=browser_profile,
				browser=browser,
				browser_context=browser_context,
				agent_current_page=page,
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
		from browser_use.utils import BROWSER_USE_CONFIG_DIR

		wal_path = BROWSER_USE_CONFIG_DIR / 'events' / f'{self.task_id}.jsonl'
		self.eventbus = EventBus(name='Agent', wal_path=wal_path)

		# Cloud sync service
		self.enable_cloud_sync = os.environ.get('BROWSERUSE_CLOUD_SYNC', 'true').lower()[0] in 'ty1'
		if self.enable_cloud_sync:
			from browser_use.sync import CloudSync

			self.cloud_sync = CloudSync()
			# Register cloud sync handler
			self.eventbus.on('*', self.cloud_sync.handle_event)

		if self.settings.save_conversation_path:
			self.settings.save_conversation_path = Path(self.settings.save_conversation_path).expanduser().resolve()
			self.logger.info(f'💬 Saving conversation to {_log_pretty_path(self.settings.save_conversation_path)}')
		self._external_pause_event = asyncio.Event()
		self._external_pause_event.set()

	@property
	def logger(self) -> logging.Logger:
		"""Get instance-specific logger with task ID in the name"""

		_browser_session_id = self.browser_session.id if self.browser_session else self.id
		_current_page_id = str(id(self.browser_session and self.browser_session.agent_current_page))[-2:]
		return logging.getLogger(f'browser_use.Agent🅰 {self.task_id[-4:]} on 🆂 {_browser_session_id[-4:]}.{_current_page_id}')

	@property
	def browser(self) -> Browser:
		assert self.browser_session is not None, 'BrowserSession is not set up'
		assert self.browser_session.browser is not None, 'Browser is not set up'
		return self.browser_session.browser

	@property
	def browser_context(self) -> BrowserContext:
		assert self.browser_session is not None, 'BrowserSession is not set up'
		assert self.browser_session.browser_context is not None, 'BrowserContext is not set up'
		return self.browser_session.browser_context

	@property
	def browser_profile(self) -> BrowserProfile:
		assert self.browser_session is not None, 'BrowserSession is not set up'
		return self.browser_session.browser_profile

	def _set_message_context(self) -> str | None:
		if self.tool_calling_method == 'raw':
			# For raw tool calling, only include actions with no filters initially
			if self.settings.message_context:
				self.settings.message_context += f'\n\nAvailable actions: {self.unfiltered_actions}'
			else:
				self.settings.message_context = f'Available actions: {self.unfiltered_actions}'
		return self.settings.message_context

	def _set_browser_use_version_and_source(self, source_override: str | None = None) -> None:
		"""Get the version from pyproject.toml and determine the source of the browser-use package"""
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

	def _set_model_names(self) -> None:
		self.chat_model_library = self.llm.__class__.__name__
		self.model_name = 'Unknown'
		if hasattr(self.llm, 'model_name'):
			model = self.llm.model_name
			self.model_name = model if model is not None else 'Unknown'
		elif hasattr(self.llm, 'model'):
			model = self.llm.model
			self.model_name = model if model is not None else 'Unknown'

		if self.settings.planner_llm:
			if hasattr(self.settings.planner_llm, 'model_name'):
				self.planner_model_name = self.settings.planner_llm.model_name
			elif hasattr(self.settings.planner_llm, 'model'):
				self.planner_model_name = self.settings.planner_llm.model
			else:
				self.planner_model_name = 'Unknown'
		else:
			self.planner_model_name = None

	def _setup_action_models(self) -> None:
		"""Setup dynamic action models from controller's registry"""
		self.ActionModel = self.controller.registry.create_action_model()
		self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)
		self.DoneActionModel = self.controller.registry.create_action_model(include_actions=['done'])
		self.DoneAgentOutput = AgentOutput.type_with_custom_actions(self.DoneActionModel)

	def add_new_task(self, new_task: str) -> None:
		"""Add a new task to the agent, keeping the same task_id as tasks are continuous"""
		self.task = new_task
		self._message_manager.add_new_task(new_task)

	async def _raise_if_stopped_or_paused(self) -> None:
		"""Utility function that raises an InterruptedError if the agent is stopped or paused."""
		if self.register_external_agent_status_raise_error_callback:
			if await self.register_external_agent_status_raise_error_callback():
				raise InterruptedError
		if self.state.stopped or self.state.paused:
			raise InterruptedError

	@time_execution_async('--step')
	async def step(self, step_info: AgentStepInfo | None = None) -> None:
		"""Execute one step of the task"""
		browser_state_summary = None
		model_output = None
		result: list[ActionResult] = []
		step_start_time = time.time()
		tokens = 0

		try:
			assert self.browser_session is not None, 'BrowserSession is not set up'
			browser_state_summary = await self.browser_session.get_state_summary(cache_clickable_elements_hashes=True)
			current_page = await self.browser_session.get_current_page()

			self._log_step_context(current_page, browser_state_summary)

			if self.enable_memory and self.memory and self.state.n_steps % self.memory.config.memory_interval == 0:
				self.memory.create_procedural_memory(self.state.n_steps)

			await self._raise_if_stopped_or_paused()
			await self._update_action_models_for_page(current_page)
			page_filtered_actions = self.controller.registry.get_prompt_description(current_page)

			if self.sensitive_data:
				self._message_manager.add_sensitive_data(current_page.url)

			if page_filtered_actions:
				page_action_message = f'For this page, these additional actions are available:\n{page_filtered_actions}'
				self._message_manager._add_message_with_tokens(HumanMessage(content=page_action_message))

			if self.tool_calling_method == 'raw':
				all_unfiltered_actions = self.controller.registry.get_prompt_description()
				all_actions = all_unfiltered_actions
				if page_filtered_actions:
					all_actions += '\n' + page_filtered_actions

				context_lines = (self._message_manager.settings.message_context or '').split('\n')
				non_action_lines = [line for line in context_lines if not line.startswith('Available actions:')]
				updated_context = '\n'.join(non_action_lines)
				if updated_context:
					updated_context += f'\n\nAvailable actions: {all_actions}'
				else:
					updated_context = f'Available actions: {all_actions}'
				self._message_manager.settings.message_context = updated_context

			self._message_manager.add_state_message(
				browser_state_summary=browser_state_summary,
				result=self.state.last_result,
				step_info=step_info,
				use_vision=self.settings.use_vision,
			)

			if self.settings.planner_llm and self.state.n_steps % self.settings.planner_interval == 0:
				plan = await self._run_planner()
				self._message_manager.add_plan(plan, position=-1)

			if step_info and step_info.is_last_step():
				msg = 'Now comes your last step. Use only the "done" action now... If the task is fully finished, set success in "done" to true.'
				self.logger.info('Last step finishing up')
				self._message_manager._add_message_with_tokens(HumanMessage(content=msg))
				self.AgentOutput = self.DoneAgentOutput

			input_messages = self._message_manager.get_messages()
			tokens = self._message_manager.state.history.current_tokens

			try:
				model_output = await self.get_next_action(input_messages)
				if not model_output.action or all(action.model_dump() == {} for action in model_output.action):
					self.logger.warning('Model returned empty action. Retrying...')
					clarification_message = HumanMessage(content='You forgot to return an action. Please respond only with a valid JSON action.')
					retry_messages = input_messages + [clarification_message]
					model_output = await self.get_next_action(retry_messages)
					if not model_output.action or all(action.model_dump() == {} for action in model_output.action):
						self.logger.warning('Model still returned empty after retry. Inserting safe noop action.')
						action_instance = self.ActionModel(**{'done': {'success': False, 'text': 'No next action returned by LLM!'}})
						model_output.action = [action_instance]

				await self._raise_if_stopped_or_paused()
				self.state.n_steps += 1

				if self.register_new_step_callback:
					if inspect.iscoroutinefunction(self.register_new_step_callback):
						await self.register_new_step_callback(browser_state_summary, model_output, self.state.n_steps)
					else:
						self.register_new_step_callback(browser_state_summary, model_output, self.state.n_steps)
				if self.settings.save_conversation_path:
					conversation_dir = Path(self.settings.save_conversation_path)
					conversation_filename = f'conversation_{self.id}_{self.state.n_steps}.txt'
					target = conversation_dir / conversation_filename
					await save_conversation(input_messages, model_output, target, self.settings.save_conversation_path_encoding)

				self._message_manager._remove_last_state_message()
				await self._raise_if_stopped_or_paused()
				self._message_manager.add_model_output(model_output)
			except (asyncio.CancelledError, InterruptedError) as e:
				self._message_manager._remove_last_state_message()
				raise InterruptedError('Model query cancelled or agent paused') from e
			except Exception as e:
				self._message_manager._remove_last_state_message()
				raise e

			result: list[ActionResult] = await self.multi_act(model_output.action)
			self.state.last_result = result
			if result and result[-1].is_done:
				self.logger.info(f'📄 Result: {result[-1].extracted_content}')
			self.state.consecutive_failures = 0

		except InterruptedError:
			self.state.last_result = [ActionResult(error='The agent was paused mid-step', include_in_memory=False)]
			return
		except asyncio.CancelledError:
			self.state.last_result = [ActionResult(error='The agent was paused with Ctrl+C', include_in_memory=False)]
			raise InterruptedError('Step cancelled by user')
		except Exception as e:
			result = await self._handle_step_error(e)
			self.state.last_result = result
		finally:
			step_end_time = time.time()
			if not result:
				return
			if browser_state_summary:
				metadata = StepMetadata(step_number=self.state.n_steps, step_start_time=step_start_time, step_end_time=step_end_time, input_tokens=tokens)
				self._make_history_item(model_output, browser_state_summary, result, metadata)
			self._log_step_completion_summary(step_start_time, result)
			if browser_state_summary and model_output:
				actions_data = [action.model_dump() for action in model_output.action] if model_output.action else []
				step_event = CreateAgentStepEvent.from_agent_step(self, model_output, result, actions_data, browser_state_summary)
				self.eventbus.dispatch(step_event)

	@time_execution_async('--handle_step_error (agent)')
	async def _handle_step_error(self, error: Exception) -> list[ActionResult]:
		"""Handle all types of errors that can occur during a step"""
		include_trace = self.logger.isEnabledFor(logging.DEBUG)
		error_msg = AgentError.format_error(error, include_trace=include_trace)
		prefix = f'❌ Result failed {self.state.consecutive_failures + 1}/{self.settings.max_failures} times:\n '
		self.state.consecutive_failures += 1

		if 'Browser closed' in error_msg:
			self.logger.error('❌  Browser is closed or disconnected, unable to proceed')
			return [ActionResult(error='Browser closed or disconnected, unable to proceed', include_in_memory=False)]

		if isinstance(error, (ValidationError, ValueError)):
			self.logger.error(f'{prefix}{error_msg}')
			if 'Max token limit reached' in error_msg:
				self._message_manager.settings.max_input_tokens -= 500
				self.logger.info(f'Cutting tokens from history - new max input tokens: {self._message_manager.settings.max_input_tokens}')
				self._message_manager.cut_messages()
			elif 'Could not parse response' in error_msg:
				error_msg += '\n\nReturn a valid JSON object with the required fields.'
		else:
			from anthropic import RateLimitError as AnthropicRateLimitError
			from google.api_core.exceptions import ResourceExhausted
			from openai import RateLimitError
			RATE_LIMIT_ERRORS = (RateLimitError, ResourceExhausted, AnthropicRateLimitError)
			if isinstance(error, RATE_LIMIT_ERRORS):
				self.logger.warning(f'{prefix}{error_msg}')
				await asyncio.sleep(self.settings.retry_delay)
			else:
				self.logger.error(f'{prefix}{error_msg}')
		return [ActionResult(error=error_msg, include_in_memory=True)]

	def _make_history_item(self, model_output: AgentOutput | None, browser_state_summary: BrowserStateSummary, result: list[ActionResult], metadata: StepMetadata | None = None):
		if model_output:
			interacted_elements = AgentHistory.get_interacted_element(model_output, browser_state_summary.selector_map)
		else:
			interacted_elements = [None]
		state_history = BrowserStateHistory(url=browser_state_summary.url, title=browser_state_summary.title, tabs=browser_state_summary.tabs, interacted_element=interacted_elements, screenshot=browser_state_summary.screenshot)
		history_item = AgentHistory(model_output=model_output, result=result, state=state_history, metadata=metadata)
		self.state.history.history.append(history_item)

	THINK_TAGS = re.compile(r'<think>.*?</think>', re.DOTALL)
	STRAY_CLOSE_TAG = re.compile(r'.*?</think>', re.DOTALL)

	def _remove_think_tags(self, text: str) -> str:
		text = re.sub(self.THINK_TAGS, '', text)
		text = re.sub(self.STRAY_CLOSE_TAG, '', text)
		return text.strip()

	def _convert_input_messages(self, input_messages: list[BaseMessage]) -> list[BaseMessage]:
		"""Convert input messages to the correct format"""
		if is_model_without_tool_support(self.model_name):
			return convert_input_messages(input_messages, self.model_name)
		return input_messages

	@time_execution_async('--get_next_action')
	async def get_next_action(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get next action from LLM based on current state"""
		input_messages = self._convert_input_messages(input_messages)

		if self.tool_calling_method == 'raw':
			self._log_llm_call_info(input_messages, self.tool_calling_method)
			try:
				output = await self.llm.ainvoke(input_messages)
				response = {'raw': output, 'parsed': None}
				output.content = self._remove_think_tags(str(output.content))
				parsed_json = extract_json_from_model_output(output.content)
				parsed = self.AgentOutput(**parsed_json)
				response['parsed'] = parsed
			except Exception as e:
				raise LLMException(getattr(e, 'status_code', 500), f'LLM API call failed: {type(e).__name__}: {e}') from e
		elif self.tool_calling_method is None:
			structured_llm = self.llm.with_structured_output(self.AgentOutput, include_raw=True)
			try:
				response = await structured_llm.ainvoke(input_messages)
			except Exception as e:
				raise LLMException(401, 'LLM API call failed') from e
		else:
			self._log_llm_call_info(input_messages, self.tool_calling_method)
			structured_llm = self.llm.with_structured_output(self.AgentOutput, include_raw=True, method=self.tool_calling_method)
			response = await structured_llm.ainvoke(input_messages)

		parsed = response.get('parsed')
		if not parsed:
			if response.get('parsing_error') and 'raw' in response and hasattr(response['raw'], 'tool_calls') and response['raw'].tool_calls:
				tool_call = response['raw'].tool_calls[0]
				current_state = {'page_summary': 'Processing tool call', 'evaluation_previous_goal': 'Executing action', 'memory': 'Using tool call', 'next_goal': f'Execute {tool_call["name"]}'}
				action = {tool_call['name']: tool_call['args']}
				parsed = self.AgentOutput(current_state=AgentBrain(**current_state), action=[self.ActionModel(**action)])
			else:
				try:
					parsed_json = extract_json_from_model_output(response['raw'].content)
					parsed = self.AgentOutput(**parsed_json)
				except Exception as e:
					raise ValueError('Could not parse response.') from e

		if len(parsed.action) > self.settings.max_actions_per_step:
			parsed.action = parsed.action[:self.settings.max_actions_per_step]
		if not (hasattr(self.state, 'paused') and (self.state.paused or self.state.stopped)):
			log_response(parsed, self.controller.registry.registry, self.logger)
		self._log_next_action_summary(parsed)
		return parsed

	def _log_agent_run(self):
		self.logger.info(f'🚀 Starting task: {self.task}')
		self.logger.debug(f'🤖 Browser-Use Library Version {self.version} ({self.source})')

	def _log_step_context(self, current_page, browser_state_summary):
		url_short = current_page.url[:50] + '...' if len(current_page.url) > 50 else current_page.url
		interactive_count = len(browser_state_summary.selector_map) if browser_state_summary else 0
		self.logger.info(f'📍 Step {self.state.n_steps}: Evaluating page with {interactive_count} interactive elements on: {url_short}')

	def _log_next_action_summary(self, parsed: 'AgentOutput'):
		if not (self.logger.isEnabledFor(logging.DEBUG) and parsed.action):
			return
		action_count = len(parsed.action)
		action_details = []
		for action in parsed.action:
			action_data = action.model_dump(exclude_unset=True)
			action_name = next(iter(action_data), 'unknown')
			action_params = action_data.get(action_name, {})
			param_summary = [f'{k}={v}' for k, v in action_params.items() if len(str(v)) < 20]
			param_str = f'({", ".join(param_summary)})' if param_summary else ''
			action_details.append(f'{action_name}{param_str}')
		if action_count == 1:
			self.logger.info(f'☝️ Decided next action: {action_details[0]}')
		else:
			summary = '\n'.join([f'          {i + 1}. {detail}' for i, detail in enumerate(action_details)])
			self.logger.info(f'✌️ Decided next {action_count} multi-actions:\n{summary}')

	def _log_step_completion_summary(self, step_start_time: float, result: list[ActionResult]):
		if not result:
			return
		step_duration = time.time() - step_start_time
		action_count = len(result)
		success_count = sum(1 for r in result if not r.error)
		failure_count = action_count - success_count
		status_parts = [f'✅ {success_count}' if success_count > 0 else '', f'❌ {failure_count}' if failure_count > 0 else '']
		status_str = ' | '.join(filter(None, status_parts)) or '✅ 0'
		self.logger.info(f'📍 Step {self.state.n_steps}: Ran {action_count} actions in {step_duration:.2f}s: {status_str}')

	def _log_llm_call_info(self, input_messages: list[BaseMessage], method: str):
		message_count = len(input_messages)
		total_chars = sum(len(str(msg.content)) for msg in input_messages)
		has_images = any(isinstance(msg.content, list) and any(isinstance(item, dict) and item.get('type') == 'image_url' for item in msg.content) for msg in input_messages)
		current_tokens = getattr(self._message_manager.state.history, 'current_tokens', 0)
		tool_count = len(self.ActionModel.model_fields) if hasattr(self, 'ActionModel') else 0
		image_status = ', 📷 img' if has_images else ''
		output_format, tool_info = ('=> raw text', '') if method == 'raw' else ('=> JSON out', f' + 🔨 {tool_count} tools ({method})')
		term_width = shutil.get_terminal_size((80, 20)).columns
		print('=' * term_width)
		self.logger.info(f'🧠 LLM call => {self.chat_model_library} [✉️ {message_count} msg, ~{current_tokens} tk, {total_chars} char{image_status}] {output_format}{tool_info}')

	def _log_agent_event(self, max_steps: int, agent_run_error: str | None = None):
		action_history_data = [item.model_output.action for item in self.state.history.history if item.model_output and item.model_output.action]
		final_res = self.state.history.final_result()
		final_result_str = json.dumps(final_res) if final_res else None
		self.telemetry.capture(AgentTelemetryEvent(task=self.task, model=self.model_name, model_provider=self.chat_model_library, planner_llm=self.planner_model_name, max_steps=max_steps, max_actions_per_step=self.settings.max_actions_per_step, use_vision=self.settings.use_vision, use_validation=self.settings.validate_output, version=self.version, source=self.source, action_errors=self.state.history.errors(), action_history=[[a.model_dump(exclude_unset=True) for a in step_actions] for step_actions in action_history_data], urls_visited=self.state.history.urls(), steps=self.state.n_steps, total_input_tokens=self.state.history.total_input_tokens(), total_duration_seconds=self.state.history.total_duration_seconds(), success=self.state.history.is_successful(), final_result_response=final_result_str, error_message=agent_run_error))

	async def take_step(self) -> tuple[bool, bool]:
		await self.step()
		if self.state.history.is_done():
			if self.settings.validate_output and not await self._validate_output():
				return True, False
			await self.log_completion()
			if self.register_done_callback:
				if inspect.iscoroutinefunction(self.register_done_callback):
					await self.register_done_callback(self.state.history)
				else:
					self.register_done_callback(self.state.history)
			return True, True
		return False, False

	@time_execution_async('--run')
	async def run(self, max_steps: int = 100, on_step_start: AgentHookFunc | None = None, on_step_end: AgentHookFunc | None = None) -> AgentHistoryList:
		loop = asyncio.get_event_loop()
		agent_run_error: str | None = None
		self._force_exit_telemetry_logged = False
		from browser_use.utils import SignalHandler
		def on_force_exit_log_telemetry():
			self._log_agent_event(max_steps=max_steps, agent_run_error='SIGINT: Cancelled by user')
			if hasattr(self, 'telemetry'):
				self.telemetry.flush()
			self._force_exit_telemetry_logged = True
		signal_handler = SignalHandler(loop=loop, pause_callback=self.pause, resume_callback=self.resume, custom_exit_callback=on_force_exit_log_telemetry, exit_on_second_int=True)
		signal_handler.register()
		try:
			self._log_agent_run()
			self._session_start_time = time.time()
			self._task_start_time = self._session_start_time
			self.eventbus.dispatch(CreateAgentSessionEvent.from_agent(self))
			self.eventbus.dispatch(CreateAgentTaskEvent.from_agent(self))
			if self.initial_actions:
				self.state.last_result = await self.multi_act(self.initial_actions, check_for_new_elements=False)
			for step in range(max_steps):
				if self.state.paused:
					await self.wait_until_resumed()
					signal_handler.reset()
				if self.state.consecutive_failures >= self.settings.max_failures:
					agent_run_error = f'Stopped due to {self.settings.max_failures} consecutive failures'
					self.logger.error(f'❌ {agent_run_error}')
					break
				if self.state.stopped:
					agent_run_error = 'Agent stopped programmatically'
					self.logger.info(f'🛑 {agent_run_error}')
					break
				if on_step_start:
					await on_step_start(self)
				await self.step(AgentStepInfo(step_number=step, max_steps=max_steps))
				if on_step_end:
					await on_step_end(self)
				if self.state.history.is_done():
					if self.settings.validate_output and step < max_steps - 1 and not await self._validate_output():
						continue
					await self.log_completion()
					break
			else:
				agent_run_error = 'Failed to complete task in maximum steps'
				self.state.history.history.append(AgentHistory(model_output=None, result=[ActionResult(error=agent_run_error, include_in_memory=True)], state=BrowserStateHistory(url='', title='', tabs=[], interacted_element=[], screenshot=None), metadata=None))
				self.logger.info(f'❌ {agent_run_error}')
			return self.state.history
		except KeyboardInterrupt:
			agent_run_error = 'KeyboardInterrupt'
			self.logger.info('Got KeyboardInterrupt during execution, returning current history')
			return self.state.history
		except Exception as e:
			agent_run_error = str(e)
			self.logger.error(f'Agent run failed with exception: {e}', exc_info=True)
			raise
		finally:
			signal_handler.unregister()
			if not self._force_exit_telemetry_logged:
				try:
					self._log_agent_event(max_steps=max_steps, agent_run_error=agent_run_error)
				except Exception as log_e:
					self.logger.error(f'Failed to log telemetry event: {log_e}', exc_info=True)
			else:
				self.logger.info('Telemetry for force exit (SIGINT) was logged by custom exit callback.')
			self.eventbus.dispatch(UpdateAgentTaskEvent.from_agent(self))
			if self.settings.generate_gif:
				output_path = self.settings.generate_gif if isinstance(self.settings.generate_gif, str) else 'agent_history.gif'
				create_history_gif(task=self.task, history=self.state.history, output_path=output_path)
				output_event = await CreateAgentOutputFileEvent.from_agent_and_file(self, output_path)
				self.eventbus.dispatch(output_event)
			if self.enable_cloud_sync and hasattr(self, 'cloud_sync'):
				await self.cloud_sync.wait_for_auth()
			await self.eventbus.stop(timeout=5.0)
			await self.close()

	@time_execution_async('--multi_act')
	async def multi_act(self, actions: list[ActionModel], check_for_new_elements: bool = True) -> list[ActionResult]:
		results = []
		assert self.browser_session, 'BrowserSession is not set up'
		cached_selector_map = await self.browser_session.get_selector_map()
		cached_path_hashes = {e.hash.branch_path_hash for e in cached_selector_map.values()}
		await self.browser_session.remove_highlights()
		for i, action in enumerate(actions):
			if action.get_index() is not None and i != 0:
				new_browser_state_summary = await self.browser_session.get_state_summary(cache_clickable_elements_hashes=False)
				new_selector_map = new_browser_state_summary.selector_map
				orig_target = cached_selector_map.get(action.get_index())
				new_target = new_selector_map.get(action.get_index())
				if (orig_target.hash.branch_path_hash if orig_target else None) != (new_target.hash.branch_path_hash if new_target else None):
					msg = f'Element index changed after action {i + 1}/{len(actions)}, because page changed.'
					self.logger.info(msg)
					results.append(ActionResult(extracted_content=msg, include_in_memory=True))
					break
				new_path_hashes = {e.hash.branch_path_hash for e in new_selector_map.values()}
				if check_for_new_elements and not new_path_hashes.issubset(cached_path_hashes):
					msg = f'Something new appeared after action {i + 1}/{len(actions)}'
					self.logger.info(msg)
					results.append(ActionResult(extracted_content=msg, include_in_memory=True))
					break
			try:
				await self._raise_if_stopped_or_paused()
				result = await self.controller.act(action=action, browser_session=self.browser_session, page_extraction_llm=self.settings.page_extraction_llm, sensitive_data=self.sensitive_data, available_file_paths=self.settings.available_file_paths, context=self.context)
				results.append(result)
				action_data = action.model_dump(exclude_unset=True)
				action_name = next(iter(action_data), 'unknown')
				action_params = getattr(action, action_name, '')
				self.logger.info(f'☑️ Executed action {i + 1}/{len(actions)}: {action_name}({action_params})')
				if results[-1].is_done or results[-1].error or i == len(actions) - 1:
					break
				await asyncio.sleep(self.browser_profile.wait_between_actions)
			except asyncio.CancelledError:
				self.logger.info(f'Action {i + 1} was cancelled due to Ctrl+C')
				if not results:
					results.append(ActionResult(error='The action was cancelled due to Ctrl+C', include_in_memory=True))
				raise InterruptedError('Action cancelled by user')
		return results

	async def _validate_output(self) -> bool:
		system_msg = 'You are a validator... your task is to validate if the output of the last action is what the user wanted and if the task is completed...'
		if self.browser_context and self.browser_session:
			browser_state_summary = await self.browser_session.get_state_summary(cache_clickable_elements_hashes=False)
			assert browser_state_summary
			content = AgentMessagePrompt(browser_state_summary=browser_state_summary, result=self.state.last_result, include_attributes=self.settings.include_attributes)
			msg = [SystemMessage(content=system_msg), content.get_user_message(self.settings.use_vision)]
		else:
			return True
		class ValidationResult(BaseModel):
			is_valid: bool
			reason: str
		validator = self.llm.with_structured_output(ValidationResult, include_raw=True)
		response = await validator.ainvoke(msg)
		parsed: ValidationResult = response['parsed']
		if not parsed.is_valid:
			self.logger.info(f'❌ Validator decision: {parsed.reason}')
			self.state.last_result = [ActionResult(extracted_content=f'The output is not yet correct. {parsed.reason}.', include_in_memory=True)]
		else:
			self.logger.info(f'✅ Validator decision: {parsed.reason}')
		return parsed.is_valid

	async def log_completion(self):
		if self.state.history.is_successful():
			self.logger.info('✅ Task completed successfully')
		else:
			self.logger.info('❌ Task completed without success')
		self.logger.debug(f'💲 Total input tokens used (approximate): {self.state.history.total_input_tokens()}')
		if self.register_done_callback:
			if inspect.iscoroutinefunction(self.register_done_callback):
				await self.register_done_callback(self.state.history)
			else:
				self.register_done_callback(self.state.history)

	async def rerun_history(self, history: AgentHistoryList, max_retries: int = 3, skip_failures: bool = True, delay_between_actions: float = 2.0) -> list[ActionResult]:
		if self.initial_actions:
			self.state.last_result = await self.multi_act(self.initial_actions)
		results = []
		for i, history_item in enumerate(history.history):
			goal = history_item.model_output.current_state.next_goal if history_item.model_output else ''
			self.logger.info(f'Replaying step {i + 1}/{len(history.history)}: goal: {goal}')
			if not history_item.model_output or not history_item.model_output.action:
				results.append(ActionResult(error='No action to replay'))
				continue
			for retry_count in range(max_retries):
				try:
					results.extend(await self._execute_history_step(history_item, delay_between_actions))
					break
				except Exception as e:
					if retry_count == max_retries - 1:
						error_msg = f'Step {i + 1} failed after {max_retries} attempts: {e}'
						self.logger.error(error_msg)
						if not skip_failures:
							results.append(ActionResult(error=error_msg))
							raise RuntimeError(error_msg)
					else:
						self.logger.warning(f'Step {i + 1} failed (attempt {retry_count + 1}/{max_retries}), retrying...')
						await asyncio.sleep(delay_between_actions)
		return results

	async def _execute_history_step(self, history_item: AgentHistory, delay: float) -> list[ActionResult]:
		assert self.browser_session, 'BrowserSession is not set up'
		state = await self.browser_session.get_state_summary(cache_clickable_elements_hashes=False)
		if not state or not history_item.model_output:
			raise ValueError('Invalid state or model output')
		updated_actions = []
		for i, action in enumerate(history_item.model_output.action):
			updated_action = await self._update_action_indices(history_item.state.interacted_element[i], action, state)
			if updated_action is None:
				raise ValueError(f'Could not find matching element {i} in current page')
			updated_actions.append(updated_action)
		result = await self.multi_act(updated_actions)
		await asyncio.sleep(delay)
		return result

	async def _update_action_indices(self, historical_element: DOMHistoryElement | None, action: ActionModel, browser_state_summary: BrowserStateSummary) -> ActionModel | None:
		if not historical_element or not browser_state_summary.element_tree:
			return action
		current_element = HistoryTreeProcessor.find_history_element_in_tree(historical_element, browser_state_summary.element_tree)
		if not current_element or current_element.highlight_index is None:
			return None
		old_index = action.get_index()
		if old_index != current_element.highlight_index:
			action.set_index(current_element.highlight_index)
			self.logger.info(f'Element moved in DOM, updated index from {old_index} to {current_element.highlight_index}')
		return action

	async def load_and_rerun(self, history_file: str | Path | None = None, **kwargs) -> list[ActionResult]:
		history_file = history_file or 'AgentHistory.json'
		history = AgentHistoryList.load_from_file(history_file, self.AgentOutput)
		return await self.rerun_history(history, **kwargs)

	def save_history(self, file_path: str | Path | None = None):
		file_path = file_path or 'AgentHistory.json'
		self.state.history.save_to_file(file_path)

	async def wait_until_resumed(self):
		await self._external_pause_event.wait()

	def pause(self):
		print('\n\n⏸️  Got [Ctrl+C], paused the agent and left the browser open.\n\tPress [Enter] to resume or [Ctrl+C] again to quit.')
		self.state.paused = True
		self._external_pause_event.clear()

	def resume(self):
		print('----------------------------------------------------------------------\n▶️  Got Enter, resuming agent execution where it left off...\n')
		self.state.paused = False
		self._external_pause_event.set()
		if self.browser:
			self.logger.info('🌎 Restarting/reconnecting to browser...')
			loop = asyncio.get_event_loop()
			loop.create_task(self.browser._init())
			loop.create_task(asyncio.sleep(5))

	def stop(self):
		self.logger.info('⏹️ Agent stopping')
		self.state.stopped = True

	def _convert_initial_actions(self, actions: list[dict[str, dict[str, Any]]]) -> list[ActionModel]:
		converted_actions = []
		for action_dict in actions:
			action_name = next(iter(action_dict))
			params = action_dict[action_name]
			action_info = self.controller.registry.registry.actions[action_name]
			validated_params = action_info.param_model(**params)
			action_model = self.ActionModel(**{action_name: validated_params})
			converted_actions.append(action_model)
		return converted_actions

	async def _run_planner(self) -> str | None:
		if not self.settings.planner_llm:
			return None
		assert self.browser_session, 'BrowserSession is not set up'
		page = await self.browser_session.get_current_page()
		standard_actions = self.controller.registry.get_prompt_description()
		page_actions = self.controller.registry.get_prompt_description(page)
		all_actions = standard_actions + ('\n' + page_actions if page_actions else '')
		planner_messages = [PlannerPrompt(all_actions).get_system_message(is_planner_reasoning=self.settings.is_planner_reasoning, extended_planner_system_prompt=self.settings.extend_planner_system_message), *self._message_manager.get_messages()[1:]]
		if not self.settings.use_vision_for_planner and self.settings.use_vision:
			last_state_message = planner_messages[-1]
			new_msg = ''.join(item['text'] for item in last_state_message.content if isinstance(item, dict) and item.get('type') == 'text')
			planner_messages[-1] = HumanMessage(content=new_msg)
		planner_messages = convert_input_messages(planner_messages, self.planner_model_name)
		try:
			response = await self.settings.planner_llm.ainvoke(planner_messages)
			plan = str(response.content)
			if self.planner_model_name and 'deepseek' in self.planner_model_name:
				plan = self._remove_think_tags(plan)
			try:
				plan_json = json.loads(plan)
				self.logger.info(f'Planning Analysis:\n{json.dumps(plan_json, indent=4)}')
			except json.JSONDecodeError:
				self.logger.info(f'Planning Analysis:\n{plan}')
			return plan
		except Exception as e:
			raise LLMException(getattr(e, 'status_code', 500), f'Planner LLM API call failed: {type(e).__name__}: {e}') from e

	@property
	def message_manager(self) -> MessageManager:
		return self._message_manager

	async def close(self):
		try:
			assert self.browser_session, 'BrowserSession is not set up'
			await self.browser_session.stop()
			gc.collect()
		except Exception as e:
			self.logger.error(f'Error during cleanup: {e}')

	async def _update_action_models_for_page(self, page):
		self.ActionModel = self.controller.registry.create_action_model(page=page)
		self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)
		self.DoneActionModel = self.controller.registry.create_action_model(include_actions=['done'], page=page)
		self.DoneAgentOutput = AgentOutput.type_with_custom_actions(self.DoneActionModel)
