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
from threading import Thread
from typing import Any, Generic, TypeVar

from dotenv import load_dotenv

from browser_use.agent.cloud_events import (
	CreateAgentOutputFileEvent,
	CreateAgentSessionEvent,
	CreateAgentStepEvent,
	CreateAgentTaskEvent,
	UpdateAgentTaskEvent,
)
from browser_use.browser.session import DEFAULT_BROWSER_PROFILE
from browser_use.eventbus.models import UUIDStr

load_dotenv()

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
	BaseMessage,
	HumanMessage,
	SystemMessage,
)
from playwright.async_api import Browser, BrowserContext, Page
from pydantic import BaseModel, ValidationError
from uuid_extensions import uuid7str

from browser_use.agent.gif import create_history_gif
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

# from lmnr.sdk.decorators import observe
from browser_use.browser.views import BrowserStateSummary
from browser_use.controller.registry.views import ActionModel
from browser_use.controller.service import Controller
from browser_use.dom.history_tree_processor.service import DOMHistoryElement, HistoryTreeProcessor
from browser_use.eventbus import EventBus
from browser_use.exceptions import LLMException
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import AgentTelemetryEvent
from browser_use.utils import get_browser_use_version, time_execution_async, time_execution_sync

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
	logger.info(f'🎯 Next goal: {response.current_state.next_goal}')


Context = TypeVar('Context')

AgentHookFunc = Callable[['Agent'], Awaitable[None]]


