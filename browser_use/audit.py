"""Agent(audit_log='audit.jsonl'): one JSON line per run_start, action, outcome and run_end, hash-chained.

Each line carries `seq` (0, 1, 2, ... within its run) and `prev`: the sha256 hex of the previous line of the same run,
its exact bytes without the newline (the run's first line: sha256 of its run_id). Deleting, reordering or editing a line
breaks the chain at the next line; verify(path) finds it. Runs, follow-ups and Agents writing one file each keep their
own chain, so their lines may interleave.

What a line never holds: secret values (sensitive_data, redacted again here) and page text: an outcome records the
output's length and sha256, not the output (audit logs are kept for years; page text holds personal data).
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # imported where used: browser_use.agent imports this module
	from browser_use.agent.hooks import Action, ActionOutcome, AfterAction, BeforeAction
	from browser_use.agent.views import AgentHistoryList

logger = logging.getLogger(__name__)

AuditSink = str | os.PathLike[str] | Callable[[dict[str, Any]], Any]

__all__ = ['AuditSink', 'verify']


def check_sink(sink: Any, metadata: Any) -> None:
	"""Agent(audit_log=, audit_metadata=) errors, raised before any browser starts."""
	if sink is not None and not isinstance(sink, (str, os.PathLike)) and not callable(sink):
		raise TypeError(f'audit_log must be a file path, a function taking a dict, or None, not {type(sink).__name__}')
	if metadata is None:
		return
	if sink is None:
		raise ValueError('audit_metadata is written to the audit log: pass audit_log=... too')
	if not isinstance(metadata, dict):
		raise TypeError(f'audit_metadata must be a dict, not {type(metadata).__name__}')
	try:
		json.dumps(metadata)
	except (TypeError, ValueError) as e:
		raise TypeError(f'audit_metadata must be JSON-serializable: {e}') from e


def _sha(data: bytes) -> str:
	return hashlib.sha256(data).hexdigest()


class AuditRun:
	"""The audit chain of one run(). write() raises when the line cannot be written: callers decide what that means."""

	def __init__(self, sink: AuditSink, run_id: str, forms: list[tuple[str, str]]):
		self.run_id, self.forms = run_id, forms
		self.seq, self.prev = 0, _sha(run_id.encode())
		self.lock = asyncio.Lock()  # an async sink awaits mid-line: two parallel tool calls must not share a seq
		self.fn = sink if callable(sink) else None
		self.fd: int | None = None
		if not callable(sink):  # opened here, before any browser: an unwritable path fails the run up front
			path = Path(sink).expanduser()
			path.parent.mkdir(parents=True, exist_ok=True)
			self.fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)  # audit lines name hosts and code

	async def write(self, kind: str, **fields: Any) -> None:
		from browser_use.repl.session import redact_forms

		async with self.lock:
			ts = datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
			event = {'seq': self.seq, 'prev': self.prev, 'run_id': self.run_id, 'ts': ts, 'type': kind}
			event |= redact_forms(fields, self.forms)  # the hooks' values are redacted already; errors and metadata may not be
			# ASCII-only JSON: the bytes a verifier hashes are the same on every platform and encoding
			line = json.dumps(event, ensure_ascii=True, separators=(',', ':'), default=str).encode()
			if self.fn is not None:
				result = self.fn(json.loads(line))  # plain JSON: json.dumps(event, separators=(',', ':')) is the line again
				if inspect.isawaitable(result):
					await result
			elif self.fd is not None:
				os.write(self.fd, line + b'\n')  # one write per line on an O_APPEND file: concurrent writers never split one
			else:
				raise OSError('the audit log is closed')
			self.seq, self.prev = self.seq + 1, _sha(line)

	def close(self) -> None:
		if self.fd is not None:
			fd, self.fd = self.fd, None
			try:
				os.fsync(fd)  # run_end is on disk before run() returns
			finally:
				os.close(fd)

	def hooks(self, before: BeforeAction | None, after: AfterAction | None) -> tuple[BeforeAction, AfterAction]:
		"""The user's hooks, wrapped: the action line records the final decision (theirs), the outcome line what ran.
		An action whose line cannot be written is refused (fail closed: nothing runs unrecorded)."""
		from browser_use.agent.hooks import decide, observe

		async def audited_before(action: Action) -> str | None:
			why = await decide(before, action) if before else None
			try:
				await self.write(
					'action',
					step=action.step,
					tool=action.tool,
					args=action.args,
					host=action.host,
					decision='refused' if why else 'allowed',
					reason=why,
				)
			except Exception as e:
				logger.error(f'audit_log: could not write step {action.step}: {type(e).__name__}: {e}; not run')
				return f'the audit log could not be written ({type(e).__name__})'
			return why

		async def audited_after(outcome: ActionOutcome) -> None:
			if after:
				await observe(after, outcome)
			if outcome.refused is not None:  # a refused action's line already says so; nothing ran
				return
			output = outcome.output.encode('utf-8', 'surrogatepass')
			try:
				await self.write(
					'outcome',
					step=outcome.action.step,
					tool=outcome.action.tool,
					error=outcome.error,
					urls=outcome.urls,
					duration_s=round(outcome.duration_s, 3),
					output_chars=len(outcome.output),
					output_sha256=_sha(output),
				)
			except Exception as e:  # it already ran, so the run goes on; the log lacks this one outcome
				logger.error(f'audit_log: could not write the outcome of step {outcome.action.step}: {type(e).__name__}: {e}')

		return audited_before, audited_after

	async def end(self, result: AgentHistoryList | None, error_type: str | None) -> None:
		"""run_end, then fsync. Never raises: the run already happened, and its result must reach the caller."""
		try:
			if result is not None:
				fields = {'status': result.status, 'steps': result.steps, 'cost_usd': result.cost_usd}
				fields |= {'success': result.success, 'error': result.error}
			else:  # run() raised: cancelled, or an error before a result existed
				status = 'cancelled' if error_type == 'CancelledError' else 'error'
				fields = {'status': status, 'steps': None, 'cost_usd': None, 'success': None, 'error': error_type}
			await self.write('run_end', **fields)
		except Exception as e:
			logger.error(f'audit_log: could not write run_end: {type(e).__name__}: {e}')
		finally:
			try:
				self.close()
			except OSError as e:
				logger.error(f'audit_log: could not sync the file: {e}')


def verify(path: str | os.PathLike[str]) -> list[str]:
	"""The problems in an audit log; empty when every run's chain is intact and ended.

	Finds a line deleted, edited, reordered or cut off, and a run without run_end (still running, killed, or its tail
	deleted). Not found: a whole run deleted, the last line of a run edited, or every line after an edit rewritten with
	new hashes; ship the lines off the machine as they are written (audit_log=a function) for that."""
	problems: list[str] = []
	runs: dict[str, tuple[int, str, int]] = {}  # run_id -> (next seq, sha256 of its last line, line number)
	ended: set[str] = set()
	data = Path(path).read_bytes()
	lines = data.split(b'\n')
	if lines[-1]:
		problems.append(f'line {len(lines)}: no newline at the end (cut off while being written)')
	for n, line in enumerate(lines[:-1] if not lines[-1] else lines, 1):
		try:
			event = json.loads(line)
			run_id, seq, prev, kind = event['run_id'], event['seq'], event['prev'], event['type']
			if not isinstance(run_id, str) or type(seq) is not int:
				raise TypeError
		except (ValueError, KeyError, TypeError):
			problems.append(f'line {n}: not an audit line')
			continue
		expected_seq, expected_prev, last = runs.get(run_id, (0, _sha(run_id.encode()), 0))
		where = f'line {n} (run {run_id}, seq {seq})'
		if seq != expected_seq:
			problems.append(f'{where}: expected seq {expected_seq}: a line before it is missing or out of order')
		if prev != expected_prev:
			after = f'line {last}' if last else 'the run_id'
			problems.append(f'{where}: prev does not match {after}: a line was edited, deleted or reordered')
		if seq == 0 and kind != 'run_start':
			problems.append(f'{where}: the run does not start with run_start')
		if run_id in ended:
			problems.append(f'{where}: written after run_end')
		if kind == 'run_end':
			ended.add(run_id)
		runs[run_id] = (seq + 1, _sha(line), n)
	problems += [
		f'run {run_id}: no run_end (still running, killed, or its last lines deleted)' for run_id in runs if run_id not in ended
	]
	return problems
