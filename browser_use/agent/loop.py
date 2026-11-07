"""Browser agent = Pydantic AI loop + one persistent Python REPL running browser-harness.

Learnings carried from browser-use-pi: deliver existing values (finish_from_repl), native screenshots
with only the last two kept, compaction (server-side, else a summary checkpoint), one delivery turn near budget,
partial results that survive timeouts, and a killable worker so a hung cell never kills the run.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, cast

from genai_prices import calc_price
from pydantic import Field, TypeAdapter, ValidationError
from pydantic_ai import Agent, BinaryContent, ModelRetry, RunContext, TextOutput, ToolOutput
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.direct import model_request
from pydantic_ai.exceptions import ToolRetryError
from pydantic_ai.messages import (
	ModelMessage,
	ModelRequest,
	ModelResponse,
	SystemPromptPart,
	TextPart,
	ThinkingPart,
	ToolReturnPart,
	UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.models.openai import OpenAIChatModel, OpenAICompaction, OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.settings import ToolOrOutput
from pydantic_ai.usage import UsageLimits
from pydantic_core import to_json, to_jsonable_python

from browser_use.agent.prompt import SYSTEM_PROMPT, secrets_prompt
from browser_use.agent.views import AgentHistoryList
from browser_use.ax import AX_PROMPT
from browser_use.llm import model_ref, skip_responses_transform
from browser_use.repl import Repl, check_mode, redact
from browser_use.repl.session import redact_forms, secret_forms
from browser_use.search import parse_usd
from browser_use.telemetry.stats import RunStats
from browser_use.tools import ActionResult, RemovedField

logger = logging.getLogger(__name__)
KEEP_IMAGE_RESULTS = 2
DELIVER_NOW = (
	'Budget nearly exhausted. Deliver the verified result now with finish/finish_from_repl. '
	'Reference saved files; explicitly list missing evidence. Do not perform more browser actions. '
	'If the task is not fully finished as requested, set success=false; else success=true.'  # 0.x last-step prompt
)
DELIVERY_REPAIR = (  # bu-pi src/agent.ts:560, verbatim except tool names
	'The run ended without a validated delivery. Use finish_from_repl for an existing result or finish for a concise '
	'answer. Preserve all verified records; report missing evidence honestly. Do not repeat browser actions. This is '
	'the single delivery repair turn.'
)
DELIVERY_TOOLS = ['finish_from_repl', 'finish']
NOT_RUN = 'Not run: this is the delivery-only turn. Call finish or finish_from_repl now with what you have.'
LINK = re.compile(r'\]\(<?([^)\s>]+)>?\)')  # markdown link targets
FILE = re.compile(r'`([\w./-]+\.(?:md|csv|json|jsonl|txt|tsv|xlsx|html|zip|pdf|png|jpe?g))`')  # `basket_brief.md`


@dataclass
class Session:
	"""Per-run state (Pydantic AI deps)."""

	repl: Repl
	timeout_s: float = 1700
	max_steps: int = 1000
	cell_timeout_s: float = 120
	vision: bool = True  # Agent(use_vision=False): screenshot() images are not sent to the model
	started: float = field(default_factory=time.monotonic)
	finalizing: bool = False
	checked_delivery: bool = False  # the delivery guard fires once; a second identical finish is accepted
	success: bool | None = None  # the verdict finish/finish_from_repl must give; None for a plain-text delivery
	messages: list[ModelMessage] = field(default_factory=list)
	after_tool: Callable[[str, dict, dict], Awaitable[None]] | None = None  # observer hook (evals)
	stats: RunStats = field(default_factory=RunStats)  # telemetry counts (TELEMETRY.md)
	finish_via: str | None = None  # finish | finish_from_repl | text: how the result was delivered
	budget_hit: str | None = None  # max_steps | timeout | browser_gone: what forced the delivery-only turn
	error_type: str | None = None  # class of the exception that ended the run
	checkpoint: ModelRequest | None = None  # Compaction: the message sent in place of messages[:covered]
	covered: int = 0
	compaction_failed: bool = False
	summaries: list[ModelResponse] = field(default_factory=list)  # summarizer responses, counted in usage and cost

	def delivery_at(self) -> float:
		"""Seconds into the run at which the delivery-only turn starts: 90% of the budget, or earlier on a short budget
		so the delivery request has up to 30 s (timeout=25 left it 2.5 s: the run ended empty)."""
		return self.timeout_s - max(0.1 * self.timeout_s, min(30.0, 0.5 * self.timeout_s))

	def partial(self) -> Any:
		"""The last checkpoint(..., partial=True), secret values redacted. None when missing or unreadable."""
		try:
			value = json.loads((self.repl.state / 'partial.json').read_text(encoding='utf-8'))['value']
		except (OSError, ValueError, KeyError, TypeError):  # recovery data must never turn a timeout into a crash
			return None
		return redact(value, self.repl.secrets)


async def python(ctx: RunContext[Session], code: str) -> list[Any]:
	"""Run Python in the persistent REPL (browser-harness helpers and raw cdp() pre-imported).

	Browser helpers are synchronous (do not await them); variables survive calls; the last expression is printed. Cell deadline
	applies; checkpoint small batches before it. screenshot() returns native images.
	"""
	started = time.monotonic()
	left = ctx.deps.delivery_at() - (started - ctx.deps.started)  # a cell never runs into the delivery turn's time
	r = await ctx.deps.repl.call('exec', code, min(ctx.deps.cell_timeout_s, max(left, 1.0)))
	ctx.deps.stats.add_cell(r, code, time.monotonic() - started)
	if r.get('browser_gone'):  # a model left without a browser went looking for another one (the user's own Chrome)
		ctx.deps.budget_hit = 'browser_gone'
	text = r['output']  # already cut to MAX_OUTPUT_CHARS by the worker
	if r['error']:
		text = f'{text}\nError: {r["error"]}'.strip()
	line = redact(next((x for x in code.splitlines() if x.strip()), ''), ctx.deps.repl.secrets)  # live progress (0.x 'Step N')
	error = (r['error'] or '').strip().splitlines()  # already redacted by Repl.call
	logger.info(f'step {ctx.run_step}: {line[:120]}' + (f' -> {error[-1][:200]}' if error else ''))
	if ctx.deps.after_tool:
		await ctx.deps.after_tool('python', {'code': code}, r)
	if r['images'] and not ctx.deps.vision:
		return [f'{text}\n(screenshot not shown: use_vision=False; read the page as text)'.strip()]
	shots = [BinaryContent(base64.b64decode(i['data']), media_type=i['media_type']) for i in r['images']]
	return [text or '(no output)', *shots]


def as_text(value: Any) -> str:
	"""A result as text: strings unchanged; models, dataclasses and lists of them as JSON (0.x model_dump_json)."""
	return value if isinstance(value, str) else to_json(value, fallback=str).decode()


def check_delivery(ctx: RunContext[Session], value: Any) -> None:
	"""One-shot repair: a placeholder or links to unwritten files."""
	s = ctx.deps
	text = as_text(value)
	if not s.checked_delivery:
		problem = None
		if not re.search(r'[^\W_]', text):  # '...', '' (a one-character answer like '7' is fine)
			problem = f'The result {text[:20]!r} is a placeholder, not the answer.'
		else:
			missing = sorted(
				{
					t
					for t in LINK.findall(text) + FILE.findall(text)
					if not re.match(r'^([a-z][\w+.-]*:|#|//)', t, re.I) and not (s.repl.workspace / t.split('#')[0]).exists()
				}
			)
			if missing:
				problem = f'These linked files do not exist in the workspace: {", ".join(missing[:10])}.'
		if problem:
			s.checked_delivery = True
			raise ModelRetry(
				f'{problem} Deliver the actual result: finish_from_repl with the existing records, or '
				'finish with the full answer inline. Do not repeat browser actions.'
			)


def _outputs(output_type: Any) -> list[Any]:
	adapter = TypeAdapter(output_type)

	def clean(ctx: RunContext[Session], value: Any) -> Any:
		"""The delivered value with secret values replaced, the instance too (result.output), redacted field by field
		before any serialization."""
		secrets = ctx.deps.repl.secrets
		if not secrets:
			return value
		if isinstance(value, str):
			return redact(value, secrets)
		plain = adapter.dump_python(value, mode='json')
		redacted = redact(plain, secrets)
		if redacted == plain:
			return value
		try:
			return adapter.validate_python(redacted)
		except ValidationError:  # a schema constraint rejects '<secret:name>': deliver the redacted plain data
			return redacted

	async def finish_from_repl(ctx: RunContext[Session], expression: str, success: bool | None = None):
		r = await ctx.deps.repl.call('eval', expression, ctx.deps.cell_timeout_s)
		if r['error']:
			raise ModelRetry(f'Expression failed: {r["error"][-2000:]}')
		if output_type is str:
			check_delivery(ctx, r['value'])
			value = r['value']
		else:
			try:
				value = adapter.validate_json(r['value'])
			except ValidationError as e:
				raise ModelRetry(f'Value does not match the result schema: {str(e)[:2000]}')
		ctx.deps.success, ctx.deps.finish_via = success, 'finish_from_repl'
		return clean(ctx, value)

	def finish(ctx: RunContext[Session], result, success: bool | None = None):
		check_delivery(ctx, result)
		ctx.deps.success, ctx.deps.finish_via = success, 'finish'
		return clean(ctx, result)

	def on_text(ctx: RunContext[Session], text: str):
		# Plain text keeps tool_choice=auto (as in bu-pi); a forced tool call every turn made finish() the only way to
		# stop and talk. A text reply ends the work. For a str result it is the answer (bu-pi repaired it: one extra
		# request on ~95% of gpt-6-luna runs). A structured result gets one delivery-only repair turn, then text is accepted.
		if output_type is not str and not ctx.deps.finalizing:
			ctx.deps.finalizing = True
			# Quoted: a compaction item at the end of this response replaces everything before it, this text included,
			# so the repair turn would otherwise not see the answer it is asked to deliver.
			raise ModelRetry(f'{DELIVERY_REPAIR}\n\nYour reply, not delivered yet:\n{text}')
		ctx.deps.finish_via = 'text'
		if output_type is str:
			check_delivery(ctx, text)
			return clean(ctx, text)
		try:
			return clean(ctx, adapter.validate_json(text))
		except ValidationError as e:
			raise ModelRetry(f'Deliver with finish or finish_from_repl; text does not match the result schema: {str(e)[:2000]}')

	verdict = Annotated[  # 0.x done(success) rule: an evidence-free verdict let a strict schema get values from memory
		bool | None,
		Field(
			description='true only when the result delivers what the task asked for, every value observed in this session; '
			'false when blocked, refused, partial, or a requested value was not found (never fill it from memory)'
		),
	]
	finish.__annotations__ = {'ctx': RunContext[Session], 'result': output_type, 'success': verdict, 'return': output_type}
	finish_from_repl.__annotations__ = {
		'ctx': RunContext[Session],
		'expression': str,
		'success': verdict,
		'return': output_type,
	}
	on_text.__annotations__ = {'ctx': RunContext[Session], 'text': str, 'return': output_type}
	return [
		TextOutput(on_text),
		ToolOutput(
			finish_from_repl,
			name='finish_from_repl',
			description=(
				'Deliver an existing value from the persistent REPL without printing or rewriting it. The Python '
				'expression must match the result schema of finish; for a string result use json.dumps(records) or an '
				'existing text variable. Evaluated once; ends the task after validation.'
			),
		),
		ToolOutput(
			finish,
			name='finish',
			description=(
				'Submit the verified final result. For data already in the REPL, prefer finish_from_repl to avoid '
				'rewriting it. This ends the task.'
			),
		),
	]


class BrowserLoop(AbstractCapability[Session]):
	"""Keep only recent screenshots; one delivery-only turn near the time/step budget or after a structured text reply."""

	async def before_model_request(self, ctx: RunContext[Session], request_context: ModelRequestContext):
		s = ctx.deps
		s.messages = ctx.messages
		pruned = _prune_images(ctx.messages)
		if pruned is not None:  # same pattern as ProcessHistory: new objects, persisted
			ctx.messages[:] = pruned
			request_context.messages = pruned.copy()
		if not s.finalizing:
			if ctx.run_step >= s.max_steps:  # 0.x: the last step is the forced done
				s.budget_hit = 'max_steps'
			elif time.monotonic() - s.started >= s.delivery_at():
				s.budget_hit = 'timeout'
			if s.budget_hit:
				s.finalizing = True
				ctx.enqueue(DELIVER_NOW)
		if s.finalizing:  # step settings were resolved before this hook: restrict this very request
			settings = dict(request_context.model_settings or {})
			settings['tool_choice'] = delivery_tool_choice(request_context.model, settings)
			request_context.model_settings = cast(Any, settings)
		return request_context

	async def wrap_tool_validate(self, ctx: RunContext[Session], *, call, tool_def, args, handler) -> Any:
		"""A tool call on a delivery-only turn is not run (wrap_tool_execute), so its arguments are not validated either:
		a rejected call would use up the tool's one retry and could end the run."""
		if ctx.deps.finalizing and tool_def.kind == 'function':
			return args
		return await handler(args)

	async def on_tool_execute_error(self, ctx: RunContext[Session], *, call, tool_def, args, error: Exception) -> Any:
		"""A custom tool (Tools) that raises returns the error to the model, which can recover, as a failing 0.x action
		did (ActionResult(error=...)); it never ends the run. ModelRetry and pydantic-ai's control flow never get here."""
		if call.tool_name == 'python' or tool_def.kind != 'function' or isinstance(error, RemovedField):
			raise error
		return ActionResult(error=f'{type(error).__name__}: {error}')

	async def wrap_tool_execute(self, ctx: RunContext[Session], *, call, tool_def, args, handler) -> Any:
		"""Custom tools (Tools) run in this process, so the worker's redaction never saw their results: redact them
		(strings, ActionResult and other models, nested values) and their retry messages before the model does."""
		if ctx.deps.finalizing and tool_def.kind == 'function':
			# The delivery-only turn withholds python where it cannot force finish (Claude), yet Claude still called it
			# (2/2 runs, one ended empty): refuse it instead of running more browser actions.
			return NOT_RUN
		secrets = ctx.deps.repl.secrets
		if call.tool_name == 'python' or tool_def.kind != 'function' or not secrets:
			return await handler(args)
		forms = secret_forms(secrets)
		try:
			result = await handler(args)
		except ToolRetryError as e:  # the tool's ModelRetry, already turned into the retry part
			raise ToolRetryError(replace(e.tool_retry, content=redact_forms(e.tool_retry.content, forms))) from None
		plain = result if isinstance(result, str) else to_jsonable_python(result, fallback=str)
		clean = redact_forms(plain, forms)
		return result if clean == plain else clean  # untouched (images, types) unless a secret was in it


