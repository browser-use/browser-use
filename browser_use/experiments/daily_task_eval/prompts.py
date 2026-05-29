from __future__ import annotations

from .models import TaskCard


def list_items(items: list[str]) -> list[str]:
	if not items:
		return ['- Not specified.']
	return [f'- {item}' for item in items]


def build_agent_task_prompt(task: TaskCard, scenario_id: str = 'normal', navigator_plan: str | None = None) -> str:
	from browser_use.agent.message_manager.utils import extract_navigator_step_focus

	scenario = next((failure for failure in task.failure_modes if failure.id == scenario_id), None)
	lines = [
		f'Task: {task.name}',
		'',
		task.task_prompt,
		'',
		'Starting conditions:',
		*list_items(task.starting_conditions),
		'',
		'Success criteria:',
		*list_items(task.success_criteria),
		'',
		'Forbidden actions:',
		*list_items(task.forbidden_actions),
		'',
		'Recovery rules:',
		*list_items(task.agent_recovery_rules),
	]
	if scenario:
		lines.extend(
			[
				'',
				f'Failure scenario under test: {scenario.name}',
				'Expected recovery:',
				*list_items(scenario.expected_recovery),
			]
		)
	if navigator_plan:
		_focus, plan_body = extract_navigator_step_focus(navigator_plan)
		lines.extend(
			[
				'',
				'Navigator plan:',
				plan_body,
				'',
				'Use the navigator plan as guidance, but trust the live page state over stale assumptions.',
			]
		)
	lines.extend(
		[
			'',
			'When the task is complete, call done with a concise final result. '
			'If blocked, call done with success=False and explain the blocker.',
			'',
			'Early-finish rule (do not over-verify):',
			'- The moment you have collected enough information to satisfy ALL items in `Success criteria` above, your VERY NEXT action MUST be `done`. Do not re-screenshot, do not refresh the page, do not re-extract the same data, do not click around to "double-check".',
			'- If a single `extract_structured_data` (or `extract_url`) call already returned the records that meet Success criteria, treat that as the authoritative answer — copy fields verbatim into `done.text` and finish.',
			'- Map / dashboard / video-heavy SPAs (e.g. map.baidu.com, amap.com) are expensive to screenshot. Once the required data is in your memory, additional steps on these pages tend to time out the browser screenshot watchdog (~15s) and waste budget; finish immediately instead.',
			'- "Not visible" is an acceptable answer for optional fields (e.g. opening hours, distance) when the visible page genuinely does not show them; do not loop trying to discover them.',
			'',
			'Hard stop (avoid retry loops):',
			'- If the site requires login, QR login, CAPTCHA, or phone/SMS verification to search, open listings, or view item detail — and no credentials appear in this task — do not repeatedly attempt the same path.',
			'- After one failed attempt on that path (or after one alternative read-only path such as only the homepage), if still blocked by auth, immediately call done with success=False naming the blocker (e.g. login required).',
			'',
			'Network reachability (CN environment):',
			'- This experiment runs from a network where google.com / google.com.hk / scholar.google.com / google maps / bing.com international / facebook / twitter / etc. are NOT reachable. Navigating to them stalls the browser and triggers ScreenshotWatchdog timeouts.',
			'- If a navigate result is net::ERR_NETWORK_CHANGED, net::ERR_TIMED_OUT, net::ERR_CONNECTION_RESET, or no DOM appears within ~15 seconds, abandon that domain immediately and DO NOT retry the same domain in this run.',
			'- Prefer CN-reachable starting points: baidu.com, map.baidu.com, amap.com, jd.com, taobao.com, dianping.com, weibo.com, zhihu.com, arxiv.org (usually OK), semanticscholar.org (usually OK).',
			'- If the task prompt explicitly mandates a specific starting URL, follow it; only fall back when that mandated URL itself becomes unreachable.',
		]
	)
	return '\n'.join(lines)


def build_navigator_prompt(task: TaskCard, scenario_id: str = 'normal') -> str:
	scenario = next((failure for failure in task.failure_modes if failure.id == scenario_id), None)
	lines = [
		'Create an execution plan for a browser automation agent.',
		'You are the navigator, not the executor. Do not claim that you opened the browser.',
		'',
		'EFFICIENCY RULES (highest priority — apply BEFORE drafting the step-by-step plan):',
		'- The executor has a tool `extract_structured_data` that pulls all required fields',
		'  from the CURRENT page in a single call (works on search-results lists, map listings,',
		'  table rows, paginated lists). It returns structured records with text fields and link hrefs.',
		'- If the task is to collect N items and a list / search-results / map-listing view is',
		'  expected to show those N items with all required fields visible (title, url, phone,',
		'  address, hours, identifier, etc.), plan the SHORT path:',
		'    navigate -> (optional search / filter / sort) -> extract_structured_data -> done.',
		'  Do NOT plan to open each item individually, do NOT plan write_file per item, and do',
		'  NOT plan go_back loops, unless a required field is confirmed missing from the list view.',
		'- Multi-page deep-dive paths (per-item detail click + go_back) should only appear in the',
		'  plan when (a) the list view structurally cannot contain the required field (e.g. BibTeX',
		'  export needs the paper page, full address detail needs the POI page), or (b) the task',
		'  explicitly requires per-item interaction (forms, downloads, citation copy).',
		'- Keep the plan SHORT: aim for ≤ 6 step bullets in "Step-by-step plan". A long plan',
		'  becomes stale fast; the executor will be re-shown your plan on every step, so noise here',
		'  permanently biases later actions.',
		'',
		'MANDATORY: Start your reply with this exact XML block (first characters of your answer), before any markdown headings.',
		'Put 1–3 short lines inside: only the NEXT concrete sub-goal the executor should achieve (no action JSON, no tool syntax).',
		'<current_step_focus>',
		'Your sub-goal lines here (replace this whole inner block).',
		'</current_step_focus>',
		'',
		'After that block, return concise markdown with these sections: Assumptions, Step-by-step plan, Recovery plan, Stop conditions.',
		'',
		f'Task id: {task.id}',
		f'Task name: {task.name}',
		'',
		'Task prompt:',
		task.task_prompt,
		'',
		'Starting conditions:',
		*list_items(task.starting_conditions),
		'',
		'Success criteria:',
		*list_items(task.success_criteria),
		'',
		'Forbidden actions:',
		*list_items(task.forbidden_actions),
		'',
		'Existing recovery rules:',
		*list_items(task.agent_recovery_rules),
	]
	if scenario:
		lines.extend(
			[
				'',
				f'Failure scenario under test: {scenario.name}',
				'Failure setup notes:',
				*list_items(scenario.setup_notes),
				'Expected recovery:',
				*list_items(scenario.expected_recovery),
			]
		)
	return '\n'.join(lines)

