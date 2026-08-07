"""Tests for the Dempster-Shafer skill-fitness accumulator.

Real objects, no mocks — the fitness math is pure Python and deterministic.
Covers:
  - MassFunction normalisation + belief/plausibility/expected axes
  - from_score confidence gating (0 → pure ignorance, 1 → point mass on singleton)
  - Dempster combination reinforces agreeing observations
  - Dempster combination on total conflict falls back to maximum-ignorance
  - SkillFitnessTracker accumulates + ranks under all three selection modes
  - SkillService wiring records every execution result
"""

from __future__ import annotations

import io
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest

from browser_use.skills.fitness import (
	MassFunction,
	SkillFitnessTracker,
	_cli,
	_serve,
	dempster_combine,
	score_from_execution,
)

_HIGH = frozenset({'HIGH'})
_LOW = frozenset({'LOW'})
_FULL = frozenset({'LOW', 'MID', 'HIGH'})


def test_mass_function_normalises_to_unit() -> None:
	m = MassFunction({_HIGH: 2.0, _FULL: 2.0})
	assert abs(sum(m.masses.values()) - 1.0) < 1e-9
	assert m.masses[_HIGH] == pytest.approx(0.5)
	assert m.masses[_FULL] == pytest.approx(0.5)


def test_mass_function_empty_collapses_to_max_ignorance() -> None:
	m = MassFunction({})
	assert m.masses == {_FULL: 1.0}
	assert m.belief() == 0.0
	assert m.plausibility() == 1.0


def test_from_score_confidence_gates_ignorance() -> None:
	certain = MassFunction.from_score(0.9, confidence=1.0)
	assert certain.masses.get(_HIGH) == pytest.approx(1.0)
	assert certain.belief() == pytest.approx(1.0)
	assert certain.plausibility() == pytest.approx(1.0)

	ignorant = MassFunction.from_score(0.9, confidence=0.0)
	assert ignorant.masses.get(_FULL) == pytest.approx(1.0)
	assert ignorant.belief() == 0.0
	assert ignorant.plausibility() == pytest.approx(1.0)

	mid = MassFunction.from_score(0.5, confidence=0.6)
	assert mid.belief(frozenset({'MID'})) == pytest.approx(0.6)


def test_score_boundaries_partition_correctly() -> None:
	low = MassFunction.from_score(0.0, confidence=1.0)
	assert _LOW in low.masses
	mid = MassFunction.from_score(0.5, confidence=1.0)
	assert frozenset({'MID'}) in mid.masses
	high = MassFunction.from_score(1.0, confidence=1.0)
	assert _HIGH in high.masses


def test_dempster_reinforces_agreement() -> None:
	m1 = MassFunction.from_score(0.9, confidence=0.6)
	m2 = MassFunction.from_score(0.9, confidence=0.6)
	combined = dempster_combine(m1, m2)
	# Two independent HIGH observations should push belief above either alone.
	assert combined.belief() > m1.belief()
	assert combined.belief() > 0.6


def test_dempster_total_conflict_reverts_to_ignorance() -> None:
	high_certain = MassFunction({_HIGH: 1.0})
	low_certain = MassFunction({_LOW: 1.0})
	combined = dempster_combine(high_certain, low_certain)
	# No mass on a shared subset → norm = 0 → fall back to full-frame ignorance.
	assert combined.masses == {_FULL: 1.0}


def test_score_from_execution_success_high_confidence_when_fast() -> None:
	score, confidence = score_from_execution(success=True, latency_ms=100, error=None)
	assert score >= 0.8
	assert confidence >= 0.9


def test_score_from_execution_failure_low_score() -> None:
	score, confidence = score_from_execution(success=False, latency_ms=None, error='boom')
	assert score < 0.3
	assert 0.5 < confidence < 1.0


