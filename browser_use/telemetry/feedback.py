"""library_feedback: one event telling the Browser Use team what went wrong with browser-use itself. From the agent mid-run
(report_issue() in a cell), Python (browser_use.feedback), the CLI (`browser-use feedback`) or an MCP client
(browser_feedback). Sent by the usage-stats sender (service.py) to the same project under the same device id; no login or
API key. The message is scrubbed (stats.scrub): secrets, credentials, emails, URL queries and home folders always, the
task and typed text too for the agent.

The user's own call (python, cli) is consent: sent even with usage stats off. A coding agent running `browser-use
feedback` in the user's shell (the skill tells it to) is the user's tool doing what they installed it for: the same.
The agent's model and an MCP client's are not the user: with usage stats off they send nothing. Code they write runs
under BU_MODEL_CODE=1 (the REPL worker, the --cli-mcp server and what either starts): its browser_use.feedback() and
`browser-use feedback` send nothing and point it at report_issue() or browser_feedback. Best effort, not a boundary:
that code can unset the variable, and it can reach the network anyway; the flag only keeps the model off the user's
path by mistake."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from browser_use.telemetry.service import Job

CATEGORIES = ('bug', 'docs', 'missing', 'other')
MAX_MESSAGE = 2000  # characters
MAX_PER_RUN = 3  # report_issue() calls sent per Agent.run(), browser_feedback calls per MCP server process
OFF = 'Feedback is off (ANONYMIZED_TELEMETRY=false or `browser-use telemetry disable`): nothing was sent.'
SENT = 'Reported to the Browser Use team. Thanks; carry on.'
MODEL_CODE = 'From an agent cell use report_issue(...), from an MCP client the browser_feedback tool: nothing was sent.'
MCP_TOOL = {  # browser_feedback, on --cli-mcp and on the server that only reports why nothing can run (cli.py)
	'name': 'browser_feedback',
	'description': (
		'Tell the Browser Use team what went wrong with browser-use itself: a helper or tool that failed or misbehaved, '
		'docs or instructions that are wrong, a helper that is missing. Not for ordinary website problems. Say what you '
		'ran and what happened; never include secrets, keys, passwords or personal data.'
	),
	'input_schema': {
		'type': 'object',
		'properties': {
			'message': {'type': 'string', 'description': 'What you ran, what you expected and what happened'},
			'category': {'type': 'string', 'enum': list(CATEGORIES), 'default': 'bug'},
		},
		'required': ['message'],
	},
}


def capture(
	source: str,
	message: Any,
	category: Any = 'bug',
	*,
	consent: bool = False,
	secrets: dict | None = None,
	tasks: list[str] | None = None,
	typed: list[str] | None = None,
	**run: Any,
) -> Job | None:
	"""Queue one library_feedback event; its Job, or None when nothing was queued (no text, usage stats off without
	consent, or the user's path called from a model's code). Scrubbed in the telemetry thread, as agent_event: secrets
	(sensitive_data), each task and each typed text as placeholders when given. run: the agent's model, run_id, step
	and last_error_type."""
	from browser_use.telemetry.service import Job, telemetry

	text = message.strip() if isinstance(message, str) else ''
	if source in ('python', 'cli') and os.environ.get('BU_MODEL_CODE'):  # a model's report under the user's name
		return None
	sender = telemetry()
	if not text or not (consent or sender.enabled):
		return None
	kind = category if category in CATEGORIES else 'other'

	def build(steps: int, keys: int) -> dict[str, Any]:
		from browser_use.repl.session import secret_forms
		from browser_use.telemetry.stats import is_internal, scrub
		from browser_use.telemetry.views import FeedbackEvent
		from browser_use.utils import get_browser_use_version

		forms = secret_forms(secrets) if secrets else []
		clean = scrub(text, forms, MAX_MESSAGE, tasks or [], typed or ()) or ''
		return FeedbackEvent(get_browser_use_version(), source, clean, kind, is_internal(), **run).properties

	job = Job('library_feedback', build, consent=consent)
	sender.capture_run(job)
	return job


def feedback(message: str, category: str = 'bug') -> bool:
	"""Tell the Browser Use team what went wrong with browser-use: a bug, wrong docs, a missing feature. category: 'bug',
	'docs', 'missing' or 'other'. Sent in the background, also with usage stats off (you asked to send it); secrets,
	API keys, emails, URL queries and home folders in the text are replaced before it leaves. True if it was queued;
	False from an agent cell or an MCP client's code (they report with report_issue() or browser_feedback)."""
	return capture('python', message, category, consent=True) is not None


_mcp_sent = 0  # browser_feedback calls this process sent: one MCP server is one client session


def mcp_call(arguments: dict) -> tuple[str, bool]:
	"""browser_feedback -> (its text, is_error). The client's model is not the user: usage stats off sends nothing. At
	most MAX_PER_RUN per server process, as report_issue() per run: a model stuck in a loop reports once, not per turn."""
	global _mcp_sent
	message = arguments.get('message')
	if not isinstance(message, str) or not message.strip():
		return "Error: 'message' must be a non-empty string", True
	if _mcp_sent >= MAX_PER_RUN:
		return f'Already reported {MAX_PER_RUN} issues this session: nothing more was sent.', False
	if not capture('mcp', message, arguments.get('category', 'bug')):
		return OFF, False
	_mcp_sent += 1
	return SENT, False


class RunReports:
	"""report_issue() for one Agent: its REPL calls it (Repl(feedback=...)) and the Agent points it at each run (start).
	Holds no REPL or session, so an Agent dropped without close() still frees its worker."""

	def __init__(self) -> None:
		self.run_id, self.sent, self.model = '', 0, ''
		self.rec: Any = None  # the run's RunRecorder: the current step and the last failed cell's class
		self.stats: Any = None  # the run's RunStats: text typed in earlier cells
		self.tasks: list[str] = []
		self.secrets: dict = {}

	def start(self, run_id: str, rec: Any, model: str, tasks: list[str], secrets: dict) -> None:
		self.run_id, self.rec, self.model, self.tasks, self.secrets = run_id, rec, model, tasks, secrets
		self.sent, self.stats = 0, None

	def __call__(self, args: dict) -> str:
		"""args: the cell's message and category, and what it typed so far (never sent: scrub's <typed>)."""
		from browser_use.telemetry.service import telemetry

		if not telemetry().enabled:
			return OFF
		if self.sent >= MAX_PER_RUN:
			return f'Already reported {MAX_PER_RUN} issues this run: nothing more was sent.'
		steps = self.rec.steps if self.rec is not None else []
		errors = [s.err for s in steps if s.err]
		typed = [*(self.stats.typed if self.stats is not None else ()), *(t for t in args.get('typed') or () if t)]
		job = capture(
			'agent',
			args.get('message'),
			args.get('category'),
			secrets=self.secrets,
			tasks=self.tasks,
			typed=typed,
			model=self.model,
			run_id=self.run_id,
			step=len(steps),
			last_error_type=errors[-1] if errors else None,
		)
		if job is None:
			return 'report_issue(message) needs text: nothing was sent.'
		self.sent += 1
		return SENT