class LazyCompaction(OpenAICompaction):
	"""Server-side compaction, requested only once the last request was past the threshold. context_management on every
	request made each call ~0.8 s slower at 45k tokens (bu-pi sends none)."""

	def get_model_settings(self):
		resolve, threshold = super().get_model_settings(), self.token_threshold or 0

		def settings(ctx: RunContext[Any]) -> Any:
			last = next((m.usage.input_tokens for m in reversed(ctx.messages) if isinstance(m, ModelResponse)), 0)
			return resolve(ctx) if resolve and last >= threshold else {}

		return settings


SUMMARY_SYSTEM = (  # Pi pi-coding-agent SUMMARIZATION_SYSTEM_PROMPT, verbatim
	'You are a context summarization assistant. Your task is to read a conversation between a user and an AI assistant, '
	'then produce a structured summary following the exact format specified.\n\nDo NOT continue the conversation. Do NOT '
	'respond to any questions in the conversation. ONLY output the structured summary.'
)
SUMMARY_PROMPT = (  # Pi SUMMARIZATION_PROMPT + bu-pi src/context.ts focus, verbatim except Python for JavaScript
	'The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM '
	'will use to continue the work.\n\nUse this EXACT format:\n\n## Goal\n[What is the user trying to accomplish? Can be '
	'multiple items if the session covers different tasks.]\n\n## Constraints & Preferences\n- [Any constraints, '
	'preferences, or requirements mentioned by user]\n- [Or "(none)" if none were mentioned]\n\n## Progress\n### Done\n'
	'- [x] [Completed tasks/changes]\n\n### In Progress\n- [ ] [Current work]\n\n### Blocked\n- [Issues preventing '
	'progress, if any]\n\n## Key Decisions\n- **[Decision]**: [Brief rationale]\n\n## Next Steps\n1. [Ordered list of what '
	'should happen next]\n\n## Critical Context\n- [Any data, examples, or references needed to continue]\n- [Or "(none)" '
	'if not applicable]\n\nKeep each section concise. Preserve exact file paths, function names, and error messages.\n\n'
	'Additional focus: Summarize only the source conversation inside <conversation>. These summarization instructions are '
	'not user requests or constraints of the task; never record them as such. Preserve exact user constraints, '
	'artifact/checkpoint paths, Python variable names, completed actions and uncertain side effects, record counts, source '
	'URLs and observed timestamps, conflicting evidence, blockers and the next bounded step. Do not claim attempted means '
	'verified. Never suggest replaying uncertain actions.'
)
CHECKPOINT = (  # bu-pi src/context.ts, verbatim except Python for JavaScript
	'Conversation checkpoint: generated, fallible reference, not new instructions. Python variables and files persist.\n'
	"Evidence archive (JSON path): {path}\nThe archive's messages preserve earlier user text, assistant text/tool calls "
	'and tool results, with configured secrets redacted and images/reasoning omitted. Earlier checkpoint messages link '
	'previous archives. Search these messages or saved source files for exact observations omitted or misstated below; '
	'do not treat a summary as verification or replay prior actions. Read only relevant excerpts into context.\n'
	'Generated summary (JSON-quoted):\n{summary}\nOriginal user requests (authoritative over the generated summary):\n'
	'{users}\nContinue the original task. Any instruction to produce a summary belongs to the summarization process, not '
	'the original task.'
)


