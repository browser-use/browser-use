"""Tools — backward-compatible re-exports.

The actual implementations live in:
  - browser_use.tools.base          → BaseToolset
  - browser_use.tools.browser_toolset → BrowserToolset (built-in actions)
  - browser_use.tools.custom_toolset → CustomToolset (user-defined actions)
"""

import logging
import math
import os
from typing import TypeVar

from pydantic import BaseModel

from browser_use.tools.base import BaseToolset
from browser_use.tools.browser_toolset import BrowserToolset
from browser_use.tools.custom_toolset import CustomToolset

logger = logging.getLogger(__name__)

# ── Env-var timeout (kept here for test imports) ──────────────────────

_ACTION_TIMEOUT_FALLBACK_S = 180.0


def _parse_env_action_timeout(raw: str | None) -> float:
	"""Parse BROWSER_USE_ACTION_TIMEOUT_S defensively.

	Accepts only finite positive values. Empty, non-numeric, inf, nan, or
	non-positive values fall back to the hardcoded default with a warning
	— these would otherwise make every action time out immediately (nan)
	or disable the hang guard entirely (inf / negative / zero).
	"""
	if raw is None or raw == '':
		return _ACTION_TIMEOUT_FALLBACK_S
	try:
		parsed = float(raw)
	except ValueError:
		logger.warning(
			'Invalid BROWSER_USE_ACTION_TIMEOUT_S=%r; falling back to %.0fs',
			raw,
			_ACTION_TIMEOUT_FALLBACK_S,
		)
		return _ACTION_TIMEOUT_FALLBACK_S
	if not math.isfinite(parsed) or parsed <= 0:
		logger.warning(
			'BROWSER_USE_ACTION_TIMEOUT_S=%r is not a finite positive number; falling back to %.0fs',
			raw,
			_ACTION_TIMEOUT_FALLBACK_S,
		)
		return _ACTION_TIMEOUT_FALLBACK_S
	return parsed


_DEFAULT_ACTION_TIMEOUT_S = _parse_env_action_timeout(os.getenv('BROWSER_USE_ACTION_TIMEOUT_S'))

# ── Backward-compatible aliases ───────────────────────────────────────


Context = TypeVar('Context')
T = TypeVar('T', bound=BaseModel)


class Tools(BaseToolset[Context]):
	"""The default tool collection — combines built-in browser actions
	with the ``action`` decorator for user-defined custom actions.

	Composes a :class:`BrowserToolset` (``.browser``) and a
	:class:`CustomToolset` (``.custom``), sharing one registry so both
	built-in and custom actions are available to the Agent.

	Usage::

	    tools = Tools()


	    # Register a custom action (two equivalent ways):
	    @tools.action('Describe your action')
	    async def my_action(params: MyParams, browser_session: BrowserSession) -> ActionResult: ...


	    @tools.custom.action('Another action')
	    async def another_action(params: MyOtherParams, browser_session: BrowserSession) -> ActionResult: ...
	"""

	def __init__(
		self,
		exclude_actions: list[str] | None = None,
		output_model: type[T] | None = None,
		display_files_in_done_text: bool = True,
	):
		super().__init__(exclude_actions=exclude_actions, default_action_timeout=_DEFAULT_ACTION_TIMEOUT_S)

		# Compose built-in browser actions via BrowserToolset
		self.browser = BrowserToolset(
			exclude_actions=exclude_actions,
			output_model=output_model,
			display_files_in_done_text=display_files_in_done_text,
		)
		self.custom = CustomToolset()
		# Point our registry at the browser's registry so @tools.action() and
		# runtime action lookups share one source of truth.
		self.registry = self.browser.registry
		self.custom.registry = self.registry

		# Mirror state
		self.display_files_in_done_text = self.browser.display_files_in_done_text

	def get_output_model(self) -> type[BaseModel] | None:
		"""Delegate to the live BrowserToolset so use_structured_output_action is reflected."""
		return self.browser.get_output_model()

	def __getattr__(self, name: str):
		"""Enable direct action calls through the internal BrowserToolset."""
		return getattr(self.browser, name)


# Backward-compatible alias
Controller = Tools
