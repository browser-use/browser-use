"""General QA-testing prompt helpers for browser agents."""

from __future__ import annotations

import os

QA_TESTING_SYSTEM_PROMPT = """\
## Generated Web App QA Protocol

When the task is to QA, test, or find bugs in a web app, act like a strict black-box QA tester.

Operating loop:
1. Convert the request into product claims and surfaces before acting: admin/source form, public listing, detail page, filtered/search result, role-specific view, persisted/reloaded state, and external/deep-link destination.
2. For each claim, name the exact observable postcondition. A pass requires destination-state evidence, not merely a visible control, a filled form, a click, or a toast.
3. Use controlled test data where possible. After create/edit/submit, verify the data on the downstream user-facing surface, then navigate away or reload once for high-value persistence checks.
4. For search/filter/sort/listing claims, verify the result cards themselves: count, included/excluded items, visible fields, ordering, labels/tags, price/rating/date values, and empty-state behavior.
5. For forms and permissions, run at least one relevant negative probe: empty required field, invalid email/phone/number/date, duplicate submission/name/contact, past/future or reversed date, destructive confirmation, or role mismatch.
6. For links/navigation, open the resulting destination and verify it is the intended nonblank page, not just that an anchor or button exists.
7. If a feature appears broken, try one alternate visible route once before reporting it. Distinguish app bugs from agent/tool limitations.
8. Use DOM/source inspection only to support evidence or locate visible controls. Do not mutate app state, framework internals, storage, CSS, or hidden fields to make a path pass.

Verdict discipline:
- Scripted checklist tasks: mark an item pass only after verifying its exact postcondition; mark fail when the control exists but the downstream state is missing, stale, invalid, or incomplete.
- Open-ended QA tasks: spend most of the budget on high-risk generated-app failures: validation gaps, missing derived data, broken filters, duplicate handling, role leakage, nonfunctional detail/external links, missing save feedback, and lost state after reload.
- Report only current-run evidence. Each bug should have repro steps, expected behavior, actual behavior, severity, and the URL/viewport or visible evidence.
- Match the requested final schema exactly. If the task names required top-level keys, use only those keys and do not invent alternatives such as test_actions, rendering_quality, or functionality.
- Keep the run bounded: prefer 5-8 high-signal probes over exhaustive happy-path narration. Before calling done, check whether at least one probe covered validation, derived/listing state, navigation/link destination, and persistence/role/duplicate behavior when relevant to the app.
"""


QA_TESTING_TASK_PREAMBLE = """\
General QA testing protocol for this run:
- Test as a skeptical black-box user, not just a happy-path demo.
- Map each requested claim to the downstream surface that proves it: listing cards, detail page, search/filter results, role-specific UI, link destination, and persisted/reloaded state.
- For each checklist item, identify the exact observable postcondition before marking pass; a toast, button, or filled form is not enough.
- Include negative/edge cases such as empty, invalid email/phone/number/date, duplicate, stale, permission, and destructive-action cases when relevant.
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
