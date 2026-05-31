import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from browser_use.agent.llm_debug_trace import append_llm_debug_trace
from browser_use.agent.runtime import NativeToolCall, NativeToolRouter
from browser_use.agent.url_shortening import (
	process_messages_and_replace_long_urls,
	replace_shortened_urls_in_string,
	replace_urls_in_text,
	restore_shortened_urls_in_dict,
	restore_shortened_urls_in_model,
	restore_shortened_urls_in_sequence,
)
from browser_use.agent.views import AgentOutput as AgentOutputModel
from browser_use.agent.views import AgentSettings, AgentState
from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage, UserMessage
from browser_use.observability import observe_debug
from browser_use.tokens.service import TokenCost
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.utils import time_execution_async


def log_response(response: AgentOutputModel, registry=None, logger=None) -> None:
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


class AgentModelIOMixin:
	settings: AgentSettings
	state: AgentState
	llm: BaseChatModel
	_original_llm: BaseChatModel
	_fallback_llm: BaseChatModel | None
	_using_fallback_llm: bool
	token_cost_service: TokenCost
	session_id: str
	agent_directory: Any
	_url_shortening_limit: int
	ActionModel: type[ActionModel]
	AgentOutput: type[AgentOutputModel]
	tools: Tools[Any]
	logger: logging.Logger
	_broadcast_model_state: Callable[[AgentOutputModel], Awaitable[None]]
	_log_next_action_summary: Callable[[AgentOutputModel], None]

	async def _get_model_output_with_retry(self, input_messages: list[BaseMessage]) -> AgentOutputModel:
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
		return replace_urls_in_text(text, self._url_shortening_limit)

	def _process_messsages_and_replace_long_urls_shorter_ones(self, input_messages: list[BaseMessage]) -> dict[str, str]:
		"""Replace long URLs with shorter ones
		? @dev edits input_messages in place

		returns:
			tuple[filtered_input_messages, urls we replaced {shorter_url: original_url}]
		"""
		return process_messages_and_replace_long_urls(input_messages, self._url_shortening_limit)

	@staticmethod
	def _recursive_process_all_strings_inside_pydantic_model(model: BaseModel, url_replacements: dict[str, str]) -> None:
		"""Recursively process all strings inside a Pydantic model, replacing shortened URLs with originals in place."""
		restore_shortened_urls_in_model(model, url_replacements)

	@staticmethod
	def _recursive_process_dict(dictionary: dict, url_replacements: dict[str, str]) -> None:
		"""Helper method to process dictionaries."""
		restore_shortened_urls_in_dict(dictionary, url_replacements)

	@staticmethod
	def _recursive_process_list_or_tuple(container: list | tuple, url_replacements: dict[str, str]) -> list | tuple:
		"""Helper method to process lists and tuples."""
		return restore_shortened_urls_in_sequence(container, url_replacements)

	@staticmethod
	def _replace_shortened_urls_in_string(text: str, url_replacements: dict[str, str]) -> str:
		"""Replace all shortened URLs in a string with their original URLs."""
		return replace_shortened_urls_in_string(text, url_replacements)

	# endregion - URL replacement

	@time_execution_async('--get_next_action')
	@observe_debug(ignore_input=True, ignore_output=True, name='get_model_output')
	async def get_model_output(self, input_messages: list[BaseMessage]) -> AgentOutputModel:
		"""Get next action from LLM based on current state"""

		urls_replaced = self._process_messsages_and_replace_long_urls_shorter_ones(input_messages)

		if self.settings.use_native_tool_calls:
			return await self._get_model_output_with_native_tool_calls(input_messages, urls_replaced)

		# Build kwargs for ainvoke
		# Note: ChatBrowserUse will automatically generate action descriptions from output_format schema
		kwargs: dict = {'output_format': self.AgentOutput, 'session_id': self.session_id}
		response = None

		try:
			await append_llm_debug_trace(
				agent_directory=self.agent_directory,
				logger=self.logger,
				event='llm_call_start',
				step=self.state.n_steps,
				session_id=self.session_id,
				llm=self.llm,
				messages=input_messages,
				output_format=self.AgentOutput,
				tools=self.tools,
				invoke_kwargs=kwargs,
			)
			response = await self.llm.ainvoke(input_messages, **kwargs)
			await append_llm_debug_trace(
				agent_directory=self.agent_directory,
				logger=self.logger,
				event='llm_call_result',
				step=self.state.n_steps,
				session_id=self.session_id,
				llm=self.llm,
				response=response,
			)
			parsed: AgentOutputModel = response.completion  # type: ignore[assignment]

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
		except ValidationError as e:
			await append_llm_debug_trace(
				agent_directory=self.agent_directory,
				logger=self.logger,
				event='llm_call_error',
				step=self.state.n_steps,
				session_id=self.session_id,
				llm=self.llm,
				error=e,
			)
			# Just re-raise - Pydantic's validation errors are already descriptive
			raise
		except (ModelRateLimitError, ModelProviderError) as e:
			await append_llm_debug_trace(
				agent_directory=self.agent_directory,
				logger=self.logger,
				event='llm_call_error',
				step=self.state.n_steps,
				session_id=self.session_id,
				llm=self.llm,
				error=e,
			)
			# Check if we can switch to a fallback LLM
			if not self._try_switch_to_fallback_llm(e):
				# No fallback available, re-raise the original error
				raise
			# Retry with the fallback LLM
			return await self.get_model_output(input_messages)
		except Exception as exc:
			await append_llm_debug_trace(
				agent_directory=self.agent_directory,
				logger=self.logger,
				event='llm_call_error',
				step=self.state.n_steps,
				session_id=self.session_id,
				llm=self.llm,
				response=response,
				error=exc,
			)
			raise

	async def _get_model_output_with_native_tool_calls(
		self,
		input_messages: list[BaseMessage],
		urls_replaced: dict[str, str],
	) -> AgentOutputModel:
		"""Call an LLM with provider-native tools and adapt registered tool calls to legacy action execution."""
		router = NativeToolRouter.from_tools(self.tools, include_experimental=False)
		tool_schemas = router.tool_schemas()
		kwargs: dict[str, Any] = {
			'output_format': None,
			'tools': tool_schemas,
			'tool_choice': 'required',
			'parallel_tool_calls': self.settings.max_actions_per_step > 1,
			'session_id': self.session_id,
		}
		await append_llm_debug_trace(
			agent_directory=self.agent_directory,
			logger=self.logger,
			event='llm_call_start',
			step=self.state.n_steps,
			session_id=self.session_id,
			llm=self.llm,
			messages=input_messages,
			native_tools=tool_schemas,
			tools=self.tools,
			invoke_kwargs=kwargs,
		)
		response = None
		try:
			response = await self.llm.ainvoke(input_messages, **kwargs)
			await append_llm_debug_trace(
				agent_directory=self.agent_directory,
				logger=self.logger,
				event='llm_call_result',
				step=self.state.n_steps,
				session_id=self.session_id,
				llm=self.llm,
				response=response,
			)
		except Exception as exc:
			await append_llm_debug_trace(
				agent_directory=self.agent_directory,
				logger=self.logger,
				event='llm_call_error',
				step=self.state.n_steps,
				session_id=self.session_id,
				llm=self.llm,
				response=response,
				error=exc,
			)
			raise
		assert response is not None
		try:
			if not response.tool_calls:
				raise ValueError('Model returned no native tool calls.')

			actions: list[ActionModel] = []
			for tool_call in response.tool_calls[: self.settings.max_actions_per_step]:
				try:
					arguments = json.loads(tool_call.function.arguments or '{}')
				except json.JSONDecodeError as exc:
					raise ValueError(f'Invalid JSON arguments for native tool {tool_call.function.name}: {exc}') from exc

				call = NativeToolCall(
					tool_name=tool_call.function.name,
					arguments=arguments,
					call_id=tool_call.id,
				)
				definition = router.resolve(call.tool_name)
				if definition.source_action is None:
					raise ValueError(f'Native tool {definition.name} cannot be adapted to the legacy action executor.')
				validated_params = router.validate_call(call)
				actions.append(self.ActionModel(**{definition.source_action: validated_params.model_dump(mode='json')}))
		except Exception as exc:
			await append_llm_debug_trace(
				agent_directory=self.agent_directory,
				logger=self.logger,
				event='llm_call_error',
				step=self.state.n_steps,
				session_id=self.session_id,
				llm=self.llm,
				response=response,
				error=exc,
			)
			raise

		parsed = self.AgentOutput(
			evaluation_previous_goal='Received provider-native tool calls.',
			memory=response.completion or 'Native tool call response.',
			next_goal='Execute the requested tool calls.',
			action=actions,
		)
		parsed.set_native_tool_calls(response.tool_calls[: self.settings.max_actions_per_step])
		if urls_replaced:
			self._recursive_process_all_strings_inside_pydantic_model(parsed, urls_replaced)

		if not (hasattr(self.state, 'paused') and (self.state.paused or self.state.stopped)):
			log_response(parsed, self.tools.registry.registry, self.logger)
			await self._broadcast_model_state(parsed)

		self._log_next_action_summary(parsed)
		return parsed

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
