"""What one Agent.run() did, step by step, for telemetry (schema 3).

Every hook runs on the agent path and is an O(1) in-memory update (perf_counter_ns, an append, an add). build() turns
the record into the event's fields once, in the telemetry thread after the run. Never text: no task, code, output,
page content, URLs or error messages; names only where browser-use, Python or an installed package chose them.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from contextvars import ContextVar
from typing import Any

from pydantic_ai.messages import CompactionPart, ModelResponse, ToolCallPart

from browser_use.telemetry.stats import MAX_NAME, RunStats, error_class

now = time.perf_counter_ns
MS = 1_000_000
MAX_STEPS = 200  # per-step arrays keep the first quarter and the last three quarters of a longer run
DELIVER = frozenset({'finish', 'finish_from_repl'})
WAITS = frozenset({'wait', 'wait_for_load', 'wait_for_network_idle', 'wait_for_element', 'solve_captcha', 'bu.settle'})
INTERACT = frozenset(
	{'click_at_xy', 'type_text', 'fill_input', 'press_key', 'dispatch_key', 'scroll', 'upload_file', 'type_secret'}
	| {'bu.click', 'bu.type'}
)
FILES = frozenset({'downloads', 'checkpoint', 'show_image'})
RESTARTS = frozenset({'CellTimeout', 'WorkerExited'})
CODE = re.compile(r'[a-z0-9_.]{1,40}')
MODEL_NAME = re.compile(r'[A-Za-z0-9._:-]{1,64}')
# s_ev bits
EV_SERVER_COMPACTION, EV_CLIENT_COMPACTION, EV_RETRIED, EV_DELIVERY = 1, 2, 4, 8
EV_CAPTCHA, EV_BLOCKED, EV_CUT, EV_NEW_PAGE, EV_SAME_CODE, EV_RESTART = 16, 32, 64, 128, 256, 512
EV_NAV_FAILED = 1024  # a navigation got Chrome's error page (DNS, TLS, refused): the page did not load
COMPACTION_KIND = {'client': 1, 'server': 2, 'overflow': 3}
# The run's recorder, for code with no RunContext (StreamedRequest: time to first event). Each run sets it in its own task.
CURRENT: ContextVar[RunRecorder | None] = ContextVar('browser_use_recorder', default=None)


class Step:
	"""One model response and the cells it ran."""

	__slots__ = (
		't',
		'model_ms',
		'ttft',
		'inp',
		'out',
		'cached',
		'reason',
		'finish',
		'tools',
		'cells',
		'cell_ms',
		'wait_ms',
		'cdp_ms',
		'err',
		'helpers',
		'host',
		'nav',
		'out_chars',
		'imgs',
		'ev',
		'code',
		'captchas',
		'blocks',
		'nav_fails',
		'checkpoint',
	)

	def __init__(self, t: int, model_ms: int, ttft: int) -> None:
		self.t, self.model_ms, self.ttft = t, model_ms, ttft
		self.inp = self.out = self.cached = self.cells = self.cell_ms = self.wait_ms = self.cdp_ms = 0
		self.nav = self.out_chars = self.imgs = self.ev = self.captchas = self.blocks = self.nav_fails = 0
		self.reason = -1
		self.finish = self.err = self.host = ''
		self.tools: list[str] = []
		self.helpers: list[str] = []
		self.code: int | None = None  # hash of the step's cell code; compared, never sent
		self.checkpoint = False

	def kind(self) -> str:
		"""What the step was for, by priority: deliver, captcha, nav, interact, search, files, wait, read, compute, none."""
		helpers = self.helpers
		if DELIVER.intersection(self.tools) or not self.tools:  # a text reply is an attempt to deliver too
			return 'deliver'
		if 'solve_captcha' in helpers or self.ev & EV_CAPTCHA:
			return 'captcha'
		if self.nav:
			return 'nav'
		if INTERACT.intersection(helpers):
			return 'interact'
		if 'search' in helpers:
			return 'search'
		if FILES.intersection(helpers) or self.checkpoint:
			return 'files'
		if WAITS.intersection(helpers):
			return 'wait'
		if helpers:
			return 'read'
		return 'compute' if self.cells else 'none'


class RunRecorder:
	"""Hooks: attempt_start/attempt_ok/attempt_failed (BrowserLoop model requests), cell (python), retry (each retry
	prompt's raise site), compaction, phase (Agent.run phases), delivery (the delivery-only turn starts)."""

	def __init__(self, tools: frozenset[str] = frozenset(), model: str = '', gateway: bool = False) -> None:
		self.t0 = now()
		self.known = DELIVER | {'python'} | tools  # tool names browser-use or the developer chose
		self.model, self.gateway = model, gateway
		self.ms: Counter = Counter()  # phase -> ns: model, ttft, cells, helpers, waits, cdp, compaction, retry_sleep, ...
		self.steps: list[Step] = []
		self.retries: Counter = Counter()
		self.model_fails: list[list[Any]] = []  # [step, ms, exception class (checked in build), provider code]
		self.compactions: list[list[int]] = []
		self.response_models: Counter = Counter()
		self.attempts = self.length_finishes = self.revisits = 0
		self.first_nav: tuple[int, int] | None = None  # (step, ms)
		self.first_ok_ms: int | None = None
		self.where: str | None = None  # 'model' | 'cell' while one runs: where an exception that ended the run came from
		self.cost_search: float | None = None
		self.cost_compaction: float | None = None
		self._att = self._ttft = 0
		self._failed = 0  # failed attempts since the last response
		self._pending_ev = 0  # bits for the next step (a client compaction before it)
		self._delivery: int | None = None

	# --- model requests (BrowserLoop) ---

	def attempt_start(self) -> None:
		self._att, self._ttft, self.where = now(), -1, 'model'

	def first_event(self) -> None:
		"""A streamed request's first event arrived (StreamedRequest)."""
		if self._ttft < 0:
			self._ttft = now() - self._att

	def attempt_ok(self, response: ModelResponse, finalizing: bool) -> None:
		d = now() - self._att
		self.ms['model'] += d
		self.attempts += 1
		self.where = None
		ttft = -1
		if self._ttft >= 0:
			self.ms['ttft'] += self._ttft
			ttft = self._ttft // MS
		s = Step((self._att - self.t0) // MS, d // MS, ttft)
		u = response.usage
		s.inp, s.out, s.cached = u.input_tokens, u.output_tokens, u.cache_read_tokens
		s.reason = int((u.details or {}).get('reasoning_tokens', -1))
		s.finish = response.finish_reason or ''
		if s.finish == 'length':
			self.length_finishes += 1
		ev = self._pending_ev
		for p in response.parts:
			if isinstance(p, ToolCallPart):
				s.tools.append(p.tool_name if p.tool_name in self.known else 'invalid')
			elif isinstance(p, CompactionPart) and not ev & EV_SERVER_COMPACTION:
				ev |= EV_SERVER_COMPACTION
				if len(self.compactions) < 20:
					self.compactions.append([len(self.steps) + 1, COMPACTION_KIND['server'], 0, s.inp, -1, 1])
		if self._failed:
			ev |= EV_RETRIED
		if finalizing:
			ev |= EV_DELIVERY
		s.ev, self._pending_ev, self._failed = ev, 0, 0
		self.response_models[response.model_name or ''] += 1
		self.steps.append(s)

	def attempt_failed(self, error: BaseException) -> None:
		d = now() - self._att
		self.ms['model'] += d
		self.attempts += 1
		self._failed += 1
		if len(self.model_fails) < 30:
			code = getattr(error, 'provider_error_code', None) or getattr(error, 'status_code', None)
			self.model_fails.append([len(self.steps) + 1, d // MS, type(error), code])

	# --- cells (python tool) ---

	def cell_start(self) -> None:
		self.where = 'cell'

	def cell(self, r: dict, code: str, d: int, vision: bool = True) -> None:
		"""One python call of the current step: r is Repl.call's result, d its wall time in ns."""
		self.where = None
		self.ms['cells'] += d
		if not self.steps:
			return
		s = self.steps[-1]
		s.cells += 1
		s.cell_ms += d // MS
		stats = r.get('stats') or {}
		helper_ns = wait_ns = 0
		interacted = False
		for name, t in (stats.get('helper_t') or {}).items():
			helper_ns += t[2]
			if name in WAITS:
				wait_ns += t[2]
			interacted = interacted or name in INTERACT
			s.checkpoint = s.checkpoint or name == 'checkpoint'
			if name not in s.helpers and len(s.helpers) < 6:
				s.helpers.append(name)
		cdp_ns = sum(t[2] for t in (stats.get('cdp_t') or {}).values())
		self.ms['helpers'] += helper_ns
		self.ms['waits'] += wait_ns
		self.ms['cdp'] += cdp_ns
		s.wait_ms += wait_ns // MS
		s.cdp_ms += cdp_ns // MS
		if r.get('error'):
			s.err = str(r.get('error_type') or 'unknown')[:MAX_NAME]
			if s.err in RESTARTS:
				s.ev |= EV_RESTART
		nav = int(stats.get('navigations') or 0)
		s.nav += nav
		if stats.get('host'):
			s.host = stats['host']
		s.out_chars += len(r.get('output') or '')
		s.imgs += len(r.get('images') or []) if vision else 0
		events = stats.get('events') or {}
		captchas = sum(int(events.get(k) or 0) for k in ('captcha_started', 'captcha_solved', 'captcha_failed'))
		if captchas:
			s.ev |= EV_CAPTCHA
			s.captchas += captchas
		if blocks := int(events.get('domain_blocked') or 0):
			s.ev |= EV_BLOCKED
			s.blocks += blocks
		if fails := int(events.get('nav_failed') or 0):
			s.ev |= EV_NAV_FAILED
			s.nav_fails += fails
		if stats.get('cut'):
			s.ev |= EV_CUT
		if stats.get('new_pages'):
			s.ev |= EV_NEW_PAGE
		self.revisits += int(stats.get('revisits') or 0)
		s.code = hash(code) if s.code is None else hash((s.code, code))
		at = (now() - self.t0) // MS
		if nav and self.first_nav is None:
			self.first_nav = (len(self.steps), at)
		if self.first_ok_ms is None and not r.get('error') and (nav or interacted):
			self.first_ok_ms = at

	# --- the rest ---

	def retry(self, cause: str) -> None:
		self.retries[cause] += 1

	def compaction(self, kind: str, d: int, before: int, after: int, ok: bool) -> None:
		self.ms['compaction'] += d
		self._pending_ev |= EV_CLIENT_COMPACTION
		if len(self.compactions) < 20:
			self.compactions.append([len(self.steps) + 1, COMPACTION_KIND[kind], d // MS, before, after, int(ok)])

	def phase(self, name: str, d: int) -> None:
		self.ms[name] += d

	def delivery(self) -> None:
		if self._delivery is None:
			self._delivery = now()

	def loop_ended(self) -> None:
		if self._delivery is not None:
			self.ms['delivery'] = now() - self._delivery

	# --- at run end, in the telemetry thread ---

	def build(self, stats: RunStats, total_ms: int, limit: int = MAX_STEPS, top_n: int = 50) -> dict[str, Any]:
		"""The event's v3 fields. limit: steps kept in the per-step arrays (0 drops them); top_n: keys per map."""
		ms = {k: v // MS for k, v in self.ms.items()}
		parts = ('preflight', 'browser_start', 'model', 'cells', 'compaction', 'retry_sleep', 'shutdown')
		steps = self.steps
		hosts = _hosts(steps)
		out: dict[str, Any] = {
			'ms_total': total_ms,
			**{f'ms_{k}': ms.get(k, 0) for k in ('preflight', 'model', 'ttft', 'cells', 'helpers', 'waits', 'cdp')},
			**{f'ms_{k}': ms.get(k, 0) for k in ('compaction', 'retry_sleep', 'delivery', 'shutdown')},
			'ms_browser_start': ms.get('browser_start'),
			'ms_repl_start': ms.get('repl_start', 0),
			'ms_other': max(0, total_ms - sum(ms.get(k, 0) for k in parts)),
			'model_attempts': self.attempts,
			'length_finishes': self.length_finishes,
			'response_models': dict(self._models().most_common(5)),
			'retries': dict(self.retries),
			'model_fails': [[step, d, error_class(cls), _code(code)] for step, d, cls, code in self.model_fails],
			'compactions': self.compactions,
			'cost_search_usd': self.cost_search,
			'cost_compaction_usd': self.cost_compaction,
			'first_nav_step': self.first_nav[0] if self.first_nav else None,
			'first_nav_ms': self.first_nav[1] if self.first_nav else None,
			'first_ok_action_ms': self.first_ok_ms,
			'revisit_navs': self.revisits,
			'nav_failures': sum(stats.nav_errors.values()),
			'nav_errors': dict(stats.nav_errors.most_common(min(top_n, 20))),
			'delivery_turn': any(s.ev & EV_DELIVERY for s in steps),
			'helper_stats': _timings(stats.helper_t, top_n),
			'cdp_stats': _timings(stats.cdp_stats(), top_n),
			'host_stats': dict(sorted(hosts.items(), key=lambda kv: -kv[1][0])[: min(top_n, 30)]),
			**_struggle(steps),
		}
		head = limit // 4  # 200: the first 50 and the last 150
		kept = steps if len(steps) <= limit else steps[:head] + steps[len(steps) - (limit - head) :] if limit > 0 else []
		out['tel_steps_dropped'] = len(steps) - len(kept)
		out.update(_arrays(kept))
		return out

	def _models(self) -> Counter:
		out: Counter = Counter()
		for name, n in self.response_models.items():
			out[self._model_name(name)] += n
		return out

	def _model_name(self, name: str) -> str:
		"""The model a response named, when it cannot be a local path or text a custom endpoint made up: through the
		gateway, or a name that starts with the configured model's last path segment."""
		if not name or not MODEL_NAME.fullmatch(name):
			return 'other' if name else ''
		base = self.model.rsplit('/', 1)[-1].rsplit(':', 1)[-1]
		return name if self.gateway or (base and name.startswith(base)) else 'other'


def _code(code: Any) -> str:
	"""A provider error code (rate_limit_exceeded, 429): at most 40 characters of [a-z0-9_.], else 'other'."""
	if code is None:
		return ''
	text = str(code).lower()
	return text if CODE.fullmatch(text) else 'other'


def _timings(timings: dict[str, list[int]], n: int) -> dict[str, list[int]]:
	"""{name: [calls, errors, ms total, ms max]}, the n with the most total time."""
	top = sorted(timings.items(), key=lambda kv: -kv[1][2])[:n]
	return {str(k)[:MAX_NAME]: [c, e, t // MS, m // MS] for k, (c, e, t, m) in top}


def _hosts(steps: list[Step]) -> dict[str, list[int]]:
	"""{host: [steps, err_steps, cell_ms, captchas, blocks, navs, failed navs]}. A step that saw no URL is on the
	previous one's host."""
	out: dict[str, list[int]] = {}
	current = ''
	for s in steps:
		s.host = current = s.host or current
		if not current:
			continue
		h = out.setdefault(current, [0, 0, 0, 0, 0, 0, 0])
		h[0] += 1
		h[1] += bool(s.err)
		h[2] += s.cell_ms
		h[3] += s.captchas
		h[4] += s.blocks
		h[5] += s.nav
		h[6] += s.nav_fails
	return out


def _struggle(steps: list[Step]) -> dict[str, Any]:
	"""Error streaks, repeats, host streaks and the last step that made progress; O(steps)."""
	best = (0, 0)  # (length, end index) of the longest error streak
	streak = streaks3 = repeat_fail = repeat_code = host_streak = max_host = last_progress = 0
	prev_fail: tuple | None = None
	prev = None
	for i, s in enumerate(steps):
		if s.err:
			streak += 1
			if streak > best[0]:
				best = (streak, i)
			key = (s.err, tuple(s.helpers))
			repeat_fail += key == prev_fail
			prev_fail = key
		else:
			streaks3 += streak >= 3
			streak = 0
		if prev is not None and s.code is not None and s.code == prev.code:
			s.ev |= EV_SAME_CODE
			repeat_code += 1
		new = bool(s.ev & EV_NEW_PAGE) and not s.ev & EV_NAV_FAILED  # an error page is not progress
		host_streak = 1 if (prev is None or new or s.host != prev.host or not s.host) else host_streak + 1
		max_host = max(max_host, host_streak if s.host else 0)
		# a final text reply is the delivery too (finish_via text): live runs on bu-fast delivered so in 6 of 11, and
		# each counted every step after its last new page as wasted
		delivered = DELIVER.intersection(s.tools) or (not s.tools and i == len(steps) - 1)
		if not s.err and (new or s.checkpoint or delivered):
			last_progress = i + 1
		prev = s
	streaks3 += streak >= 3
	length, end = best
	inside = steps[end - length + 1 : end + 1] if length else []

	def common(values: list[str]) -> str | None:
		values = [v for v in values if v]
		return Counter(values).most_common(1)[0][0] if values else None

	return {
		'max_err_streak': length,
		'err_streaks_3': streaks3,
		'streak_err': common([s.err for s in inside]),
		'streak_kind': common([s.kind() for s in inside]),
		'streak_helper': common([s.helpers[0] if s.helpers else '' for s in inside]),
		'repeat_fail_steps': repeat_fail,
		'repeat_code_steps': repeat_code,
		'max_host_streak': max_host,
		'last_progress_step': last_progress,
		'wasted_steps': len(steps) - last_progress,
	}


def _arrays(kept: list[Step]) -> dict[str, list]:
	return {
		's_t': [s.t for s in kept],
		's_model_ms': [s.model_ms for s in kept],
		's_ttft_ms': [s.ttft for s in kept],
		's_in': [s.inp for s in kept],
		's_out': [s.out for s in kept],
		's_cached': [s.cached for s in kept],
		's_reason': [s.reason for s in kept],
		's_finish': [s.finish for s in kept],
		's_tools': [','.join(s.tools) for s in kept],
		's_cells': [s.cells for s in kept],
		's_cell_ms': [s.cell_ms for s in kept],
		's_wait_ms': [s.wait_ms for s in kept],
		's_cdp_ms': [s.cdp_ms for s in kept],
		's_err': [s.err for s in kept],
		's_helpers': [','.join(s.helpers) for s in kept],
		's_kind': [s.kind() for s in kept],
		's_host': [s.host for s in kept],
		's_nav': [s.nav for s in kept],
		's_out_chars': [s.out_chars for s in kept],
		's_imgs': [s.imgs for s in kept],
		's_ev': [s.ev for s in kept],
	}
