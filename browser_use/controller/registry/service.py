import asyncio
import logging
import re
from collections.abc import Callable
from inspect import iscoroutinefunction, signature
from typing import Any, Generic, Optional, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field, create_model

from browser_use.browser import BrowserSession
from browser_use.controller.registry.views import (
	ActionModel,
	ActionRegistry,
	RegisteredAction,
	SpecialActionParameters,
)
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import (
	ControllerRegisteredFunctionsTelemetryEvent,
	RegisteredFunction,
)
from browser_use.utils import match_url_with_domain_pattern, time_execution_async

Context = TypeVar('Context')

logger = logging.getLogger(__name__)


class Registry(Generic[Context]):
	"""Service for registering and managing actions"""

	def __init__(self, exclude_actions: list[str] | None = None):
		self.registry = ActionRegistry()
		self.telemetry = ProductTelemetry()
		self.exclude_actions = exclude_actions if exclude_actions is not None else []

	# @time_execution_sync('--create_param_model')
	def _create_param_model(self, function: Callable) -> type[BaseModel]:
		"""Creates a Pydantic model from function signature"""
		sig = signature(function)
		special_param_names = set(SpecialActionParameters.model_fields.keys())
		params = {
			name: (param.annotation, ... if param.default == param.empty else param.default)
			for name, param in sig.parameters.items()
			if name not in special_param_names
		}
		# TODO: make the types here work
		return create_model(
			f'{function.__name__}_parameters',
			__base__=ActionModel,
			**params,  # type: ignore
		)

	def action(
		self,
		description: str,
		param_model: type[BaseModel] | None = None,
		domains: list[str] | None = None,
		allowed_domains: list[str] | None = None,
		page_filter: Callable[[Any], bool] | None = None,
	):
		"""Decorator for registering actions"""
		# Handle aliases: domains and allowed_domains are the same parameter
		if allowed_domains is not None and domains is not None:
			raise ValueError("Cannot specify both 'domains' and 'allowed_domains' - they are aliases for the same parameter")

		final_domains = allowed_domains if allowed_domains is not None else domains

		def decorator(func: Callable):
			# Skip registration if action is in exclude_actions
			if func.__name__ in self.exclude_actions:
				return func

			# Create param model from function if not provided
			actual_param_model = param_model or self._create_param_model(func)

			# Wrap sync functions to make them async
			if not iscoroutinefunction(func):

				async def async_wrapper(*args, **kwargs):
					return await asyncio.to_thread(func, *args, **kwargs)

				# Copy the signature and other metadata from the original function
				async_wrapper.__signature__ = signature(func)
				async_wrapper.__name__ = func.__name__
				async_wrapper.__annotations__ = func.__annotations__
				wrapped_func = async_wrapper
			else:
				wrapped_func = func

			action = RegisteredAction(
				name=func.__name__,
				description=description,
				function=wrapped_func,
				param_model=actual_param_model,
				domains=final_domains,
				page_filter=page_filter,
			)
			self.registry.actions[func.__name__] = action
			return func

		return decorator

	@time_execution_async('--execute_action')
	async def execute_action(
		self,
		action_name: str,
		params: dict,
		browser_session: BrowserSession | None = None,
		page_extraction_llm: BaseChatModel | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		available_file_paths: list[str] | None = None,
		#
		context: Context | None = None,
	) -> Any:
		"""Execute a registered action with enhanced parameter handling for backward compatibility"""
		if action_name not in self.registry.actions:
			raise ValueError(f'Action {action_name} not found')

		action = self.registry.actions[action_name]
		try:
			# Create the validated Pydantic model
			try:
				validated_params = action.param_model(**params)
			except Exception as e:
				raise ValueError(f'Invalid parameters {params} for action {action_name}: {type(e)}: {e}') from e

			# Analyze function signature for smart parameter injection
			sig = signature(action.function)
			parameters = list(sig.parameters.values())
			parameter_names = [param.name for param in parameters]

			# Check if the first parameter is a Pydantic model (using original safe logic)
			# Only consider it pydantic if:
			# 1. There are parameters
			# 2. First parameter has a BaseModel annotation
			# 3. AND the function signature actually takes a BaseModel as first param (not auto-generated)
			try:
				is_pydantic = (
					parameters
					and len(parameters) > 0
					and hasattr(parameters[0], 'annotation')
					and parameters[0].annotation != parameters[0].empty
					and issubclass(parameters[0].annotation, BaseModel)
					# Additional check: make sure the first parameter name suggests it's actually a pydantic model
					# and parameters[0].name in ['params', 'param', 'model']
					# or parameters[0].name.endswith('_model')
				)
			except (TypeError, AttributeError):
				is_pydantic = False

			if sensitive_data:
				# Get current URL if browser_session is provided
				current_url = None
				if browser_session:
					if browser_session.agent_current_page:
						current_url = browser_session.agent_current_page.url
					else:
						current_page = await browser_session.get_current_page()
						current_url = current_page.url if current_page else None
				validated_params = self._replace_sensitive_data(validated_params, sensitive_data, current_url)

			# Check if the action requires special parameters and validate they're provided
			if (
				'browser_session' in parameter_names
				or 'browser' in parameter_names
				or 'browser_context' in parameter_names
				or 'page' in parameter_names
			) and not browser_session:
				raise ValueError(f'Action {action_name} requires browser_session but none provided.')
			if 'page_extraction_llm' in parameter_names and not page_extraction_llm:
				raise ValueError(f'Action {action_name} requires page_extraction_llm but none provided.')
			if 'available_file_paths' in parameter_names and not available_file_paths:
				raise ValueError(f'Action {action_name} requires available_file_paths but none provided.')
			if 'context' in parameter_names and not context:
				raise ValueError(f'Action {action_name} requires context but none provided.')

			# Create special parameters model with all available values
			special_params_data = {
				'context': context,
				'browser_session': browser_session,
				'browser': browser_session,  # legacy support
				'browser_context': browser_session,  # legacy support
				'page_extraction_llm': page_extraction_llm,
				'available_file_paths': available_file_paths,
				'has_sensitive_data': action_name == 'input_text' and bool(sensitive_data),
			}

			# Handle async page parameter if needed
			if 'page' in parameter_names and browser_session:
				special_params_data['page'] = await browser_session.get_current_page()

			# Create special parameters object without validation to preserve BrowserSession state
			# We bypass model_validate to avoid copying BrowserSession and losing private attributes
			special_params = SpecialActionParameters.model_construct(**special_params_data)

			# Log legacy usage
			if 'browser' in parameter_names:
				logger.debug(
					f'You should update this action {action_name}(browser: BrowserContext) -> to take {action_name}(browser_session: BrowserSession) instead'
				)
			if 'browser_context' in parameter_names:
				logger.debug(
					f'You should update this action {action_name}(browser_context: BrowserContext) -> to take {action_name}(browser_session: BrowserSession) instead'
				)

			# Enhanced parameter injection logic using Pydantic
			if is_pydantic:
				# For pydantic functions: function(pydantic_model, **special_params)
				# Extract special parameters needed by this function (keep objects, don't serialize)
				needed_special_params = set(parameter_names[1:]) & set(SpecialActionParameters.model_fields.keys())
				injection_params = {}
				for param_name in needed_special_params:
					value = getattr(special_params, param_name, None)
					if value is not None:
						injection_params[param_name] = value

				return await action.function(validated_params, **injection_params)
			else:
				# For individual parameter functions: function(**all_params)
				# Merge user params with needed special params, avoiding conflicts
				param_dict = validated_params.model_dump()

				# Extract special parameters needed by this function (keep objects, don't serialize)
				needed_special_params = set(parameter_names) & set(SpecialActionParameters.model_fields.keys())
				injection_params = {}
				for param_name in needed_special_params:
					value = getattr(special_params, param_name, None)
					if value is not None:
						injection_params[param_name] = value

				# Remove any special params from user params to avoid conflicts (special params take precedence)
				for param_name in injection_params:
					if param_name in param_dict:
						logger.debug(f'Removing {param_name} from param_dict to avoid conflict')
						param_dict.pop(param_name)

				# Combine all parameters
				final_params = {**param_dict, **injection_params}
				return await action.function(**final_params)

		except Exception as e:
			raise RuntimeError(f'Error executing action {action_name}: {str(e)}') from e

	def _log_sensitive_data_usage(self, placeholders_used: set[str], current_url: str | None) -> None:
		"""Log when sensitive data is being used on a page"""
		if placeholders_used:
			url_info = f' on {current_url}' if current_url and current_url != 'about:blank' else ''
			logger.info(f'🔒 Using sensitive data placeholders: {", ".join(sorted(placeholders_used))}{url_info}')

	def _replace_sensitive_data(self, params: BaseModel, sensitive_data: dict[str, Any], current_url: str = None) -> BaseModel:
		"""
		Replaces sensitive data placeholders in params with actual values.

		Args:
			params: The parameter object containing <secret>placeholder</secret> tags
			sensitive_data: Dictionary of sensitive data, either in old format {key: value}
						   or new format {domain_pattern: {key: value}}
			current_url: Optional current URL for domain matching

		Returns:
			BaseModel: The parameter object with placeholders replaced by actual values
		"""
		secret_pattern = re.compile(r'<secret>(.*?)</secret>')

		# Set to track all missing placeholders across the full object
		all_missing_placeholders = set()
		# Set to track successfully replaced placeholders
		replaced_placeholders = set()

		# Process sensitive data based on format and current URL
		applicable_secrets = {}

		for domain_or_key, content in sensitive_data.items():
			if isinstance(content, dict):
				# New format: {domain_pattern: {key: value}}
				# Only include secrets for domains that match the current URL
				if current_url and current_url != 'about:blank':
					# it's a real url, check it using our custom allowed_domains scheme://*.example.com glob matching
					if match_url_with_domain_pattern(current_url, domain_or_key):
						applicable_secrets.update(content)
			else:
				# Old format: {key: value}, expose to all domains (only allowed for legacy reasons)
				applicable_secrets[domain_or_key] = content

		# Filter out empty values
		applicable_secrets = {k: v for k, v in applicable_secrets.items() if v}

		def recursively_replace_secrets(value: str | dict | list) -> str | dict | list:
			if isinstance(value, str):
				matches = secret_pattern.findall(value)

				for placeholder in matches:
					if placeholder in applicable_secrets:
						value = value.replace(f'<secret>{placeholder}</secret>', applicable_secrets[placeholder])
						replaced_placeholders.add(placeholder)
					else:
						# Keep track of missing placeholders
						all_missing_placeholders.add(placeholder)
						# Don't replace the tag, keep it as is

				return value
			elif isinstance(value, dict):
				return {k: recursively_replace_secrets(v) for k, v in value.items()}
			elif isinstance(value, list):
				return [recursively_replace_secrets(v) for v in value]
			return value

		params_dump = params.model_dump()
		processed_params = recursively_replace_secrets(params_dump)

		# Log sensitive data usage
		self._log_sensitive_data_usage(replaced_placeholders, current_url)

		# Log a warning if any placeholders are missing
		if all_missing_placeholders:
			logger.warning(f'Missing or empty keys in sensitive_data dictionary: {", ".join(all_missing_placeholders)}')

		return type(params).model_validate(processed_params)

	# @time_execution_sync('--create_action_model')
	def create_action_model(self, include_actions: list[str] | None = None, page=None) -> type[ActionModel]:
		"""Creates a Pydantic model from registered actions, used by LLM APIs that support tool calling & enforce a schema"""

		# Filter actions based on page if provided:
		#   if page is None, only include actions with no filters
		#   if page is provided, only include actions that match the page

		available_actions = {}
		for name, action in self.registry.actions.items():
			if include_actions is not None and name not in include_actions:
				continue

			# If no page provided, only include actions with no filters
			if page is None:
				if action.page_filter is None and action.domains is None:
					available_actions[name] = action
				continue

			# Check page_filter if present
			domain_is_allowed = self.registry._match_domains(action.domains, page.url)
			page_is_allowed = self.registry._match_page_filter(action.page_filter, page)

			# Include action if both filters match (or if either is not present)
			if domain_is_allowed and page_is_allowed:
				available_actions[name] = action

		fields = {
			name: (
				Optional[action.param_model],
				Field(default=None, description=action.description),
			)
			for name, action in available_actions.items()
		}

		self.telemetry.capture(
			ControllerRegisteredFunctionsTelemetryEvent(
				registered_functions=[
					RegisteredFunction(name=name, params=action.param_model.model_json_schema())
					for name, action in available_actions.items()
				]
			)
		)

		return create_model('ActionModel', __base__=ActionModel, **fields)  # type:ignore

	def get_prompt_description(self, page=None) -> str:
		"""Get a description of all actions for the prompt

		If page is provided, only include actions that are available for that page
		based on their filter_func
		"""
		return self.registry.get_prompt_description(page=page)
