"""Agent(before_action=..., after_action=...): see every action before it runs, refuse it, and see what it did.

An action is one tool call: a Python cell (`tool == 'python'`, the code in `action.code`), finish_from_repl (it evaluates
a Python expression in the REPL, also in `action.code`) or one of your own `Tools` actions. finish is not one.
before_action decides; after_action observes. Both may be plain functions or coroutines.

before_action returns:
  None or True          run it
  False                 refuse it; the model reads "Not run: refused by before_action."
  a non-empty str       refuse it; the model reads "Not run: <your reason>." and can choose another way
  raises                refuse it (fail closed); the model reads the exception class and message

Secret values (sensitive_data) are replaced with `<secret:name>` in what the hooks receive, as in the cell output.
A guard for what the agent does through browser-use, not a sandbox: see MIGRATING.md "Action hooks".

Agent(approve=..., approve_on=...) asks about effects instead of code: an upload, typing a secret, the first visit to
an origin. The REPL helpers stop at the effect and wait while this process asks approve() (Approvals); a denial raises
PermissionError in the cell with the reason. See MIGRATING.md "Approvals".
"""

from __future__ import annotations

import asyncio
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
	tool: str  # 'python' for a cell, 'finish_from_repl', else the name of your Tools action
	# {'code': ...} for a cell, {'expression': ...} for finish_from_repl, else the action's arguments; secrets redacted
	args: dict[str, Any]
	task: str  # the task this run works on (a follow-up's own task), secret values redacted
	host: str | None  # the hostname the agent's last cell was on; None before the first navigation

	@property
	def code(self) -> str | None:
		"""The Python this action runs: a cell's code, or the expression finish_from_repl evaluates; None for a Tools
		action."""
		key = {'python': 'code', 'finish_from_repl': 'expression'}.get(self.tool)
		return self.args.get(key) if key else None


@dataclass(frozen=True)
class ActionOutcome:
	"""What an action did, after it ran or was refused."""

	action: Action
	refused: str | None  # the reason when before_action refused it; then nothing ran
	output: str  # what the model reads back (cell output, or the action's result as text); secret values redacted
	error: str | None  # the cell's or the tool's error (a Tools action's ModelRetry too), None when it ran clean
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


APPROVE_KINDS = ('upload', 'type_secret', 'new_origin')
DEFAULT_APPROVE_ON = frozenset({'upload', 'type_secret'})  # new_origin is off: every new site would ask
APPROVE_TIMEOUT_S = 900.0  # an approval not given by then is a denial; the run's own timeout keeps counting meanwhile


@dataclass(frozen=True)
class ApprovalRequest:
	"""One effect the agent is about to cause, asked before it happens."""

	kind: str  # 'upload', 'type_secret' or 'new_origin'
	# upload: {'files': [absolute paths], 'origin'}; type_secret: {'secret': name (never the value), 'origin'};
	# new_origin: {'origin', 'url'}. origin is the page's 'https://host[:port]', None when unknown
	detail: dict[str, Any]
	step: int  # the model request whose cell caused it
	task: str  # this run's task, secret values redacted

	@property
	def message(self) -> str:
		"""The question for a human, as the Codex browser plugin asks it: 'Allow upload of a.pdf to https://x.com?'"""
		d, where = self.detail, self.detail.get('origin') or 'an unknown page'
		if self.kind == 'upload':
			names = ', '.join(str(f).replace('\\', '/').rsplit('/', 1)[-1] for f in d.get('files') or [])
			return f'Allow upload of {names or "files"} to {where}?'
		if self.kind == 'type_secret':
			return f'Allow typing the secret {d.get("secret")!r} into {where}?'
		return f'Allow access to {where}?'


Approve = Callable[[ApprovalRequest], bool | str | Awaitable[bool | str]]


def check_approve(approve: Any, approve_on: Any) -> frozenset[str]:
	"""The kinds approve() is asked about. Raises before any browser starts."""
	check_hook(approve, 'approve')
	if approve_on is None:
		return DEFAULT_APPROVE_ON if approve else frozenset()
	if approve is None:
		raise TypeError('approve_on needs approve=: the function that decides')
	kinds = frozenset([approve_on] if isinstance(approve_on, str) else approve_on)
	if unknown := sorted(kinds - set(APPROVE_KINDS)):
		raise ValueError(f'approve_on: unknown kind {", ".join(map(repr, unknown))}; the kinds are {", ".join(APPROVE_KINDS)}')
	return kinds


class Approvals:
	"""One run's approvals: asks approve() and remembers what it allowed per (kind, origin), per secret for
	type_secret and per files for upload (the human approved cv.pdf, not every file). Denials, and anything on a page
	whose origin is unknown, are not remembered: the next attempt asks again."""

	def __init__(self, approve: Approve, task: str):
		self.approve, self.task = approve, task
		self.step = 0  # the step of the cell running now (loop.python)
		self.allowed: set[tuple] = set()

	async def ask(self, kind: str, detail: dict[str, Any]) -> str | None:
		"""None when allowed, else the text the cell's PermissionError carries. Fails closed: a raise, a timeout or
		any answer but True or a reason denies."""
		key = (kind, detail.get('origin'), detail.get('secret'), tuple(detail.get('files') or ()))
		if key in self.allowed:
			return None
		request = ApprovalRequest(kind, detail, self.step, self.task)
		try:  # a plain function runs in a thread: it may block on a human while the run's event loop goes on
			value = await asyncio.wait_for(_call_blocking(self.approve, request), APPROVE_TIMEOUT_S)
		except TimeoutError:
			value = f'no answer within {APPROVE_TIMEOUT_S:g} s'
		except Exception as e:
			value = f'approve raised {type(e).__name__}: {e}'
		if value is True:
			if key[1] is not None:
				self.allowed.add(key)
			return None
		why = value.strip() if isinstance(value, str) and value.strip() else 'denied'
		logger.info(f'step {request.step}: {request.message} {why}')
		what = request.message.removeprefix('Allow ').rstrip('?')
		return f'Not allowed: {what} was denied ({why}). Nothing was done. Do not try to get around it.'


async def _call_blocking(fn: Callable[..., Any], arg: Any) -> Any:
	if inspect.iscoroutinefunction(fn):
		return await fn(arg)
	result = await asyncio.to_thread(fn, arg)
	return await result if inspect.isawaitable(result) else result
