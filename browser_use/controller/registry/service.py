import asyncio
from collections.abc import Callable
from inspect import iscoroutinefunction, signature
from typing import Any, Generic, Optional, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field, create_model

from browser_use.browser.context import BrowserContext
from browser_use.controller.registry.views import (
	ActionModel,
	ActionRegistry,
	RegisteredAction,
)
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import (
	ControllerRegisteredFunctionsTelemetryEvent,
	RegisteredFunction,
)
from browser_use.utils import time_execution_async

Context = TypeVar('Context')


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
		params = {
			name: (param.annotation, ... if param.default == param.empty else param.default)
			for name, param in sig.parameters.items()
			if name != 'browser' and name != 'page_extraction_llm' and name != 'available_file_paths'
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
		page_filter: Callable[[Any], bool] | None = None,
	):
		"""Decorator for registering actions"""

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
				domains=domains,
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
		browser: BrowserContext | None = None,
		page_extraction_llm: BaseChatModel | None = None,
		sensitive_data: dict[str, str] | None = None,
		available_file_paths: list[str] | None = None,
		#
		context: Context | None = None,
	) -> Any:
		"""Execute a registered action"""
		if action_name not in self.registry.actions:
			raise ValueError(f'Action {action_name} not found')

		action = self.registry.actions[action_name]
		try:
			# Create the validated Pydantic model
			validated_params = action.param_model(**params)

			# Check if the first parameter is a Pydantic model
			sig = signature(action.function)
			parameters = list(sig.parameters.values())
			is_pydantic = parameters and issubclass(parameters[0].annotation, BaseModel)
			parameter_names = [param.name for param in parameters]

			if sensitive_data:
				validated_params = self._replace_sensitive_data(validated_params, sensitive_data)

			# Check if the action requires browser
			if 'browser' in parameter_names and not browser:
				raise ValueError(f'Action {action_name} requires browser but none provided.')
			if 'page_extraction_llm' in parameter_names and not page_extraction_llm:
				raise ValueError(f'Action {action_name} requires page_extraction_llm but none provided.')
			if 'available_file_paths' in parameter_names and not available_file_paths:
				raise ValueError(f'Action {action_name} requires available_file_paths but none provided.')

			if 'context' in parameter_names and not context:
				raise ValueError(f'Action {action_name} requires context but none provided.')

			# Prepare arguments based on parameter type
			extra_args = {}
			if 'context' in parameter_names:
				extra_args['context'] = context
			if 'browser' in parameter_names:
				extra_args['browser'] = browser
			if 'page_extraction_llm' in parameter_names:
				extra_args['page_extraction_llm'] = page_extraction_llm
			if 'available_file_paths' in parameter_names:
				extra_args['available_file_paths'] = available_file_paths
			if action_name == 'input_text' and sensitive_data:
				extra_args['has_sensitive_data'] = True
			if is_pydantic:
				return await action.function(validated_params, **extra_args)
			return await action.function(**validated_params.model_dump(), **extra_args)

		except Exception as e:
			raise RuntimeError(f'Error executing action {action_name}: {str(e)}') from e

	def _replace_sensitive_data(self, params: BaseModel, sensitive_data: dict[str, str]) -> BaseModel:
		"""Replaces the sensitive data in the params"""
		# if there are any str with <secret>placeholder</secret> in the params, replace them with the actual value from sensitive_data

		import re

		secret_pattern = re.compile(r'<secret>(.*?)</secret>')

		def replace_secrets(value):
			if isinstance(value, str):
				matches = secret_pattern.findall(value)
				for placeholder in matches:
					if placeholder in sensitive_data:
						value = value.replace(f'<secret>{placeholder}</secret>', sensitive_data[placeholder])
				return value
			elif isinstance(value, dict):
				return {k: replace_secrets(v) for k, v in value.items()}
			elif isinstance(value, list):
				return [replace_secrets(v) for v in value]
			return value

		params_dump = params.model_dump()
		processed_params = replace_secrets(params_dump)
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