class Agent(Generic[Context]):
	@time_execution_sync('--init (agent)')
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
		sensitive_data: dict[str, str] | dict[str, dict[str, str]] | None = None,
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
		save_conversation_path: str | None = None,
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
	):
		if page_extraction_llm is None:
			page_extraction_llm = llm

		# Generate unique IDs for this agent session and task early
		self.session_id: UUIDStr = uuid7str()
		self.task_id: UUIDStr = uuid7str()

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
		self._verify_and_setup_llm()

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
		# assert not (browser_session and browser_profile), 'Cannot provide both browser_session and browser_profile'
		# assert not (browser_session and browser), 'Cannot provide both browser_session and browser'
		# assert not (browser_profile and browser), 'Cannot provide both browser_profile and browser'
		# assert not (browser_profile and browser_context), 'Cannot provide both browser_profile and browser_context'
		# assert not (browser and browser_context), 'Cannot provide both browser and browser_context'
		# assert not (browser_session and browser_context), 'Cannot provide both browser_session and browser_context'
		browser_profile = browser_profile or DEFAULT_BROWSER_PROFILE

		if browser_session:
			# always copy sessions that are passed in to avoid conflicting with other agents sharing the same session
			self.browser_session = browser_session.model_copy(
				update={
					'agent_current_page': None,
					'human_current_page': None,
				},
			)
		else:
			self.browser_session = BrowserSession(
				browser_profile=browser_profile,
				browser=browser,
				browser_context=browser_context,
				page=page,
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
		# Default to ~/.config/browseruse/events/{agent_task_id}.jsonl
		wal_path = Path.home() / '.config' / 'browseruse' / 'events' / f'{self.task_id}.jsonl'
		self.eventbus = EventBus(name='Agent', wal_path=wal_path)

		if self.settings.save_conversation_path:
			self.logger.info(f'Saving conversation to {self.settings.save_conversation_path}')
		self._external_pause_event = asyncio.Event()
		self._external_pause_event.set()

	@property
	def logger(self) -> logging.Logger:
		"""Get instance-specific logger with task ID in the name"""
		return self._logger

	@property
	def browser(self) -> Browser:
		return self.browser_session.browser

	@property
	def browser_context(self) -> BrowserContext:
		return self.browser_session.browser_context

	@property
	def browser_profile(self) -> BrowserProfile:
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
		self.logger.debug(f'Version: {version}, Source: {source}')
		self.version = version
		self.source = source

	def _set_model_names(self) -> None:
		self.chat_model_library = self.llm.__class__.__name__
		self.model_name = 'Unknown'
		if hasattr(self.llm, 'model_name'):
			model = self.llm.model_name  # type: ignore
			self.model_name = model if model is not None else 'Unknown'
		elif hasattr(self.llm, 'model'):
			model = self.llm.model  # type: ignore
			self.model_name = model if model is not None else 'Unknown'

		if self.settings.planner_llm:
			if hasattr(self.settings.planner_llm, 'model_name'):
				self.planner_model_name = self.settings.planner_llm.model_name  # type: ignore
			elif hasattr(self.settings.planner_llm, 'model'):
				self.planner_model_name = self.settings.planner_llm.model  # type: ignore
			else:
				self.planner_model_name = 'Unknown'
		else:
			self.planner_model_name = None

	def _setup_action_models(self) -> None:
		"""Setup dynamic action models from controller's registry"""
		# Initially only include actions with no filters
		self.ActionModel = self.controller.registry.create_action_model()
		# Create output model with the dynamic actions
		self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)

		# used to force the done action when max_steps is reached
		self.DoneActionModel = self.controller.registry.create_action_model(include_actions=['done'])
		self.DoneAgentOutput = AgentOutput.type_with_custom_actions(self.DoneActionModel)

	def _test_tool_calling_method(self, method: str) -> bool:
		"""Test if a specific tool calling method works with the current LLM."""
		try:
			# Test configuration
			CAPITAL_QUESTION = 'What is the capital of France? Respond with just the city name in lowercase.'
			EXPECTED_ANSWER = 'paris'

			class CapitalResponse(BaseModel):
				"""Response model for capital city question"""

				answer: str  # The name of the capital city in lowercase

			def is_valid_raw_response(response, expected_answer: str) -> bool:
				"""
				Cleans and validates a raw JSON response string against an expected answer.
				"""
				content = getattr(response, 'content', '').strip()
				# self.logger.debug(f'Raw response content: {content}')

				# Remove surrounding markdown code blocks if present
				if content.startswith('```json') and content.endswith('```'):
					content = content[7:-3].strip()
				elif content.startswith('```') and content.endswith('```'):
					content = content[3:-3].strip()

				# Attempt to parse and validate the answer
				try:
					result = json.loads(content)
					answer = str(result.get('answer', '')).strip().lower().strip(' .')

					if expected_answer.lower() not in answer:
						self.logger.debug(f"🛠️ Tool calling method {method} failed: expected '{expected_answer}', got '{answer}'")
						return False

					return True

				except (json.JSONDecodeError, AttributeError, TypeError) as e:
					self.logger.debug(f'🛠️ Tool calling method {method} failed: Failed to parse JSON content: {e}')
					return False

			if method == 'raw' or method == 'json_mode':
				# For raw mode, test JSON response format
				test_prompt = f"""{CAPITAL_QUESTION}
					Respond with a json object like: {{"answer": "city_name_in_lowercase"}}"""

				response = self.llm.invoke([test_prompt])
				# Basic validation of response
				if not response or not hasattr(response, 'content'):
					return False

				if not is_valid_raw_response(response, EXPECTED_ANSWER):
					return False
				return True
			else:
				# For other methods, try to use structured output
				structured_llm = self.llm.with_structured_output(CapitalResponse, include_raw=True, method=method)
				response = structured_llm.invoke([HumanMessage(content=CAPITAL_QUESTION)])

				if not response:
					self.logger.debug(f'🛠️ Tool calling method {method} failed: empty response')
					return False

				def extract_parsed(response: Any) -> CapitalResponse | None:
					if isinstance(response, dict):
						return response.get('parsed')
					return getattr(response, 'parsed', None)

				parsed = extract_parsed(response)

				if not isinstance(parsed, CapitalResponse):
					self.logger.debug(f'🛠️ Tool calling method {method} failed: LLM responded with invalid JSON')
					return False

				if EXPECTED_ANSWER not in parsed.answer.lower():
					self.logger.debug(f'🛠️ Tool calling method {method} failed: LLM failed to answer test question correctly')
					return False
				return True

		except Exception as e:
			self.logger.debug(f"🛠️ Tool calling method '{method}' test failed: {type(e).__name__}: {str(e)}")
			return False

	async def _test_tool_calling_method_async(self, method: str) -> tuple[str, bool]:
		"""Test if a specific tool calling method works with the current LLM (async version)."""
		# Run the synchronous test in a thread pool to avoid blocking
		loop = asyncio.get_event_loop()
		result = await loop.run_in_executor(None, self._test_tool_calling_method, method)
		return (method, result)

	def _detect_best_tool_calling_method(self) -> str | None:
		"""Detect the best supported tool calling method by testing each one."""
		start_time = time.time()

		# Order of preference for tool calling methods
		methods_to_try = [
			'function_calling',  # Most capable and efficient
			'tools',  # Works with some models that don't support function_calling
			'json_mode',  # More basic structured output
			'raw',  # Fallback - no tool calling support
		]

		# Try parallel testing for faster detection
		try:
			# Run async parallel tests
			async def test_all_methods():
				tasks = [self._test_tool_calling_method_async(method) for method in methods_to_try]
				results = await asyncio.gather(*tasks, return_exceptions=True)
				return results

			# Execute async tests
			try:
				loop = asyncio.get_running_loop()
				# Running loop: create a new loop in a separate thread
				result = {}

				def run_in_thread():
					new_loop = asyncio.new_event_loop()
					asyncio.set_event_loop(new_loop)
					try:
						result['value'] = new_loop.run_until_complete(test_all_methods())
					except Exception as e:
						result['error'] = e
					finally:
						new_loop.close()

				t = Thread(target=run_in_thread)
				t.start()
				t.join()
				if 'error' in result:
					raise result['error']
				results = result['value']

			except RuntimeError as e:
				if 'no running event loop' in str(e):
					results = asyncio.run(test_all_methods())
				else:
					raise

			# Process results in order of preference
			for i, method in enumerate(methods_to_try):
				if isinstance(results[i], tuple) and results[i][1]:  # (method, success)
					self.llm._verified_api_keys = True
					self.llm._verified_tool_calling_method = method  # Cache on LLM instance
					elapsed = time.time() - start_time
					self.logger.debug(f'🛠️ Tested LLM in parallel and chose tool calling method: [{method}] in {elapsed:.2f}s')
					return method

		except Exception as e:
			self.logger.debug(f'Parallel testing failed: {e}, falling back to sequential')
			# Fall back to sequential testing
			for method in methods_to_try:
				if self._test_tool_calling_method(method):
					# if we found the method which means api is verified.
					self.llm._verified_api_keys = True
					self.llm._verified_tool_calling_method = method  # Cache on LLM instance
					elapsed = time.time() - start_time
					self.logger.debug(f'🛠️ Tested LLM and chose tool calling method: [{method}] in {elapsed:.2f}s')
					return method

		# If we get here, no methods worked
		raise ConnectionError('Failed to connect to LLM. Please check your API key and network connection.')

	def _get_known_tool_calling_method(self) -> str | None:
		"""Get known tool calling method for common model/library combinations."""
		# Fast path for known combinations
		model_lower = self.model_name.lower()

		# OpenAI models
		if self.chat_model_library == 'ChatOpenAI':
			if any(m in model_lower for m in ['gpt-4', 'gpt-3.5']):
				return 'function_calling'
			if any(m in model_lower for m in ['llama']):
				return 'json_mode'

		# Azure OpenAI models
		elif self.chat_model_library == 'AzureChatOpenAI':
			if 'gpt-4-' in model_lower:
				return 'tools'
			else:
				return 'function_calling'

		# Google models
		elif self.chat_model_library == 'ChatGoogleGenerativeAI':
			return None  # Google uses native tool support

		# Anthropic models
		elif self.chat_model_library in ['ChatAnthropic', 'AnthropicChat']:
			if any(m in model_lower for m in ['claude-3', 'claude-2']):
				return 'tools'

		# Models known to not support tools
		elif is_model_without_tool_support(self.model_name):
			return 'raw'

		return None  # Unknown combination, needs testing

	def _set_tool_calling_method(self) -> ToolCallingMethod | None:
		"""Determine the best tool calling method to use with the current LLM."""

		# old hardcoded logic
		# 			if is_model_without_tool_support(self.model_name):
		# 				return 'raw'
		# 			elif self.chat_model_library == 'ChatGoogleGenerativeAI':
		# 				return None
		# 			elif self.chat_model_library == 'ChatOpenAI':
		# 				return 'function_calling'
		# 			elif self.chat_model_library == 'AzureChatOpenAI':
		# 				# Azure OpenAI API requires 'tools' parameter for GPT-4
		# 				# The error 'content must be either a string or an array' occurs when
		# 				# the API expects a tools array but gets something else
		# 				if 'gpt-4-' in self.model_name.lower():
		# 					return 'tools'
		# 				else:
		# 					return 'function_calling'

		# If a specific method is set, use it
		if self.settings.tool_calling_method != 'auto':
			# Skip test if already verified
			if getattr(self.llm, '_verified_api_keys', None) is True or SKIP_LLM_API_KEY_VERIFICATION:
				self.llm._verified_api_keys = True
				self.llm._verified_tool_calling_method = self.settings.tool_calling_method
				return self.settings.tool_calling_method

			if not self._test_tool_calling_method(self.settings.tool_calling_method):
				if self.settings.tool_calling_method == 'raw':
					# if raw failed means error in API key or network connection
					raise ConnectionError('Failed to connect to LLM. Please check your API key and network connection.')
				else:
					raise RuntimeError(
						f"Configured tool calling method '{self.settings.tool_calling_method}' "
						'is not supported by the current LLM.'
					)
			self.llm._verified_tool_calling_method = self.settings.tool_calling_method
			return self.settings.tool_calling_method

		# Check if we already have a cached method on this LLM instance
		if hasattr(self.llm, '_verified_tool_calling_method'):
			self.logger.debug(
				f'🛠️ Using cached tool calling method for {self.chat_model_library}/{self.model_name}: [{self.llm._verified_tool_calling_method}]'
			)
			return self.llm._verified_tool_calling_method

		# Try fast path for known model/library combinations
		known_method = self._get_known_tool_calling_method()
		if known_method is not None:
			# Trust known combinations without testing if verification is already done or skipped
			if getattr(self.llm, '_verified_api_keys', None) is True or SKIP_LLM_API_KEY_VERIFICATION:
				self.llm._verified_api_keys = True
				self.llm._verified_tool_calling_method = known_method  # Cache on LLM instance
				self.logger.debug(
					f'🛠️ Using known tool calling method for {self.chat_model_library}/{self.model_name}: [{known_method}] (skipped test)'
				)
				return known_method

			start_time = time.time()
			# Verify the known method works
			if self._test_tool_calling_method(known_method):
				self.llm._verified_api_keys = True
				self.llm._verified_tool_calling_method = known_method  # Cache on LLM instance
				elapsed = time.time() - start_time
				self.logger.debug(
					f'🛠️ Using known tool calling method for {self.chat_model_library}/{self.model_name}: [{known_method}] in {elapsed:.2f}s'
				)
				return known_method
			# If known method fails, fall back to detection
			self.logger.debug(
				f'Known method {known_method} failed for {self.chat_model_library}/{self.model_name}, falling back to detection'
			)

		# Auto-detect the best method
		return self._detect_best_tool_calling_method()

	def add_new_task(self, new_task: str) -> None:
		"""Add a new task to the agent, keeping the same task_id as tasks are continuous"""
		# Simply delegate to message manager - no need for new task_id or events
		# The task continues with new instructions, it doesn't end and start a new one
		self.task = new_task
		self._message_manager.add_new_task(new_task)

	async def _raise_if_stopped_or_paused(self) -> None:
		"""Utility function that raises an InterruptedError if the agent is stopped or paused."""

		if self.register_external_agent_status_raise_error_callback:
			if await self.register_external_agent_status_raise_error_callback():
				raise InterruptedError

		if self.state.stopped or self.state.paused:
			# self.logger.debug('Agent paused after getting state')
			raise InterruptedError

	# @observe(name='agent.step', ignore_output=True, ignore_input=True)
	@time_execution_async('--step (agent)')
	async def step(self, step_info: AgentStepInfo | None = None) -> None:
		"""Execute one step of the task"""
		browser_state_summary = None
		model_output = None
		result: list[ActionResult] = []
		step_start_time = time.time()
		tokens = 0

		try:
			browser_state_summary = await self.browser_session.get_state_summary(cache_clickable_elements_hashes=True)
			current_page = await self.browser_session.get_current_page()

			self._log_step_context(current_page, browser_state_summary)

			# generate procedural memory if needed
			if self.enable_memory and self.memory and self.state.n_steps % self.memory.config.memory_interval == 0:
				self.memory.create_procedural_memory(self.state.n_steps)

			await self._raise_if_stopped_or_paused()

			# Update action models with page-specific actions
			await self._update_action_models_for_page(current_page)

			# Get page-specific filtered actions
			page_filtered_actions = self.controller.registry.get_prompt_description(current_page)

			if self.sensitive_data:
				self._message_manager.add_sensitive_data(current_page.url)

			# If there are page-specific actions, add them as a special message for this step only
			if page_filtered_actions:
				page_action_message = f'For this page, these additional actions are available:\n{page_filtered_actions}'
				self._message_manager._add_message_with_tokens(HumanMessage(content=page_action_message))

			# If using raw tool calling method, we need to update the message context with new actions
			if self.tool_calling_method == 'raw':
				# For raw tool calling, get all non-filtered actions plus the page-filtered ones
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

			# Run planner at specified intervals if planner is configured
			if self.settings.planner_llm and self.state.n_steps % self.settings.planner_interval == 0:
				plan = await self._run_planner()
				# add plan before last state message
				self._message_manager.add_plan(plan, position=-1)

			if step_info and step_info.is_last_step():
				# Add last step warning if needed
				msg = 'Now comes your last step. Use only the "done" action now. No other actions - so here your action sequence must have length 1.'
				msg += '\nIf the task is not yet fully finished as requested by the user, set success in "done" to false! E.g. if not all steps are fully completed.'
				msg += '\nIf the task is fully finished, set success in "done" to true.'
				msg += '\nInclude everything you found out for the ultimate task in the done text.'
				self.logger.info('Last step finishing up')
				self._message_manager._add_message_with_tokens(HumanMessage(content=msg))
				self.AgentOutput = self.DoneAgentOutput

			input_messages = self._message_manager.get_messages()
			tokens = self._message_manager.state.history.current_tokens

			try:
				model_output = await self.get_next_action(input_messages)
				if (
					not model_output.action
					or not isinstance(model_output.action, list)
					or all(action.model_dump() == {} for action in model_output.action)
				):
					self.logger.warning('Model returned empty action. Retrying...')

					clarification_message = HumanMessage(
						content='You forgot to return an action. Please respond only with a valid JSON action according to the expected format.'
					)

					retry_messages = input_messages + [clarification_message]
					model_output = await self.get_next_action(retry_messages)

					if not model_output.action or all(action.model_dump() == {} for action in model_output.action):
						self.logger.warning('Model still returned empty after retry. Inserting safe noop action.')
						action_instance = self.ActionModel(
							done={
								'success': False,
								'text': 'No next action returned by LLM!',
							}
						)
						model_output.action = [action_instance]

				# Check again for paused/stopped state after getting model output
				await self._raise_if_stopped_or_paused()

				self.state.n_steps += 1

				if self.register_new_step_callback:
					if inspect.iscoroutinefunction(self.register_new_step_callback):
						await self.register_new_step_callback(browser_state_summary, model_output, self.state.n_steps)
					else:
						self.register_new_step_callback(browser_state_summary, model_output, self.state.n_steps)
				if self.settings.save_conversation_path:
					target = self.settings.save_conversation_path + f'_{self.state.n_steps}.txt'
					save_conversation(input_messages, model_output, target, self.settings.save_conversation_path_encoding)

				self._message_manager._remove_last_state_message()  # we dont want the whole state in the chat history

				# check again if Ctrl+C was pressed before we commit the output to history
				await self._raise_if_stopped_or_paused()

				self._message_manager.add_model_output(model_output)
			except asyncio.CancelledError:
				# Task was cancelled due to Ctrl+C
				self._message_manager._remove_last_state_message()
				raise InterruptedError('Model query cancelled by user')
			except InterruptedError:
				# Agent was paused during get_next_action
				self._message_manager._remove_last_state_message()
				raise  # Re-raise to be caught by the outer try/except
			except Exception as e:
				# model call failed, remove last state message from history
				self._message_manager._remove_last_state_message()
				raise e

			result: list[ActionResult] = await self.multi_act(model_output.action)

			self.state.last_result = result

			if len(result) > 0 and result[-1].is_done:
				self.logger.info(f'📄 Result: {result[-1].extracted_content}')

			self.state.consecutive_failures = 0

		except InterruptedError:
			# self.logger.debug('Agent paused')
			self.state.last_result = [
				ActionResult(
					error='The agent was paused mid-step - the last action might need to be repeated', include_in_memory=False
				)
			]
			return
		except asyncio.CancelledError:
			# Directly handle the case where the step is cancelled at a higher level
			# self.logger.debug('Task cancelled - agent was paused with Ctrl+C')
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
				metadata = StepMetadata(
					step_number=self.state.n_steps,
					step_start_time=step_start_time,
					step_end_time=step_end_time,
					input_tokens=tokens,
				)
				self._make_history_item(model_output, browser_state_summary, result, metadata)

			# Log step completion summary
			self._log_step_completion_summary(step_start_time, result)

			# Emit both step created and executed events
			if browser_state_summary and model_output:
				# Extract key step data for the event
				actions_data = []
				if model_output.action:
					for action in model_output.action:
						action_dict = action.model_dump() if hasattr(action, 'model_dump') else {}
						actions_data.append(action_dict)

				# Emit CreateAgentStepEvent
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
				# cut tokens from history
				self._message_manager.settings.max_input_tokens = self.settings.max_input_tokens - 500
				self.logger.info(
					f'Cutting tokens from history - new max input tokens: {self._message_manager.settings.max_input_tokens}'
				)
				self._message_manager.cut_messages()
			elif 'Could not parse response' in error_msg:
				# give model a hint how output should look like
				error_msg += '\n\nReturn a valid JSON object with the required fields.'

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

			if isinstance(error, RATE_LIMIT_ERRORS):
				self.logger.warning(f'{prefix}{error_msg}')
				await asyncio.sleep(self.settings.retry_delay)
			else:
				self.logger.error(f'{prefix}{error_msg}')

		return [ActionResult(error=error_msg, include_in_memory=True)]

	def _make_history_item(
		self,
		model_output: AgentOutput | None,
		browser_state_summary: BrowserStateSummary,
		result: list[ActionResult],
		metadata: StepMetadata | None = None,
	) -> None:
		"""Create and store history item"""

		if model_output:
			interacted_elements = AgentHistory.get_interacted_element(model_output, browser_state_summary.selector_map)
		else:
			interacted_elements = [None]

		state_history = BrowserStateHistory(
			url=browser_state_summary.url,
			title=browser_state_summary.title,
			tabs=browser_state_summary.tabs,
			interacted_element=interacted_elements,
			screenshot=browser_state_summary.screenshot,
		)

		history_item = AgentHistory(model_output=model_output, result=result, state=state_history, metadata=metadata)

		self.state.history.history.append(history_item)

	THINK_TAGS = re.compile(r'<think>.*?</think>', re.DOTALL)
	STRAY_CLOSE_TAG = re.compile(r'.*?</think>', re.DOTALL)

	def _remove_think_tags(self, text: str) -> str:
		# Step 1: Remove well-formed <think>...</think>
		text = re.sub(self.THINK_TAGS, '', text)
		# Step 2: If there's an unmatched closing tag </think>,
		#         remove everything up to and including that.
		text = re.sub(self.STRAY_CLOSE_TAG, '', text)
		return text.strip()

	def _convert_input_messages(self, input_messages: list[BaseMessage]) -> list[BaseMessage]:
		"""Convert input messages to the correct format"""
		if is_model_without_tool_support(self.model_name):
			return convert_input_messages(input_messages, self.model_name)
		else:
			return input_messages

	@time_execution_async('--get_next_action (agent)')
	async def get_next_action(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get next action from LLM based on current state"""
		input_messages = self._convert_input_messages(input_messages)

		if self.tool_calling_method == 'raw':
			self._log_llm_call_info(input_messages, self.tool_calling_method)
			try:
				output = self.llm.invoke(input_messages)
				response = {'raw': output, 'parsed': None}
			except Exception as e:
				self.logger.error(f'Failed to invoke model: {str(e)}')
				raise LLMException(401, 'LLM API call failed') from e
			# TODO: currently invoke does not return reasoning_content, we should override invoke
			output.content = self._remove_think_tags(str(output.content))
			try:
				parsed_json = extract_json_from_model_output(output.content)
				parsed = self.AgentOutput(**parsed_json)
				response['parsed'] = parsed
			except (ValueError, ValidationError) as e:
				self.logger.warning(f'Failed to parse model output: {output} {str(e)}')
				raise ValueError('Could not parse response.')

		elif self.tool_calling_method is None:
			structured_llm = self.llm.with_structured_output(self.AgentOutput, include_raw=True)
			try:
				response: dict[str, Any] = await structured_llm.ainvoke(input_messages)  # type: ignore
				parsed: AgentOutput | None = response['parsed']

			except Exception as e:
				self.logger.error(f'Failed to invoke model: {str(e)}')
				raise LLMException(401, 'LLM API call failed') from e

		else:
			self._log_llm_call_info(input_messages, self.tool_calling_method)
			structured_llm = self.llm.with_structured_output(self.AgentOutput, include_raw=True, method=self.tool_calling_method)
			response: dict[str, Any] = await structured_llm.ainvoke(input_messages)  # type: ignore

		# Handle tool call responses
		if response.get('parsing_error') and 'raw' in response:
			raw_msg = response['raw']
			if hasattr(raw_msg, 'tool_calls') and raw_msg.tool_calls:
				# Convert tool calls to AgentOutput format

				tool_call = raw_msg.tool_calls[0]  # Take first tool call

				# Create current state
				tool_call_name = tool_call['name']
				tool_call_args = tool_call['args']

				current_state = {
					'page_summary': 'Processing tool call',
					'evaluation_previous_goal': 'Executing action',
					'memory': 'Using tool call',
					'next_goal': f'Execute {tool_call_name}',
				}

				# Create action from tool call
				action = {tool_call_name: tool_call_args}

				parsed = self.AgentOutput(current_state=current_state, action=[self.ActionModel(**action)])
			else:
				parsed = None
		else:
			parsed = response['parsed']

		if not parsed:
			try:
				parsed_json = extract_json_from_model_output(response['raw'].content)
				parsed = self.AgentOutput(**parsed_json)
			except Exception as e:
				self.logger.warning(f'Failed to parse model output: {response["raw"].content} {str(e)}')
				raise ValueError('Could not parse response.')

		# cut the number of actions to max_actions_per_step if needed
		if len(parsed.action) > self.settings.max_actions_per_step:
			parsed.action = parsed.action[: self.settings.max_actions_per_step]

		if not (hasattr(self.state, 'paused') and (self.state.paused or self.state.stopped)):
			log_response(parsed, self.controller.registry.registry, self.logger)

		self._log_next_action_summary(parsed)
		return parsed

	def _log_agent_run(self) -> None:
		"""Log the agent run"""
		self.logger.info(f'🚀 Starting task: {self.task}')

		self.logger.debug(f'Version: {self.version}, Source: {self.source}')

	def _log_step_context(self, current_page, browser_state_summary) -> None:
		"""Log step context information"""
		url_short = current_page.url[:50] + '...' if len(current_page.url) > 50 else current_page.url
		interactive_count = len(browser_state_summary.selector_map) if browser_state_summary else 0
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
					elif isinstance(value, (str, int, bool)) and len(str(value)) < 20:
						param_summary.append(f'{key}={value}')

			param_str = f'({", ".join(param_summary)})' if param_summary else ''
			action_details.append(f'{action_name}{param_str}')

		# Create summary based on single vs multi-action
		if action_count == 1:
			self.logger.info(f'⚡️ Decided next action: {action_name}{param_str}')
		else:
			summary_lines = [f'⚡️ Decided next {action_count} multi-actions:']
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

	def _log_llm_call_info(self, input_messages: list[BaseMessage], method: str) -> None:
		"""Log comprehensive information about the LLM call being made"""
		# Count messages and check for images
		message_count = len(input_messages)
		total_chars = sum(len(str(msg.content)) for msg in input_messages)
		has_images = any(
			hasattr(msg, 'content')
			and isinstance(msg.content, list)
			and any(isinstance(item, dict) and item.get('type') == 'image_url' for item in msg.content)
			for msg in input_messages
		)
		current_tokens = getattr(self._message_manager.state.history, 'current_tokens', 0)

		# Count available tools/actions from the current ActionModel
		# This gives us the actual number of tools exposed to the LLM for this specific call
		tool_count = len(self.ActionModel.model_fields) if hasattr(self, 'ActionModel') else 0

		# Format the log message parts
		image_status = ', 📷 img' if has_images else ''
		if method == 'raw':
			output_format = '=> raw text'
			tool_info = ''
		else:
			output_format = '=> JSON out'
			tool_info = f' + 🔨 {tool_count} tools ({method})'

		term_width = shutil.get_terminal_size((80, 20)).columns
		print('=' * term_width)
		self.logger.info(
			f'🧠 LLM call => {self.chat_model_library} [✉️ {message_count} msg, ~{current_tokens} tk, {total_chars} char{image_status}] {output_format}{tool_info}'
		)

	def _log_agent_event(self, max_steps: int, agent_run_error: str | None = None) -> None:
		"""Sent the agent event for this run to telemetry"""

		# Prepare action_history data correctly
		action_history_data = []
		for item in self.state.history.history:
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

		final_res = self.state.history.final_result()
		final_result_str = json.dumps(final_res) if final_res is not None else None

		self.telemetry.capture(
			AgentTelemetryEvent(
				task=self.task,
				model=self.model_name,
				model_provider=self.chat_model_library,
				planner_llm=self.planner_model_name,
				max_steps=max_steps,
				max_actions_per_step=self.settings.max_actions_per_step,
				use_vision=self.settings.use_vision,
				use_validation=self.settings.validate_output,
				version=self.version,
				source=self.source,
				action_errors=self.state.history.errors(),
				action_history=action_history_data,
				urls_visited=self.state.history.urls(),
				steps=self.state.n_steps,
				total_input_tokens=self.state.history.total_input_tokens(),
				total_duration_seconds=self.state.history.total_duration_seconds(),
				success=self.state.history.is_successful(),
				final_result_response=final_result_str,
				error_message=agent_run_error,
			)
		)

	async def take_step(self) -> tuple[bool, bool]:
		"""Take a step

		Returns:
			Tuple[bool, bool]: (is_done, is_valid)
		"""
		await self.step()

		if self.state.history.is_done():
			if self.settings.validate_output:
				if not await self._validate_output():
					return True, False

			await self.log_completion()
			if self.register_done_callback:
				if inspect.iscoroutinefunction(self.register_done_callback):
					await self.register_done_callback(self.state.history)
				else:
					self.register_done_callback(self.state.history)
			return True, True

		return False, False

	# @observe(name='agent.run', ignore_output=True)
	@time_execution_async('--run (agent)')
	async def run(
		self, max_steps: int = 100, on_step_start: AgentHookFunc | None = None, on_step_end: AgentHookFunc | None = None
	) -> AgentHistoryList:
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

			# Initialize timing for session and task
			self._session_start_time = time.time()
			self._task_start_time = self._session_start_time  # Initialize task start time

			# Emit CreateAgentSessionEvent at the START of run()
			self.eventbus.dispatch(CreateAgentSessionEvent.from_agent(self))

			# Emit CreateAgentTaskEvent at the START of run()
			self.eventbus.dispatch(CreateAgentTaskEvent.from_agent(self))

			# Execute initial actions if provided
			if self.initial_actions:
				result = await self.multi_act(self.initial_actions, check_for_new_elements=False)
				self.state.last_result = result

			for step in range(max_steps):
				# Replace the polling with clean pause-wait
				if self.state.paused:
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

				step_info = AgentStepInfo(step_number=step, max_steps=max_steps)
				await self.step(step_info)

				if on_step_end is not None:
					await on_step_end(self)

				if self.state.history.is_done():
					if self.settings.validate_output and step < max_steps - 1:
						if not await self._validate_output():
							continue

					await self.log_completion()

					# Task completed
					break
			else:
				agent_run_error = 'Failed to complete task in maximum steps'

				self.state.history.history.append(
					AgentHistory(
						model_output=None,
						result=[ActionResult(error=agent_run_error, include_in_memory=True)],
						state=BrowserStateHistory(
							url='',
							title='',
							tabs=[],
							interacted_element=[],
							screenshot=None,
						),
						metadata=None,
					)
				)

				self.logger.info(f'❌ {agent_run_error}')

			return self.state.history

		except KeyboardInterrupt:
			# Already handled by our signal handler, but catch any direct KeyboardInterrupt as well
			self.logger.info('Got KeyboardInterrupt during execution, returning current history')
			agent_run_error = 'KeyboardInterrupt'
			return self.state.history

		except Exception as e:
			self.logger.error(f'Agent run failed with exception: {e}', exc_info=True)
			agent_run_error = str(e)
			raise e

		finally:
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

				create_history_gif(task=self.task, history=self.state.history, output_path=output_path)

				# Emit output file generated event for GIF
				output_event = await CreateAgentOutputFileEvent.from_agent_and_file(self, output_path)
				self.eventbus.dispatch(output_event)

			# Stop the event bus gracefully, waiting for all events to be processed
			await self.eventbus.stop(timeout=5.0)

			await self.close()

	# @observe(name='controller.multi_act')
	@time_execution_async('--multi_act')
	async def multi_act(
		self,
		actions: list[ActionModel],
		check_for_new_elements: bool = True,
	) -> list[ActionResult]:
		"""Execute multiple actions"""
		results = []

		cached_selector_map = await self.browser_session.get_selector_map()
		cached_path_hashes = {e.hash.branch_path_hash for e in cached_selector_map.values()}

		await self.browser_session.remove_highlights()

		for i, action in enumerate(actions):
			if action.get_index() is not None and i != 0:
				new_browser_state_summary = await self.browser_session.get_state_summary(cache_clickable_elements_hashes=False)
				new_selector_map = new_browser_state_summary.selector_map

				# Detect index change after previous action
				orig_target = cached_selector_map.get(action.get_index())  # type: ignore
				orig_target_hash = orig_target.hash.branch_path_hash if orig_target else None
				new_target = new_selector_map.get(action.get_index())  # type: ignore
				new_target_hash = new_target.hash.branch_path_hash if new_target else None
				if orig_target_hash != new_target_hash:
					msg = f'Element index changed after action {i} / {len(actions)}, because page changed.'
					self.logger.info(msg)
					results.append(ActionResult(extracted_content=msg, include_in_memory=True))
					break

				new_path_hashes = {e.hash.branch_path_hash for e in new_selector_map.values()}
				if check_for_new_elements and not new_path_hashes.issubset(cached_path_hashes):
					# next action requires index but there are new elements on the page
					msg = f'Something new appeared after action {i} / {len(actions)}'
					self.logger.info(msg)
					results.append(ActionResult(extracted_content=msg, include_in_memory=True))
					break

			try:
				await self._raise_if_stopped_or_paused()

				result = await self.controller.act(
					action=action,
					browser_session=self.browser_session,
					page_extraction_llm=self.settings.page_extraction_llm,
					sensitive_data=self.sensitive_data,
					available_file_paths=self.settings.available_file_paths,
					context=self.context,
				)

				results.append(result)

				# Get action name from the action model
				action_data = action.model_dump(exclude_unset=True)
				action_name = next(iter(action_data.keys())) if action_data else 'unknown'
				self.logger.info(f'☑️ Executed action {i + 1}/{len(actions)}: {action_name}')
				if results[-1].is_done or results[-1].error or i == len(actions) - 1:
					break

				await asyncio.sleep(self.browser_profile.wait_between_actions)
				# hash all elements. if it is a subset of cached_state its fine - else break (new elements on page)

			except asyncio.CancelledError:
				# Gracefully handle task cancellation
				self.logger.info(f'Action {i + 1} was cancelled due to Ctrl+C')
				if not results:
					# Add a result for the cancelled action
					results.append(ActionResult(error='The action was cancelled due to Ctrl+C', include_in_memory=True))
				raise InterruptedError('Action cancelled by user')

		return results

	async def _validate_output(self) -> bool:
		"""Validate the output of the last action is what the user wanted"""
		system_msg = (
			f'You are a validator of an agent who interacts with a browser. '
			f'Validate if the output of last action is what the user wanted and if the task is completed. '
			f'If the task is unclear defined, you can let it pass. But if something is missing or the image does not show what was requested dont let it pass. '
			f'Try to understand the page and help the model with suggestions like scroll, do x, ... to get the solution right. '
			f'Task to validate: {self.task}. Return a JSON object with 2 keys: is_valid and reason. '
			f'is_valid is a boolean that indicates if the output is correct. '
			f'reason is a string that explains why it is valid or not.'
			f' example: {{"is_valid": false, "reason": "The user wanted to search for "cat photos", but the agent searched for "dog photos" instead."}}'
		)

		if self.browser_context:
			browser_state_summary = await self.browser_session.get_state_summary(cache_clickable_elements_hashes=False)
			assert browser_state_summary
			content = AgentMessagePrompt(
				browser_state_summary=browser_state_summary,
				result=self.state.last_result,
				include_attributes=self.settings.include_attributes,
			)
			msg = [SystemMessage(content=system_msg), content.get_user_message(self.settings.use_vision)]
		else:
			# if no browser session, we can't validate the output
			return True

		class ValidationResult(BaseModel):
			"""
			Validation results.
			"""

			is_valid: bool
			reason: str

		validator = self.llm.with_structured_output(ValidationResult, include_raw=True)
		response: dict[str, Any] = await validator.ainvoke(msg)  # type: ignore
		parsed: ValidationResult = response['parsed']
		is_valid = parsed.is_valid
		if not is_valid:
			self.logger.info(f'❌ Validator decision: {parsed.reason}')
			msg = f'The output is not yet correct. {parsed.reason}.'
			self.state.last_result = [ActionResult(extracted_content=msg, include_in_memory=True)]
		else:
			self.logger.info(f'✅ Validator decision: {parsed.reason}')
		return is_valid

	async def log_completion(self) -> None:
		"""Log the completion of the task"""
		if self.state.history.is_successful():
			self.logger.info('✅ Task completed successfully')
		else:
			self.logger.info('❌ Task completed without success')

		total_tokens = self.state.history.total_input_tokens()
		self.logger.debug(f'📝 Total input tokens used (approximate): {total_tokens}')

		if self.register_done_callback:
			if inspect.iscoroutinefunction(self.register_done_callback):
				await self.register_done_callback(self.state.history)
			else:
				self.register_done_callback(self.state.history)

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
		state = await self.browser_session.get_state_summary(cache_clickable_elements_hashes=False)
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
		historical_element: DOMHistoryElement | None,
		action: ActionModel,  # Type this properly based on your action model
		browser_state_summary: BrowserStateSummary,
	) -> ActionModel | None:
		"""
		Update action indices based on current page state.
		Returns updated action or None if element cannot be found.
		"""
		if not historical_element or not browser_state_summary.element_tree:
			return action

		current_element = HistoryTreeProcessor.find_history_element_in_tree(
			historical_element, browser_state_summary.element_tree
		)

		if not current_element or current_element.highlight_index is None:
			return None

		old_index = action.get_index()
		if old_index != current_element.highlight_index:
			action.set_index(current_element.highlight_index)
			self.logger.info(f'Element moved in DOM, updated index from {old_index} to {current_element.highlight_index}')

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
		self.state.history.save_to_file(file_path)

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

		# playwright browser is always immediately killed by the first Ctrl+C (no way to stop that)
		# so we need to restart the browser if user wants to continue
		if self.browser:
			self.logger.info('🌎 Restarting/reconnecting to browser...')
			loop = asyncio.get_event_loop()
			loop.create_task(self.browser._init())
			loop.create_task(asyncio.sleep(5))

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

	def _verify_and_setup_llm(self) -> bool:
		"""
		Verify that the LLM API keys are setup and the LLM API is responding properly.
		Also handles tool calling method detection if in auto mode.
		"""
		self.tool_calling_method = self._set_tool_calling_method()

		# Skip verification if already done
		if getattr(self.llm, '_verified_api_keys', None) is True or SKIP_LLM_API_KEY_VERIFICATION:
			self.llm._verified_api_keys = True
			return True

	async def _run_planner(self) -> str | None:
		"""Run the planner to analyze state and suggest next steps"""
		# Skip planning if no planner_llm is set
		if not self.settings.planner_llm:
			return None

		# Get current state to filter actions by page
		page = await self.browser_session.get_current_page()

		# Get all standard actions (no filter) and page-specific actions
		standard_actions = self.controller.registry.get_prompt_description()  # No page = system prompt actions
		page_actions = self.controller.registry.get_prompt_description(page)  # Page-specific actions

		# Combine both for the planner
		all_actions = standard_actions
		if page_actions:
			all_actions += '\n' + page_actions

		# Create planner message history using full message history with all available actions
		planner_messages = [
			PlannerPrompt(all_actions).get_system_message(
				is_planner_reasoning=self.settings.is_planner_reasoning,
				extended_planner_system_prompt=self.settings.extend_planner_system_message,
			),
			*self._message_manager.get_messages()[1:],  # Use full message history except the first
		]

		if not self.settings.use_vision_for_planner and self.settings.use_vision:
			last_state_message: HumanMessage = planner_messages[-1]
			# remove image from last state message
			new_msg = ''
			if isinstance(last_state_message.content, list):
				for msg in last_state_message.content:
					if msg['type'] == 'text':  # type: ignore
						new_msg += msg['text']  # type: ignore
					elif msg['type'] == 'image_url':  # type: ignore
						continue  # type: ignore
			else:
				new_msg = last_state_message.content

			planner_messages[-1] = HumanMessage(content=new_msg)

		planner_messages = convert_input_messages(planner_messages, self.planner_model_name)

		# Get planner output
		try:
			response = await self.settings.planner_llm.ainvoke(planner_messages)
		except Exception as e:
			self.logger.error(f'Failed to invoke planner: {str(e)}')
			raise LLMException(401, 'LLM API call failed') from e

		plan = str(response.content)
		# if deepseek-reasoner, remove think tags
		if self.planner_model_name and (
			'deepseek-r1' in self.planner_model_name or 'deepseek-reasoner' in self.planner_model_name
		):
			plan = self._remove_think_tags(plan)
		try:
			plan_json = json.loads(plan)
			self.logger.info(f'Planning Analysis:\n{json.dumps(plan_json, indent=4)}')
		except json.JSONDecodeError:
			self.logger.info(f'Planning Analysis:\n{plan}')
		except Exception as e:
			self.logger.debug(f'Error parsing planning analysis: {e}')
			self.logger.info(f'Plan: {plan}')

		return plan

	@property
	def message_manager(self) -> MessageManager:
		return self._message_manager

	async def close(self):
		"""Close all resources"""
		try:
			# First close browser resources
			await self.browser_session.stop()

			# Force garbage collection
			gc.collect()

		except Exception as e:
			self.logger.error(f'Error during cleanup: {e}')

	async def _update_action_models_for_page(self, page) -> None:
		"""Update action models with page-specific actions"""
		# Create new action model with current page's filtered actions
		self.ActionModel = self.controller.registry.create_action_model(page=page)
		# Update output model with the new actions
		self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)

		# Update done action model too
		self.DoneActionModel = self.controller.registry.create_action_model(include_actions=['done'], page=page)
		self.DoneAgentOutput = AgentOutput.type_with_custom_actions(self.DoneActionModel)
