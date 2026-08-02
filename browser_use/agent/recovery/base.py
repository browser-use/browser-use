"""Recovery framework — contracts, data models and shared helpers.

Recovery is a deterministic, pluggable layer that repairs browser-agent
failures before they are escalated back to the planner LLM. Strategies
follow the Strategy pattern: the engine only knows about the
``RecoveryStrategy`` interface, so single strategies and composite chains
are interchangeable.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from browser_use.agent.views import ActionResult
from browser_use.browser.views import BrowserStateSummary
from browser_use.tools.registry.views import ActionModel

if TYPE_CHECKING:
	from browser_use.agent.service import Agent
	from browser_use.browser.session import BrowserSession

logger = logging.getLogger(__name__)


class RecoveryPhase(str, enum.Enum):
	"""Execution phase a strategy operates in.

	Phases are ordered from most to least disruptive so the engine can
	repair the environment before touching elements or retrying actions.
	"""

	ENVIRONMENT = 'environment'
	PAGE = 'page'
	ELEMENT = 'element'
	ACTION = 'action'
	RETRY = 'retry'


class RecoveryCost(str, enum.Enum):
	"""Relative cost and risk of a strategy, from cheapest to most disruptive."""

	LOW = 'low'
	MEDIUM = 'medium'
	HIGH = 'high'


class RecoveryOutcome(str, enum.Enum):
	"""Result of a recovery attempt.

	- SUCCESS: the failure was repaired; the action is ready to re-run.
	- RETRY:  a recovery action was prepared; re-run the (possibly updated) action.
	- GIVE_UP: recovery cannot repair this; hand the error back to the LLM.
	- ESCALATE: the failure is severe (e.g. browser crash) and should surface
	  to the pipeline immediately.
	"""

	SUCCESS = 'success'
	RETRY = 'retry'
	GIVE_UP = 'give_up'
	ESCALATE = 'escalate'


class ActionKind(str, enum.Enum):
	"""Capability filter — which action categories a strategy applies to."""

	NAVIGATE = 'navigate'
	CLICK = 'click'
	TYPE = 'type'
	SCROLL = 'scroll'
	EXTRACT = 'extract'
	DOWNLOAD = 'download'
	UPLOAD = 'upload'
	DONE = 'done'
	OTHER = 'other'


#: Action names that map to each capability bucket.
_ACTION_KIND_MAP: dict[ActionKind, set[str]] = {
	ActionKind.NAVIGATE: {'navigate', 'search', 'go_back', 'switch', 'open_tab', 'close_tab', 'close'},
	ActionKind.CLICK: {'click', 'select_dropdown', 'dropdown_options'},
	ActionKind.TYPE: {'input', 'send_keys'},
	ActionKind.SCROLL: {'scroll', 'find_text'},
	ActionKind.EXTRACT: {'extract', 'find_elements', 'search_page', 'screenshot', 'save_as_pdf', 'evaluate'},
	ActionKind.DOWNLOAD: {'download_file'},
	ActionKind.UPLOAD: {'upload_file'},
	ActionKind.DONE: {'done'},
}


def infer_action_kind(action: ActionModel) -> ActionKind:
	"""Infer the capability bucket of an action from its registered name."""
	action_data = action.model_dump(exclude_unset=True)
	name = next(iter(action_data), 'unknown')
	for kind, names in _ACTION_KIND_MAP.items():
		if name in names:
			return kind
	return ActionKind.OTHER


class RecoveryContext:
	"""Everything a strategy needs to inspect and act.

	The context is created per failed action and mutated across attempts so
	strategies can track per-strategy retry counts and compare page state
	before/after a recovery action.
	"""

	def __init__(
		self,
		agent: Agent,
		action: ActionModel,
		action_name: str,
		failed_result: ActionResult,
		browser_state: BrowserStateSummary | None,
		attempts: dict[str, int] | None = None,
		step_id: int | None = None,
		page_hash_before: str | None = None,
		page_hash_after: str | None = None,
		screenshot_hash_before: str | None = None,
		screenshot_hash_after: str | None = None,
	) -> None:
		self.agent = agent
		self.action = action
		self.action_name = action_name
		self.action_kind = infer_action_kind(action)
		self.failed_result = failed_result
		self.browser_state = browser_state
		self.attempts: dict[str, int] = attempts or {}
		self.step_id = step_id
		self.page_hash_before = page_hash_before
		self.page_hash_after = page_hash_after
		self.screenshot_hash_before = screenshot_hash_before
		self.screenshot_hash_after = screenshot_hash_after

	@property
	def error(self) -> str:
		"""Lowercased error message from the failed result."""
		return (self.failed_result.error or '').lower()

	@property
	def browser_session(self) -> BrowserSession | None:
		return self.agent.browser_session

	@staticmethod
	def page_hash(state: BrowserStateSummary | None) -> str | None:
		"""A lightweight fingerprint of the current page (URL + element count)."""
		if state is None:
			return None
		element_count = len(state.dom_state.selector_map) if state.dom_state else 0
		return f'{state.url}|{state.title}|{element_count}'


class RecoveryResult(BaseModel):
	"""Outcome of a recovery attempt, including the chain and metadata."""

	outcome: RecoveryOutcome
	strategy: str | None = None
	chain: list[str] = field(default_factory=list)
	attempts: int = 0
	retry_action: ActionModel | None = None
	reason: str | None = None
	explanation: str | None = None


class RecoveryStrategy:
	"""Base class for all recovery strategies.

	Subclasses declare their phase, cost and capabilities, implement
	``can_handle`` to decide when they apply, and ``recover`` to perform the
	repair. Strategies must never call the LLM — they only do deterministic
	work (waiting, scrolling, relocating, reconnecting).
	"""

	name: str = 'base'
	phase: RecoveryPhase = RecoveryPhase.ACTION
	cost: RecoveryCost = RecoveryCost.LOW
	destructive: bool = False
	max_attempts: int = 2
	#: Capability filter; ``None`` means the strategy applies to every action kind.
	supports: set[ActionKind] | None = None

	def can_handle(self, ctx: RecoveryContext) -> bool:
		"""Return True when this strategy applies to the current failure."""
		return False

	async def recover(self, ctx: RecoveryContext) -> RecoveryResult:
		"""Repair the failure and return a decision."""
		raise NotImplementedError

	def explain(self, ctx: RecoveryContext) -> str:
		"""Human-readable reason recorded in history/telemetry."""
		return f'{self.name}: {ctx.error or "unknown failure"}'

	async def run_action(self, ctx: RecoveryContext, action: ActionModel) -> ActionResult:
		"""Execute an action through the same entry point as the main loop."""
		session = ctx.browser_session
		return await ctx.agent.tools.act(
			action=action,
			browser_session=session,
			file_system=ctx.agent.file_system,
			page_extraction_llm=ctx.agent.settings.page_extraction_llm,
			sensitive_data=ctx.agent.sensitive_data,
			available_file_paths=ctx.agent.available_file_paths,
			extraction_schema=ctx.agent.extraction_schema,
		)

	async def run_registered_action(
		self, ctx: RecoveryContext, action_name: str, params: dict[str, Any] | None = None
	) -> ActionResult:
		"""Execute a registered action by name with plain params."""
		session = ctx.browser_session
		return await ctx.agent.tools.registry.execute_action(
			action_name=action_name,
			params=params or {},
			browser_session=session,
			page_extraction_llm=ctx.agent.settings.page_extraction_llm,
			file_system=ctx.agent.file_system,
			sensitive_data=ctx.agent.sensitive_data,
			available_file_paths=ctx.agent.available_file_paths,
			extraction_schema=ctx.agent.extraction_schema,
		)
