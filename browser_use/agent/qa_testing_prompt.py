"""General QA-testing prompt helpers for browser agents."""

from __future__ import annotations

import os

QA_TESTING_SYSTEM_PROMPT = """\
## Generated Web App QA Protocol

When the task is to QA, test, or find bugs in a web app, act like a strict black-box QA tester.

Before finishing:
- Convert the user request into a small checklist of product claims to verify.
- Cover at least one happy path, one invalid or edge path, one state change, and one refresh/navigation persistence check when relevant.
- For create/edit/delete/submit/search/filter/sort flows, verify the postcondition in the visible product state, not just a toast, label, or button click.
- Try common generated-app failure modes: empty required fields, invalid numbers/dates/email, duplicate names, long text, stale validation, missing confirmation for destructive actions, lost data after refresh, broken detail/deep links, mobile overflow, and hidden primary actions.
- Use real browser interactions for verdicts. DOM/source inspection may support evidence, but do not mutate app state, framework internals, storage, CSS, or hidden fields to make a path pass.
- If a feature appears broken, try one alternate visible route once before reporting it. Distinguish app bugs from agent/tool limitations.
- Report only current-run evidence. Each bug should have repro steps, expected behavior, actual behavior, severity, and the URL/viewport or visible evidence.
- Match the requested final schema exactly. Do not finish with file paths or notes outside the requested answer.
"""


QA_TESTING_TASK_PREAMBLE = """\
General QA testing protocol for this run:
- Test as a skeptical black-box user, not just a happy-path demo.
- Verify real postconditions after actions, including persistence after reload/navigation when relevant.
- Include negative/edge cases such as empty, invalid, duplicate, long, stale, and destructive-action cases when relevant.
- Do not use hidden DOM/framework mutations to make the app pass.
- Before done, ensure the final answer exactly follows the requested schema and includes only current-run evidence.
"""


def looks_like_qa_testing_task(task: str) -> bool:
	"""Return True for broad web QA tasks without matching a specific benchmark."""
	task_lower = task.lower()
	qa_terms = (
		'qa',
		'test',
		'testing',
		'bug',
		'bugs',
		'regression',
		'checklist',
		'verify',
		'validation',
	)
	web_terms = (
		'web app',
		'website',
		'browser',
		'application',
		'app ',
		'ui',
		'page',
		'form',
		'workflow',
	)
	return any(term in task_lower for term in qa_terms) and any(term in task_lower for term in web_terms)


def qa_testing_skill_enabled(task: str, source: str | None = None) -> bool:
	"""Enable the general QA skill for eval/web QA tasks or by explicit env opt-in."""
	env_value = os.getenv('BROWSER_USE_QA_TESTING_SKILL', '').strip().lower()
	if env_value in {'1', 'true', 'yes', 'on'}:
		return True
	if env_value in {'0', 'false', 'no', 'off'}:
		return False
	return source == 'eval_platform' and looks_like_qa_testing_task(task)


def extend_with_qa_testing_system_prompt(existing: str | None, *, task: str, source: str | None = None) -> str | None:
	"""Append the QA protocol to the system prompt when applicable."""
	if not qa_testing_skill_enabled(task, source):
		return existing
	if existing:
		return f'{existing.rstrip()}\n\n{QA_TESTING_SYSTEM_PROMPT}'
	return QA_TESTING_SYSTEM_PROMPT


def task_with_qa_testing_preamble(task: str, *, source: str | None = None) -> str:
	"""Prepend compact QA guidance for runtimes without a native skill/system channel."""
	if not qa_testing_skill_enabled(task, source):
		return task
	if QA_TESTING_TASK_PREAMBLE in task:
		return task
	return f'{QA_TESTING_TASK_PREAMBLE}\n\nOriginal task:\n{task}'