def test_tracker_accumulates_belief_across_calls() -> None:
	tracker = SkillFitnessTracker()
	assert tracker.fitness('skill-a') is None
	assert tracker.invocations('skill-a') == 0

	for _ in range(3):
		tracker.record('skill-a', success=True, latency_ms=200)
	fitness = tracker.fitness('skill-a')
	assert fitness is not None
	# Three fast successes should give near-certain HIGH belief.
	assert fitness.belief() > 0.85
	assert tracker.invocations('skill-a') == 3


def test_tracker_ranks_by_selection_mode() -> None:
	tracker = SkillFitnessTracker()
	# Reliable skill: three fast successes.
	for _ in range(3):
		tracker.record('reliable', success=True, latency_ms=100)
	# Noisy skill: one success then one failure — high conflict, low belief but wide plausibility.
	tracker.record('noisy', success=True, latency_ms=100)
	tracker.record('noisy', success=False, error='transient')
	# Untried skill: never recorded.
	# Cold skill: one moderate-latency success.
	tracker.record('cold', success=True, latency_ms=5_000)

	belief_ranked = tracker.ranked('belief')
	plausibility_ranked = tracker.ranked('plausibility')
	expected_ranked = tracker.ranked('expected')

	# All three modes should list reliable first.
	assert belief_ranked[0][0] == 'reliable'
	assert plausibility_ranked[0][0] == 'reliable'
	assert expected_ranked[0][0] == 'reliable'

	# Rankings are proper permutations of what was recorded.
	assert {name for name, _ in belief_ranked} == {'reliable', 'noisy', 'cold'}


def test_tracker_top_k_returns_best_first() -> None:
	tracker = SkillFitnessTracker()
	tracker.record('slow', success=True, latency_ms=5_000)
	for _ in range(3):
		tracker.record('fast', success=True, latency_ms=100)
	tracker.record('flaky', success=False, error='oops')
	top2 = tracker.top_k(2, mode='belief')
	assert top2[0] == 'fast'
	# When k exceeds population, returns what exists.
	assert set(tracker.top_k(10)) == {'fast', 'slow', 'flaky'}
	# k=0 returns empty; negative also returns empty.
	assert tracker.top_k(0) == []
	assert tracker.top_k(-1) == []


def test_tracker_recommend_filters_by_threshold() -> None:
	tracker = SkillFitnessTracker()
	for _ in range(3):
		tracker.record('reliable', success=True, latency_ms=100)
	tracker.record('broken', success=False, error='500')
	tracker.record('broken', success=False, error='500')
	# reliable > 0.5 belief, broken far below.
	survivors = tracker.recommend(['reliable', 'broken'], min_score=0.5)
	assert survivors == ['reliable']
	# Input order preserved among survivors.
	survivors = tracker.recommend(['broken', 'reliable'], min_score=0.5)
	assert survivors == ['reliable']


def test_tracker_recommend_include_unseen_default_true() -> None:
	tracker = SkillFitnessTracker()
	tracker.record('known', success=True, latency_ms=100)
	# 'unseen' has never been recorded — default keeps it (no evidence != bad evidence).
	assert tracker.recommend(['known', 'unseen'], min_score=0.5) == ['known', 'unseen']
	# Explicit False filters unseen skills out.
	assert tracker.recommend(['known', 'unseen'], min_score=0.5, include_unseen=False) == ['known']


def test_tracker_reset_clears_state() -> None:
	tracker = SkillFitnessTracker()
	tracker.record('x', success=True, latency_ms=100)
	assert tracker.fitness('x') is not None
	tracker.reset()
	assert tracker.fitness('x') is None
	assert tracker.invocations('x') == 0
	assert tracker.ranked() == []


def test_mass_function_json_roundtrip() -> None:
	original = MassFunction.from_score(0.9, confidence=0.65)
	serialized = original.to_dict()
	# Wire format: sorted-comma-joined strings mapped to floats.
	assert all(isinstance(k, str) and isinstance(v, float) for k, v in serialized.items())
	# Full-frame key is sorted alphabetically.
	assert 'HIGH,LOW,MID' in serialized
	restored = MassFunction.from_dict(json.loads(json.dumps(serialized)))
	assert restored.belief() == pytest.approx(original.belief())
	assert restored.plausibility() == pytest.approx(original.plausibility())
	assert restored.expected_value() == pytest.approx(original.expected_value())


