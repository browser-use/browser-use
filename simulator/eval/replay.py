"""Action-replay evaluation: can the recorded context reproduce each step offline?

Reload each step's exact recorded context (messages.json) and tool schema, ask the
model to predict the action again, and compare to what was actually taken. Measures
offline reproducibility of decisions, not task correctness. No browser.
"""

from __future__ import annotations

import json
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import TypeAdapter

from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from simulator.config import DEFAULT_MODEL
from simulator.eval.common import client, find_task_dirs

_MSGS = TypeAdapter(list[BaseMessage])


def _action_names(action_list) -> list[str]:
	names = []
	for a in action_list or []:
		if isinstance(a, dict):
			keys = [key for key, v in a.items() if v is not None]
			names.append(keys[0] if keys else next(iter(a), '?'))
	return names


async def _predict(judge: AsyncOpenAI, model: str, messages_bm, schema_obj: dict) -> dict:
	name = schema_obj['name']
	resp = await judge.chat.completions.create(
		model=model,
		messages=OpenAIMessageSerializer.serialize_messages(messages_bm),
		tools=[
			{
				'type': 'function',
				'function': {
					'name': name,
					'description': f'Return a JSON object of type {name}',
					'parameters': schema_obj['schema'],
				},
			}
		],
		tool_choice={'type': 'function', 'function': {'name': name}},
		temperature=0.2,
		frequency_penalty=0.3,
		max_completion_tokens=4096,
	)
	tc = resp.choices[0].message.tool_calls
	if not tc:
		raise RuntimeError('model returned no tool call')
	return json.loads(tc[0].function.arguments)


async def evaluate_replay(path: Path, model: str = DEFAULT_MODEL) -> list[dict]:
	task_dirs = find_task_dirs(path)
	if not task_dirs:
		raise SystemExit(f'No task folders with step_* found under {path}')
	judge = client()
	print(f'Replay-evaluating {len(task_dirs)} task(s) with model={model} (no web)')

	results = []
	for td in task_dirs:
		schema_obj = json.loads((td / 'tool_schema.json').read_text())
		print(f'\n=== {td.name} ===')
		per_step, matches = [], 0
		for sd in sorted(td.glob('step_*')):
			if not (sd / 'messages.json').exists():
				continue
			messages_bm = _MSGS.validate_python(json.loads((sd / 'messages.json').read_text())['messages'])
			recorded = json.loads((sd / 'output.json').read_text()) if (sd / 'output.json').exists() else {}
			rec_a = _action_names(recorded.get('action'))
			try:
				pred_a = _action_names((await _predict(judge, model, messages_bm, schema_obj)).get('action'))
				err = None
			except Exception as e:  # noqa: BLE001
				pred_a, err = [], str(e)[:160]
			match = bool(rec_a) and rec_a[:1] == pred_a[:1]
			matches += int(match)
			per_step.append({'step': sd.name, 'recorded': rec_a, 'predicted': pred_a, 'match': match, 'error': err})
			print(f'    {"OK " if match else "   "}{sd.name}: recorded={rec_a} predicted={pred_a}')
		n = len(per_step)
		print(f'    -> first-action match: {matches}/{n}')
		results.append({'task': td.name, 'n_steps': n, 'first_action_matches': matches, 'steps': per_step})
		(td / 'replay_eval.json').write_text(json.dumps(results[-1], ensure_ascii=False, indent=2))

	tot_m = sum(r['first_action_matches'] for r in results)
	tot_n = sum(r['n_steps'] for r in results)
	print('\n' + '=' * 64)
	print(f'REPLAY first-action match: {tot_m}/{tot_n} ({(tot_m / tot_n if tot_n else 0):.0%})')
	return results