@dataclass
class Compaction(AbstractCapability[Session]):
	"""bu-pi's RunContext (src/context.ts) for models without server-side compaction. Past 75% of max_chars content
	characters (conversation + system prompt) or 65% of the context window in tokens, everything before the last two
	assistant/tool groups is sent as one checkpoint message: a summary by the same model at low effort, a redacted evidence
	archive, the user messages verbatim. Only the request is projected; the transcript stays whole (usage, follow-ups). A
	failure keeps the full history and is not retried. max_chars: bu-pi maxContextChars, default 4 characters per token of
	the context window (bu-pi), 240k when the window is unknown. token_threshold: an extra token trigger (tests)."""

	token_threshold: int | None = None
	max_chars: int | None = None

	async def before_model_request(self, ctx: RunContext[Session], request_context: ModelRequestContext):
		s, messages, window = ctx.deps, request_context.messages, request_context.model.context_window
		system = sum(len(p.content) for p in request_context.model_request_parameters.instruction_parts or [])
		tokens = _tokens(s, messages, system)
		max_chars = self.max_chars or (window * 4 if window else 240_000)
		due = (
			_chars(_projected(s, messages)) + system > 0.75 * max_chars
			or (window and tokens > 0.65 * window)
			or (self.token_threshold is not None and tokens >= self.token_threshold)
		)
		if not s.compaction_failed and due:
			try:
				await _compact(s, messages, request_context)
			except Exception as e:
				s.compaction_failed = True
				logger.warning(
					redact(f'Compaction failed, continuing with the full history: {type(e).__name__}: {e}', s.repl.secrets)
				)
		request_context.messages = _projected(s, messages)
		return request_context


