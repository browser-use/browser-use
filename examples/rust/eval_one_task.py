"""Run a single eval task locally with the brust runtime.

Usage:
    OPENAI_API_KEY=... GEMINI_API_KEY=... \
      EVALUATION_TOOL_URL=... EVALUATION_TOOL_SECRET_KEY=... \
      python examples/rust/eval_one_task.py <test_case_name> <task_index>

Pulls the task list from convex, runs task at <task_index>, prints the agent
final answer + cost + Laminar trace id + the comprehensive judge verdict
using gemini-3-flash-preview. Lets me iterate on prompt/agent changes without
a 5-min CI roundtrip per attempt.

Example:
    python examples/rust/eval_one_task.py WebBench_READ_v5 0
    python examples/rust/eval_one_task.py real_v8 3
"""

import asyncio
import os
import sys
from typing import Any

import requests

from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.rust import Agent


def _resolve_llm(model_name: str):
	"""Pick the right LLM class based on model name. Matches the pattern
	the eval pipeline uses so local + CI behave the same."""
	low = model_name.lower()
	if low.startswith('claude') or 'sonnet' in low or 'haiku' in low or 'opus' in low:
		from browser_use.llm.anthropic.chat import ChatAnthropic

		return ChatAnthropic(model=model_name)
	if low.startswith('gemini') or 'gemini' in low:
		from browser_use.llm.google.chat import ChatGoogle

		return ChatGoogle(model=model_name)
	if low.startswith('deepseek'):
		from browser_use.llm.deepseek.chat import ChatDeepSeek

		return ChatDeepSeek(model=model_name)
	if low.startswith('openrouter'):
		from browser_use.llm.openrouter.chat import ChatOpenRouter

		return ChatOpenRouter(model=model_name)
	return ChatOpenAI(model=model_name)


def fetch_task(test_case_name: str, task_index: int) -> dict[str, Any]:
	url = os.environ['EVALUATION_TOOL_URL'].rstrip('/') + '/api/getTestCase'
	r = requests.post(
		url,
		headers={
			'Authorization': f'Bearer {os.environ["EVALUATION_TOOL_SECRET_KEY"]}',
			'Content-Type': 'application/json',
		},
		json={'name': test_case_name},
		timeout=30,
	)
	r.raise_for_status()
	tasks = r.json()
	if not isinstance(tasks, list):
		raise RuntimeError(f'unexpected response shape: {type(tasks)}')
	if task_index >= len(tasks):
		raise IndexError(f'task_index {task_index} out of range, dataset has {len(tasks)} tasks')
	return tasks[task_index]


async def main() -> None:
	if len(sys.argv) < 3:
		print(__doc__, file=sys.stderr)
		sys.exit(2)

	test_case_name = sys.argv[1]
	task_index = int(sys.argv[2])

	task = fetch_task(test_case_name, task_index)
	task_id = task.get('task_id') or task.get('id') or 'unknown'
	task_text = task.get('confirmed_task') or task.get('task') or task.get('description') or ''
	website = task.get('website') or ''

	if website:
		task_text = f'{task_text}\nwebsite: {website}'

	print(f'== task {task_id} ({test_case_name} #{task_index}) ==')
	print(f'  {task_text[:200]}')
	print()

	# Force screenshots so the judge has visual context.
	os.environ.setdefault('BU_RUST_FORCE_SCREENSHOTS', '1')

	llm = _resolve_llm(os.environ.get('BU_MODEL', 'gpt-5'))
	agent = Agent(task=task_text, llm=llm)
	result = await agent.run(max_steps=int(os.environ.get('BU_MAX_STEPS', '15')))

	u = result.usage
	print('\n== run ==')
	print(f'  steps        : {len(result.steps)}')
	print(f'  duration     : {result.duration_seconds:.1f}s')
	print(f'  exit_code    : {result.exit_code}')
	print(f'  input tokens : {u.input_tokens}')
	print(f'  output tokens: {u.output_tokens}')
	print(f'  $ cost       : ${u.cost:.4f}')
	print(f'  model        : {u.model}')

	url = result.laminar_trace_url()
	if url:
		print(f'  laminar      : {url}')

	print('\n== final ==')
	print(f'  {(result.final_summary or "(no summary)")[:500]}')

	# Per-step screenshot count
	print('\n== per-step screenshot count ==')
	for i, step in enumerate(result.steps):
		print(f'  step {i:>2d} {step.tool:<14s} screenshots={len(step.screenshot_paths)}')

	# Run comprehensive judge (Gemini if available, else gpt-4o-mini)
	print('\n== judge ==')
	await agent._judge_and_log()
	j = result.judgement()
	if j:
		verdict = '✅ PASS' if j['verdict'] else '❌ FAIL'
		print(f'  {verdict}')
		if j.get('failure_reason'):
			print(f'  reason: {j["failure_reason"][:300]}')
		if j.get('reasoning'):
			print(f'  reasoning: {j["reasoning"][:500]}')
	else:
		print('  (no judgement returned)')


if __name__ == '__main__':
	asyncio.run(main())
