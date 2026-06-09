"""WebVoyager task-success evaluation (the official protocol, reference-aware).

A multimodal judge sees the task, the agent's final answer, the reference answer
(ground truth, when available), and the last k screenshots, and returns
SUCCESS / NOT SUCCESS at temperature 0. Reads only captured files + screenshots;
never opens a browser.

The base system prompt is verbatim from WebVoyager (evaluation/auto_eval.py). We
additionally pass the reference answer when the task has one — WebVoyager ships
reference answers (reference_answer.json for the 643 web tasks; an inline "Final
answer" for the 90 GAIA tasks), and grounding the judge in them improves accuracy.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from openai import AsyncOpenAI

from simulator.config import DEFAULT_JUDGE_MODEL
from simulator.eval.common import client, find_task_dirs

WV_SYSTEM_PROMPT = """As an evaluator, you will be presented with three primary components to assist you in your role:

1. Web Task Instruction: This is a clear and specific directive provided in natural language, detailing the online activity to be carried out. These requirements may include conducting searches, verifying information, comparing prices, checking availability, or any other action relevant to the specified web service (such as Amazon, Apple, ArXiv, BBC News, Booking etc).

2. Result Screenshots: This is a visual representation of the screen showing the result or intermediate state of performing a web task. It serves as visual proof of the actions taken in response to the instruction.

3. Result Response: This is a textual response obtained after the execution of the web task. It serves as textual result in response to the instruction.

-- You DO NOT NEED to interact with web pages or perform actions such as booking flights or conducting searches on websites.
-- You SHOULD NOT make assumptions based on information not presented in the screenshot when comparing it to the instructions.
-- Your primary responsibility is to conduct a thorough assessment of the web task instruction against the outcome depicted in the screenshot and in the response, evaluating whether the actions taken align with the given instructions.
-- NOTE that the instruction may involve more than one task, for example, locating the garage and summarizing the review. Failing to complete either task, such as not providing a summary, should be considered unsuccessful.
-- NOTE that the screenshot is authentic, but the response provided by LLM is generated at the end of web browsing, and there may be discrepancies between the text and the screenshots.
-- Note the difference: 1) Result response may contradict the screenshot, then the content of the screenshot prevails, 2) The content in the Result response is not mentioned on the screenshot, choose to believe the content.

You should elaborate on how you arrived at your final evaluation and then provide a definitive verdict on whether the task has been successfully accomplished, either as 'SUCCESS' or 'NOT SUCCESS'."""

REFERENCE_GUIDANCE = """

You are additionally given a Reference Answer (ground truth). Use it as follows:
- If the reference type is 'golden', 'exact', or 'gaia', the agent's Result Response must match the reference answer to be SUCCESS.
- If the reference type is 'possible', the reference is one acceptable example; the response should be consistent with the task, the reference, and the screenshots.
- Real-time values (review counts, prices, dates, availability) may differ slightly from the reference; that is acceptable when the response is clearly current and on-topic."""


def _parse_verdict(text: str) -> bool | None:
	up = text.upper()
	if 'NOT SUCCESS' in up:
		return False
	if 'SUCCESS' in up:
		return True
	return None


async def judge_success(judge: AsyncOpenAI, model: str, task_dir: Path, k: int) -> dict:
	meta = json.loads((task_dir / 'meta.json').read_text())
	question = meta.get('question', '')
	answer = meta.get('answer') or '(the agent did not return a final answer)'
	ref = meta.get('reference_answer')
	ref_type = meta.get('reference_type')
	ref_notice = meta.get('reference_notice')
	shots = sorted(task_dir.glob('step_*/screenshot.*'))[-k:]

	text = f'TASK: {question}\n'
	if ref:
		text += f'Reference Answer (type={ref_type}): {ref}\n'
		if ref_notice:
			text += f'Note: {ref_notice}\n'
	text += f'Result Response: {answer}\n{len(shots)} screenshots at the end: '

	content: list[dict] = [{'type': 'text', 'text': text}]
	for p in shots:
		mime = 'image/jpeg' if p.suffix.lower() in ('.jpg', '.jpeg') else 'image/png'
		b64 = base64.b64encode(p.read_bytes()).decode()
		content.append({'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{b64}'}})
	content.append({'type': 'text', 'text': 'Your verdict:\n'})

	system = WV_SYSTEM_PROMPT + (REFERENCE_GUIDANCE if ref else '')
	verdict, reason, err = None, '', None
	try:
		resp = await judge.chat.completions.create(
			model=model,
			messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
			temperature=0.0,
			max_completion_tokens=1024,
		)
		reason = resp.choices[0].message.content or ''
		verdict = _parse_verdict(reason)
	except Exception as e:  # noqa: BLE001
		err = str(e)[:200]

	out = {
		'task': task_dir.name,
		'site': meta.get('site'),
		'source': meta.get('source'),
		'question': question,
		'answer': answer,
		'reference_answer': ref,
		'reference_type': ref_type,
		'used_reference': bool(ref),
		'screenshots_used': len(shots),
		'success': verdict,
		'judge_reasoning': reason,
		'error': err,
	}
	(task_dir / 'webvoyager_eval.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
	mark = {True: 'SUCCESS', False: 'NOT SUCCESS', None: 'UNKNOWN'}[verdict]
	ref_tag = 'ref' if ref else 'no-ref'
	print(f'  [{mark:11s}] ({ref_tag:6s}) {task_dir.name:28s} {question[:60]}' + (f'  ERR={err}' if err else ''))
	return out


async def evaluate_success(path: Path, model: str = DEFAULT_JUDGE_MODEL, k: int = 2) -> list[dict]:
	task_dirs = find_task_dirs(path)
	if not task_dirs:
		raise SystemExit(f'No task folders with step_* found under {path}')
	judge = client()
	print(f'WebVoyager success-judging {len(task_dirs)} task(s) | judge={model} | last {k} screenshot(s) (no web)\n')
	results = []
	for td in task_dirs:
		ef = td / 'webvoyager_eval.json'
		if ef.exists():  # resume: reuse a prior non-error verdict
			try:
				prev = json.loads(ef.read_text())
				if prev.get('error') is None and prev.get('success') is not None:
					results.append(prev)
					continue
			except Exception:  # noqa: BLE001
				pass
		results.append(await judge_success(judge, model, td, k))
	n_succ = sum(1 for r in results if r['success'] is True)
	n_ref = sum(1 for r in results if r['used_reference'])
	print('\n' + '=' * 64)
	print(
		f'TASK SUCCESS: {n_succ}/{len(results)} ({n_succ / len(results):.0%}) | reference answer used for {n_ref}/{len(results)}'
	)
	return results