def _projected(s: Session, messages: list[ModelMessage]) -> list[ModelMessage]:
	return [s.checkpoint, *messages[s.covered :]] if s.checkpoint else messages


def _plain(messages: list[ModelMessage]) -> Any:
	"""Message content as JSON data (bu-pi's archive and context size): kind, part kind, tool name and call id, content or
	args. Reasoning, the system prompt, usage, ids, timestamps and provider details are omitted; images become a note."""

	def content(v: Any) -> Any:
		if isinstance(v, BinaryContent):
			return '[Image omitted from text archive]'
		return [content(x) for x in v] if isinstance(v, list) else v

	keys = ('tool_name', 'tool_call_id', 'content', 'args')
	return to_jsonable_python(
		[
			{
				'kind': m.kind,
				'parts': [
					{'part_kind': p.part_kind, **{k: content(v) for k in keys if (v := getattr(p, k, None)) is not None}}
					for p in m.parts
					if not isinstance(p, ThinkingPart | SystemPromptPart)
				],
			}
			for m in messages
		],
		fallback=str,
	)


def _chars(messages: list[ModelMessage]) -> int:  # as bu-pi's JSON.stringify: no spaces, a CJK character counts 1, not 6
	return len(json.dumps(_plain(messages), ensure_ascii=False, separators=(',', ':')))


