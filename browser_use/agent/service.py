from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import platform
import re
import textwrap
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from dotenv import load_dotenv
from google.api_core.exceptions import ResourceExhausted
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
	AIMessage,
	BaseMessage,
	HumanMessage,
	SystemMessage,
)
from lmnr import observe
from openai import RateLimitError
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, ValidationError

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.prompts import AgentMessagePrompt, PlannerPrompt, SystemPrompt
from browser_use.agent.views import (
	ActionResult,
	AgentError,
	AgentHistory,
	AgentHistoryList,
	AgentOutput,
	AgentStepInfo,
)
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContext
from browser_use.browser.views import BrowserState, BrowserStateHistory
from browser_use.controller.registry.views import ActionModel
from browser_use.controller.service import Controller
from browser_use.dom.history_tree_processor.service import (
	DOMHistoryElement,
	HistoryTreeProcessor,
)
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import (
	AgentEndTelemetryEvent,
	AgentRunTelemetryEvent,
	AgentStepTelemetryEvent,
)
from browser_use.utils import time_execution_async

load_dotenv()
logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class Agent:
	def __init__(
		self,
		task: str,
		llm: BaseChatModel,
		browser: Browser | None = None,
		browser_context: BrowserContext | None = None,
		controller: Controller = Controller(),
		use_vision: bool = True,
		use_vision_for_planner: bool = False,
		save_conversation_path: Optional[str] = None,
		save_conversation_path_encoding: Optional[str] = 'utf-8',
		max_failures: int = 3,
		retry_delay: int = 10,
		system_prompt_class: Type[SystemPrompt] = SystemPrompt,
		max_input_tokens: int = 128000,
		validate_output: bool = False,
		message_context: Optional[str] = None,
		generate_gif: bool | str = True,
		sensitive_data: Optional[Dict[str, str]] = None,
		available_file_paths: Optional[list[str]] = None,
		include_attributes: list[str] = [
			'title',
			'type',
			'name',
			'role',
			'tabindex',
			'aria-label',
			'placeholder',
			'value',
			'alt',
			'aria-expanded',
		],
		max_error_length: int = 400,
		max_actions_per_step: int = 10,
		tool_call_in_content: bool = True,
		initial_actions: Optional[List[Dict[str, Dict[str, Any]]]] = None,
		# Cloud Callbacks
		register_new_step_callback: Callable[['BrowserState', 'AgentOutput', int], None] | None = None,
		register_done_callback: Callable[['AgentHistoryList'], None] | None = None,
		tool_calling_method: Optional[str] = 'auto',
		page_extraction_llm: Optional[BaseChatModel] = None,
		planner_llm: Optional[BaseChatModel] = None,
		planner_interval: int = 1,  # Run planner every N steps
	):
		self.agent_id = str(uuid.uuid4())  # unique identifier for the agent
		self.sensitive_data = sensitive_data
		if not page_extraction_llm:
			self.page_extraction_llm = llm
		else:
			self.page_extraction_llm = page_extraction_llm
		self.available_file_paths = available_file_paths
		self.task = task
		self.use_vision = use_vision
		self.use_vision_for_planner = use_vision_for_planner
		self.llm = llm
		self.save_conversation_path = save_conversation_path
		if self.save_conversation_path and '/' not in self.save_conversation_path:
			self.save_conversation_path = f'{self.save_conversation_path}/'
		self.save_conversation_path_encoding = save_conversation_path_encoding
		self._last_result = None
		self.include_attributes = include_attributes
		self.max_error_length = max_error_length
		self.generate_gif = generate_gif

		# Initialize planner
		self.planner_llm = planner_llm
		self.planning_interval = planner_interval
		self.last_plan = None
		# Controller setup
		self.controller = controller
		self.max_actions_per_step = max_actions_per_step

		# Browser setup
		self.injected_browser = browser is not None
		self.injected_browser_context = browser_context is not None
		self.message_context = message_context

		# Initialize browser first if needed
		self.browser = browser if browser is not None else (None if browser_context else Browser())

		# Initialize browser context
		if browser_context:
			self.browser_context = browser_context
		elif self.browser:
			self.browser_context = BrowserContext(browser=self.browser, config=self.browser.config.new_context_config)
		else:
			# If neither is provided, create both new
			self.browser = Browser()
			self.browser_context = BrowserContext(browser=self.browser)

		self.system_prompt_class = system_prompt_class

		# Telemetry setup
		self.telemetry = ProductTelemetry()

		# Action and output models setup
		self._setup_action_models()
		self._set_version_and_source()
		self.max_input_tokens = max_input_tokens

		self._set_model_names()

		self.tool_calling_method = self.set_tool_calling_method(tool_calling_method)

		self.message_manager = MessageManager(
			llm=self.llm,
			task=self.task,
			action_descriptions=self.controller.registry.get_prompt_description(),
			system_prompt_class=self.system_prompt_class,
			max_input_tokens=self.max_input_tokens,
			include_attributes=self.include_attributes,
			max_error_length=self.max_error_length,
			max_actions_per_step=self.max_actions_per_step,
			message_context=self.message_context,
			sensitive_data=self.sensitive_data,
		)
		if self.available_file_paths:
			self.message_manager.add_file_paths(self.available_file_paths)
		# Step callback
		self.register_new_step_callback = register_new_step_callback
		self.register_done_callback = register_done_callback

		# Tracking variables
		self.history: AgentHistoryList = AgentHistoryList(history=[])
		self.n_steps = 1
		self.consecutive_failures = 0
		self.max_failures = max_failures
		self.retry_delay = retry_delay
		self.validate_output = validate_output
		self.initial_actions = self._convert_initial_actions(initial_actions) if initial_actions else None
		if save_conversation_path:
			logger.info(f'Saving conversation to {save_conversation_path}')

		self._paused = False
		self._stopped = False

		self.action_descriptions = self.controller.registry.get_prompt_description()

	def _set_version_and_source(self) -> None:
		try:
			import pkg_resources

			version = pkg_resources.get_distribution('browser-use').version
			source = 'pip'
		except Exception:
			try:
				import subprocess

				version = subprocess.check_output(['git', 'describe', '--tags']).decode('utf-8').strip()
				source = 'git'
			except Exception:
				version = 'unknown'
				source = 'unknown'
		logger.debug(f'Version: {version}, Source: {source}')
		self.version = version
		self.source = source

	def _set_model_names(self) -> None:
		self.chat_model_library = self.llm.__class__.__name__
		self.model_name = "Unknown"
		# Check for 'model_name' attribute first
		if hasattr(self.llm, "model_name"):
			model = self.llm.model_name
			self.model_name = model if model is not None else "Unknown"
		# Fallback to 'model' attribute if needed
		elif hasattr(self.llm, "model"):
			model = self.llm.model
			self.model_name = model if model is not None else "Unknown"

		if self.planner_llm:
			if hasattr(self.planner_llm, 'model_name'):
				self.planner_model_name = self.planner_llm.model_name  # type: ignore
			elif hasattr(self.planner_llm, 'model'):
				self.planner_model_name = self.planner_llm.model  # type: ignore
			else:
				self.planner_model_name = 'Unknown'
		else:
			self.planner_model_name = None

	def _setup_action_models(self) -> None:
		"""Setup dynamic action models from controller's registry"""
		self.ActionModel = self.controller.registry.create_action_model()
		# Create output model with the dynamic actions
		self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)

	def set_tool_calling_method(self, tool_calling_method: Optional[str]) -> Optional[str]:
		if tool_calling_method == 'auto':
			if self.chat_model_library == 'ChatGoogleGenerativeAI':
				return None
			elif self.chat_model_library == 'ChatOpenAI':
				return 'function_calling'
			elif self.chat_model_library == 'AzureChatOpenAI':
				return 'function_calling'
			else:
				return None
		else:
			return tool_calling_method

	def add_new_task(self, new_task: str) -> None:
		self.message_manager.add_new_task(new_task)

	def _check_if_stopped_or_paused(self) -> bool:
		if self._stopped or self._paused:
			logger.debug('Agent paused after getting state')
			raise InterruptedError
		return False

	@observe(name='agent.step', ignore_output=True, ignore_input=True)
	@time_execution_async('--step')
	async def step(self, step_info: Optional[AgentStepInfo] = None) -> None:
		"""Execute one step of the task"""
		logger.info(f'📍 Step {self.n_steps}')
		state = None
		model_output = None
		result: list[ActionResult] = []

		try:
			state = await self.browser_context.get_state()

			self._check_if_stopped_or_paused()
			self.message_manager.add_state_message(state, self._last_result, step_info, self.use_vision)

			# Run planner at specified intervals if planner is configured
			if self.planner_llm and self.n_steps % self.planning_interval == 0:
				plan = await self._run_planner()
				# add plan before last state message
				self.message_manager.add_plan(plan, position=-1)

			input_messages = self.message_manager.get_messages()

			self._check_if_stopped_or_paused()

			try:
				model_output = await self.get_next_action(input_messages)

				if self.register_new_step_callback:
					self.register_new_step_callback(state, model_output, self.n_steps)

				self._save_conversation(input_messages, model_output)
				self.message_manager._remove_last_state_message()  # we dont want the whole state in the chat history

				self._check_if_stopped_or_paused()

				self.message_manager.add_model_output(model_output)
			except Exception as e:
				# model call failed, remove last state message from history
				self.message_manager._remove_last_state_message()
				raise e

			result: list[ActionResult] = await self.controller.multi_act(
				model_output.action,
				self.browser_context,
				page_extraction_llm=self.page_extraction_llm,
				sensitive_data=self.sensitive_data,
				check_break_if_paused=lambda: self._check_if_stopped_or_paused(),
				available_file_paths=self.available_file_paths,
			)
			self._last_result = result

			if len(result) > 0 and result[-1].is_done:
				logger.info(f'📄 Result: {result[-1].extracted_content}')

			self.consecutive_failures = 0

		except InterruptedError:
			logger.debug('Agent paused')
			self._last_result = [
				ActionResult(
					error='The agent was paused - now continuing actions might need to be repeated', include_in_memory=True
				)
			]
			return
		except Exception as e:
			result = await self._handle_step_error(e)
			self._last_result = result

		finally:
			actions = [a.model_dump(exclude_unset=True) for a in model_output.action] if model_output else []
			self.telemetry.capture(
				AgentStepTelemetryEvent(
					agent_id=self.agent_id,
					step=self.n_steps,
					actions=actions,
					consecutive_failures=self.consecutive_failures,
					step_error=[r.error for r in result if r.error] if result else ['No result'],
				)
			)
			if not result:
				return

			if state:
				self._make_history_item(model_output, state, result)

	async def _handle_step_error(self, error: Exception) -> list[ActionResult]:
		"""Handle all types of errors that can occur during a step"""
		include_trace = logger.isEnabledFor(logging.DEBUG)
		error_msg = AgentError.format_error(error, include_trace=include_trace)
		prefix = f'❌ Result failed {self.consecutive_failures + 1}/{self.max_failures} times:\n '

		if isinstance(error, (ValidationError, ValueError)):
			logger.error(f'{prefix}{error_msg}')
			if 'Max token limit reached' in error_msg:
				# cut tokens from history
				self.message_manager.max_input_tokens = self.max_input_tokens - 500
				logger.info(f'Cutting tokens from history - new max input tokens: {self.message_manager.max_input_tokens}')
				self.message_manager.cut_messages()
			elif 'Could not parse response' in error_msg:
				# give model a hint how output should look like
				error_msg += '\n\nReturn a valid JSON object with the required fields.'

			self.consecutive_failures += 1
		elif isinstance(error, RateLimitError) or isinstance(error, ResourceExhausted):
			logger.warning(f'{prefix}{error_msg}')
			await asyncio.sleep(self.retry_delay)
			self.consecutive_failures += 1
		else:
			logger.error(f'{prefix}{error_msg}')
			self.consecutive_failures += 1

		return [ActionResult(error=error_msg, include_in_memory=True)]

	def _make_history_item(
		self,
		model_output: AgentOutput | None,
		state: BrowserState,
		result: list[ActionResult],
	) -> None:
		"""Create and store history item"""
		interacted_element = None
		len_result = len(result)

		if model_output:
			interacted_elements = AgentHistory.get_interacted_element(model_output, state.selector_map)
		else:
			interacted_elements = [None]

		state_history = BrowserStateHistory(
			url=state.url,
			title=state.title,
			tabs=state.tabs,
			interacted_element=interacted_elements,
			screenshot=state.screenshot,
		)

		history_item = AgentHistory(model_output=model_output, result=result, state=state_history)

		self.history.history.append(history_item)

	THINK_TAGS = re.compile(r'<think>.*?</think>', re.DOTALL)

	def _remove_think_tags(self, text: str) -> str:
		"""Remove think tags from text"""
		return re.sub(self.THINK_TAGS, '', text)

	def _convert_input_messages(self, input_messages: list[BaseMessage], model_name: Optional[str]) -> list[BaseMessage]:
		"""Convert input messages to a format that is compatible with the planner model"""
		if model_name is None:
			return input_messages
		if model_name == 'deepseek-reasoner' or model_name.startswith('deepseek-r1'):
			converted_input_messages = self.message_manager.convert_messages_for_non_function_calling_models(input_messages)
			merged_input_messages = self.message_manager.merge_successive_messages(converted_input_messages, HumanMessage)
			merged_input_messages = self.message_manager.merge_successive_messages(merged_input_messages, AIMessage)
			return merged_input_messages
		return input_messages

	@time_execution_async('--get_next_action')
	async def get_next_action(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get next action from LLM based on current state"""
		converted_input_messages = self._convert_input_messages(input_messages, self.model_name)

		if self.model_name == 'deepseek-reasoner' or self.model_name.startswith('deepseek-r1'):
			output = self.llm.invoke(converted_input_messages)
			output.content = self._remove_think_tags(output.content)
			# TODO: currently invoke does not return reasoning_content, we should override invoke
			try:
				parsed_json = self.message_manager.extract_json_from_model_output(output.content)
				parsed = self.AgentOutput(**parsed_json)
			except (ValueError, ValidationError) as e:
				logger.warning(f'Failed to parse model output: {output} {str(e)}')
				raise ValueError('Could not parse response.')
		elif self.tool_calling_method is None:
			structured_llm = self.llm.with_structured_output(self.AgentOutput, include_raw=True)
			response: dict[str, Any] = await structured_llm.ainvoke(input_messages)  # type: ignore
			parsed: AgentOutput | None = response['parsed']
		else:
			structured_llm = self.llm.with_structured_output(self.AgentOutput, include_raw=True, method=self.tool_calling_method)
			response: dict[str, Any] = await structured_llm.ainvoke(input_messages)  # type: ignore
			parsed: AgentOutput | None = response['parsed']

		if parsed is None:
			raise ValueError('Could not parse response.')

		# cut the number of actions to max_actions_per_step
		parsed.action = parsed.action[: self.max_actions_per_step]
		self._log_response(parsed)
		self.n_steps += 1

		return parsed

	def _log_response(self, response: AgentOutput) -> None:
		"""Log the model's response"""
		if 'Success' in response.current_state.evaluation_previous_goal:
			emoji = '👍'
		elif 'Failed' in response.current_state.evaluation_previous_goal:
			emoji = '⚠'
		else:
			emoji = '🤷'
		logger.debug(f'🤖 {emoji} Page summary: {response.current_state.page_summary}')
		logger.info(f'{emoji} Eval: {response.current_state.evaluation_previous_goal}')
		logger.info(f'🧠 Memory: {response.current_state.memory}')
		logger.info(f'🎯 Next goal: {response.current_state.next_goal}')
		for i, action in enumerate(response.action):
			logger.info(f'🛠️  Action {i + 1}/{len(response.action)}: {action.model_dump_json(exclude_unset=True)}')

	def _save_conversation(self, input_messages: list[BaseMessage], response: Any) -> None:
		"""Save conversation history to file if path is specified"""
		if not self.save_conversation_path:
			return

		# create folders if not exists
		os.makedirs(os.path.dirname(self.save_conversation_path), exist_ok=True)

		with open(
			self.save_conversation_path + f'_{self.n_steps}.txt',
			'w',
			encoding=self.save_conversation_path_encoding,
		) as f:
			self._write_messages_to_file(f, input_messages)
			self._write_response_to_file(f, response)

	def _write_messages_to_file(self, f: Any, messages: list[BaseMessage]) -> None:
		"""Write messages to conversation file"""
		for message in messages:
			f.write(f' {message.__class__.__name__} \n')

			if isinstance(message.content, list):
				for item in message.content:
					if isinstance(item, dict) and item.get('type') == 'text':
						f.write(item['text'].strip() + '\n')
			elif isinstance(message.content, str):
				try:
					content = json.loads(message.content)
					f.write(json.dumps(content, indent=2) + '\n')
				except json.JSONDecodeError:
					f.write(message.content.strip() + '\n')

			f.write('\n')

	def _write_response_to_file(self, f: Any, response: Any) -> None:
		"""Write model response to conversation file"""
		f.write(' RESPONSE\n')
		f.write(json.dumps(json.loads(response.model_dump_json(exclude_unset=True)), indent=2))

	def _log_agent_run(self) -> None:
		"""Log the agent run"""
		logger.info(f'🚀 Starting task: {self.task}')

		logger.debug(f'Version: {self.version}, Source: {self.source}')
		self.telemetry.capture(
			AgentRunTelemetryEvent(
				agent_id=self.agent_id,
				use_vision=self.use_vision,
				task=self.task,
				model_name=self.model_name,
				chat_model_library=self.chat_model_library,
				version=self.version,
				source=self.source,
			)
		)

	@observe(name='agent.run', ignore_output=True)
	async def run(self, max_steps: int = 100) -> AgentHistoryList:
		"""Execute the task with maximum number of steps"""
		try:
			self._log_agent_run()

			# Execute initial actions if provided
			if self.initial_actions:
				result = await self.controller.multi_act(
					self.initial_actions,
					self.browser_context,
					check_for_new_elements=False,
					page_extraction_llm=self.page_extraction_llm,
					check_break_if_paused=lambda: self._check_if_stopped_or_paused(),
					available_file_paths=self.available_file_paths,
				)
				self._last_result = result

			for step in range(max_steps):
				if self._too_many_failures():
					break

				# Check control flags before each step
				if not await self._handle_control_flags():
					break

				await self.step()

				if self.history.is_done():
					if self.validate_output and step < max_steps - 1:
						if not await self._validate_output():
							continue

					logger.info('✅ Task completed successfully')
					if self.register_done_callback:
						self.register_done_callback(self.history)
					break
			else:
				logger.info('❌ Failed to complete task in maximum steps')

			return self.history
		finally:
			self.telemetry.capture(
				AgentEndTelemetryEvent(
					agent_id=self.agent_id,
					success=self.history.is_done(),
					steps=self.n_steps,
					max_steps_reached=self.n_steps >= max_steps,
					errors=self.history.errors(),
				)
			)

			if not self.injected_browser_context:
				await self.browser_context.close()

			if not self.injected_browser and self.browser:
				await self.browser.close()

			if self.generate_gif:
				output_path: str = 'agent_history.gif'
				if isinstance(self.generate_gif, str):
					output_path = self.generate_gif

				self.create_history_gif(output_path=output_path)

	def _too_many_failures(self) -> bool:
		"""Check if we should stop due to too many failures"""
		if self.consecutive_failures >= self.max_failures:
			logger.error(f'❌ Stopping due to {self.max_failures} consecutive failures')
			return True
		return False

	async def _handle_control_flags(self) -> bool:
		"""Handle pause and stop flags. Returns True if execution should continue."""
		if self._stopped:
			logger.info('Agent stopped')
			return False

		while self._paused:
			await asyncio.sleep(0.2)  # Small delay to prevent CPU spinning
			if self._stopped:  # Allow stopping while paused
				return False
		return True

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

		if self.browser_context.session:
			state = await self.browser_context.get_state()
			content = AgentMessagePrompt(
				state=state,
				result=self._last_result,
				include_attributes=self.include_attributes,
				max_error_length=self.max_error_length,
			)
			msg = [SystemMessage(content=system_msg), content.get_user_message(self.use_vision)]
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
			logger.info(f'❌ Validator decision: {parsed.reason}')
			msg = f'The output is not yet correct. {parsed.reason}.'
			self._last_result = [ActionResult(extracted_content=msg, include_in_memory=True)]
		else:
			logger.info(f'✅ Validator decision: {parsed.reason}')
		return is_valid

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
			await self.controller.multi_act(
				self.initial_actions,
				self.browser_context,
				check_for_new_elements=False,
				page_extraction_llm=self.page_extraction_llm,
				check_break_if_paused=lambda: self._check_if_stopped_or_paused(),
				available_file_paths=self.available_file_paths,
				sensitive_data=self.sensitive_data,
			)

		results = []

		for i, history_item in enumerate(history.history):
			goal = history_item.model_output.current_state.next_goal if history_item.model_output else ''
			logger.info(f'Replaying step {i + 1}/{len(history.history)}: goal: {goal}')

			if (
				not history_item.model_output
				or not history_item.model_output.action
				or history_item.model_output.action == [None]
			):
				logger.warning(f'Step {i + 1}: No action to replay, skipping')
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
						logger.error(error_msg)
						if not skip_failures:
							results.append(ActionResult(error=error_msg))
							raise RuntimeError(error_msg)
					else:
						logger.warning(f'Step {i + 1} failed (attempt {retry_count}/{max_retries}), retrying...')
						await asyncio.sleep(delay_between_actions)

		return results

	async def _execute_history_step(self, history_item: AgentHistory, delay: float) -> list[ActionResult]:
		"""Execute a single step from history with element validation"""
		state = await self.browser_context.get_state()
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

		result = await self.controller.multi_act(
			updated_actions,
			self.browser_context,
			page_extraction_llm=self.page_extraction_llm,
			check_break_if_paused=lambda: self._check_if_stopped_or_paused(),
			sensitive_data=self.sensitive_data,
		)

		await asyncio.sleep(delay)
		return result

	async def _update_action_indices(
		self,
		historical_element: Optional[DOMHistoryElement],
		action: ActionModel,  # Type this properly based on your action model
		current_state: BrowserState,
	) -> Optional[ActionModel]:
		"""
		Update action indices based on current page state.
		Returns updated action or None if element cannot be found.
		"""
		if not historical_element or not current_state.element_tree:
			return action

		current_element = HistoryTreeProcessor.find_history_element_in_tree(historical_element, current_state.element_tree)

		if not current_element or current_element.highlight_index is None:
			return None

		old_index = action.get_index()
		if old_index != current_element.highlight_index:
			action.set_index(current_element.highlight_index)
			logger.info(f'Element moved in DOM, updated index from {old_index} to {current_element.highlight_index}')

		return action

	async def load_and_rerun(self, history_file: Optional[str | Path] = None, **kwargs) -> list[ActionResult]:
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

	def save_history(self, file_path: Optional[str | Path] = None) -> None:
		"""Save the history to a file"""
		if not file_path:
			file_path = 'AgentHistory.json'
		self.history.save_to_file(file_path)

	def create_history_gif(
		self,
		output_path: str = 'agent_history.gif',
		duration: int = 3000,
		show_goals: bool = True,
		show_task: bool = True,
		show_logo: bool = False,
		font_size: int = 40,
		title_font_size: int = 56,
		goal_font_size: int = 44,
		margin: int = 40,
		line_spacing: float = 1.5,
	) -> None:
		"""Create a GIF from the agent's history with overlaid task and goal text."""
		if not self.history.history:
			logger.warning('No history to create GIF from')
			return

		images = []
		# if history is empty or first screenshot is None, we can't create a gif
		if not self.history.history or not self.history.history[0].state.screenshot:
			logger.warning('No history or first screenshot to create GIF from')
			return

		# Try to load fonts with multi-language support
		try:
			# Try different font options in order of preference
			# System-specific fonts
			if platform.system() == 'Windows':
				font_options = [
					'msyh.ttc',  # Microsoft YaHei
					'seguiemj.ttf',  # Segoe UI Emoji
					'segoe.ttf',  # Segoe UI
				]
			elif platform.system() == 'Darwin':  # macOS
				font_options = [
					'Hiragino Sans GB',  # Primary font with full Unicode support (CJK + Latin)
					'.AppleSystemUIFont',  # System UI font as fallback
					'Apple Color Emoji',  # Emoji and special characters
				]
			else:  # Linux and others
				font_options = [
					'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
				]

			# Add common fallback fonts
			font_options.extend(['Arial Unicode MS', 'Helvetica', 'Arial', 'DejaVuSans', 'Verdana'])

			font_loaded = False
			for font_name in font_options:
				try:
					if platform.system() == 'Windows':
						if not font_name.endswith(('.ttf', '.ttc')):
							font_name = os.path.join(os.getenv('WIN_FONT_DIR', 'C:\\Windows\\Fonts'), font_name + '.ttf')
					regular_font = ImageFont.truetype(font_name, font_size)
					title_font = ImageFont.truetype(font_name, title_font_size)
					goal_font = ImageFont.truetype(font_name, goal_font_size)
					logger.debug(f'Loaded font: {font_name}')
					font_loaded = True
					break
				except OSError:
					continue

			if not font_loaded:
				raise OSError('No suitable fonts found')

		except OSError:
			logger.warning('Failed to load Unicode fonts, falling back to default')
			regular_font = ImageFont.load_default()
			title_font = ImageFont.load_default()

			goal_font = regular_font

		# Load logo if requested
		logo = None
		if show_logo:
			try:
				logo = Image.open('./static/browser-use.png')
				# Resize logo to be small (e.g., 40px height)
				logo_height = 150
				aspect_ratio = logo.width / logo.height
				logo_width = int(logo_height * aspect_ratio)
				logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
			except Exception as e:
				logger.warning(f'Could not load logo: {e}')

		# Create task frame if requested
		if show_task and self.task:
			task_frame = self._create_task_frame(
				self.task,
				self.history.history[0].state.screenshot,
				title_font,
				regular_font,
				logo,
				line_spacing,
			)
			images.append(task_frame)

		# Process each history item
		for i, item in enumerate(self.history.history, 1):
			if not item.state.screenshot:
				continue

			# Convert base64 screenshot to PIL Image
			img_data = base64.b64decode(item.state.screenshot)
			image = Image.open(io.BytesIO(img_data))

			if show_goals and item.model_output:
				image = self._add_overlay_to_image(
					image=image,
					step_number=i,
					goal_text=item.model_output.current_state.next_goal,
					regular_font=regular_font,
					title_font=title_font,
					margin=margin,
					logo=logo,
				)

			images.append(image)

		if images:
			# Save the GIF
			images[0].save(
				output_path,
				save_all=True,
				append_images=images[1:],
				duration=duration,
				loop=0,
				optimize=False,
			)
			logger.info(f'Created GIF at {output_path}')
		else:
			logger.warning('No images found in history to create GIF')

	def _create_task_frame(
		self,
		task: str,
		first_screenshot: str,
		title_font: ImageFont.FreeTypeFont,
		regular_font: ImageFont.FreeTypeFont,
		logo: Optional[Image.Image] = None,
		line_spacing: float = 1.5,
	) -> Image.Image:
		"""Create initial frame showing the task."""
		img_data = base64.b64decode(first_screenshot)
		template = Image.open(io.BytesIO(img_data))
		image = Image.new('RGB', template.size, (0, 0, 0))
		draw = ImageDraw.Draw(image)

		# Calculate vertical center of image
		center_y = image.height // 2

		# Draw task text with increased font size
		margin = 140  # Increased margin
		max_width = image.width - (2 * margin)
		larger_font = ImageFont.truetype(regular_font.path, regular_font.size + 16)  # Increase font size more
		wrapped_text = self._wrap_text(task, larger_font, max_width)

		# Calculate line height with spacing
		line_height = larger_font.size * line_spacing

		# Split text into lines and draw with custom spacing
		lines = wrapped_text.split('\n')
		total_height = line_height * len(lines)

		# Start position for first line
		text_y = center_y - (total_height / 2) + 50  # Shifted down slightly

		for line in lines:
			# Get line width for centering
			line_bbox = draw.textbbox((0, 0), line, font=larger_font)
			text_x = (image.width - (line_bbox[2] - line_bbox[0])) // 2

			draw.text(
				(text_x, text_y),
				line,
				font=larger_font,
				fill=(255, 255, 255),
			)
			text_y += line_height

		# Add logo if provided (top right corner)
		if logo:
			logo_margin = 20
			logo_x = image.width - logo.width - logo_margin
			image.paste(logo, (logo_x, logo_margin), logo if logo.mode == 'RGBA' else None)

		return image

	def _add_overlay_to_image(
		self,
		image: Image.Image,
		step_number: int,
		goal_text: str,
		regular_font: ImageFont.FreeTypeFont,
		title_font: ImageFont.FreeTypeFont,
		margin: int,
		logo: Optional[Image.Image] = None,
		display_step: bool = True,
		text_color: tuple[int, int, int, int] = (255, 255, 255, 255),
		text_box_color: tuple[int, int, int, int] = (0, 0, 0, 255),
	) -> Image.Image:
		"""Add step number and goal overlay to an image."""
		image = image.convert('RGBA')
		txt_layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
		draw = ImageDraw.Draw(txt_layer)
		if display_step:
			# Add step number (bottom left)
			step_text = str(step_number)
			step_bbox = draw.textbbox((0, 0), step_text, font=title_font)
			step_width = step_bbox[2] - step_bbox[0]
			step_height = step_bbox[3] - step_bbox[1]

			# Position step number in bottom left
			x_step = margin + 10  # Slight additional offset from edge
			y_step = image.height - margin - step_height - 10  # Slight offset from bottom

			# Draw rounded rectangle background for step number
			padding = 20  # Increased padding
			step_bg_bbox = (
				x_step - padding,
				y_step - padding,
				x_step + step_width + padding,
				y_step + step_height + padding,
			)
			draw.rounded_rectangle(
				step_bg_bbox,
				radius=15,  # Add rounded corners
				fill=text_box_color,
			)

			# Draw step number
			draw.text(
				(x_step, y_step),
				step_text,
				font=title_font,
				fill=text_color,
			)

		# Draw goal text (centered, bottom)
		max_width = image.width - (4 * margin)
		wrapped_goal = self._wrap_text(goal_text, title_font, max_width)
		goal_bbox = draw.multiline_textbbox((0, 0), wrapped_goal, font=title_font)
		goal_width = goal_bbox[2] - goal_bbox[0]
		goal_height = goal_bbox[3] - goal_bbox[1]

		# Center goal text horizontally, place above step number
		x_goal = (image.width - goal_width) // 2
		y_goal = y_step - goal_height - padding * 4  # More space between step and goal

		# Draw rounded rectangle background for goal
		padding_goal = 25  # Increased padding for goal
		goal_bg_bbox = (
			x_goal - padding_goal,  # Remove extra space for logo
			y_goal - padding_goal,
			x_goal + goal_width + padding_goal,
			y_goal + goal_height + padding_goal,
		)
		draw.rounded_rectangle(
			goal_bg_bbox,
			radius=15,  # Add rounded corners
			fill=text_box_color,
		)

		# Draw goal text
		draw.multiline_text(
			(x_goal, y_goal),
			wrapped_goal,
			font=title_font,
			fill=text_color,
			align='center',
		)

		# Add logo if provided (top right corner)
		if logo:
			logo_layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
			logo_margin = 20
			logo_x = image.width - logo.width - logo_margin
			logo_layer.paste(logo, (logo_x, logo_margin), logo if logo.mode == 'RGBA' else None)
			txt_layer = Image.alpha_composite(logo_layer, txt_layer)

		# Composite and convert
		result = Image.alpha_composite(image, txt_layer)
		return result.convert('RGB')

	def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
		"""
		Wrap text to fit within a given width.

		Args:
			text: Text to wrap
			font: Font to use for text
			max_width: Maximum width in pixels

		Returns:
			Wrapped text with newlines
		"""
		words = text.split()
		lines = []
		current_line = []

		for word in words:
			current_line.append(word)
			line = ' '.join(current_line)
			bbox = font.getbbox(line)
			if bbox[2] > max_width:
				if len(current_line) == 1:
					lines.append(current_line.pop())
				else:
					current_line.pop()
					lines.append(' '.join(current_line))
					current_line = [word]

		if current_line:
			lines.append(' '.join(current_line))

		return '\n'.join(lines)

	def _create_frame(self, screenshot: str, text: str, step_number: int, width: int = 1200, height: int = 800) -> Image.Image:
		"""Create a frame for the GIF with improved styling"""

		# Create base image
		frame = Image.new('RGB', (width, height), 'white')

		# Load and resize screenshot
		screenshot_img = Image.open(BytesIO(base64.b64decode(screenshot)))
		screenshot_img.thumbnail((width - 40, height - 160))  # Leave space for text

		# Calculate positions
		screenshot_x = (width - screenshot_img.width) // 2
		screenshot_y = 120  # Leave space for header

		# Draw screenshot
		frame.paste(screenshot_img, (screenshot_x, screenshot_y))

		# Load browser-use logo
		logo_size = 100  # Increased size for browser-use logo
		logo_path = os.path.join(os.path.dirname(__file__), 'assets/browser-use-logo.png')
		if os.path.exists(logo_path):
			logo = Image.open(logo_path)
			logo.thumbnail((logo_size, logo_size))
			frame.paste(logo, (width - logo_size - 20, 20), logo if 'A' in logo.getbands() else None)

		# Create drawing context
		draw = ImageDraw.Draw(frame)

		# Load fonts
		try:
			title_font = ImageFont.truetype('Arial.ttf', 36)  # Increased font size
			text_font = ImageFont.truetype('Arial.ttf', 24)  # Increased font size
			number_font = ImageFont.truetype('Arial.ttf', 48)  # Increased font size for step number
		except:
			title_font = ImageFont.load_default()
			text_font = ImageFont.load_default()
			number_font = ImageFont.load_default()

		# Draw task text with increased spacing
		margin = 80  # Increased margin
		max_text_width = width - (2 * margin)

		# Create rounded rectangle for goal text
		text_padding = 20
		text_lines = textwrap.wrap(text, width=60)
		text_height = sum(draw.textsize(line, font=text_font)[1] for line in text_lines)
		text_box_height = text_height + (2 * text_padding)

		# Draw rounded rectangle background for goal
		goal_bg_coords = [
			margin - text_padding,
			40,  # Top position
			width - margin + text_padding,
			40 + text_box_height,
		]
		draw.rounded_rectangle(
			goal_bg_coords,
			radius=15,  # Increased radius for more rounded corners
			fill='#f0f0f0',
		)

		# Draw browser-use small logo in top left of goal box
		small_logo_size = 30
		if os.path.exists(logo_path):
			small_logo = Image.open(logo_path)
			small_logo.thumbnail((small_logo_size, small_logo_size))
			frame.paste(
				small_logo,
				(margin - text_padding + 10, 45),  # Positioned inside goal box
				small_logo if 'A' in small_logo.getbands() else None,
			)

		# Draw text with proper wrapping
		y = 50  # Starting y position for text
		for line in text_lines:
			draw.text((margin + small_logo_size + 20, y), line, font=text_font, fill='black')
			y += draw.textsize(line, font=text_font)[1] + 5

		# Draw step number with rounded background
		number_text = str(step_number)
		number_size = draw.textsize(number_text, font=number_font)
		number_padding = 20
		number_box_width = number_size[0] + (2 * number_padding)
		number_box_height = number_size[1] + (2 * number_padding)

		# Draw rounded rectangle for step number
		number_bg_coords = [
			20,  # Left position
			height - number_box_height - 20,  # Bottom position
			20 + number_box_width,
			height - 20,
		]
		draw.rounded_rectangle(
			number_bg_coords,
			radius=15,
			fill='#007AFF',  # Blue background
		)

		# Center number in its background
		number_x = number_bg_coords[0] + ((number_box_width - number_size[0]) // 2)
		number_y = number_bg_coords[1] + ((number_box_height - number_size[1]) // 2)
		draw.text((number_x, number_y), number_text, font=number_font, fill='white')

		return frame

	def pause(self) -> None:
		"""Pause the agent before the next step"""
		logger.info('🔄 pausing Agent ')
		self._paused = True

	def resume(self) -> None:
		"""Resume the agent"""
		logger.info('▶️ Agent resuming')
		self._paused = False

	def stop(self) -> None:
		"""Stop the agent"""
		logger.info('⏹️ Agent stopping')
		self._stopped = True

	def _convert_initial_actions(self, actions: List[Dict[str, Dict[str, Any]]]) -> List[ActionModel]:
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

	async def _run_planner(self) -> Optional[str]:
		"""Run the planner to analyze state and suggest next steps"""
		# Skip planning if no planner_llm is set
		if not self.planner_llm:
			return None

		# Create planner message history using full message history
		planner_messages = [
			PlannerPrompt(self.action_descriptions).get_system_message(),
			*self.message_manager.get_messages()[1:],  # Use full message history except the first
		]

		if not self.use_vision_for_planner and self.use_vision:
			last_state_message = planner_messages[-1]
			# remove image from last state message
			new_msg = ''
			if isinstance(last_state_message.content, list):
				for msg in last_state_message.content:
					if msg['type'] == 'text':
						new_msg += msg['text']
					elif msg['type'] == 'image_url':
						continue
			else:
				new_msg = last_state_message.content

			planner_messages[-1] = HumanMessage(content=new_msg)

		planner_messages = self._convert_input_messages(planner_messages, self.planner_model_name)
		# Get planner output
		response = await self.planner_llm.ainvoke(planner_messages)
		plan = response.content
		# if deepseek-reasoner, remove think tags
		if self.planner_model_name == 'deepseek-reasoner':
			plan = self._remove_think_tags(plan)
		try:
			plan_json = json.loads(plan)
			logger.info(f'Planning Analysis:\n{json.dumps(plan_json, indent=4)}')
		except json.JSONDecodeError:
			logger.info(f'Planning Analysis:\n{plan}')
		except Exception as e:
			logger.debug(f'Error parsing planning analysis: {e}')
			logger.info(f'Plan: {plan}')

		return plan
