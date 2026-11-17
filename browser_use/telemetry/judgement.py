"""library_judgement: one event per judged or self-reported run, with the same fields from every Browser Use surface.
The Agent sends it after its judge (surface 'python', judge_source 'judge'), next to agent_event.judgement. The
browser-use CLI's report_run() (surface 'cli') and --cli-mcp's browser_report_run tool (surface 'cli-mcp') send what the
calling coding agent says about its own run (judge_source 'self'). It goes through the usage-stats sender (service.py)
and is usage telemetry, never consent: nothing is sent with usage stats off or with BROWSER_USE_OFFLINE=1. With
BROWSER_USE_ZDR=1 the texts are sent empty and texts_withheld is true (stats.judged). Texts are scrubbed (stats.scrub)
and cut to 300 chars, with at most 5 gotchas and 20 hostnames."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from browser_use.telemetry.service import Job

MAX_PER_PROCESS = 3  # self-reports sent per process: a model stuck in a loop reports once, not every turn
MAX_HOSTS = 20
SENT = 'Reported this run to the Browser Use team. Thanks.'
OFF = 'Usage stats are off (ANONYMIZED_TELEMETRY=false, `browser-use telemetry disable` or BROWSER_USE_OFFLINE=1): nothing was sent.'
GOTCHAS = (  # JUDGE_PROMPT's gotcha rules, shortened for a coding agent that reports its own run
	'Gotchas: at most 5 short lessons for the next agent about the sites, from what you observed (website behavior, tool '
	'or environment failures): the action or condition and the result you saw, a recovery only if it worked; no guesses. '
	"Never emails, names, account data, credentials, secrets or the task's own values; URLs are fine."
)
MCP_TOOL = {
	'name': 'browser_report_run',
	'description': (
		'Call once when the task is done (or abandoned): report honestly whether it succeeded and what you learned about '
		f'the sites, for the Browser Use team. {GOTCHAS}'
	),
	'input_schema': {
		'type': 'object',
		'properties': {
			'success': {'type': 'boolean', 'description': 'The whole task is done and the user would be satisfied'},
			'failure_reason': {'type': ['string', 'null'], 'description': 'Why it failed, in one line; null on success'},
			'gotchas': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 5, 'description': 'Up to 5 observed lessons'},
			'bot_block': {'type': 'boolean', 'default': False, 'description': 'You met a CAPTCHA, a bot check or a block'},
			'description': {'type': 'string', 'default': '', 'description': 'What you did and what came of it, 1-3 sentences'},
		},
		'required': ['success'],
	},
}

_sent = 0  # self-reports this process sent


def properties(
	surface: str,
	judge_source: str,
	judgement: dict[str, Any],
	*,
	hosts: Iterable[str] = (),
	model: str | None = None,
	run_id: str | None = None,
) -> dict[str, Any]:
	"""The event's properties from a judgement as stats.judged returns it (already scrubbed, or withheld)."""
	from browser_use.telemetry.stats import is_internal
	from browser_use.telemetry.views import LibraryJudgementEvent
	from browser_use.utils import get_browser_use_version

	return LibraryJudgementEvent(
		version=get_browser_use_version(),
		surface=surface,
		judge_source=judge_source,
		success=bool(judgement.get('success')),
		run_id=run_id or None,
		model=model or None,
		failure_reason=judgement.get('failure_reason') or None,
		description=judgement.get('description') or '',
		prompt_injection_detected=bool(judgement.get('prompt_injection_detected')),
		bot_block_or_captcha_detected=bool(judgement.get('bot_block_or_captcha_detected')),
		gotchas=list(judgement.get('gotchas') or []),
		hosts=list(hosts)[:MAX_HOSTS],
		cost_usd=judgement.get('cost_usd'),
		texts_withheld=bool(judgement.get('texts_withheld')),
		is_internal=is_internal(),
	).properties


def capture(build: Callable[[], dict[str, Any]]) -> Job | None:
	"""Queue one library_judgement event built by build() in the telemetry thread; None with usage stats off."""
	from browser_use.telemetry.service import Job, telemetry

	sender = telemetry()
	if not sender.enabled:
		return None
	job = Job('library_judgement', lambda steps, keys: build())
	sender.capture_run(job)
	return job


def report(
	surface: str,
	success: Any,
	failure_reason: Any = None,
	gotchas: Any = (),
	bot_block: Any = False,
	description: Any = '',
) -> tuple[str, bool]:
	"""A coding agent's report of its own run -> (the text it gets back, is_error). At most MAX_PER_PROCESS per process."""
	global _sent
	if not isinstance(success, bool):
		return "Error: 'success' must be true or false", True
	if failure_reason is not None and not isinstance(failure_reason, str):
		return "Error: 'failure_reason' must be a string or null", True
	if isinstance(gotchas, str) or not isinstance(gotchas, Iterable):
		return "Error: 'gotchas' must be a list of strings", True
	gotchas = list(gotchas)
	if not all(isinstance(g, str) for g in gotchas):
		return "Error: 'gotchas' must be a list of strings", True
	if not isinstance(bot_block, bool) or not isinstance(description, str):
		return "Error: 'bot_block' must be true or false and 'description' a string", True
	if _sent >= MAX_PER_PROCESS:
		return f'Already reported {MAX_PER_PROCESS} runs: nothing more was sent.', False
	answer = {
		'success': success,
		'failure_reason': failure_reason,
		'description': description,
		'prompt_injection_detected': False,
		'bot_block_or_captcha_detected': bot_block,
		'gotchas': gotchas,
	}

	def build() -> dict[str, Any]:
		from browser_use.telemetry.stats import MAX_ERROR, judged, scrub

		clean = judged(answer, None, lambda text: scrub(text, [], MAX_ERROR)) or {}
		return properties(surface, 'self', clean)

	if capture(build) is None:
		return OFF, False
	_sent += 1
	return SENT, False


def mcp_call(arguments: dict) -> tuple[str, bool]:
	"""browser_report_run on --cli-mcp -> (its text, is_error). As browser_feedback: the client's model is not the user,
	so usage stats off sends nothing."""
	get = arguments.get
	return report(
		'cli-mcp',
		get('success'),
		get('failure_reason'),
		get('gotchas') or (),
		False if get('bot_block') is None else get('bot_block'),
		get('description') or '',
	)


def report_run(
	success: bool,
	failure_reason: str | None = None,
	gotchas: Iterable[str] = (),
	bot_block: bool = False,
	description: str = '',
) -> str:
	"""Report this run to the Browser Use team once, when the task is done or abandoned: honest success, why it failed,
	up to 5 gotchas about the sites (what you observed, not guesses) and whether a CAPTCHA or bot check blocked you.
	Scrubbed of secrets, emails, URL queries and home folders; nothing is sent with usage stats off."""
	text, failed = report('cli', success, failure_reason, gotchas, bot_block, description)
	if failed:
		raise TypeError(text.removeprefix('Error: '))
	return text
