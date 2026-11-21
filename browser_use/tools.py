"""Custom actions: plain functions the model can call as tools, next to its Python REPL.

tools = Tools()

@tools.action('Look up the internal price of a product')
def get_price(sku: str) -> str:
    return prices[sku]

Agent(task, tools=tools)
"""

from __future__ import annotations

import ast
import inspect
import logging
import re
import textwrap
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_ai import Tool

from browser_use.dacs import wrap_action_with_dacs
from browser_use.exceptions import removed

logger = logging.getLogger(__name__)
# 0.x's browser_use.tools was a package (tools.service, tools.registry.views, ...): an empty __path__ lets those imports
# reach the 0.x import hook (browser_use/legacy.py), which names Tools; without it Python stops at "not a package"
__path__: list[str] = []
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
	# kept as an extra field it reached the model as JSON text: base64 image data in the conversation, never an image
	'images': 'return text; the agent takes screenshots itself (screenshot()).',
	'success': 'the model may give a verdict in finish(..., success=...); result.success holds it (None when omitted).',
	'attachments': 'save files in the workspace; files the agent wrote there are delivered.',
}
# Ignored with a warning, never raised: an action runs after the browser started (and a cloud browser is billed), and
# 1.0 keeps every result in the conversation anyway
IGNORED_FIELDS: dict[str, str] = dict.fromkeys(
	('include_in_memory', 'include_extracted_content_only_once'), 'every action result stays in the conversation.'
)
_warned: set[str] = set()


class ActionResult(BaseModel):
	"""0.x return type, kept so existing actions run. The model sees it as JSON."""

	model_config = ConfigDict(extra='allow')

	extracted_content: str | None = None
	error: str | None = None

	@model_validator(mode='before')
	@classmethod
	def _no_removed_fields(cls, data: Any) -> Any:
		if isinstance(data, dict):
			data = _without_0x_defaults(data)
		if isinstance(data, dict) and (name := next((k for k in data if k in REMOVED_FIELDS), None)):
			raise RemovedField(removed(f'ActionResult({name}=...)', REMOVED_FIELDS[name]))
		if isinstance(data, dict) and (names := [k for k in data if k in IGNORED_FIELDS]):
			for name in names:  # every one: an ignored field left in reached the model as JSON
				if name not in _warned:  # once: an action returns it on every call
					_warned.add(name)
					logger.warning(f'ActionResult({name}=...) is ignored in browser-use 1.0: {IGNORED_FIELDS[name]}')
			data = {k: v for k, v in data.items() if k not in IGNORED_FIELDS}
		return data


def _without_0x_defaults(data: dict) -> dict:
	"""0.x actions often spelled out the defaults: ActionResult(extracted_content=..., is_done=False, success=True). Those
	changed nothing in 0.x (success counted only with is_done=True), so they ended a billed run for no reason."""
	if data.get('is_done'):
		return data
	return {k: v for k, v in data.items() if not (