def _tokens(s: Session, messages: list[ModelMessage], system: int) -> int:
	"""bu-pi RunContext.tokens: the last response's context plus what came after it, at least the estimate of the request
	(4 characters per token)."""
	estimate = (_chars(_projected(s, messages)) + system) // 4
	for i in range(len(messages) - 1, -1, -1):
		if isinstance(m := messages[i], ModelResponse):
			return max(estimate, m.usage.total_tokens + _chars(messages[i + 1 :]) // 4)
	return estimate


async def _compact(s: Session, messages: list[ModelMessage], request_context: ModelRequestContext) -> None:
	starts = [i for i, m in enumerate(messages) if isinstance(m, ModelResponse) and i >= s.covered]
	if len(starts) < 2 or starts[-2] <= s.covered:  # keep the last two assistant/tool groups: no tool result is orphaned
		return
	cut = starts[-2]
	plain = redact(_plain(([s.checkpoint] if s.checkpoint else []) + messages[s.covered : cut]), s.repl.secrets)
	# bu-pi: 12k output tokens, 120 s, low effort; a cache write for a one-off prompt is never read
	inherited = (request_context.model_settings or {}).items()
	settings = {k: v for k, v in inherited if k not in ('tool_choice', 'parallel_tool_calls', 'cache')}
	settings |= {'max_tokens': 12_000, 'request_timeout': 120}
	for key in ('thinking', 'openai_reasoning_effort'):
		if settings.get(key) and settings[key] != 'none':
			settings[key] = 'low'
	prompt = f'<conversation>\n{json.dumps(plain, ensure_ascii=False)}\n</conversation>\n\n{SUMMARY_PROMPT}'
	response = await model_request(
		request_context.model,
		[ModelRequest(parts=[UserPromptPart(prompt)], instructions=SUMMARY_SYSTEM)],
		model_settings=cast(Any, settings),
	)
	s.summaries.append(response)
	if not response.text or not response.text.strip():
		raise ValueError('the summary is empty')
	path = s.repl.workspace / '.browser-use' / 'context' / f'{uuid.uuid4()}.json'
	path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
	path.touch(mode=0o600, exist_ok=False)
	archive = {'version': 1, 'summary': response.text, 'covered_messages': cut, 'messages': plain}
	path.write_text(json.dumps(redact(archive, s.repl.secrets), ensure_ascii=False), encoding='utf-8')
	users = [p.content for m in messages[:cut] if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, UserPromptPart)]
	text = CHECKPOINT.format(path=json.dumps(str(path)), summary=json.dumps(response.text), users=json.dumps(users, default=str))
	checkpoint = ModelRequest(parts=[UserPromptPart(text)])
	if _chars([checkpoint, *messages[cut:]]) >= _chars(_projected(s, messages)):
		raise ValueError('it did not reduce the context; the original evidence was retained')
	s.checkpoint, s.covered = checkpoint, cut