def test_tracker_json_roundtrip() -> None:
	tracker = SkillFitnessTracker()
	tracker.record('a', success=True, latency_ms=100)
	tracker.record('a', success=True, latency_ms=200)
	tracker.record('b', success=False, error='blocked')
	blob = json.dumps(tracker.to_dict())
	restored = SkillFitnessTracker.from_dict(json.loads(blob))
	assert restored.invocations('a') == 2
	assert restored.invocations('b') == 1
	a_before = tracker.fitness('a')
	a_after = restored.fitness('a')
	assert a_before is not None and a_after is not None
	assert a_after.belief() == pytest.approx(a_before.belief())


def test_tracker_from_dict_ignores_unknown_keys() -> None:
	restored = SkillFitnessTracker.from_dict({'fitness': {}, 'unrelated': 'ignored'})
	assert restored.fitness('nope') is None


def test_cli_reads_jsonl_and_ranks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
	records = [
		{'skill_id': 'reliable', 'success': True, 'latency_ms': 100},
		{'skill_id': 'reliable', 'success': True, 'latency_ms': 100},
		{'skill_id': 'flaky', 'success': False, 'error': 'oops'},
		{'skill_id': 'flaky', 'success': True, 'latency_ms': 500},
		'',  # Blank line — should be skipped without error.
	]
	stdin_text = '\n'.join(json.dumps(r) if r else '' for r in records)
	# Feed stdin via monkeypatching. Also verify --save writes valid state.
	save_path = tmp_path / 'state.json'
	original_stdin = sys.stdin
	sys.stdin = io.StringIO(stdin_text)
	try:
		exit_code = _cli(['--mode', 'belief', '--save', str(save_path)])
	finally:
		sys.stdin = original_stdin
	assert exit_code == 0
	captured = capsys.readouterr()
	lines = [line for line in captured.out.splitlines() if line.strip()]
	assert len(lines) == 2
	first_skill = lines[0].split('\t')[-1]
	assert first_skill == 'reliable'
	# Saved state round-trips.
	saved = json.loads(save_path.read_text())
	restored = SkillFitnessTracker.from_dict(saved)
	assert restored.invocations('reliable') == 2
	assert restored.invocations('flaky') == 2


def test_cli_top_limits_output(capsys: pytest.CaptureFixture[str]) -> None:
	stdin_text = '\n'.join(json.dumps({'skill_id': f's{i}', 'success': True, 'latency_ms': 100 * i}) for i in range(1, 6))
	original_stdin = sys.stdin
	sys.stdin = io.StringIO(stdin_text)
	try:
		exit_code = _cli(['--top', '2'])
	finally:
		sys.stdin = original_stdin
	assert exit_code == 0
	captured = capsys.readouterr()
	lines = [line for line in captured.out.splitlines() if line.strip()]
	assert len(lines) == 2


def test_cli_skips_malformed_lines(capsys: pytest.CaptureFixture[str]) -> None:
	stdin_text = '\n'.join(
		[
			'{not valid json}',
			json.dumps({'no_skill_id': True}),
			json.dumps({'skill_id': 'ok', 'success': True, 'latency_ms': 100}),
		]
	)
	original_stdin = sys.stdin
	sys.stdin = io.StringIO(stdin_text)
	try:
		exit_code = _cli([])
	finally:
		sys.stdin = original_stdin
	assert exit_code == 0
	captured = capsys.readouterr()
	# Warnings for malformed lines went to stderr.
	assert 'malformed JSON' in captured.err
	assert 'without skill_id' in captured.err
	# The one valid record still ranked.
	assert 'ok' in captured.out


