"""Context- and output-length stats over a captured run (text only, no images).

Walks a run directory (either ``<run_dir>/data/<source>__<id>/`` or task folders
directly under ``<run_dir>``) and reports token counts per domain, overall, and by
step index — for the LLM **input context** (``context``) or the LLM **output**
(``output``). Images are excluded; tokens use ``tiktoken`` as a tokenizer-agnostic
proxy (Qwen's own tokenizer differs in absolute counts but the relative picture holds).

	python -m simulator.scripts.trajectory_stats context simulator/runs/my_run
	python -m simulator.scripts.trajectory_stats output  simulator/runs/my_run

context: total = system prompt + agent-history text; "history" column drops the
	(constant) system prompt to isolate the page-driven part.
output : text = thinking + evaluation_previous_goal + memory + next_goal; "full" adds
	the structured action/plan; "thinking" is the free-form reasoning alone.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

# cl100k_base: consistent proxy for Qwen's tokenizer; change here to retokenize.
ENCODING = 'cl100k_base'
NL_FIELDS = ('thinking', 'evaluation_previous_goal', 'memory', 'next_goal')


def _enc():
	import tiktoken

	return tiktoken.get_encoding(ENCODING)


def _task_dirs(run_dir: Path) -> list[Path]:
	base = run_dir / 'data' if (run_dir / 'data').is_dir() else run_dir
	return sorted(d for d in base.glob('*__*') if d.is_dir() and (d / 'meta.json').exists())


def _context_tokens(enc, messages: list[dict]) -> tuple[int, int]:
	"""(total_text, history_text) tokens; history = non-system text, image excluded."""
	system = hist = 0
	for m in messages:
		role, content = m.get('role'), m.get('content')
		got = 0
		if isinstance(content, str):
			got = len(enc.encode(content))
		elif isinstance(content, list):
			for p in content:
				if isinstance(p, dict) and p.get('type') != 'image_url' and 'text' in p:
					got += len(enc.encode(p.get('text') or ''))
		if role == 'system':
			system += got
		else:
			hist += got
	return system + hist, hist


def _output_tokens(enc, o: dict) -> tuple[int, int, int]:
	"""(text_only, full, thinking) tokens for one parsed structured completion."""
	text_only = len(enc.encode('\n'.join(str(o.get(f) or '') for f in NL_FIELDS)))
	full = len(enc.encode(json.dumps(o, ensure_ascii=False)))
	thinking = len(enc.encode(str(o.get('thinking') or '')))
	return text_only, full, thinking


def _records(run_dir: Path, mode: str) -> tuple[list[dict], dict[str, set]]:
	enc = _enc()
	recs: list[dict] = []
	tasks: dict[str, set] = defaultdict(set)
	for td in _task_dirs(run_dir):
		meta = json.loads((td / 'meta.json').read_text())
		dom, src = meta.get('site'), meta.get('source')
		tasks[dom].add(td.name)
		for sd in sorted(td.glob('step_*')):
			if mode == 'context':
				mp = sd / 'messages.json'
				if not mp.exists():
					continue
				try:
					msgs = json.loads(mp.read_text())['messages']
				except Exception:  # noqa: BLE001
					continue
				total, hist = _context_tokens(enc, msgs)
				extra = {'primary': total, 'history': hist}
			else:
				op = sd / 'output.json'
				if not op.exists():
					continue
				try:
					o = json.loads(op.read_text())
				except Exception:  # noqa: BLE001
					continue
				if not isinstance(o, dict):
					continue
				text_only, full, thinking = _output_tokens(enc, o)
				extra = {'primary': text_only, 'full': full, 'thinking': thinking}
			recs.append({'domain': dom, 'source': src, 'step': int(sd.name.split('_')[1]), **extra})
	return recs, tasks


def _pctile(xs: list[int], q: float) -> float:
	xs = sorted(xs)
	k = (len(xs) - 1) * q
	f = int(k)
	return xs[f] if f + 1 >= len(xs) else xs[f] + (xs[f + 1] - xs[f]) * (k - f)


def _agg(rs: list[dict], extra_keys: tuple[str, ...]) -> dict:
	prim = [r['primary'] for r in rs]
	out = {
		'n': len(rs),
		'mean': round(st.mean(prim)),
		'median': round(st.median(prim)),
		'p95': round(_pctile(prim, 0.95)),
		'max': max(prim),
	}
	for k in extra_keys:
		out[k] = round(st.mean([r[k] for r in rs]))
	return out


def _report(recs: list[dict], tasks: dict[str, set], extra_keys: tuple[str, ...], extra_hdr: str) -> None:
	ntasks = sum(len(v) for v in tasks.values())
	cols = '| mean | median | p95 | max ' + extra_hdr
	print(f'step-messages: {len(recs)} | tasks: {ntasks} | tokenizer: {ENCODING}\n')

	# per domain
	print('### per domain (+ overall)')
	print(f'| domain | tasks | steps {cols}|')
	print('|---|--:|--:|--:|--:|--:|--:|' + '--:|' * len(extra_keys))
	by_dom = defaultdict(list)
	for r in recs:
		by_dom[r['domain']].append(r)
	rows = [(d, _agg(rs, extra_keys)) for d, rs in by_dom.items()]
	for d, a in sorted(rows, key=lambda x: -x[1]['mean']):
		ex = ''.join(f' {a[k]} |' for k in extra_keys)
		print(f'| {d} | {len(tasks[d])} | {a["n"]} | {a["mean"]} | {a["median"]} | {a["p95"]} | {a["max"]} |{ex}')
	a = _agg(recs, extra_keys)
	ex = ''.join(f' {a[k]} |' for k in extra_keys)
	print(f'| **OVERALL** | {ntasks} | {a["n"]} | **{a["mean"]}** | {a["median"]} | {a["p95"]} | {a["max"]} |{ex}')

	# by step
	print('\n### by step index (overall)')
	print(f'| step | messages {cols}|')
	print('|--:|--:|--:|--:|--:|--:|' + '--:|' * len(extra_keys))
	by_step = defaultdict(list)
	for r in recs:
		by_step[r['step']].append(r)
	for s in sorted(by_step):
		a = _agg(by_step[s], extra_keys)
		ex = ''.join(f' {a[k]} |' for k in extra_keys)
		print(f'| {s} | {a["n"]} | {a["mean"]} | {a["median"]} | {a["p95"]} | {a["max"]} |{ex}')

	# source rollup
	print('\n### source rollup')
	print(f'| source | steps {cols}|')
	print('|---|--:|--:|--:|--:|--:|' + '--:|' * len(extra_keys))
	by_src = defaultdict(list)
	for r in recs:
		by_src[r['source']].append(r)
	for src in sorted(by_src):
		a = _agg(by_src[src], extra_keys)
		ex = ''.join(f' {a[k]} |' for k in extra_keys)
		print(f'| {src} | {a["n"]} | {a["mean"]} | {a["median"]} | {a["p95"]} | {a["max"]} |{ex}')


def main() -> None:
	ap = argparse.ArgumentParser(prog='python -m simulator.scripts.trajectory_stats')
	ap.add_argument('mode', choices=['context', 'output'])
	ap.add_argument('run_dir', type=Path, help='A captured run dir (with data/<source>__<id>/ or task folders).')
	a = ap.parse_args()
	recs, tasks = _records(a.run_dir, a.mode)
	if not recs:
		raise SystemExit(f'no {a.mode} records found under {a.run_dir}')
	if a.mode == 'context':
		_report(recs, tasks, ('history',), ' | mean history-only ')
	else:
		_report(recs, tasks, ('full', 'thinking'), ' | mean full | mean thinking ')


if __name__ == '__main__':
	main()
