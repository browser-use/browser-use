"""Replay-mode LATENCY benchmark (no browser, no web).

Drives the TreeSparseAttention server with the *recorded* per-step contexts of a
captured run and measures inference latency under real batched serving:

- Sample ``task_num`` tasks from a run folder.
- Keep a pool of ``batch_size`` active tasks (continuous refill: when a task's
  trajectory ends, record its end-to-end latency and pull in the next task).
- Each iteration sends the current step's context of every active task to the
  server *concurrently in lockstep* — the server's scheduler batches them into a
  single batched prefill+decode (one inference over the whole batch) — then we
  wait for all and record the batch-step latency.
- Advance every task one step; repeat until ``task_num`` tasks are done.

Each replay step re-sends the FULL recorded context (which already includes that
step's growing history + screenshot), so every batched step is a fresh batched
prefill of ``batch_size`` long contexts + a grammar-constrained decode of the
action — exactly what the live agent pays per step. Decode is xgrammar-constrained
with each step's recorded JSON schema, matching the real serving run.

Records per-batch-step latency, per-task end-to-end latency, plus prefill/decode
token counts, throughput, and context lengths.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import TypeAdapter

from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from simulator.config import TSA_MODEL
from simulator.eval.common import client, find_task_dirs

_MSGS = TypeAdapter(list[BaseMessage])


@dataclass(slots=True)
class TaskReplay:
	"""One task's replayable steps + live cursor/accumulators."""

	name: str
	dir: Path
	step_files: list[Path]  # step_*/messages.json paths, in order
	response_format: dict  # xgrammar json_schema response_format
	start_idx: int = 0
	cur_idx: int = 0
	own_latency_ms: float = 0.0  # sum of this task's own request latencies
	e2e_latency_ms: float = 0.0  # wall-clock it experienced (sum of batch-step latencies)
	ctx_text_chars: list[int] = field(default_factory=list)
	completion_tokens: list[int] = field(default_factory=list)
	step_latency_ms: list[float] = field(default_factory=list)
	steps_done: int = 0

	@property
	def finished(self) -> bool:
		return self.cur_idx >= len(self.step_files)


def _load_task(td: Path, start_mode: str, rng: random.Random) -> TaskReplay | None:
	"""Build a TaskReplay from a task dir, or None if it has no usable steps/schema."""
	step_files = sorted(p / 'messages.json' for p in sorted(td.glob('step_*')) if (p / 'messages.json').exists())
	if not step_files:
		return None
	sp = td / 'tool_schema.json'
	if not sp.exists():
		return None
	try:
		schema_obj = json.loads(sp.read_text())
	except Exception:  # noqa: BLE001
		return None
	if 'schema' not in schema_obj:  # tool_schema.json stored an {'error': ...}
		return None
	rf = {
		'type': 'json_schema',
		'json_schema': {'name': schema_obj.get('name', 'AgentOutput'), 'strict': True, 'schema': schema_obj['schema']},
	}
	start = rng.randrange(len(step_files)) if start_mode == 'random' else 0
	return TaskReplay(name=td.name, dir=td, step_files=step_files, response_format=rf, start_idx=start, cur_idx=start)


async def _one_request(
	judge: AsyncOpenAI, model: str, msg_path: Path, response_format: dict, max_tokens: int, temperature: float
) -> dict:
	"""Replay a single step: send the recorded context, time the call, return latency + usage."""
	messages_bm = _MSGS.validate_python(json.loads(msg_path.read_text())['messages'])
	serialized = OpenAIMessageSerializer.serialize_messages(messages_bm)
	# Client-side context-size proxy (the server's usage.prompt_tokens is 0 and the
	# exact multimodal prefill length is only known server-side / in its log):
	# total text chars + number of image parts in the prompt.
	text_chars, n_images = 0, 0
	for m in serialized:
		c = m.get('content')
		if isinstance(c, str):
			text_chars += len(c)
		elif isinstance(c, list):
			for part in c:
				if part.get('type') == 'text':
					text_chars += len(part.get('text', '') or '')
				elif part.get('type') == 'image_url':
					n_images += 1
	t0 = time.perf_counter()
	try:
		resp = await judge.chat.completions.create(
			model=model,
			messages=serialized,
			response_format=response_format,
			temperature=temperature,
			max_completion_tokens=max_tokens,
		)
		dt = (time.perf_counter() - t0) * 1000.0
		u = resp.usage
		pt = getattr(u, 'prompt_tokens', 0) if u else 0
		return {
			'latency_ms': dt,
			'server_prompt_tokens': pt,  # server reports 0 (not populated); kept for completeness
			'ctx_text_chars': text_chars,
			'ctx_images': n_images,
			'completion_tokens': getattr(u, 'completion_tokens', None) if u else None,
			'finish_reason': resp.choices[0].finish_reason if resp.choices else None,
			'error': None,
		}
	except Exception as e:  # noqa: BLE001
		return {
			'latency_ms': (time.perf_counter() - t0) * 1000.0,
			'server_prompt_tokens': 0,
			'ctx_text_chars': text_chars,
			'ctx_images': n_images,
			'completion_tokens': None,
			'finish_reason': None,
			'error': str(e)[:200],
		}