def test_cli_via_subprocess_end_to_end(tmp_path: Path) -> None:
	"""Real subprocess invocation — confirms `python -m browser_use.skills.fitness` works."""
	stdin_text = '\n'.join(json.dumps({'skill_id': sid, 'success': True, 'latency_ms': 100}) for sid in ('alpha', 'beta'))
	proc = subprocess.run(
		[sys.executable, '-m', 'browser_use.skills.fitness', '--mode', 'belief'],
		input=stdin_text,
		capture_output=True,
		text=True,
		timeout=30,
	)
	assert proc.returncode == 0, proc.stderr
	lines = [line for line in proc.stdout.splitlines() if line.strip()]
	assert len(lines) == 2
	assert {line.split('\t')[-1] for line in lines} == {'alpha', 'beta'}


def test_fitness_import_does_not_load_sdk() -> None:
	"""Importing fitness alone must not drag the browser-use SDK / pydantic-heavy chain.

	This is what makes standalone / cross-platform use viable. If someone adds an
	eager import chain that pulls in browser_use_sdk from fitness.py, this fails.
	"""
	code = (
		'import sys, importlib\n'
		'for m in list(sys.modules):\n'
		"    if m == 'browser_use' or m.startswith('browser_use.'):\n"
		'        sys.modules.pop(m, None)\n'
		'importlib.import_module("browser_use.skills.fitness")\n'
		'sdk_loaded = any(m.startswith("browser_use_sdk") for m in sys.modules)\n'
		"print('sdk_loaded=' + ('true' if sdk_loaded else 'false'))\n"
	)
	proc = subprocess.run(
		[sys.executable, '-c', code],
		capture_output=True,
		text=True,
		timeout=30,
	)
	assert proc.returncode == 0, proc.stderr
	assert 'sdk_loaded=false' in proc.stdout, f'browser_use_sdk was loaded transitively: {proc.stdout}'


def _find_free_port() -> int:
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.bind(('127.0.0.1', 0))
		return sock.getsockname()[1]


def _http_json(method: str, url: str, body: object | None = None) -> tuple[int, object]:
	data = None if body is None else json.dumps(body).encode('utf-8')
	req = urllib.request.Request(url, data=data, method=method)
	if data is not None:
		req.add_header('Content-Type', 'application/json')
	try:
		with urllib.request.urlopen(req, timeout=5) as resp:
			return resp.status, json.loads(resp.read().decode('utf-8'))
	except urllib.error.HTTPError as e:
		return e.code, json.loads(e.read().decode('utf-8'))


@pytest.fixture
def fitness_server(tmp_path: Path):
	"""Start _serve on a free port in a background thread; yield (base_url, tracker, save_path)."""
	tracker = SkillFitnessTracker()
	port = _find_free_port()
	save_path = tmp_path / 'state.json'
	thread = threading.Thread(
		target=_serve,
		args=(tracker,),
		kwargs={'host': '127.0.0.1', 'port': port, 'save_path': str(save_path)},
		daemon=True,
	)
	thread.start()
	# Poll /health until the server is up (500ms cap).
	base_url = f'http://127.0.0.1:{port}'
	deadline = time.monotonic() + 0.5
	while time.monotonic() < deadline:
		try:
			status, _ = _http_json('GET', f'{base_url}/health')
			if status == 200:
				break
		except (urllib.error.URLError, ConnectionRefusedError):
			time.sleep(0.02)
	else:
		pytest.fail('fitness server did not become ready within 500ms')
	yield base_url, tracker, save_path
	# Best-effort shutdown — the thread is a daemon so it dies with the test process anyway.


def test_http_health(fitness_server) -> None:
	base_url, _, _ = fitness_server
	status, body = _http_json('GET', f'{base_url}/health')
	assert status == 200
	assert body == {'status': 'ok'}


