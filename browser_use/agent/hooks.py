"""Agent(before_action=..., after_action=...): see every action before it runs, refuse it, and see what it did.

An action is one tool call: a Python cell (`tool == 'python'`, the code in `action.code`) or one of your own `Tools`
actions. before_action decides; after_action observes. Both may be plain functions or coroutines.

before_action returns:
  None or True          run it
  False                 refuse it; the model reads "Not run: refused by before_action."
  a non-empty str       refuse it; the model reads "Not run: <your reason>." and can choose another way
  raises                refuse it (fail closed); the model reads the exception class and message

Secret values (sensitive_data) are replaced with `<secret:name>` in what the hooks receive, as in the cell output.
A guard for what the agent does through browser-use, not a sandbox: see MIGRATING.md "Action hooks".
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Action:
	"""One tool call the model asked for, before it runs."""

	step: int  # the model request that asked for it (1-based, as result.steps counts)
	tool: str  # 'python' for a cell, else the name of your Tools action
	args: dict[str, Any]  # {'code': ...} for a cell, else the action's arguments; secret values redacted
	task: str  # the task this run works on (a follow-up's own task), secret values redacted
	host: str | None  # the hostname the agent's last cell was on; None before the first navigation

	@property
	def code(self) -> str | None:
		"""The cell's Python; None for a Tools action."""
		return self.args.get('code') if self.tool == 'python' else None


@dataclass(frozen=True)
class ActionOutcome:
	"""What an action did, after it ran or was refused."""

	action: Action
	refused: str | None  # the reason when before_action refused it; then nothing ran
	output: str  # what the model reads back (cell output, or the action's result as text); secret values redacted
	error: str | None  # the cell's error, None when it ran clean
	urls: list[str] = field(default_factory=list)  # the cell's navigations in order, full URLs (no #fragment), at most 50
	duration_s: float = 0.0


Decision = bool | str | None
BeforeAction = Callable[[Action], Decision | Awaitable[Decision]]
AfterAction = Callable[[ActionOutcome], None | Awaitable[None]]


def check_hook(value: Any, name: str) -> None:
	if value is not None and not callable(value):
		raise TypeError(f'{name} must be a function (sync or async) or None, not {type(value).__name__}')


async def _call(fn: Callable[..., Any], arg: Any) -> Any:
	result = fn(arg)
	if inspect.isawaitable(result):
		result = await result
	return result


async def decide(before: BeforeAction, action: Action) -> str | None:
	"""None to run the action, else the reason the model reads. Fails closed: a hook that raises or returns something
	other than None/bool/str refuses the action."""
	try:
		value = await _call(before, action)
	except Exception as e:
		logger.warning(f'before_action raised {type(e).__name__}: {e}; step {action.step} was not run')
		return f'refused: before_action raised {type(e).__name__}: {e}'
	if value is None or value is True:
		return None
	if value is False:
		return 'refused by before_action'
	if isinstance(value, str) and value.strip():
		return value.strip()
	logger.warning(f'before_action returned {value!r}; step {action.step} was not run (return None/True to run it)')
	return 'refused by before_action'


async def observe(after: AfterAction, outcome: ActionOutcome) -> None:
	"""after_action never changes the run: an exception it raises is logged, not raised."""
	try:
		await _call(after, outcome)
	except Exception as e:
		logger.warning(f'after_action raised {type(e).__name__}: {e} (ignored)')


def refusal(reason: str) -> str:
	return f'Not run: {reason.rstrip(".")}. Do not try to get around it.'
