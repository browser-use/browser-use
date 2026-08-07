"""Dempster-Shafer skill-fitness accumulator.

Each skill invocation (success + latency + error) becomes a MassFunction over
{LOW, MID, HIGH}; repeated invocations combine via Dempster's rule of
combination (Dempster 1967, Shafer 1976), giving a belief/plausibility
interval per skill rather than a point estimate.

Downstream selectors can pick by:
  belief       — conservative (max lower bound; avoid unproven skills)
  plausibility — exploratory (max upper bound; try promising-but-noisy skills)
  expected     — pignistic Bayesian collapse (spread ignorance uniformly)

Zero third-party dependencies — pure Python, ships in the core install.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Literal, cast

FrozenFrame = frozenset[str]

_LOW: FrozenFrame = frozenset({'LOW'})
_MID: FrozenFrame = frozenset({'MID'})
_HIGH: FrozenFrame = frozenset({'HIGH'})
_FULL: FrozenFrame = frozenset({'LOW', 'MID', 'HIGH'})

SelectionMode = Literal['belief', 'plausibility', 'expected']


@dataclass(frozen=True)
class MassFunction:
	"""Mass assignment over subsets of {LOW, MID, HIGH}. Masses sum to 1.

	Mass on the full frame represents pure ignorance — the feature that
	distinguishes Dempster-Shafer from Bayesian probability.
	"""

	masses: dict[FrozenFrame, float] = field(default_factory=dict)

	def __post_init__(self) -> None:
		total = sum(self.masses.values())
		if total <= 0:
			object.__setattr__(self, 'masses', {_FULL: 1.0})
			return
		if abs(total - 1.0) > 1e-9:
			object.__setattr__(self, 'masses', {k: v / total for k, v in self.masses.items()})

	@classmethod
	def from_score(cls, score: float, confidence: float = 0.7) -> MassFunction:
		"""Map a [0,1] point score to a mass function.

		confidence ∈ [0,1]: mass placed on the singleton hypothesis; the
		remainder (1 - confidence) is assigned to the full frame as ignorance.
		"""
		score = max(0.0, min(1.0, float(score)))
		confidence = max(0.0, min(1.0, float(confidence)))
		if score < 1.0 / 3.0:
			singleton = _LOW
		elif score < 2.0 / 3.0:
			singleton = _MID
		else:
			singleton = _HIGH
		return cls({singleton: confidence, _FULL: 1.0 - confidence})

	def belief(self, hypothesis: FrozenFrame = _HIGH) -> float:
		"""Lower probability bound: sum of masses on subsets of the hypothesis."""
		return sum(m for s, m in self.masses.items() if s.issubset(hypothesis))

	def plausibility(self, hypothesis: FrozenFrame = _HIGH) -> float:
		"""Upper probability bound: sum of masses on subsets intersecting the hypothesis."""
		return sum(m for s, m in self.masses.items() if s & hypothesis)

	def expected_value(self) -> float:
		"""Pignistic expectation: non-singleton mass spread uniformly over members."""
		values = {'LOW': 0.15, 'MID': 0.5, 'HIGH': 0.85}
		total = 0.0
		for subset, m in self.masses.items():
			if not subset:
				continue
			per = m / len(subset)
			for hypothesis in subset:
				total += per * values[hypothesis]
		return total

	def score(self, mode: SelectionMode = 'belief') -> float:
		"""One-shot scalar for ranking. Belief = conservative, plausibility = exploratory."""
		if mode == 'belief':
			return self.belief()
		if mode == 'plausibility':
			return self.plausibility()
		return self.expected_value()

	def to_dict(self) -> dict[str, float]:
		"""JSON-safe wire format. Frozenset keys become sorted comma-joined strings."""
		return {','.join(sorted(subset)): mass for subset, mass in self.masses.items()}

	@classmethod
	def from_dict(cls, data: dict[str, float]) -> MassFunction:
		"""Inverse of to_dict — accepts the sorted-comma-joined key form."""
		masses: dict[FrozenFrame, float] = {}
		for key, mass in data.items():
			subset = frozenset(part for part in key.split(',') if part)
			if not subset:
				continue
			masses[subset] = float(mass)
		return cls(masses)


def dempster_combine(m1: MassFunction, m2: MassFunction) -> MassFunction:
	"""Dempster's rule of combination — normalises out the conflict mass.

	Falls back to maximum-ignorance on total conflict (norm ≈ 0), which happens
	when two mass functions place all their weight on disjoint singletons.
	"""
	combined: dict[FrozenFrame, float] = {}
	conflict = 0.0
	for s1, v1 in m1.masses.items():
		for s2, v2 in m2.masses.items():
			inter = s1 & s2
			if not inter:
				conflict += v1 * v2
			else:
				combined[inter] = combined.get(inter, 0.0) + v1 * v2
	norm = 1.0 - conflict
	if norm <= 1e-9:
		return MassFunction({_FULL: 1.0})
	return MassFunction({k: v / norm for k, v in combined.items()})


def score_from_execution(success: bool, latency_ms: int | None, error: str | None) -> tuple[float, float]:
	"""Turn one skill-execution result into a (score, confidence) pair.

	success maps to a hard 0/1 anchor; latency modulates confidence (fast +
	successful → very confident; slow + successful → less confident because
	we can't tell if the skill just got lucky).
	"""
	if success and error is None:
		if latency_ms is None:
			return 0.8, 0.6
		# Latency curve: <500ms full confidence, >30s minimum confidence.
		latency_conf = max(0.4, min(0.95, 1.0 - (latency_ms / 30_000.0)))
		return 0.9, latency_conf
	# Failure — high-confidence LOW score, but leave a sliver of ignorance in
	# case the failure was environmental (blocked cookie, transient 5xx).
	return 0.1, 0.7


@dataclass
class SkillFitnessTracker:
	"""Per-skill Dempster-Shafer fitness accumulator.

	Records every execution result, combines belief across the history via
	Dempster's rule, and exposes rankings under three selection modes.
	"""

	_fitness: dict[str, MassFunction] = field(default_factory=dict)
	_invocations: dict[str, int] = field(default_factory=dict)

	def record(
		self,
		skill_id: str,
		success: bool,
		latency_ms: int | None = None,
		error: str | None = None,
	) -> MassFunction:
		"""Fold this execution into the skill's belief interval; return the updated function."""
		score, confidence = score_from_execution(success, latency_ms, error)
		observation = MassFunction.from_score(score, confidence)
		prior = self._fitness.get(skill_id)
		combined = dempster_combine(prior, observation) if prior is not None else observation
		self._fitness[skill_id] = combined
		self._invocations[skill_id] = self._invocations.get(skill_id, 0) + 1
		return combined

	def fitness(self, skill_id: str) -> MassFunction | None:
		"""Return the accumulated mass function for a skill, or None if unseen."""
		return self._fitness.get(skill_id)

	def invocations(self, skill_id: str) -> int:
		"""How many times this skill has been recorded. Zero if unseen."""
		return self._invocations.get(skill_id, 0)

	def ranked(self, mode: SelectionMode = 'belief') -> list[tuple[str, float]]:
		"""Skill IDs sorted by the chosen selection mode, best first."""
		return sorted(
			((skill_id, mf.score(mode)) for skill_id, mf in self._fitness.items()),
			key=lambda pair: pair[1],
			reverse=True,
		)

	def top_k(self, k: int, mode: SelectionMode = 'belief') -> list[str]:
		"""Top-k skill IDs under the chosen mode. Returns fewer if fewer are known.

		Zero-cost primitive for "give me the k safest actions to expose to the LLM".
		"""
		if k <= 0:
			return []
		return [skill_id for skill_id, _ in self.ranked(mode)[:k]]

	def recommend(
		self,
		candidates: list[str],
		mode: SelectionMode = 'belief',
		min_score: float = 0.5,
		include_unseen: bool = True,
	) -> list[str]:
		"""Filter candidates to those meeting the score threshold under the chosen mode.

		candidates: pool to pick from — preserves input order among survivors.
		min_score: threshold on the mode's scalar; a skill must score >= this to survive.
		include_unseen: when True (default), skills never recorded are kept — they haven't
			accumulated evidence yet and shouldn't be filtered out on that basis alone.
			Set False to require prior evidence before recommending.

		Use this to gate an action registry before showing it to the LLM:
			allowed = tracker.recommend(list(registry.keys()), min_score=0.4)
		"""
		out: list[str] = []
		for skill_id in candidates:
			mf = self._fitness.get(skill_id)
			if mf is None:
				if include_unseen:
					out.append(skill_id)
				continue
			if mf.score(mode) >= min_score:
				out.append(skill_id)
		return out

	def reset(self) -> None:
		"""Drop all accumulated fitness. Useful for scoped experiments."""
		self._fitness.clear()
		self._invocations.clear()

	def to_dict(self) -> dict[str, Any]:
		"""JSON-safe snapshot of the full accumulator state. Round-trips via from_dict."""
		return {
			'fitness': {skill_id: mf.to_dict() for skill_id, mf in self._fitness.items()},
			'invocations': dict(self._invocations),
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> SkillFitnessTracker:
		"""Restore a tracker from to_dict output. Unknown keys are ignored."""
		fitness_raw = data.get('fitness', {}) or {}
		invocations_raw = data.get('invocations', {}) or {}
		fitness = {skill_id: MassFunction.from_dict(mf) for skill_id, mf in fitness_raw.items()}
		invocations = {skill_id: int(count) for skill_id, count in invocations_raw.items()}
		return cls(_fitness=fitness, _invocations=invocations)


def _cli(argv: list[str] | None = None) -> int:
	"""Read (skill_id, success, latency_ms, error) records as JSONL from stdin, print rankings.

	Pipe from any tool that emits skill-execution results — CI runs, agent traces,
	audit scripts. Load prior state with --state; persist accumulated state with --save.
	Or run --serve <port> for an HTTP surface any webapp/dashboard can hit.

	Examples:
	    cat runs.jsonl | python -m browser_use.skills.fitness
	    python -m browser_use.skills.fitness --mode plausibility --state prior.json --save next.json
	    python -m browser_use.skills.fitness --serve 8765
	"""
	import argparse

	parser = argparse.ArgumentParser(
		prog='python -m browser_use.skills.fitness',
		description='Accumulate Dempster-Shafer skill fitness from JSONL records on stdin, or serve over HTTP.',
	)
	parser.add_argument(
		'--mode',
		choices=('belief', 'plausibility', 'expected'),
		default='belief',
		help='Ranking mode (default: belief).',
	)
	parser.add_argument('--state', type=str, default=None, help='Load prior tracker state from this JSON file.')
	parser.add_argument('--save', type=str, default=None, help='Write updated tracker state to this JSON file.')
	parser.add_argument('--top', type=int, default=0, help='Show only the top N skills (0 = all).')
	parser.add_argument(
		'--serve',
		type=int,
		default=None,
		metavar='PORT',
		help='Serve an HTTP surface on 127.0.0.1:PORT instead of reading stdin.',
	)
	parser.add_argument('--host', type=str, default='127.0.0.1', help='Bind host for --serve (default: 127.0.0.1).')
	args = parser.parse_args(argv)

	if args.state:
		with open(args.state, encoding='utf-8') as f:
			tracker = SkillFitnessTracker.from_dict(json.load(f))
	else:
		tracker = SkillFitnessTracker()

	if args.serve is not None:
		return _serve(tracker, host=args.host, port=args.serve, save_path=args.save)

	for line_num, line in enumerate(sys.stdin, start=1):
		line = line.strip()
		if not line:
			continue
		try:
			record = json.loads(line)
		except json.JSONDecodeError as e:
			print(f'line {line_num}: skipping malformed JSON: {e}', file=sys.stderr)
			continue
		skill_id = record.get('skill_id')
		if not skill_id:
			print(f'line {line_num}: skipping record without skill_id', file=sys.stderr)
			continue
		tracker.record(
			skill_id=str(skill_id),
			success=bool(record.get('success', False)),
			latency_ms=record.get('latency_ms'),
			error=record.get('error'),
		)

	ranked = tracker.ranked(args.mode)
	if args.top > 0:
		ranked = ranked[: args.top]
	for skill_id, score in ranked:
		invocations = tracker.invocations(skill_id)
		print(f'{score:.4f}\t{invocations}\t{skill_id}')

	if args.save:
		with open(args.save, 'w', encoding='utf-8') as f:
			json.dump(tracker.to_dict(), f, indent=2, sort_keys=True)
	return 0


_OPENAPI_SCHEMA: dict[str, Any] = {
	'openapi': '3.1.0',
	'info': {
		'title': 'skill-fitness',
		'version': '1',
		'description': 'Dempster-Shafer per-skill fitness accumulator over HTTP.',
	},
	'paths': {
		'/health': {
			'get': {
				'summary': 'Liveness probe.',
				'responses': {'200': {'description': 'Process is up.'}},
			}
		},
		'/ready': {
			'get': {
				'summary': 'Readiness probe.',
				'responses': {'200': {'description': 'Service is accepting traffic.'}},
			}
		},
		'/metrics': {
			'get': {
				'summary': 'Prometheus text-format metrics.',
				'responses': {'200': {'description': 'text/plain; version=0.0.4'}},
			}
		},
		'/record': {
			'post': {
				'summary': 'Record one skill invocation outcome.',
				'requestBody': {
					'content': {
						'application/json': {
							'schema': {
								'type': 'object',
								'required': ['skill_id'],
								'properties': {
									'skill_id': {'type': 'string'},
									'success': {'type': 'boolean'},
									'latency_ms': {'type': ['integer', 'null']},
									'error': {'type': ['string', 'null']},
								},
							}
						}
					}
				},
				'responses': {'200': {'description': 'Updated MassFunction dict.'}},
			}
		},
		'/ranked': {
			'get': {
				'summary': 'Skills sorted best-first under the chosen mode.',
				'parameters': [
					{'name': 'mode', 'in': 'query', 'schema': {'enum': ['belief', 'plausibility', 'expected']}},
					{'name': 'top', 'in': 'query', 'schema': {'type': 'integer'}},
				],
				'responses': {'200': {'description': '[[skill_id, score], ...]'}},
			}
		},
		'/top_k': {
			'get': {
				'summary': 'Top-k skill IDs under the chosen mode.',
				'parameters': [
					{'name': 'mode', 'in': 'query', 'schema': {'enum': ['belief', 'plausibility', 'expected']}},
					{'name': 'k', 'in': 'query', 'schema': {'type': 'integer'}},
				],
				'responses': {'200': {'description': '[skill_id, ...]'}},
			}
		},
		'/fitness/{skill_id}': {
			'get': {
				'summary': 'MassFunction for one skill.',
				'parameters': [{'name': 'skill_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}],
				'responses': {'200': {'description': 'MassFunction dict.'}, '404': {'description': 'Unknown skill_id.'}},
			}
		},
		'/state': {
			'get': {'summary': 'Full tracker snapshot.', 'responses': {'200': {'description': 'to_dict output.'}}},
			'post': {'summary': 'Replace tracker snapshot.', 'responses': {'200': {'description': '{"replaced": true}'}}},
		},
		'/reset': {'post': {'summary': 'Wipe tracker.', 'responses': {'200': {'description': '{"reset": true}'}}}},
		'/recommend': {
			'post': {
				'summary': 'Filter candidates by score threshold under the chosen mode.',
				'requestBody': {
					'content': {
						'application/json': {
							'schema': {
								'type': 'object',
								'required': ['candidates'],
								'properties': {
									'candidates': {'type': 'array', 'items': {'type': 'string'}},
									'mode': {'enum': ['belief', 'plausibility', 'expected']},
									'min_score': {'type': 'number'},
									'include_unseen': {'type': 'boolean'},
								},
							}
						}
					}
				},
				'responses': {'200': {'description': 'Filtered [skill_id, ...]'}},
			}
		},
	},
}


def _serve(tracker: SkillFitnessTracker, host: str, port: int, save_path: str | None = None) -> int:
	"""Serve the tracker over stdlib http.server. Local/internal use — wrap in ASGI for prod.

	Routes (all also aliased under /v1/... for stable API versioning):

	  Health/observability:
	    GET  /health         → {"status": "ok"}       — liveness probe
	    GET  /ready          → {"status": "ready"}    — readiness probe
	    GET  /metrics        → Prometheus text/plain — total records, per-skill invocations, tracker size
	    GET  /openapi.json   → OpenAPI 3.1 schema of this surface

	  Data:
	    POST /record         → body = {skill_id, success, latency_ms?, error?}; returns updated MassFunction
	    GET  /ranked?mode=..&top=..   → [[skill_id, score], ...] best-first
	    GET  /top_k?mode=..&k=..      → [skill_id, ...] best-first, capped at k
	    GET  /fitness/<skill_id>      → MassFunction dict or 404
	    GET  /state          → full tracker snapshot (to_dict output)
	    POST /state          → replace tracker snapshot (from_dict input)
	    POST /reset          → wipe all accumulated fitness
	    POST /recommend      → body = {candidates: [str], mode?, min_score?, include_unseen?}; returns filtered [str]

	Modern-service defaults:
	  - Every mutating request auto-persists to save_path when provided.
	  - CORS: read-only endpoints send Access-Control-Allow-Origin: * for browser dashboards.
	  - Structured access log on mutating requests: one JSON line per POST to stderr.
	  - Graceful shutdown on SIGTERM as well as SIGINT.
	  - Binds 127.0.0.1 by default. Set --host explicitly to expose off-box.
	"""
	import signal
	import threading
	from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
	from urllib.parse import parse_qs, urlparse

	lock = threading.Lock()

	def persist_locked() -> None:
		if save_path is None:
			return
		with open(save_path, 'w', encoding='utf-8') as f:
			json.dump(tracker.to_dict(), f, indent=2, sort_keys=True)

	def render_metrics_locked() -> bytes:
		total_records = sum(tracker._invocations.values())
		lines = [
			'# HELP skill_fitness_records_total Total number of recorded skill invocations.',
			'# TYPE skill_fitness_records_total counter',
			f'skill_fitness_records_total {total_records}',
			'# HELP skill_fitness_tracked_skills Number of distinct skills with at least one recorded outcome.',
			'# TYPE skill_fitness_tracked_skills gauge',
			f'skill_fitness_tracked_skills {len(tracker._fitness)}',
			'# HELP skill_fitness_invocations Per-skill invocation counter.',
			'# TYPE skill_fitness_invocations counter',
		]
		for skill_id, count in tracker._invocations.items():
			# Prometheus label escaping: backslash, quote, newline.
			escaped = skill_id.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
			lines.append(f'skill_fitness_invocations{{skill="{escaped}"}} {count}')
		lines.append('# HELP skill_fitness_belief_high Belief that a skill is HIGH-fitness (Dempster-Shafer lower bound).')
		lines.append('# TYPE skill_fitness_belief_high gauge')
		for skill_id, mf in tracker._fitness.items():
			escaped = skill_id.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
			lines.append(f'skill_fitness_belief_high{{skill="{escaped}"}} {mf.belief():.6f}')
		return ('\n'.join(lines) + '\n').encode('utf-8')

	def _strip_v1(path: str) -> str:
		return path[len('/v1') :] if path.startswith('/v1/') else path

	class Handler(BaseHTTPRequestHandler):
		def _cors_headers_get(self) -> None:
			self.send_header('Access-Control-Allow-Origin', '*')
			self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')

		def _write_json(self, status: int, payload: Any, cors_get: bool = False) -> None:
			body = json.dumps(payload).encode('utf-8')
			self.send_response(status)
			self.send_header('Content-Type', 'application/json')
			self.send_header('Content-Length', str(len(body)))
			if cors_get:
				self._cors_headers_get()
			self.end_headers()
			self.wfile.write(body)

		def _write_text(self, status: int, body: bytes, content_type: str, cors_get: bool = False) -> None:
			self.send_response(status)
			self.send_header('Content-Type', content_type)
			self.send_header('Content-Length', str(len(body)))
			if cors_get:
				self._cors_headers_get()
			self.end_headers()
			self.wfile.write(body)

		def _read_json(self) -> Any:
			length = int(self.headers.get('Content-Length', '0') or 0)
			if length <= 0:
				return None
			raw = self.rfile.read(length)
			return json.loads(raw.decode('utf-8'))

		def log_message(self, fmt: str, *log_args: Any) -> None:
			# Default access log is silenced — mutating requests emit their own structured JSON line.
			return

		def _log_mutation(self, method: str, path: str, status: int) -> None:
			entry = {
				'ts_ns': time.time_ns(),
				'method': method,
				'path': path,
				'status': status,
				'remote': self.client_address[0] if self.client_address else None,
			}
			print(json.dumps(entry), file=sys.stderr)

		def do_OPTIONS(self) -> None:
			# Basic CORS preflight support for browser-side dashboards hitting GET endpoints.
			self.send_response(204)
			self.send_header('Access-Control-Allow-Origin', '*')
			self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
			self.send_header('Access-Control-Allow-Headers', 'Content-Type')
			self.send_header('Access-Control-Max-Age', '600')
			self.end_headers()

		def do_GET(self) -> None:
			parsed = urlparse(self.path)
			path = _strip_v1(parsed.path)
			query = parse_qs(parsed.query)
			if path == '/health':
				self._write_json(200, {'status': 'ok'}, cors_get=True)
				return
			if path == '/ready':
				self._write_json(200, {'status': 'ready'}, cors_get=True)
				return
			if path == '/metrics':
				with lock:
					body = render_metrics_locked()
				self._write_text(200, body, 'text/plain; version=0.0.4; charset=utf-8', cors_get=True)
				return
			if path == '/openapi.json':
				self._write_json(200, _OPENAPI_SCHEMA, cors_get=True)
				return
			if path == '/state':
				with lock:
					self._write_json(200, tracker.to_dict(), cors_get=True)
				return
			if path == '/ranked':
				mode_raw = query.get('mode', ['belief'])[0]
				if mode_raw not in {'belief', 'plausibility', 'expected'}:
					self._write_json(400, {'error': f'unknown mode: {mode_raw}'}, cors_get=True)
					return
				try:
					top = int(query.get('top', ['0'])[0])
				except ValueError:
					self._write_json(400, {'error': 'top must be an integer'}, cors_get=True)
					return
				with lock:
					ranked = tracker.ranked(cast(SelectionMode, mode_raw))
				if top > 0:
					ranked = ranked[:top]
				self._write_json(200, [[skill_id, score] for skill_id, score in ranked], cors_get=True)
				return
			if path.startswith('/fitness/'):
				skill_id = path[len('/fitness/') :]
				with lock:
					mf = tracker.fitness(skill_id)
				if mf is None:
					self._write_json(404, {'error': f'unknown skill_id: {skill_id}'}, cors_get=True)
					return
				self._write_json(200, mf.to_dict(), cors_get=True)
				return
			if path == '/top_k':
				mode_raw = query.get('mode', ['belief'])[0]
				if mode_raw not in {'belief', 'plausibility', 'expected'}:
					self._write_json(400, {'error': f'unknown mode: {mode_raw}'}, cors_get=True)
					return
				try:
					k = int(query.get('k', ['10'])[0])
				except ValueError:
					self._write_json(400, {'error': 'k must be an integer'}, cors_get=True)
					return
				with lock:
					self._write_json(200, tracker.top_k(k, cast(SelectionMode, mode_raw)), cors_get=True)
				return
			self._write_json(404, {'error': f'unknown path: {parsed.path}'}, cors_get=True)

		def do_POST(self) -> None:
			path = _strip_v1(urlparse(self.path).path)
			try:
				payload = self._read_json()
			except json.JSONDecodeError as e:
				self._write_json(400, {'error': f'malformed JSON: {e}'})
				self._log_mutation('POST', path, 400)
				return
			if path == '/record':
				if not isinstance(payload, dict) or not payload.get('skill_id'):
					self._write_json(400, {'error': 'body must be a JSON object with skill_id'})
					self._log_mutation('POST', path, 400)
					return
				with lock:
					mf = tracker.record(
						skill_id=str(payload['skill_id']),
						success=bool(payload.get('success', False)),
						latency_ms=payload.get('latency_ms'),
						error=payload.get('error'),
					)
					persist_locked()
				self._write_json(200, mf.to_dict())
				self._log_mutation('POST', path, 200)
				return
			if path == '/state':
				if not isinstance(payload, dict):
					self._write_json(400, {'error': 'body must be a JSON object'})
					self._log_mutation('POST', path, 400)
					return
				restored = SkillFitnessTracker.from_dict(payload)
				with lock:
					tracker._fitness = dict(restored._fitness)
					tracker._invocations = dict(restored._invocations)
					persist_locked()
				self._write_json(200, {'replaced': True})
				self._log_mutation('POST', path, 200)
				return
			if path == '/reset':
				with lock:
					tracker.reset()
					persist_locked()
				self._write_json(200, {'reset': True})
				self._log_mutation('POST', path, 200)
				return
			if path == '/recommend':
				if not isinstance(payload, dict):
					self._write_json(400, {'error': 'body must be a JSON object'})
					self._log_mutation('POST', path, 400)
					return
				candidates = payload.get('candidates')
				if not isinstance(candidates, list) or not all(isinstance(c, str) for c in candidates):
					self._write_json(400, {'error': 'candidates must be a list of strings'})
					self._log_mutation('POST', path, 400)
					return
				mode_raw = str(payload.get('mode', 'belief'))
				if mode_raw not in {'belief', 'plausibility', 'expected'}:
					self._write_json(400, {'error': f'unknown mode: {mode_raw}'})
					self._log_mutation('POST', path, 400)
					return
				try:
					min_score = float(payload.get('min_score', 0.5))
				except (TypeError, ValueError):
					self._write_json(400, {'error': 'min_score must be a number'})
					self._log_mutation('POST', path, 400)
					return
				include_unseen = bool(payload.get('include_unseen', True))
				with lock:
					out = tracker.recommend(
						candidates,
						mode=cast(SelectionMode, mode_raw),
						min_score=min_score,
						include_unseen=include_unseen,
					)
				self._write_json(200, out)
				self._log_mutation('POST', path, 200)
				return
			self._write_json(404, {'error': f'unknown path: {path}'})
			self._log_mutation('POST', path, 404)

	server = ThreadingHTTPServer((host, port), Handler)

	def _sigterm(_signum: int, _frame: Any) -> None:
		# ThreadingHTTPServer.shutdown() must be called from a different thread than serve_forever().
		threading.Thread(target=server.shutdown, daemon=True).start()

	# SIGTERM support for supervisor-managed deploys (systemd, kubelet, docker stop).
	try:
		signal.signal(signal.SIGTERM, _sigterm)
	except (ValueError, OSError):
		# signal.signal only works in the main thread; skip when embedded (e.g. tests).
		pass

	print(f'skill-fitness serving on http://{host}:{port} (persist={save_path or "off"})', file=sys.stderr)
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		server.server_close()
		print('shutdown', file=sys.stderr)
	return 0


if __name__ == '__main__':
	sys.exit(_cli())