async def measure_latency(
	run_dir: Path,
	task_num: int,
	batch_size: int,
	start_mode: str = 'zero',
	seed: int = 0,
	max_tokens: int = 1024,
	temperature: float = 0.0,
	top_k_label: str | None = None,
	out: Path | None = None,
) -> dict:
	task_dirs = find_task_dirs(run_dir)
	if not task_dirs:
		raise SystemExit(f'No task folders with step_* found under {run_dir}')

	rng = random.Random(seed)
	rng.shuffle(task_dirs)
	# Build replayable tasks until we have task_num usable ones.
	pool: list[TaskReplay] = []
	for td in task_dirs:
		if len(pool) >= task_num:
			break
		t = _load_task(td, start_mode, rng)
		if t is not None:
			pool.append(t)
	if not pool:
		raise SystemExit('No tasks with messages.json + tool_schema.json found')
	task_num = len(pool)
	batch_size = min(batch_size, task_num)

	judge = client()
	model = TSA_MODEL
	print(
		f'Replay-latency: {task_num} tasks | batch_size={batch_size} | start={start_mode} | '
		f'model={model} | top_k={top_k_label or "?"} | max_tokens={max_tokens}'
	)

	pending = list(pool)  # not yet activated
	active: list[TaskReplay] = []  # currently in the batch
	completed: list[TaskReplay] = []
	batch_steps: list[dict] = []

	def _fill():
		while len(active) < batch_size and pending:
			active.append(pending.pop(0))

	_fill()
	it = 0
	t_run0 = time.perf_counter()
	while active:
		it += 1
		# Send the current step of every active task concurrently -> one server batch.
		t0 = time.perf_counter()
		results = await asyncio.gather(
			*[_one_request(judge, model, t.step_files[t.cur_idx], t.response_format, max_tokens, temperature) for t in active]
		)
		batch_latency_ms = (time.perf_counter() - t0) * 1000.0

		rec_tasks = []
		for t, r in zip(active, results):
			t.own_latency_ms += r['latency_ms']
			t.e2e_latency_ms += batch_latency_ms  # lockstep: each task waits the whole batch step
			t.step_latency_ms.append(r['latency_ms'])
			t.ctx_text_chars.append(r['ctx_text_chars'])
			if r['completion_tokens'] is not None:
				t.completion_tokens.append(r['completion_tokens'])
			t.steps_done += 1
			rec_tasks.append({'task': t.name, 'step_idx': t.cur_idx, **r})
			t.cur_idx += 1

		comp = sum(r['completion_tokens'] or 0 for r in results)
		chars = sum(r['ctx_text_chars'] for r in results)
		imgs = sum(r['ctx_images'] for r in results)
		errs = sum(1 for r in results if r['error'])
		batch_steps.append(
			{
				'iter': it,
				'batch_size': len(active),
				'batch_latency_ms': batch_latency_ms,
				'sum_ctx_text_chars': chars,
				'sum_ctx_images': imgs,
				'sum_completion_tokens': comp,
				'e2e_tok_s_incl_prefill': (comp / (batch_latency_ms / 1000.0)) if batch_latency_ms > 0 else 0,
				'errors': errs,
				'tasks': rec_tasks,
			}
		)
		if it % 5 == 0 or errs:
			print(
				f'  iter {it:4d}: B={len(active)} batch_lat={batch_latency_ms:8.1f}ms '
				f'ctx~{chars // 1000}k_chars+{imgs}img decode_tok={comp:5d} '
				f'e2e_tok/s={comp / (batch_latency_ms / 1000.0):6.1f}' + (f' ERRORS={errs}' if errs else '')
			)

		# Retire finished tasks, refill from pending.
		for t in [t for t in active if t.finished]:
			completed.append(t)
		active = [t for t in active if not t.finished]
		_fill()

	total_wall_s = time.perf_counter() - t_run0

	# ---- aggregate ----
	import statistics as st

	bl = [b['batch_latency_ms'] for b in batch_steps]
	per_task = [
		{
			'task': t.name,
			'start_step': t.start_idx,
			'steps_replayed': t.steps_done,
			'e2e_latency_ms': round(t.e2e_latency_ms, 1),
			'own_latency_ms': round(t.own_latency_ms, 1),
			'mean_ctx_text_chars': round(st.mean(t.ctx_text_chars), 1) if t.ctx_text_chars else None,
			'mean_completion_tokens': round(st.mean(t.completion_tokens), 1) if t.completion_tokens else None,
			'mean_step_latency_ms': round(st.mean(t.step_latency_ms), 1) if t.step_latency_ms else None,
		}
		for t in completed
	]
	summary = {
		'meta': {
			'run_dir': str(run_dir),
			'task_num': task_num,
			'batch_size': batch_size,
			'start_mode': start_mode,
			'seed': seed,
			'model': model,
			'top_k_label': top_k_label,
			'max_tokens': max_tokens,
			'temperature': temperature,
			'total_wall_s': round(total_wall_s, 1),
			'num_batch_steps': len(batch_steps),
		},
		'aggregate': {
			'batch_latency_ms': {
				'mean': round(st.mean(bl), 1) if bl else 0,
				'median': round(st.median(bl), 1) if bl else 0,
				'p90': round(sorted(bl)[int(0.9 * len(bl))], 1) if bl else 0,
				'min': round(min(bl), 1) if bl else 0,
				'max': round(max(bl), 1) if bl else 0,
			},
			'task_e2e_latency_ms': {
				'mean': round(st.mean([t['e2e_latency_ms'] for t in per_task]), 1) if per_task else 0,
				'median': round(st.median([t['e2e_latency_ms'] for t in per_task]), 1) if per_task else 0,
			},
			'mean_ctx_text_chars_per_req': round(
				st.mean([b['sum_ctx_text_chars'] / max(b['batch_size'], 1) for b in batch_steps]), 1
			)
			if batch_steps
			else 0,
			'mean_decode_tokens_per_step': round(
				st.mean([b['sum_completion_tokens'] / max(b['batch_size'], 1) for b in batch_steps]), 1
			)
			if batch_steps
			else 0,
			'total_errors': sum(b['errors'] for b in batch_steps),
		},
		'per_task': per_task,
		'batch_steps': batch_steps,
	}

	print('\n' + '=' * 72)
	a = summary['aggregate']
	print(
		f'batch-step latency: mean={a["batch_latency_ms"]["mean"]}ms  median={a["batch_latency_ms"]["median"]}ms  '
		f'p90={a["batch_latency_ms"]["p90"]}ms  (n={len(batch_steps)} steps)'
	)
	print(
		f'task e2e latency:   mean={a["task_e2e_latency_ms"]["mean"]}ms  median={a["task_e2e_latency_ms"]["median"]}ms  (n={task_num} tasks)'
	)
	print(
		f'ctx ~{a["mean_ctx_text_chars_per_req"]:.0f} text-chars/req | decode ~{a["mean_decode_tokens_per_step"]:.0f} tok/step '
		f'| total wall: {total_wall_s:.1f}s | errors: {a["total_errors"]}'
	)

	if out is None:
		from datetime import datetime, timezone

		ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
		out = run_dir / f'latency_b{batch_size}_n{task_num}_{start_mode}_{ts}.json'
	out.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
	print(f'Saved -> {out}')
	return summary