def test_http_record_then_ranked_and_persist(fitness_server) -> None:
	base_url, tracker, save_path = fitness_server
	# Record three fast successes for 'reliable' and one failure for 'flaky'.
	for _ in range(3):
		status, mf = _http_json('POST', f'{base_url}/record', {'skill_id': 'reliable', 'success': True, 'latency_ms': 100})
		assert status == 200
		assert isinstance(mf, dict)
	status, _ = _http_json('POST', f'{base_url}/record', {'skill_id': 'flaky', 'success': False, 'error': 'boom'})
	assert status == 200
	# Ranked endpoint puts reliable first under belief mode.
	status, ranked = _http_json('GET', f'{base_url}/ranked?mode=belief')
	assert status == 200
	assert isinstance(ranked, list)
	assert ranked[0][0] == 'reliable'
	# Auto-persistence: save_path was written on every mutation.
	saved = json.loads(save_path.read_text())
	restored = SkillFitnessTracker.from_dict(saved)
	assert restored.invocations('reliable') == 3
	assert restored.invocations('flaky') == 1


def test_http_fitness_endpoint_and_404(fitness_server) -> None:
	base_url, _, _ = fitness_server
	_http_json('POST', f'{base_url}/record', {'skill_id': 'seen', 'success': True, 'latency_ms': 100})
	status, mf = _http_json('GET', f'{base_url}/fitness/seen')
	assert status == 200
	assert isinstance(mf, dict)
	status, body = _http_json('GET', f'{base_url}/fitness/never-seen')
	assert status == 404
	assert 'unknown skill_id' in body['error']  # type: ignore[index]


def test_http_state_get_and_replace(fitness_server) -> None:
	base_url, _, _ = fitness_server
	_http_json('POST', f'{base_url}/record', {'skill_id': 'a', 'success': True, 'latency_ms': 100})
	status, state = _http_json('GET', f'{base_url}/state')
	assert status == 200
	assert 'a' in state['invocations']  # type: ignore[index]
	# Replace state with a fresh snapshot.
	fresh = SkillFitnessTracker()
	fresh.record('b', success=True, latency_ms=200)
	status, body = _http_json('POST', f'{base_url}/state', fresh.to_dict())
	assert status == 200 and body == {'replaced': True}
	status, state_after = _http_json('GET', f'{base_url}/state')
	assert 'a' not in state_after['invocations']  # type: ignore[index]
	assert 'b' in state_after['invocations']  # type: ignore[index]


def test_http_reset(fitness_server) -> None:
	base_url, _, _ = fitness_server
	_http_json('POST', f'{base_url}/record', {'skill_id': 'x', 'success': True, 'latency_ms': 100})
	status, body = _http_json('POST', f'{base_url}/reset')
	assert status == 200 and body == {'reset': True}
	status, ranked = _http_json('GET', f'{base_url}/ranked')
	assert status == 200 and ranked == []


def test_http_top_k(fitness_server) -> None:
	base_url, _, _ = fitness_server
	for sid in ('a', 'b', 'c', 'd'):
		_http_json('POST', f'{base_url}/record', {'skill_id': sid, 'success': True, 'latency_ms': 100})
	status, top = _http_json('GET', f'{base_url}/top_k?mode=belief&k=2')
	assert status == 200
	assert isinstance(top, list) and len(top) == 2


def test_http_recommend(fitness_server) -> None:
	base_url, _, _ = fitness_server
	for _ in range(3):
		_http_json('POST', f'{base_url}/record', {'skill_id': 'good', 'success': True, 'latency_ms': 100})
	_http_json('POST', f'{base_url}/record', {'skill_id': 'bad', 'success': False, 'error': 'e'})
	# Default include_unseen=True keeps 'unseen' in the output.
	status, out = _http_json(
		'POST',
		f'{base_url}/recommend',
		{'candidates': ['good', 'bad', 'unseen'], 'min_score': 0.5},
	)
	assert status == 200
	assert out == ['good', 'unseen']
	# include_unseen=False drops it.
	status, out = _http_json(
		'POST',
		f'{base_url}/recommend',
		{'candidates': ['good', 'bad', 'unseen'], 'min_score': 0.5, 'include_unseen': False},
	)
	assert status == 200
	assert out == ['good']
	# Bad body → 400.
	status, _ = _http_json('POST', f'{base_url}/recommend', {'candidates': 'not-a-list'})
	assert status == 400


