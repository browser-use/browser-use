"""LLM service — handles LLM calls, retry, fallback, and URL processing.

Extracted from Agent.service for modularity.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.agent.pipeline import BaseStepPipeline
	from browser_use.agent.service import Agent

from pydantic import BaseModel, ValidationError

from browser_use.agent.views import AgentOutput
from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage, ContentPartTextParam, UserMessage
from browser_use.observability import observe_debug
from browser_use.utils import URL_PATTERN

logger = logging.getLogger(__name__)


def log_response(response: AgentOutput, registry=None, logger=None) -> None:
	"""Utility function to log the model's response."""

	# Use module logger if no logger provided
	if logger is None:
		logger = logging.getLogger(__name__)

	# Only log thinking if it's present
	if response.current_state.thinking:
		logger.debug(f'💭 {response.current_state.thinking}')

	# Only log evaluation if it's present
	if response.current_state.evaluation_previous_goal:
		logger.debug(f'🧐 Evaluating: {response.current_state.evaluation_previous_goal}')

	# Only log next goal if it's present
	if response.current_state.memory:
		logger.debug(f'🎯 New goal: {response.current_state.memory}')

	# Log the actions
	for i, action in enumerate(response.action):
		action_data = action.model_dump(exclude_unset=True)
		action_name = next(iter(action_data.keys())) if action_data else 'unknown'
		action_params = action_data.get(action_name, {}) if action_data else {}

		# Format parameters for compact display
		param_str = ''
		if isinstance(action_params, dict) and action_params:
			parts = []
			for k, v in action_params.items():
				if isinstance(v, str) and len(v) > 50:
					v = v[:50] + '...'
				parts.append(f'{k}={v}')
			param_str = ' ' + ' '.join(parts)

		logger.debug(f'🛠️  [{i + 1}] {action_name}{param_str}')