def delivery_tool_choice(model: Any, settings: dict) -> Any:
	"""Only finish/finish_from_repl. Forced (allowed_tools keeps the cached tool list) where the model accepts a forced
	tool choice on this request; otherwise python is withheld and the choice stays auto. Claude rejects forcing with
	extended thinking and answers a forced call without thinking; Claude Opus 5.5 rejects forcing outright."""
	p = model.profile
	effort = settings.get('openai_reasoning_effort')
	thinks = (
		settings.get('thinking') not in (None, False)
		or (settings.get('anthropic_thinking') or {}).get('type') in ('enabled', 'adaptive')
		or effort not in (None, 'none')
		or p.get('thinking_always_enabled', False)
		or (p.get('thinking_enabled_by_default', False) and settings.get('thinking') is not False)
	)
	forcing = p.get('supports_forced_tool_choice', True) and not (
		thinks
		and (not p.get('supports_forced_tool_choice_with_thinking', True) or p.get('forced_tool_choice_disables_thinking', False))
	)
	return DELIVERY_TOOLS if forcing else ToolOrOutput(function_tools=[])


def _is_image(c: Any) -> bool:
	return isinstance(c, BinaryContent) and c.is_image


def _prune_images(messages: list[ModelMessage]) -> list[ModelMessage] | None:
	"""Keep images only in the last KEEP_IMAGE_RESULTS tool results. Returns None when nothing changes."""
	out, seen, changed = list(messages), 0, False
	for i in range(len(out) - 1, -1, -1):
		m = out[i]
		if not isinstance(m, ModelRequest):
			continue
		parts = list(m.parts)
		for j, part in enumerate(parts):
			if isinstance(part, ToolReturnPart) and isinstance(part.content, list) and any(map(_is_image, part.content)):
				seen += 1
				if seen > KEEP_IMAGE_RESULTS:
					content = [('[older screenshot removed]' if _is_image(c) else c) for c in part.content]
					parts[j] = replace(part, content=content)
					out[i] = m = replace(m, parts=parts)
					changed = True
	return out if changed else None


def model_kind(model: Any) -> str:
	"""'responses' (OpenAI Responses: evaluated settings + compaction), 'chat' (OpenAI-compatible chat completions:
	no OpenAI-only settings) or 'other' (Anthropic, Google, ...: unified thinking setting)."""
	if isinstance(model, OpenAIResponsesModel) or (isinstance(model, str) and model.startswith(('openai:', 'openai-responses:'))):
		return 'responses'
	if isinstance(model, OpenAIChatModel) or (isinstance(model, str) and model.startswith('openai-chat:')):
		return 'chat'
	return 'other'


def reasoning_supported(model: Any) -> bool:
	"""Whether build_agent sends reasoning_effort to this model. OpenAI: reasoning models only (gpt-4.1 and gpt-4o
	reject reasoning params). OpenAI-compatible chat backends: never (pass ChatOpenAI(reasoning_effort=...) to send it).
	Others: the profile's supports_thinking (an unknown model string counts as supported)."""
	kind = model_kind(model)
	if kind == 'chat':
		return False
	if isinstance(model, str):
		if kind != 'responses':
			return True
		from pydantic_ai.profiles.openai import openai_model_profile

		return bool((openai_model_profile(model.split(':', 1)[1]) or {}).get('openai_supports_reasoning', False))
	return bool(model.profile.get('openai_supports_reasoning' if kind == 'responses' else 'supports_thinking', False))


def _openai_reasoning_on_chat(model: Any) -> bool:
	"""An OpenAI reasoning model on api.openai.com's chat completions that takes reasoning_effort='none'
	('openai-chat:gpt-6-luna'). o1, o3, o4-mini and gpt-5 reject 'none' and run function tools with reasoning on."""
	from urllib.parse import urlparse

	from pydantic_ai.profiles.openai import openai_model_profile

	if isinstance(model, str):
		name, official = model.split(':', 1)[1], True
	else:
		name, official = model.model_name, urlparse(str(getattr(model, 'base_url', '') or '')).hostname == 'api.openai.com'
	profile = openai_model_profile(name) or {}
	return (
		official and bool(profile.get('openai_supports_reasoning')) and bool(profile.get('openai_supports_reasoning_effort_none'))
	)