def test_http_bad_input_returns_400(fitness_server) -> None:
	base_url, _, _ = fitness_server
	# Missing skill_id.
	status, body = _http_json('POST', f'{base_url}/record', {'success': True})
	assert status == 400
	assert 'skill_id' in body['error']  # type: ignore[index]
	# Unknown mode.
	status, body = _http_json('GET', f'{base_url}/ranked?mode=nonsense')
	assert status == 400
	# Unknown route.
	status, _ = _http_json('GET', f'{base_url}/does-not-exist')
	assert status == 404


def test_agent_record_action_fitness_success() -> None:
	"""The Agent._record_action_fitness helper feeds the tracker on success."""
	from browser_use.agent.service import Agent
	from browser_use.agent.views import ActionResult

	tracker = SkillFitnessTracker()

	class _Shim:
		action_fitness_tracker = tracker

	# 250ms fake latency by lying about the start timestamp.
	start_ns = time.perf_counter_ns() - 250 * 1_000_000
	result = ActionResult(extracted_content='ok')
	# Agent._record_action_fitness reads only self.action_fitness_tracker — safe to call unbound.
	Agent._record_action_fitness(cast(Any, _Shim()), 'click_by_index', result, start_ns)

	mf = tracker.fitness('click_by_index')
	assert mf is not None
	assert mf.belief() > 0.5
	assert tracker.invocations('click_by_index') == 1


def test_agent_record_action_fitness_soft_failure() -> None:
	"""ActionResult.error set → tracker records a failure without an exception path."""
	from browser_use.agent.service import Agent
	from browser_use.agent.views import ActionResult

	tracker = SkillFitnessTracker()

	class _Shim:
		action_fitness_tracker = tracker

	Agent._record_action_fitness(
		cast(Any, _Shim()),
		'extract_content',
		ActionResult(error='no matching element'),
		time.perf_counter_ns(),
	)
	mf = tracker.fitness('extract_content')
	assert mf is not None
	# Failure → LOW singleton dominates → HIGH belief must be near zero.
	assert mf.belief() < 0.1


def test_agent_record_action_fitness_hard_exception() -> None:
	"""The exception path records with the exception's type + message."""
	from browser_use.agent.service import Agent

	tracker = SkillFitnessTracker()

	class _Shim:
		action_fitness_tracker = tracker

	Agent._record_action_fitness(
		cast(Any, _Shim()),
		'unstable_skill',
		None,
		time.perf_counter_ns(),
		exc=RuntimeError('kaboom'),
	)
	mf = tracker.fitness('unstable_skill')
	assert mf is not None
	assert tracker.invocations('unstable_skill') == 1


def test_agent_record_action_fitness_no_tracker_is_noop() -> None:
	"""When action_fitness_tracker is None, the helper is a zero-cost no-op."""
	from browser_use.agent.service import Agent
	from browser_use.agent.views import ActionResult

	class _Shim:
		action_fitness_tracker = None

	# Should not raise.
	Agent._record_action_fitness(cast(Any, _Shim()), 'anything', ActionResult(), time.perf_counter_ns())


def test_service_exposes_fitness_and_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
	"""SkillService should expose fitness() and ranked_by_fitness() and populate on record."""
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'test-not-called')
	from browser_use.skills import SkillService

	svc = SkillService(skill_ids=['abc'])
	# No calls yet.
	assert svc.fitness('abc') is None
	assert svc.ranked_by_fitness() == []

	# Simulate what execute_skill's tail would do — feed the tracker directly.
	svc._fitness_tracker.record('abc', success=True, latency_ms=250)
	svc._fitness_tracker.record('abc', success=True, latency_ms=250)
	mf = svc.fitness('abc')
	assert mf is not None
	assert mf.belief() > 0.6

	svc._fitness_tracker.record('def', success=False, error='blocked')
	ranking = svc.ranked_by_fitness('belief')
	names = [name for name, _ in ranking]
	assert names.index('abc') < names.index('def')
