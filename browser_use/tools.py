"""Custom actions: plain functions the model can call as tools, next to its Python REPL.

tools = Tools()

@tools.action('Look up the internal price of a product')
def get_price(sku: str) -> str:
    return prices[sku]

Agent(task, tools=tools)
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_ai import Tool

from browser_use.exceptions import removed

RESERVED = {'python', 'finish', 'finish_from_repl'}
# Retries of one tool's rejected calls (invalid or truncated arguments, ModelRetry). bu-pi returns the error and goes on;
# max_steps bounds it. A budget of 1 ended the run on two bad python calls in a row (a truncated cell, a JSON slip).
TOOL_RETRIES = 1_000_000
TOOL_NAME = re.compile(r'[a-zA-Z0-9_-]{1,64}')  # what OpenAI, Anthropic and Google accept
# 0.13.14 injected these into actions (registry _get_special_param_types); any other name, `page` or `browser` too,
# came from the model and still does. 1.0 actions get only what the model passes; the model drives the browser in Python.
INJECTED = {
	'browser_session',
	'context',
	'cdp_client',
	'page_url',
	'page_extraction_llm',
	'file_system',
	'available_file_paths',
	'has_sensitive_data',
	'extraction_schema',
}


class RemovedField(TypeError):
	"""A 0.x ActionResult field 1.0 dropped. It ends the run (never handed to the model as a tool error), so the
	developer sees it."""


REMOVED_FIELDS = {  # 0.x ActionResult fields -> the 1.0 alternative
	'is_done': 'the model ends the run with finish.',
	'success': 'the model may give a verdict in finish(..., success=...); result.success holds it (None when omitted).',
	'include_in_memory': 'every action result stays in the conversation.',
	'attachments': 'save files in the workspace; files the agent wrote there are delivered.',
}


class ActionResult(BaseModel):
	"""0.x return type, kept so existing actions run. The model sees it as JSON."""

	model_config = ConfigDict(extra='allow')

	extracted_content: str | None = None
	error: str | None = None

	@model_validator(mode='before')
	@classmethod
	def _no_removed_fields(cls, data: Any) -> Any:
		if isinstance(data, dict) and (name := next((k for k in data if k in REMOVED_FIELDS), None)):
			raise RemovedField(removed(f'ActionResult({name}=...)', REMOVED_FIELDS[name]))
		return data


TOOLS_REMOVED = {  # 0.x Tools(...) / Controller(...) arguments -> the 1.0 alternative
	'exclude_actions': 'there are no built-in actions to exclude: the model acts in Python.',
	'output_model': 'Agent(output_model_schema=...).',
	'display_files_in_done_text': '',
}


class Tools:
	def __init__(self, **kwargs: Any) -> None:
		if kwargs:
			name = next(iter(kwargs))
			if name not in TOOLS_REMOVED:
				raise TypeError(f'Tools({name}=...) is not a browser-use 1.0 option; see MIGRATING.md.')
			raise TypeError(removed(f'Tools({name}=...)', TOOLS_REMOVED[name]))
		self.functions: list[Tool] = []

	@property
	def registry(self) -> Tools:  # 0.x: @controller.registry.action(...)
		return self

	def action(
		self,
		description: str = '',
		param_model: type[BaseModel] | None = None,
		domains: list[str] | None = None,
		allowed_domains: list[str] | None = None,
		**kwargs: Any,
	) -> Callable[[Callable], Callable]:
		if callable(description):  # @tools.action without parentheses registered nothing
			raise TypeError("Use @tools.action('what the action does') with parentheses; @tools.action alone registers nothing")
		if domains or allowed_domains:
			name = 'domains' if domains else 'allowed_domains'
			raise TypeError(
				removed(f'@tools.action({name}=...)', 'Browser(allowed_domains=...) limits where the whole browser navigates.')
			)
		if kwargs:
			raise TypeError(f'@tools.action({next(iter(kwargs))}=...) is not a browser-use 1.0 option; see MIGRATING.md.')

		def decorator(fn: Callable) -> Callable:
			params = list(inspect.signature(fn).parameters)
			injected = [p for p in params if p in INJECTED]
			if injected:
				raise TypeError(
					removed(
						f'Injecting {", ".join(injected)} into @tools.action {fn.__name__}()',
						'actions get only the arguments the model passes; the model drives the browser itself in Python.',
					)
				)
			if fn.__name__ in RESERVED:
				raise ValueError(f'@tools.action: {fn.__name__!r} is a built-in tool name; rename the function')
			if not TOOL_NAME.fullmatch(fn.__name__):  # a lambda ('<lambda>') failed only at the provider, with a 400
				raise ValueError(
					f'@tools.action: {fn.__name__!r} is not a valid tool name (letters, digits, _ and -, at most 64); use a '
					'named function'
				)
			if param_model is not None and params:  # 0.x: def action(params, ...) with param_model=Model; it wins
				fn.__annotations__[params[0]] = param_model
			self.functions.append(
				Tool(fn, takes_ctx=False, name=fn.__name__, description=description or None, max_retries=TOOL_RETRIES)
			)
			return fn

		return decorator


Controller = Tools  # 0.x alias