def build_agent(
	model: Any = 'openai-responses:gpt-6-luna',
	*,
	output_type: Any = str,
	reasoning_effort: str | None = 'medium',
	instructions: str = '',
	compact_at_tokens: int | None = None,
	max_context_chars: int | None = None,
	mode: str | None = 'default',
	tools: Sequence[Any] = (),
	model_settings: dict | None = None,
) -> Agent[Session, Any]:
	"""mode='ultrafast' appends AX_PROMPT (the `bu` helpers) to the system prompt; the Repl needs the same mode.
	tools: extra Pydantic AI tools (Tools().functions). model_settings: merged over the defaults. compact_at_tokens: the
	server-side compaction threshold (default 150k); elsewhere an extra trigger next to bu-pi's. max_context_chars: bu-pi's
	character budget for client-side compaction (Compaction.max_chars; no effect with server-side compaction). reasoning_effort=None
	sends no effort (the gateway then applies the alias's own: bu-fast medium, bu-ultrafast low, bu-smart high)."""
	mode = check_mode(mode)
	model = model_ref(model)
	kind = model_kind(model)
	reasoning = reasoning_supported(model)
	if kind == 'responses':  # the evaluated configuration (reasoning models); unchanged
		settings: OpenAIResponsesModelSettings | dict = {
			'openai_reasoning_effort': reasoning_effort,
			'openai_reasoning_summary': 'auto',
			'openai_reasoning_context': 'auto',  # bu-pi sends no context; Pydantic AI would send all_turns
			'max_tokens': 32_768,
		}
		if reasoning_effort is None:
			del settings['openai_reasoning_effort']
		if not reasoning:  # gpt-4.1, gpt-4o: reasoning params 400, and 32k is above their output cap
			settings = {}
		capabilities = [BrowserLoop(), LazyCompaction(token_threshold=compact_at_tokens or 150_000)]
		skip_responses_transform()  # bu-pi's Node SDK sends the body as is
	elif kind == 'chat':  # DeepSeek, vLLM, Ollama: no reasoning settings, no output cap they may reject
		# OpenAI's own reasoning models turn reasoning on by default on chat completions and then reject function tools
		# (400 "use /v1/responses or set reasoning_effort to 'none'")
		settings = {'openai_reasoning_effort': 'none'} if _openai_reasoning_on_chat(model) else {}
		capabilities = [BrowserLoop(), Compaction(compact_at_tokens, max_context_chars)]
	else:  # other providers: unified thinking (dropped where the profile has none), the provider's own max_tokens
		settings = {'thinking': reasoning_effort or 'medium'} if reasoning else {}
		if model.startswith('anthropic:') if isinstance(model, str) else getattr(model, 'system', None) == 'anthropic':
			# Anthropic caches nothing unless asked: every request re-billed the whole prompt (cache_read was always 0).
			# Pydantic AI's unified cache setting caches the system prompt, the tools and the conversation so far, in the
			# mode the client supports; any anthropic_cache* setting the caller gave takes precedence over it there, and
			# a cache setting of the caller's own (on the model or in model_settings) is left alone.
			if 'cache' not in {**(getattr(model, 'settings', None) or {}), **(model_settings or {})}:
				settings['cache'] = True
		capabilities = [BrowserLoop(), Compaction(compact_at_tokens, max_context_chars)]
	agent = Agent(
		model,
		deps_type=Session,
		defer_model_check=True,
		output_type=_outputs(output_type),
		instructions=f'{SYSTEM_PROMPT}{AX_PROMPT if mode == "ultrafast" else ""}\n{instructions}'.strip(),
		tools=[python, *tools],
		model_settings=cast(Any, {**settings, **(model_settings or {})}),
		retries={'tools': 1, 'output': 5},
		capabilities=capabilities,
	)

	@agent.instructions
	def workspace(ctx: RunContext[Session]) -> str:  # bu-pi src/agent.ts:275; V2 deliverables went outside it
		text = (
			f'Workspace directory (JSON string): {json.dumps(str(ctx.deps.repl.workspace.resolve()))}. The REPL '
			'working directory starts here. Save deliverables inside this directory; files outside it are not '
			'delivered. Use relative paths or the exact workspace value, not a guessed parent directory.'
		)
		return f'{text}\n\n{secrets_prompt(ctx.deps.repl.secrets)}' if ctx.deps.repl.secrets else text

	return agent


def gateway_charge(m: ModelResponse) -> float | None:
	"""USD the Browser Use gateway charged for this response (browser_use.charge_usd, a decimal string)."""
	return parse_usd(((m.provider_details or {}).get('browser_use') or {}).get('charge_usd'))