class LLMService:
	"""Handles LLM calls, retry logic, fallback switching, and URL processing.

	Follows the same (agent, pipeline) constructor pattern as ActionExecutor.
	"""

	def __init__(self, agent: Agent, pipeline: BaseStepPipeline) -> None:
		self._agent = agent
		self._pipeline = pipeline

		# Fallback LLM configuration
		self._fallback_llm: BaseChatModel | None = None
		self._using_fallback_llm: bool = False
		self._original_llm: BaseChatModel | None = None

	# ── Public API ───────────────────────────────────────────────────

	@property
	def is_using_fallback_llm(self) -> bool:
		"""Check if the agent is currently using the fallback LLM."""
		return self._using_fallback_llm

	@property
	def current_llm_model(self) -> str:
		"""Get the model name of the currently active LLM."""
		return self._agent.llm.model if hasattr(self._agent.llm, 'model') else 'unknown'

	def setup_fallback(self, fallback_llm: BaseChatModel | None) -> None:
		"""Configure fallback LLM after construction."""
		self._fallback_llm = fallback_llm
		self._original_llm = self._agent.llm

	def verify_and_setup_llm(self) -> bool | None:
		"""
		Verify that the LLM API keys are setup and the LLM API is responding properly.
		Also handles tool calling method detection if in auto mode.
		"""
		from browser_use.config import CONFIG

		# Skip verification if already done
		if getattr(self._agent.llm, '_verified_api_keys', None) is True or CONFIG.SKIP_LLM_API_KEY_VERIFICATION:
			setattr(self._agent.llm, '_verified_api_keys', True)
			return True

		return None

	# ── Core LLM call ───────────────────────────────────────────────

	@observe_debug(ignore_input=True, ignore_output=True, name='get_model_output')
	async def get_model_output(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get next action from LLM based on current state"""

		urls_replaced = self._process_messsages_and_replace_long_urls_shorter_ones(input_messages)

		# Build kwargs for ainvoke
		# Note: ChatBrowserUse will automatically generate action descriptions from output_format schema
		kwargs: dict = {'output_format': self._agent.AgentOutput, 'session_id': self._agent.session_id}

		try:
			response = await self._agent.llm.ainvoke(input_messages, **kwargs)
			parsed: AgentOutput = response.completion  # type: ignore[assignment]

			# Replace any shortened URLs in the LLM response back to original URLs
			if urls_replaced:
				self._recursive_process_all_strings_inside_pydantic_model(parsed, urls_replaced)

			# cut the number of actions to max_actions_per_step if needed
			if len(parsed.action) > self._agent.settings.max_actions_per_step:
				parsed.action = parsed.action[: self._agent.settings.max_actions_per_step]

			if not (hasattr(self._agent.state, 'paused') and (self._agent.state.paused or self._agent.state.stopped)):
				log_response(parsed, self._agent.tools.registry.registry, self._agent.logger)
				await self._pipeline.broadcast_model_state(parsed)

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

	async def get_model_output_with_retry(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get model output with retry logic for empty actions"""
		model_output = await self.get_model_output(input_messages)
		self._agent.logger.debug(
			f'✅ Step {self._agent.state.n_steps}: Got LLM response with {len(model_output.action) if model_output.action else 0} actions'
		)

		if (
			not model_output.action
			or not isinstance(model_output.action, list)
			or all(action.model_dump() == {} for action in model_output.action)
		):
			self._agent.logger.warning('Model returned empty action. Retrying...')

			clarification_message = UserMessage(
				content='You forgot to return an action. Please respond with a valid JSON action according to the expected schema with your assessment and next actions.'
			)

			retry_messages = input_messages + [clarification_message]
			model_output = await self.get_model_output(retry_messages)

			if not model_output.action or all(action.model_dump() == {} for action in model_output.action):
				self._agent.logger.warning('Model still returned empty after retry. Inserting safe noop action.')
				action_instance = self._agent.ActionModel()
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

	# ── Fallback logic ──────────────────────────────────────────────

	def _try_switch_to_fallback_llm(self, error: ModelRateLimitError | ModelProviderError) -> bool:
		"""
		Attempt to switch to a fallback LLM after a rate limit or provider error.

		Returns True if successfully switched to a fallback, False if no fallback available.
		Once switched, the agent will use the fallback LLM for the rest of the run.
		"""
		# Already using fallback - can't switch again
		if self._using_fallback_llm:
			self._agent.logger.warning(
				f'⚠️ Fallback LLM also failed ({type(error).__name__}: {error.message}), no more fallbacks available'
			)
			return False

		# Check if error is retryable (rate limit, auth errors, or server errors)
		# 401: API key invalid/expired - fallback to different provider
		# 402: Insufficient credits/payment required - fallback to different provider
		# 429: Rate limit exceeded
		# 500, 502, 503, 504: Server errors
		# ModelOutputTruncatedError: not retryable on the same model, but a fallback may have a higher cap
		retryable_status_codes = {401, 402, 429, 500, 502, 503, 504}
		is_retryable = isinstance(error, (ModelRateLimitError, ModelOutputTruncatedError)) or (
			hasattr(error, 'status_code') and error.status_code in retryable_status_codes
		)

		if not is_retryable:
			return False

		# Check if we have a fallback LLM configured
		if self._fallback_llm is None:
			self._agent.logger.warning(f'⚠️ LLM error ({type(error).__name__}: {error.message}) but no fallback_llm configured')
			return False

		self._log_fallback_switch(error, self._fallback_llm)

		# Switch to the fallback LLM
		self._agent.llm = self._fallback_llm
		self._using_fallback_llm = True

		# Register the fallback LLM for token cost tracking
		self._agent.token_cost_service.register_llm(self._fallback_llm)

		return True

	def _log_fallback_switch(self, error: ModelRateLimitError | ModelProviderError, fallback: BaseChatModel) -> None:
		"""Log when switching to a fallback LLM."""
		original_model = self._original_llm.model if hasattr(self._original_llm, 'model') else 'unknown'  # type: ignore[union-attr]
		fallback_model = fallback.model if hasattr(fallback, 'model') else 'unknown'
		error_type = type(error).__name__
		status_code = getattr(error, 'status_code', 'N/A')

		self._agent.logger.warning(
			f'⚠️ Primary LLM ({original_model}) failed with {error_type} (status={status_code}), '
			f'switching to fallback LLM ({fallback_model})'
		)

	# ── Text / URL processing ──────────────────────────────────────

	@staticmethod
	def _remove_think_tags(text: str) -> str:
		THINK_TAGS = re.compile(r'<think>.*?</think>', re.DOTALL)
		STRAY_CLOSE_TAG = re.compile(r'.*?</think>', re.DOTALL)
		# Step 1: Remove well-formed <think>...</think>
		text = re.sub(THINK_TAGS, '', text)
		# Step 2: If there's an unmatched closing tag </think>,
		#         remove everything up to and including that.
		text = re.sub(STRAY_CLOSE_TAG, '', text)
		return text.strip()

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
			if len(after_path) <= self._agent._url_shortening_limit:
				return original_url

			# If after_path is too long, truncate and add hash
			if after_path:
				truncated_after_path = after_path[: self._agent._url_shortening_limit]
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
				for shortened, original in url_replacements.items():
					if shortened in field_value:
						field_value = field_value.replace(shortened, original)
				model.__dict__[field_name] = field_value  # type: ignore[index]
			elif isinstance(field_value, BaseModel):
				# Recursively process nested Pydantic models
				LLMService._recursive_process_all_strings_inside_pydantic_model(field_value, url_replacements)
			elif isinstance(field_value, dict):
				for key, value in field_value.items():
					if isinstance(value, str):
						for shortened, original in url_replacements.items():
							if shortened in value:
								field_value[key] = value.replace(shortened, original)
					elif isinstance(value, BaseModel):
						LLMService._recursive_process_all_strings_inside_pydantic_model(value, url_replacements)
			elif isinstance(field_value, (list, tuple)):
				for item in field_value:
					if isinstance(item, str):
						for shortened, original in url_replacements.items():
							if shortened in item:
								model.__dict__[field_name] = [  # type: ignore[index]
									item.replace(shortened, original) if isinstance(x, str) else x for x in field_value
								]
					elif isinstance(item, BaseModel):
						LLMService._recursive_process_all_strings_inside_pydantic_model(item, url_replacements)

	# ── Logging ─────────────────────────────────────────────────────

	def _log_next_action_summary(self, parsed: AgentOutput) -> None:
		"""Log a comprehensive summary of the next action(s)"""
		if not (self._agent.logger.isEnabledFor(logging.DEBUG) and parsed.action):
			return

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

		# Log in compact format
		action_str = ' │ '.join(action_details)
		self._agent.logger.debug(f'📋 Next actions: {action_str}')
