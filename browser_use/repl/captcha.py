"""Browser Use Cloud captcha solver, seen from the REPL worker.

Our cloud browsers answer two custom CDP methods (BrowserUse.setCaptchaSolverEnabled {enabled},
BrowserUse.getCaptchaSolverEnabled) and broadcast BrowserUse.captchaSolverStarted {targetId, vendor, url, startedAt} and
BrowserUse.captchaSolverFinished {targetId, vendor, url, durationMs, finishedAt, success} on every connection, the
browser-harness daemon's included. The events are not replayed: they must be read as they come, so the worker reads the
daemon's event buffer continuously (EventPump, or ax.AxHelpers in ultrafast mode) and Captcha keeps the solver's state.
Any other browser rejects the methods: solve_captcha() then reports "solver unavailable".
A cell timeout kills the worker; the solver state is saved next to the cells, so the next worker still knows a running
solve.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

SOLVE_START_S = 20.0  # bu-pi solve_captcha: a solver that has not started by then found no captcha
SOLVE_S = 95.0  # bu-pi: then 'still solving'; fits the 120 s cell timeout
LOST_AFTER_S = 150.0  # bu-pi lostAfterMs: the solver gives up within 120 s; a solve open past this has no finish coming
EVENT_BUFFER = 500  # browser-harness daemon's own event buffer size
PUMP_INTERVAL_S = 0.025  # as ax.AxHelpers: a page-load burst must not fill the daemon's buffer between reads

STARTED, FINISHED = 'BrowserUse.captchaSolverStarted', 'BrowserUse.captchaSolverFinished'


class Captcha:
	"""Solver state from the started/finished events, and solve_captcha() for the agent."""

	def __init__(self, cdp: Callable[..., dict], path: Path | None = None, *, off: bool = False):
		"""path: where the state survives a worker restart within one Repl (which deletes it when it is created).
		off: Browser(captcha_solver=False): solve() never turns the solver on."""
		self.cdp, self.off = cdp, off
		self.turned_on = False  # solve() turned the solver on and left it on for a solve still running (saved)
		self._solving = False  # a solve() call is waiting: it turns the solver off itself
		self.pump: Callable[[], None] = lambda: None  # reads new daemon events into observe(); set by the worker
		self.active: dict[str, dict] = {}  # targetId -> started params + '_t' (monotonic start)
		self.finished: list[dict] = []  # every finished event's params, in order
		self.reported = 0  # finished events already shown in a cell's output
		self.shown = 0  # first finished event shown in the latest cell's output: solve() answers with it
		self.answered = 0  # finished events already returned by solve()
		self._lock = threading.Lock()
		self.path = path
		self._load()

	def _load(self) -> None:
		"""What a worker killed by a cell timeout knew: running solves and finishes it had not shown yet."""
		if not self.path or not self.path.exists():
			return
		try:
			saved = json.loads(self.path.read_text(encoding='utf-8'))
			ago = time.time() - time.monotonic()
			self.active = {str(t): {**a, '_t': a.pop('_wall') - ago} for t, a in saved['active'].items()}
			self.finished = list(saved['pending'])
			self.turned_on = bool(saved.get('turned_on'))
		except (OSError, ValueError, KeyError, TypeError, AttributeError):  # - unreadable: start empty
			self.active, self.finished = {}, []

	def _save(self) -> None:
		"""Hold _lock."""
		if not self.path:
			return
		ago = time.time() - time.monotonic()
		active = {t: {**{k: v for k, v in a.items() if k != '_t'}, '_wall': a['_t'] + ago} for t, a in self.active.items()}
		data = {'active': active, 'pending': self.finished[self.reported :], 'turned_on': self.turned_on}
		try:
			tmp = self.path.with_suffix('.tmp')
			tmp.write_text(json.dumps(data), encoding='utf-8')
			os.replace(tmp, self.path)
		except OSError:  # - state for a restart only; never fail a cell over it
			pass

	def observe(self, event: dict) -> None:
		method, params = event.get('method'), event.get('params') or {}
		if method not in (STARTED, FINISHED):
			return
		with self._lock:
			if method == STARTED:
				self.active[str(params.get('targetId', ''))] = {**params, '_t': time.monotonic()}
			else:
				self.active.pop(str(params.get('targetId', '')), None)
				self.finished.append(params)
			self._save()
		if method == FINISHED:
			self._release()

	def _release(self) -> None:
		"""Turn the solver off once the solves solve() left it on for have ended, without waiting for another solve()."""
		with self._lock:
			if not self.turned_on or self.active or self._solving:
				return
			self.turned_on = False
			self._save()
		try:
			self.cdp('BrowserUse.setCaptchaSolverEnabled', enabled=False)
		except Exception:  # - the browser is gone or restarting: nothing left to turn off
			pass

	def _prune(self) -> None:
		"""Close solves whose finished event will not come (tab closed, daemon restarted, event missed) as lost. Hold
		_lock."""
		now = time.monotonic()
		for target, a in list(self.active.items()):
			if now - a['_t'] > LOST_AFTER_S:
				del self.active[target]
				params = {k: v for k, v in a.items() if k != '_t'}
				self.finished.append({**params, 'success': False, 'lost': True, 'durationMs': (now - a['_t']) * 1000})
				self._save()

	def solve(self, start_timeout: float = SOLVE_START_S, timeout: float = SOLVE_S) -> dict:
		"""Wait for the browser's captcha solver: a solve that is running, or one it starts within start_timeout s.
		Waits until no solve runs on any tab; several solves: a failure is reported, not whichever finished last.
		Returns {'solved', 'detail', 'seconds'}: detail is 'solved', 'the solver failed', 'no result from the solver
		after 150s', 'still solving' (call again), 'the solver found no captcha on the page' or 'solver unavailable:
		...'. Turns the solver on if it was off,
		and off again afterwards unless a solve is still running."""
		began = time.monotonic()

		def out(solved: bool, detail: str, **extra) -> dict:
			return {'solved': solved, 'detail': detail, 'seconds': round(time.monotonic() - began, 1), **extra}

		if self.off:  # the user turned it off; turning it on would override that for the rest of the session
			return out(False, 'solver unavailable: Browser(captcha_solver=False) turned it off; handle the captcha yourself')
		try:
			# on only because an earlier solve() left it on for a running solve: still ours to turn off
			enabled = bool(self.cdp('BrowserUse.getCaptchaSolverEnabled').get('enabled'))
			was_on = enabled and not self.turned_on
			if not enabled:
				self.cdp('BrowserUse.setCaptchaSolverEnabled', enabled=True)
		except Exception as e:
			why = str(e) or type(e).__name__
			if "wasn't found" in why or '-32601' in why:  # Chrome: method not found
				why = 'this browser has no captcha solver (Browser Use Cloud browsers do)'
			return out(False, f'solver unavailable: {why[:300]}')
		keep_on, self._solving = was_on, True
		with self._lock:  # a solve that ended after the last cell's output, or that its notice showed, is the answer
			seen = max(self.shown, self.answered)
		try:
			while True:
				try:
					self.pump()
				except Exception:  # the daemon restarting: keep waiting on what the next read brings
					pass
				with self._lock:
					self._prune()
					done, started = self.finished[seen:], bool(self.active)
					if done and not started:
						self.answered = len(self.finished)
				if done and not started:
					if failed := next((f for f in done if not f.get('success')), None):
						lost = f'no result from the solver after {LOST_AFTER_S:.0f}s'
						return out(False, lost if failed.get('lost') else 'the solver failed')
					return out(True, 'solved')
				if time.monotonic() - began >= (timeout if started else start_timeout):
					if started:
						keep_on = True
						return out(False, 'still solving', next='call solve_captcha() again')
					return out(False, 'the solver found no captcha on the page')
				time.sleep(PUMP_INTERVAL_S)
		finally:
			with self._lock:
				self.turned_on, self._solving = keep_on and not was_on, False
				self._save()
			if not keep_on:
				try:
					self.cdp('BrowserUse.setCaptchaSolverEnabled', enabled=False)
				except Exception:
					pass

	def report(self) -> str:
		"""Lines for the cell's output: solves that ended since the last report, and a running one."""
		with self._lock:
			self._prune()
			self.shown = self.reported
			done, self.reported = self.finished[self.reported :], len(self.finished)
			active = list(self.active.values())
			if done:
				self._save()
		self._release()  # a solve closed as lost, or one that ended while the worker restarted
		lines = []
		for f in done:
			what, s = f.get('vendor') or 'captcha', round((f.get('durationMs') or 0) / 1000)
			lines.append(
				f'[captcha solver: solved {what} in {s}s]'
				if f.get('success')
				else f'[captcha solver: no result for {what} after {s}s; handle it yourself or find another route]'
				if f.get('lost')
				else f'[captcha solver: {what} stopped unsolved after {s}s; handle it yourself or find another route]'
			)
		for a in active:
			lines.append(
				f'[captcha solver: solving {a.get("vendor") or "a captcha"} on {str(a.get("url", ""))[:200]} for '
				f'{time.monotonic() - a["_t"]:.0f}s. Call solve_captcha() to wait for it; do not reload, navigate, switch '
				'tabs or click the challenge meanwhile]'
			)
		return '\n'.join(lines)


class EventPump:
	"""The one reader of the daemon's event buffer (ultrafast mode: ax.AxHelpers is). Read continuously, a busy page's
	Network events never push a captcha event out of the daemon's 500-event buffer. drain_events() still returns every
	event to the agent, in order."""

	def __init__(self, send: Callable[[dict], dict], observe: Callable[[dict], None]):
		self._send, self._observe = send, observe
		self.events: deque = deque(maxlen=EVENT_BUFFER)
		self._lock = threading.Lock()

	def pump(self) -> None:
		with self._lock:
			events = self._send({'meta': 'drain_events'})['events']
			for e in events:
				self._observe(e)
			self.events.extend(events)

	def start(self) -> None:
		def run() -> None:
			while True:
				try:
					self.pump()
					time.sleep(PUMP_INTERVAL_S)
				except Exception:  # - daemon not up yet or restarting
					time.sleep(0.5)

		threading.Thread(target=run, daemon=True, name='browser-use-events').start()

	def drain_events(self) -> list[dict]:
		"""Buffered CDP events since the last call (browser-harness drain_events). Raises, as that does, when the
		daemon cannot be read; what was buffered stays for the next call."""
		self.pump()
		with self._lock:
			out = list(self.events)
			self.events.clear()
		return out