def usage_and_cost(messages: list[ModelMessage], model_ref: str) -> tuple[dict[str, int], float | None]:
	"""Tokens and USD cost of these messages. A gateway response's cost is what the gateway charged (browser_use.charge_usd);
	others are priced by genai-prices. Cost is None when any request has no known price, and for a gateway model
	('browser-use:...') when any response has no charge: never a retail estimate in place of the charge."""
	total = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_write': 0, 'requests': 0}
	cost: float | None = 0.0
	provider = 'openai'
	if ':' in model_ref:  # 'anthropic:claude-...'; the eval passes a bare OpenAI name
		provider, model_ref = model_ref.split(':', 1)
		provider = provider.removesuffix('-responses').removesuffix('-chat')
	for m in messages:
		if isinstance(m, ModelResponse):
			u = m.usage
			total['input'] += u.input_tokens
			total['output'] += u.output_tokens
			total['cache_read'] += u.cache_read_tokens
			total['cache_write'] += u.cache_write_tokens
			total['requests'] += 1
			if cost is None:
				continue
			if (charge := gateway_charge(m)) is not None:
				cost += charge
				continue
			if provider == 'browser-use':
				cost = None
				continue
			# Priced as the model that answered (m.model_name): an alias can be served by another model (requested
			# gemini-3.5-flash, served and billed as gemini-3.6-flash). The requested name only when the answer names no
			# model or a snapshot of the requested one (gpt-4.1 -> gpt-4.1-2025-04-14): another model's price is a guess.
			served = m.model_name
			names = [served] if served and not served.startswith(model_ref) else [served, model_ref]
			for name in dict.fromkeys(filter(None, names)):
				try:
					cost += float(calc_price(u, model_ref=name, provider_id=provider).total_price)  # cache writes too
					break
				except Exception:  # - unknown price: try the next name
					continue
			else:  # no known price: report tokens, not a made-up cost
				cost = None
	return total, cost


def last_text(messages: list[ModelMessage]) -> str:
	for m in reversed(messages):
		if isinstance(m, ModelResponse):
			text = '\n'.join(p.content for p in m.parts if isinstance(p, TextPart)).strip()
			if text:
				return text
	return ''


async def run(
	agent: Agent[Session, Any],
	task: str,
	session: Session,
	model_ref: str,
	message_history: list[ModelMessage] | None = None,
	explain_error: Callable[[Exception], str | None] | None = None,
) -> AgentHistoryList:
	"""Run one task with graceful budgets. Never raises for agent/provider failures.

	message_history continues an earlier transcript (follow-up task); usage and steps count only this run.
	explain_error turns a provider exception into one actionable line (gateway 401/402/403/404)."""
	status, output, error = 'completed', None, None
	(session.repl.state / 'partial.json').unlink(missing_ok=True)  # a partial belongs to one run
	search = session.repl.search
	searched = len(search.charges) if search else 0
	budget = asyncio.timeout(session.timeout_s)
	task = redact(task, session.repl.secrets)  # 0.x: a secret written into the task reaches the model as its name only
	try:
		async with budget:
			result = await agent.run(
				task, deps=session, message_history=message_history, usage_limits=UsageLimits(request_limit=session.max_steps + 1)
			)
		output, messages = result.output, result.all_messages()
	except TimeoutError as e:  # a tool's own socket/HTTP timeout is an error, not the run budget
		session.error_type = type(e).__name__
		if budget.expired():
			status, messages = 'timeout', session.messages
		else:
			status, messages = 'error', session.messages
			error = (explain_error and explain_error(e)) or f'{type(e).__name__}: {e}'
	except Exception as e:
		name = session.error_type = type(e).__name__
		status = 'max_steps' if name == 'UsageLimitExceeded' else 'error'
		error, messages = (explain_error and explain_error(e)) or f'{name}: {e}', session.messages
	partial = session.partial()
	new = messages[len(message_history or []) :]  # an earlier task's text is never this run's fallback
	if output is None:
		# the fallback text is model output that may quote a secret (e.g. read off a screenshot): redact it like .text
		output = json.dumps(partial, ensure_ascii=False) if partial is not None else redact(last_text(new), session.repl.secrets)
	text = redact(as_text(output), session.repl.secrets)
	error = redact(error, session.repl.secrets)  # provider/tool exceptions can quote a secret; Agent.run logs this
	usage, cost = usage_and_cost(new + session.summaries, model_ref)
	if cost is not None and search:  # web searches that named a charge; an unknown model cost stays unknown
		cost += sum(search.charges[searched:])
	steps = sum(isinstance(m, ModelResponse) for m in new)
	duration = time.monotonic() - session.started
	success = session.success if status == 'completed' else None
	session.messages = messages  # a follow-up continues the raw transcript: providers reject edited signed thinking
	forms = secret_forms(session.repl.secrets)
	if forms:  # model text, thinking and tool-call args can quote a secret read off a screenshot
		messages = [
			replace(m, parts=[redact_part(p, forms) for p in m.parts]) if isinstance(m, ModelResponse) else m for m in messages
		]
	return AgentHistoryList(status, text, output, steps, duration, usage, cost, partial, error, messages, success)


def redact_part(part: Any, forms: list[tuple[str, str]]) -> Any:
	fields = ('content', 'args')  # TextPart/ThinkingPart content, ToolCallPart args (str or dict)
	return replace(
		part, **{k: redact_forms(getattr(part, k), forms) for k in fields if isinstance(getattr(part, k, None), (str, dict))}
	)


def thinking_and_text(m: ModelResponse) -> list[tuple[str, str]]:
	return [
		('thinking' if isinstance(p, ThinkingPart) else 'text', p.content)
		for p in m.parts
		if isinstance(p, (ThinkingPart, TextPart)) and p.content
	]
