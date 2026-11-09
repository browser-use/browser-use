"""Browser agent = Pydantic AI loop + one persistent Python REPL running browser-harness.

Learnings carried from browser-use-pi: deliver existing values (finish_from_repl), native screenshots
with only the last two kept, compaction (server-side, else a summary checkpoint), one delivery turn near budget,
partial results that survive timeouts, and a killable worker so a hung cell never kills the run.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterable, Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, cast

import httpx2
from genai_prices import calc_price
from pydantic import Field, TypeAdapter, ValidationError
from pydantic_ai import Agent, BinaryContent, ModelRetry, RunContext, TextOutput, Tool, ToolOutput
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.direct import model_request
from pydantic_ai.exceptions import (
	ModelAPIError,
	ModelConnectionError,
	ModelContextWindowExceededError,
	ModelRateLimitError,
	ModelRequestTimeout,
	ModelServerError,
	ModelUnavailableError,
	RetryModelRequest,
	ToolRetryError,
)
from pydantic_ai.messages import (
	CompactionPart,
	ModelMessage,
	ModelRequest,
	ModelResponse,
	RetryFeedbackPart,
	RetryPromptPart,
	SystemPromptPart,
	TextPart,
	ThinkingPart,
	ToolCallPart,
	ToolReturnPart,
	UserPromptPart,
	tool_return_ta,
)
from pydantic_ai.models import Model, ModelRequestContext
from pydantic_ai.models.openai import OpenAIChatModel, OpenAICompaction, OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles.anthropic import anthropic_model_profile
from pydantic_ai.settings import ToolOrOutput
from pydantic_ai.usage import UsageLimits
from pydantic_core import PydanticSerializationError, to_json, to_jsonable_python

from browser_use.agent.prompt import SYSTEM_PROMPT, secrets_prompt
from browser_use.agent.views import AgentHistoryList
from browser_use.ax import AX_PROMPT
from browser_use.llm import model_ref, skip_responses_transform
from browser_use.logging_config import printable
from browser_use.repl import Repl, check_mode, redact
from browser_use.repl.session import SECRET_PLACEHOLDER, redact_forms, secret_forms
from browser_use.search import parse_usd
from browser_use.telemetry.recorder import CURRENT, RunRecorder, now
from browser_use.telemetry.stats import RunStats
from browser_use.tools import TOOL_RETRIES, ActionResult, RemovedField

try:
	import httpx
except ImportError:  # optional: Pydantic AI needs only httpx2
	httpx = None

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
TOOL_CALL_MARKUP = re.compile(r'</?tool_call>')
TRANSIENT = (ModelRateLimitError, ModelUnavailableError, ModelServerError, ModelConnectionError)
_HTTPX = [httpx2, *([httpx] if httpx else [])]  # Pydantic AI's providers use httpx2; a caller's own client may be httpx
_HTTP_ERRORS = tuple(m.TransportError for m in _HTTPX)
_HTTP_RETRIED = tuple(c for m in _HTTPX for c in (m.ConnectError, m.TimeoutException))  # what google-genai retries
# A Responses failure reported inside an HTTP 200 (a body with status=failed, or a response.failed / error stream event)
# with one of these codes is transient: the gateway's non-streamed request past 300 s ends with request_timeout, and its
# error frame for an upstream stream that failed (openaistream ErrorSSE: OpenAI silent 30 s while compacting) carries
# upstream_stream_failed. Neither is charged: the gateway bills a Responses stream only after its terminal event.
TRANSIENT_FAILED_CODES = frozenset(
	{'server_error', 'overloaded', 'request_timeout', 'upstream_stream_failed', 'model_request_failed'}
)
MODEL_TIMEOUT_S = 300  # bu-pi modelTimeoutMs: one model request, all its SDK attempts included
# A streamed request (StreamResponses) gets MODEL_TIMEOUT_S for its first event, then runs while events flow, up to the
# gateway's stream limit (15 min, llmGatewayStreamTimeout) plus 30 s, so the gateway's own end arrives first. 300 s in
# all cut bu-smart turns that were still streaming and asked again; the gateway billed every cut attempt in full, and
# cost_usd counted none of them (staging: 5 cuts, $1.84 billed, cost_usd $0.0074).
STREAM_TIMEOUT_S = 930
NOT_RUN = 'Not run: this is the delivery-only turn. Call finish or finish_from_repl now with what you have.'
NO_TIME = 'Not run: the time budget is spent. The next turn is delivery-only: finish or finish_from_repl with what you have.'
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
	split_delivery_step: int | None = None  # the request step whose response check_split_delivery refused (once per run)
	success: bool | None = None  # the verdict finish/finish_from_repl must give; None for a plain-text delivery
	messages: list[ModelMessage] = field(default_factory=list)
	after_tool: Callable[[str, dict, dict], Awaitable[None]] | None = None  # observer hook (evals)
	stats: RunStats = field(default_factory=RunStats)  # telemetry counts
	finish_via: str | None = None  # finish | finish_from_repl | text: how the result was delivered
	budget_hit: str | None = None  # max_steps | timeout | browser_gone: what forced the delivery-only turn
	error_type: str | None = None  # class of the exception that ended the run
	checkpoint: ModelRequest | None = None  # Compaction: the message sent in place of messages[:covered]
	covered: int = 0
	usage_after: int = 0  # Compaction: responses before this index were measured before the checkpoint
	overflowed_step: int | None = None  # Compaction: the request step a context-window error forced a compaction in
	provider_retried: bool = False  # BrowserLoop: bu-pi's one provider retry per run is used
	summaries: list[ModelResponse] = field(default_factory=list)  # summarizer responses, counted in usage and cost
	rec: RunRecorder = field(default_factory=RunRecorder)  # telemetry, step by step

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
	# python is sequential (one cell at a time, as bu-pi): this cell starts now
	started, t0, repl = time.monotonic(), now(), ctx.deps.repl
	left = ctx.deps.delivery_at() - (started - ctx.deps.started)  # a cell never runs into the delivery turn's time
	if left <= 0:  # a later call of the same response, after an earlier one used the time up
		return [NO_TIME]
	ctx.deps.rec.cell_start()
	starts = getattr(repl, 'start_ns', 0)  # test doubles have none
	r = await repl.call('exec', code, min(ctx.deps.cell_timeout_s, max(left, 1.0)))
	ctx.deps.stats.add_cell(r, code, time.monotonic() - started)
	ctx.deps.rec.phase('repl_start', getattr(repl, 'start_ns', 0) - starts)
	ctx.deps.rec.cell(r, code, now() - t0, ctx.deps.vision)
	if r.get('browser_gone'):  # a model left without a browser went looking for another one (the user's own Chrome)
		ctx.deps.budget_hit = 'browser_gone'
	text = r['output']  # already cut to MAX_OUTPUT_CHARS by the worker
	if r['error']:
		text = f'{text}\nError: {r["error"]}'.strip()
	line = redact(next((x for x in code.splitlines() if x.strip()), ''), ctx.deps.repl.secrets)  # live progress (0.x 'Step N')
	error = (r['error'] or '').strip().splitlines()  # already redacted by Repl.call
	# the page controls the error text (a JS exception's message), the model the code: no terminal escapes from either
	logger.info(printable(f'step {ctx.run_step}: {line[:120]}' + (f' -> {error[-1][:200]}' if error else '')))
	if ctx.deps.after_tool:
		await ctx.deps.after_tool('python', {'code': code}, r)
	if r['images'] and not ctx.deps.vision:
		return [f'{text}\n(screenshot not shown: use_vision=False; read the page as text)'.strip()]
	shots = [BinaryContent(base64.b64decode(i['data']), media_type=i['media_type']) for i in r['images']]
	return [text or '(no output)', *shots]


def as_text(value: Any) -> str:
	"""A result as text: strings unchanged; models, dataclasses and lists of them as JSON (0.x model_dump_json)."""
	return value if isinstance(value, str) else to_json(value, fallback=str).decode()


def _holds_nothing(v: Any) -> bool:
	"""JSON with no value: empty lists, objects and strings, null. A number or a boolean is a value."""
	if isinstance(v, dict):
		return all(_holds_nothing(x) for x in v.values())
	if isinstance(v, list):
		return all(_holds_nothing(x) for x in v)
	return v is None or (isinstance(v, str) and not re.search(r'[^\W_]', v))


def check_split_delivery(ctx: RunContext[Session]) -> None:
	"""A delivery that shares its response with another delivery call, or with any call after it, is not taken: Pydantic
	AI ends the run with the first one. Sonnet 5.5 sent a stub finish(success=False) first and the real
	finish_from_repl, or a python call, after it (2 of 3 runs of one customer task): the run completed with the stub. A
	python call before the delivery still delivers in the same response. Refused in one response per run; never on the
	delivery-only turn, where nothing else runs."""
	s = ctx.deps
	if s.finalizing or s.split_delivery_step not in (None, ctx.run_step):
		return
	response = next((m for m in reversed(ctx.messages) if isinstance(m, ModelResponse)), None)
	calls = [p for p in response.parts if isinstance(p, ToolCallPart)] if response else []
	at = next((i for i, p in enumerate(calls) if p.tool_call_id == ctx.tool_call_id), None)
	if at is None:
		return
	others = [p.tool_name for i, p in enumerate(calls) if i > at or (i < at and p.tool_name in DELIVERY_TOOLS)]
	if not others:
		return
	s.split_delivery_step = ctx.run_step
	s.rec.retry('delivery_split')
	raise ModelRetry(
		f'Not delivered: {", ".join(others)} came in the same response as this {ctx.tool_name}, so it was not the final '
		'answer. Deliver once, in a response with no tool call after the delivery: finish_from_repl with the existing '
		'records, or finish with the full answer.'
	)


def check_delivery(ctx: RunContext[Session], value: Any) -> None:
	"""One-shot repair: a placeholder or links to unwritten files."""
	s = ctx.deps
	text = as_text(value)
	if not s.checked_delivery:
		problem = None
		# '...', '' (a one-character answer like '7' is fine); a structured result with no value in it: Sonnet 5.5 sent
		# finish({"authors": []}, success=False) with 34 authors in the REPL. Not on the run's last request (the repair
		# after the delivery-only turn): nothing can follow it, and the refused result was lost (status max_steps, '')
		empty = not isinstance(value, str) and ctx.run_step <= s.max_steps and _holds_nothing(json.loads(text))
		if not re.search(r'[^\W_]', text) or empty:
			problem = f'The result {text[:20]!r} is a placeholder, not the answer.'
			s.rec.retry('delivery_placeholder')
		else:
			missing = sorted(
				{
					t
					for t in LINK.findall(text) + FILE.findall(text)
					if not re.match(r'^([a-z][\w+.-]*:|#|//)', t, re.I)
					# downloads land in workspace/downloads; an answer names them by file name
					and not any((d / t.split('#')[0]).exists() for d in (s.repl.workspace, s.repl.workspace / 'downloads'))
				}
			)
			if missing:
				problem = f'These linked files do not exist in the workspace: {", ".join(missing[:10])}.'
				s.rec.retry('delivery_missing_files')
		if problem:
			s.checked_delivery = True
			raise ModelRetry(
				f'{problem} Deliver the actual result: finish_from_repl with the existing records, or '
				'finish with the full answer inline. Do not repeat browser actions.'
			)


def _unquoted(value: str, expression: str) -> str:
	"""A str result delivered as the JSON literal of a string, the text itself. The tool says 'for a string result use
	json.dumps(records) or an existing text variable', and gpt-6-luna sent finish_from_repl('json.dumps(final_text)'):
	result.text began with a quote and read '\\n' for every line break (live longrun, 2 of ~45 runs). Only when it is
	one: a json.dumps(...) expression, or an escape inside. An answer that is a quotation keeps its quotes."""
	if len(value) > 1 and value[0] == value[-1] == '"' and ('\\' in value or _dumps_call(expression)):
		try:
			text = json.loads(value)
		except ValueError:
			return value
		if isinstance(text, str):
			return text
	return value


def _dumps_call(expression: str) -> bool:
	"""Whether the expression is a call to json.dumps (or a dumps imported by name)."""
	try:
		node = ast.parse(expression.strip(), mode='eval').body
	except (SyntaxError, ValueError):
		return False
	func = node.func if isinstance(node, ast.Call) else None
	return (isinstance(func, ast.Attribute) and func.attr == 'dumps') or (isinstance(func, ast.Name) and func.id == 'dumps')


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
		check_split_delivery(ctx)
		r = await ctx.deps.repl.call('eval', expression, ctx.deps.cell_timeout_s)
		if r['error']:
			ctx.deps.rec.retry('finish_expr_error')
			raise ModelRetry(f'Expression failed: {r["error"][-2000:]}')
		if output_type is str:
			value = _unquoted(r['value'], expression)
			check_delivery(ctx, value)
		else:
			try:
				value = adapter.validate_json(r['value'])
			except ValidationError as e:
				try:  # a str comes back as is, not as JSON text: answer = 'no' for Literal['yes', 'no'] or a StrEnum
					value = adapter.validate_python(r['value'])
				except ValidationError:
					ctx.deps.rec.retry('finish_schema')
					raise ModelRetry(f'Value does not match the result schema: {str(e)[:2000]}') from None
			check_delivery(ctx, value)  # as finish: an empty structured value or links to unwritten files get the repair
		ctx.deps.success, ctx.deps.finish_via = success, 'finish_from_repl'
		return clean(ctx, value)

	def finish(ctx: RunContext[Session], result, success: bool | None = None):
		check_split_delivery(ctx)
		check_delivery(ctx, result)
		ctx.deps.success, ctx.deps.finish_via = success, 'finish'
		return clean(ctx, result)

	def on_text(ctx: RunContext[Session], text: str):
		# Plain text keeps tool_choice=auto (as in bu-pi); a forced tool call every turn made finish() the only way to
		# stop and talk. A text reply ends the work. For a str result it is the answer (bu-pi repaired it: one extra
		# request on ~95% of gpt-6-luna runs). A structured result gets one delivery-only repair turn, then text is accepted.
		# A tool call written as text (Grok bub2-020 ended with '<tool_call>{"name": "finish_from_repl", ...}</tool_call>')
		# ran nothing and is no answer: it gets the repair turn too, and is never delivered.
		markup = TOOL_CALL_MARKUP.search(text)
		if markup or (output_type is not str and not ctx.deps.finalizing):
			ctx.deps.finalizing = True
			ctx.deps.rec.delivery()
			ctx.deps.rec.retry('text_tool_markup' if markup else 'text_repair')
			# Quoted: a compaction item at the end of this response replaces everything before it, this text included,
			# so the repair turn would otherwise not see the answer it is asked to deliver.
			note = 'That reply wrote a tool call as text; it was not run. ' if markup else ''
			raise ModelRetry(f'{note}{DELIVERY_REPAIR}\n\nYour reply, not delivered yet:\n{text}')
		ctx.deps.finish_via = 'text'
		if output_type is str:
			check_delivery(ctx, text)
			return clean(ctx, text)
		try:
			return clean(ctx, adapter.validate_json(text))
		except ValidationError as e:
			ctx.deps.rec.retry('text_schema')
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
	"""Keep only recent screenshots; one delivery-only turn near the time/step budget or after a structured text reply;
	one retry of a transient provider error per run; a deadline per model request."""

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
				s.rec.delivery()
				ctx.enqueue(DELIVER_NOW)
		settings: dict[str, Any] = dict(request_context.model_settings or {})  # resolved before this hook
		_deadlines(s, settings, request_context.model, MODEL_TIMEOUT_S)
		if s.finalizing:  # restrict this very request
			settings['tool_choice'] = delivery_tool_choice(request_context.model, settings)
		request_context.model_settings = cast(Any, settings)
		return request_context

	async def on_model_request_error(self, ctx: RunContext[Session], *, request_context: ModelRequestContext, error: Exception):
		"""bu-pi's provider retry (src/agent.ts transientModelError): a rate limit, overload, 5xx or dropped connection
		sends the same request once more per run, after the provider's Retry-After (at most 60 s, pi-ai's cap). Only the
		inference is repeated: a failed request returned no tool calls. Not where the provider's SDK client has already
		retried it: OpenAI, Anthropic and OpenAI-compatible clients (max_retries=2 with backoff), any client given the
		max_retries setting (build_agent gives Google 2), and xAI's UNAVAILABLE (xai-sdk's gRPC retry policy: 5 attempts).
		xAI's 429 "at capacity" ended grok bub2-007 on the first try. Bedrock's botocore retries throttling without a
		max_retries attribute, so it gets this one more. A failure inside an HTTP 200 (Responses status=failed or a
		failed stream) was never retried by the SDK: server_error, overloaded and request_timeout get the retry too."""
		s, model = ctx.deps, request_context.model
		if isinstance(error, ModelRequestTimeout):  # a new request step: the delivery turn when its time has come
			s.rec.retry('model_timeout')
			logger.warning(f'{error.model_name}: no answer within {error.timeout:.1f} s; asking again')
			raise ModelRetry(f'The model request got no answer within {error.timeout:.1f} s.')
		if s.provider_retried or not isinstance(error, ModelAPIError):
			raise error
		retries = (request_context.model_settings or {}).get('max_retries')  # the SDK's retries for this request, if set
		retries = getattr(getattr(model, 'client', None), 'max_retries', 0) if retries is None else retries
		code, failed = error.provider_error_code, error.provider_error_code in TRANSIENT_FAILED_CODES
		# The SDK retries HTTP errors only: a failure inside a 200 (stream, or a body without a status) is on its first try
		in_200 = error.in_stream or (failed and getattr(error, 'status_code', None) is None) or _cut_after_response(error, model)
		transient = isinstance(error, TRANSIENT) or (in_200 and failed)
		sdk_retried = not in_200 and (retries or (model.system == 'xai' and code == 'UNAVAILABLE'))
		if not transient or sdk_retried:
			raise error
		s.provider_retried = True
		s.rec.retry('provider_transient')
		delay = min(error.retry_after or 0, 60)
		logger.warning(f'{type(error).__name__} from {error.model_name}: retrying once in {delay:g} s')
		slept = now()
		await asyncio.sleep(delay)
		s.rec.phase('retry_sleep', now() - slept)
		raise RetryModelRequest()

	async def wrap_tool_validate(self, ctx: RunContext[Session], *, call, tool_def, args, handler) -> Any:
		"""A tool call on a delivery-only turn is not run (wrap_tool_execute), so its arguments are not validated either:
		a rejected call would cost a retry turn instead of the refusal."""
		if ctx.deps.finalizing and tool_def.kind == 'function':
			return args
		return await handler(args)

	async def on_tool_execute_error(self, ctx: RunContext[Session], *, call, tool_def, args, error: Exception) -> Any:
		"""A custom tool (Tools) that raises returns the error to the model, which can recover, as a failing 0.x action
		did (ActionResult(error=...)); it never ends the run. ModelRetry and pydantic-ai's control flow never get here."""
		if call.tool_name == 'python' or tool_def.kind != 'function' or isinstance(error, RemovedField):
			raise error
		ctx.deps.rec.retry('custom_tool')
		return ActionResult(error=f'{type(error).__name__}: {error}')

	async def wrap_tool_execute(self, ctx: RunContext[Session], *, call, tool_def, args, handler) -> Any:
		"""Custom tools (Tools) run in this process, so the worker's redaction never saw their results: redact them
		(strings, ActionResult and other models, nested values) and their retry messages before the model does."""
		if ctx.deps.finalizing and tool_def.kind == 'function':
			# The delivery-only turn withholds python where it cannot force finish (Claude), yet Claude still called it
			# (2/2 runs, one ended empty): refuse it instead of running more browser actions.
			return NOT_RUN
		secrets = ctx.deps.repl.secrets
		if call.tool_name == 'python' or tool_def.kind != 'function':
			return await handler(args)
		if not secrets:
			return _sendable(await handler(args))
		names = {name for name, _, _ in secrets}
		placeholder = next((m for m in SECRET_PLACEHOLDER.finditer(_js(args)) if (m[1] or m[2]) in names), None)
		if placeholder:  # 0.x replaced it with the value; a tool silently given the placeholder sent it on as the password
			return ActionResult(
				error=f'{call.tool_name} was not run: custom tools do not receive secret values ({placeholder[0]} is not '
				f"replaced). Type secrets in the browser with type_secret('{placeholder[1] or placeholder[2]}')."
			)
		forms = secret_forms(secrets)
		try:
			result = _sendable(await handler(args))
		except ToolRetryError as e:  # the tool's ModelRetry, already turned into the retry part
			raise ToolRetryError(replace(e.tool_retry, content=redact_forms(e.tool_retry.content, forms))) from None
		plain = result if isinstance(result, str) else to_jsonable_python(result, fallback=str)
		clean = redact_forms(plain, forms)
		return result if clean == plain else clean  # untouched (images, types) unless a secret was in it


class Recording(AbstractCapability[Session]):
	"""Telemetry of every model request attempt (RunRecorder). Last in the capability list: its prepare hook runs after
	compaction (timed apart), and its error hook sees each failure first, as the provider raised it."""

	async def prepare_model_request(self, ctx: RunContext[Session], request_context: ModelRequestContext):
		ctx.deps.rec.attempt_start()
		return request_context

	async def after_model_request(
		self, ctx: RunContext[Session], *, request_context: ModelRequestContext, response: ModelResponse
	):
		ctx.deps.rec.attempt_ok(response, ctx.deps.finalizing)
		return response

	async def on_model_request_error(self, ctx: RunContext[Session], *, request_context: ModelRequestContext, error: Exception):
		ctx.deps.rec.attempt_failed(error)
		raise error


def _sendable(result: Any) -> Any:
	"""A custom tool's result as Pydantic AI can send it to the model. An object it cannot serialize (an SDK response, a
	client object) ended the run with PydanticSerializationError; MIGRATING promises the model sees any value: its str()."""
	try:
		tool_return_ta.dump_json(result)
	except (PydanticSerializationError, ValueError):  # ValueError: a value that contains itself (a parent link)
		try:
			return to_jsonable_python(result, fallback=str, bytes_mode='base64')
		except ValueError:
			return str(result)
	return result


def _cut_after_response(error: ModelAPIError, model: Model) -> bool:
	"""A connection that broke while the response was read: no SDK retried it. The OpenAI and Anthropic SDKs wrap what
	they retry in their own APIConnectionError; a bare httpx error came from a response the SDK had already returned
	(Claude's stream: live 'peer closed connection without sending complete message body' ended the run on its first
	try). google-genai never wraps them and retries only connect errors and timeouts (a cut JSON body, live, too)."""
	cause = error.__cause__
	if not isinstance(error, ModelConnectionError) or not isinstance(cause, _HTTP_ERRORS):
		return False
	return not (model.system.startswith('google') and isinstance(cause, _HTTP_RETRIED))


class StreamResponses(AbstractCapability[Session]):
	"""Every OpenAI Responses request (the gateway, api.openai.com) goes out with stream=true and comes back as the
	assembled response, as bu-pi streams every request. The gateway cuts a non-streamed request at 300 s: it answered
	HTTP 200 status=failed request_timeout and a long bu-smart turn (often the delivery) ended the run. Usage, the
	gateway's charge (browser_use on response.completed), reasoning and compaction items come from the terminal event
	as from a body. Hooks still see one non-streamed request, so an error at any point of the stream is retried."""

	def get_wrapper_model(self, model: Model) -> Model | None:
		return StreamedRequest(model) if isinstance(model, OpenAIResponsesModel) else None


class StreamedRequest(WrapperModel):
	async def request(self, messages: Any, model_settings: Any, model_request_parameters: Any) -> ModelResponse:
		"""bub2-010 (gpt-6-luna, 1 of 5 streamed compactions): the next request got 400 invalid_encrypted_content on the
		compaction item and the run ended. The messages still hold the history that item replaced, so the request goes
		out again without it and the server compacts that history again; never more often than there are such items, and
		once for the gateway's 400, which does not say which item. A reasoning item OpenAI names so (live, one changed
		character: the run ended) is left out the same way: the request loses that turn's reasoning, not the run."""
		guessed = False
		while True:
			try:
				return await self._request(messages, model_settings, model_request_parameters)
			except ModelAPIError as e:
				if not (item := _unreadable_compaction(e, messages, guessed)):
					raise
				guessed = guessed or e.provider_error_code != 'invalid_encrypted_content'
				if rec := CURRENT.get():
					rec.retry('compaction_unreadable')
				what = 'reasoning item' if item.startswith('rs_') else 'compaction item'
				logger.warning(f'{self.model_name} could not read {what} {item}; sending the request without it')
				if item.startswith('rs_'):  # in place: the run's history, which every later request sends, too
					for m in messages:
						if isinstance(m, ModelResponse):
							m.parts = _without_part(m, item).parts
				else:  # the history keeps it: the next compaction item supersedes it
					messages = [_without_part(m, item) if isinstance(m, ModelResponse) else m for m in messages]

	async def _request(self, messages: Any, model_settings: Any, model_request_parameters: Any) -> ModelResponse:
		terminal: list[Any] = []
		# first_event_timeout (_deadlines) is enforced here: the agent sees a non-streamed request, so Pydantic AI skips it
		wait = (model_settings or {}).get('first_event_timeout')
		async with AsyncExitStack() as stack:
			first_event = asyncio.timeout(wait)
			try:
				async with first_event:  # opening the stream counts, as in Pydantic AI
					stream = await stack.enter_async_context(
						self.wrapped.request_stream(messages, model_settings, model_request_parameters)
					)
					if handle := getattr(
						stream, '_handle_terminal_response', None
					):  # Responses: the Response a terminal event carries
						setattr(stream, '_handle_terminal_response', lambda r: (terminal.append(r), handle(r))[1])
					events = _in_stream(stream)
					stack.push_async_callback(events.aclose)
					await anext(events, None)
					if rec := CURRENT.get():
						rec.first_event()
			except TimeoutError:
				if not first_event.expired():
					raise
				raise ModelRequestTimeout(self.model_name, cast(float, wait), setting='first_event_timeout') from None
			async for _ in events:
				pass
		response = stream.get()
		# A stream closed before its terminal event (response.completed, .incomplete, .failed) is cut off, as a body
		# that ended early: a half answer taken as the result, a half summary as the checkpoint, no usage or charge
		if response.state != 'complete':
			raise ModelConnectionError(self.model_name, 'The response stream ended before the response did.', in_stream=True)
		return _sealed_as_completed(response, terminal[-1]) if terminal else response


def _sealed_as_completed(response: ModelResponse, final: Any) -> ModelResponse:
	"""Compaction items as response.completed carries them, as in a non-streamed body. A compaction item's own events
	can carry another encrypted_content (output_item.added: a provisional 1016-character token, live gpt-6-luna), and
	only the response's is the one to send back. One the events never finished goes first, where the server puts it."""
	items = {o.id: o for o in getattr(final, 'output', None) or () if getattr(o, 'type', None) == 'compaction'}
	if not items:
		return response
	parts = [
		replace(p, provider_details=items.pop(p.id).model_dump()) if isinstance(p, CompactionPart) and p.id in items else p
		for p in response.parts
	]
	missing = [
		CompactionPart(None, id=i.id, provider_name=response.provider_name, provider_details=i.model_dump())
		for i in items.values()
	]
	return replace(response, parts=[*missing, *parts])


def _unreadable_compaction(error: ModelAPIError, messages: Sequence[ModelMessage], guessed: bool) -> str | None:
	"""The id of the compaction item in `messages` that the provider's 400 invalid_encrypted_content names, if any. The
	gateway answers every provider 400 as invalid_request with neither the code nor the message (cloud llmgateway
	publicError), so there it is the newest item, the only one a request carries, once (`guessed`: already tried)."""
	sent = [p.id for m in messages if isinstance(m, ModelResponse) for p in m.parts if isinstance(p, CompactionPart)]
	if error.provider_error_code == 'invalid_encrypted_content':
		ids = re.findall(r'\b(?:cmp|rs)_\w+', error.body if isinstance(error.body, str) else json.dumps(error.body, default=str))
		thoughts = {p.id for m in messages if isinstance(m, ModelResponse) for p in m.parts if isinstance(p, ThinkingPart)}
		return next((i for i in ids if i in sent or i in thoughts), None)
	if error.provider_error_code == 'invalid_request' and getattr(error, 'status_code', None) == 400 and sent and not guessed:
		return sent[-1]
	return None


def _without_part(message: ModelResponse, item: str) -> ModelResponse:
	parts = [p for p in message.parts if not (isinstance(p, (CompactionPart, ThinkingPart)) and p.id == item)]
	return message if len(parts) == len(message.parts) else replace(message, parts=parts)


async def _in_stream(stream: AsyncIterable[Any]) -> AsyncGenerator[Any]:
	try:
		async for event in stream:
			yield event
	except ModelAPIError as e:  # the SDK retries a request until its stream opens, never a stream that broke off
		e.in_stream = True  # BrowserLoop's one retry, as for any failure inside an HTTP 200
		raise


def _deadlines(s: Session, settings: dict[str, Any], model: Model, wait_s: float) -> None:
	"""request_timeout of one model request, and first_event_timeout of a streamed one (OpenAI Responses, streamed by
	StreamResponses). A non-streamed request gets wait_s in all; a streamed one gets wait_s until its first event, then
	STREAM_TIMEOUT_S in all. bu-pi deadlineStream: neither holds the run past the delivery turn's start."""
	left = max(1.0, (s.timeout_s if s.finalizing else s.delivery_at()) - (time.monotonic() - s.started))
	if isinstance(model, OpenAIResponsesModel):
		settings['first_event_timeout'] = min(settings.get('first_event_timeout') or wait_s, left)
		wait_s = STREAM_TIMEOUT_S
	settings['request_timeout'] = min(settings.get('request_timeout') or wait_s, left)


class LazyCompaction(OpenAICompaction):
	"""Server-side compaction, requested only once the last request was past the threshold. context_management on every
	request made each call ~0.8 s slower at 45k tokens (bu-pi sends none). Threshold: token_threshold, else 150k capped
	at 65% of the model's context window (Compaction's trigger): gpt-4o's 128k window rejected every request before a
	fixed 150k was reached, and the run ended on the context-window error."""

	def get_model_settings(self):
		def settings(ctx: RunContext[Any]) -> Any:
			if (ctx.model_settings or {}).get('openai_context_management'):  # the caller's own, as OpenAICompaction
				return {}
			window = ctx.model.context_window
			threshold = self.token_threshold or (min(150_000, int(0.65 * window)) if window else 150_000)
			last = next((m.usage.input_tokens for m in reversed(ctx.messages) if isinstance(m, ModelResponse)), 0)
			if last < threshold:
				return {}
			return {'openai_context_management': [{'type': 'compaction', 'compact_threshold': threshold}]}

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
	"""bu-pi's RunContext (src/context.ts) for models without server-side compaction. Past 75% of max_chars (bu-pi's
	contextChars of the conversation plus the system prompt) or 65% of the context window in tokens, everything before
	the last two assistant/tool groups is sent as one checkpoint message: a summary by the same model at low effort, a
	redacted evidence archive, the user messages verbatim. Only the request is projected; the transcript stays whole
	(usage, follow-ups). A failure keeps the full history for this request and compaction is tried again on the next
	(bu-pi agent.ts). A provider's context-window error forces one compaction and the same request again (bu-pi
	agent.ts overflow recovery); a second one in that step ends the run. max_chars: bu-pi maxContextChars, default 4
	characters per token of the context window (bu-pi), 240k when the window is unknown. token_threshold: bu-pi
	compactAtTokens, which replaces both triggers. overflow_only: compact on a context-window error alone (Responses
	models, which the server compacts; it cannot rescue a request already over the window: 400 with or without
	context_management, live gpt-5-nano)."""

	token_threshold: int | None = None
	max_chars: int | None = None
	overflow_only: bool = False

	async def prepare_model_request(self, ctx: RunContext[Session], request_context: ModelRequestContext):
		s, messages = ctx.deps, request_context.messages
		overflowed = s.overflowed_step == ctx.run_step  # this attempt follows a context-window error
		if overflowed or (not self.overflow_only and self._due(s, request_context)):
			started, covered, summaries, failed = now(), s.covered, len(s.summaries), False
			before = _estimate(_projected(s, messages))
			try:
				await _compact(s, messages, request_context)
			except Exception as e:
				failed = True
				logger.warning(
					redact(f'Compaction failed, continuing with the full history: {type(e).__name__}: {e}', s.repl.secrets)
				)
			if failed or len(s.summaries) > summaries:  # a summary was asked for (not: too little history to compact)
				after = _estimate(_projected(s, messages))
				s.rec.compaction('overflow' if overflowed else 'client', now() - started, before, after, s.covered != covered)
		request_context.messages = _projected(s, messages)
		return request_context

	def _due(self, s: Session, request_context: ModelRequestContext) -> bool:
		messages, window = request_context.messages, request_context.model.context_window
		params = request_context.model_request_parameters
		system = sum(len(p.content) for p in params.instruction_parts or [])
		tools = len(
			_js(
				[
					{'name': t.name, 'description': t.description, 'parameters': t.parameters_json_schema}
					for t in [*params.function_tools, *params.output_tools]
				]
			)
		)
		tokens = _tokens(s, messages, system + tools)
		if self.token_threshold is not None:
			return tokens >= self.token_threshold
		max_chars = self.max_chars or (window * 4 if window else 240_000)
		chars = _chars(_projected(s, messages)) + system
		return chars > 0.75 * max_chars or bool(window and tokens > 0.65 * window)

	async def on_model_request_error(self, ctx: RunContext[Session], *, request_context: ModelRequestContext, error: Exception):
		s = ctx.deps
		if not isinstance(error, ModelContextWindowExceededError) or s.overflowed_step == ctx.run_step:
			raise error
		s.overflowed_step = ctx.run_step
		logger.warning(f'{error.model_name}: the request is over the context window; compacting and sending it again')
		raise RetryModelRequest()


def _projected(s: Session, messages: list[ModelMessage]) -> list[ModelMessage]:
	return [s.checkpoint, *messages[s.covered :]] if s.checkpoint else messages


def _plain(messages: list[ModelMessage]) -> Any:
	"""Message content as JSON data (bu-pi's archive): kind, part kind, tool name and call id, content or args. The system
	prompt, reasoning, usage, ids, timestamps, signatures and provider details are omitted; images become a note."""

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
					if not isinstance(p, (SystemPromptPart, ThinkingPart))
				],
			}
			for m in messages
		],
		fallback=str,
	)


def _pi(messages: list[ModelMessage]) -> list[dict[str, Any]]:
	"""The messages as bu-pi holds them (pi-ai UserMessage, AssistantMessage, ToolResultMessage: one per request part)
	after contextChars' replacer: no signatures, no tool result details, an image as {type: image}. Usage, ids,
	timestamps and model are wire metadata bu-pi counts too (20-30% of its size in matrix v2). Not reproducible from a
	Pydantic AI message: cost amounts (0 here) and pi-ai's api name (the provider name here)."""

	def ms(m: ModelMessage) -> int:
		return int((m.timestamp.timestamp() if m.timestamp else time.time()) * 1000)

	def blocks(content: Any) -> list[dict[str, Any]]:
		items = content if isinstance(content, list) else [content]
		return [
			{'type': 'image'} if _is_image(c) else {'type': 'text', 'text': c if isinstance(c, str) else as_text(c)}
			for c in items
		]

	out: list[dict[str, Any]] = []
	for m in messages:
		if isinstance(m, ModelResponse):
			content: list[dict[str, Any]] = []
			for p in m.parts:
				if isinstance(p, TextPart):
					content.append({'type': 'text', 'text': p.content})
				elif isinstance(p, ThinkingPart):
					content.append({'type': 'thinking', 'thinking': p.content})
				elif isinstance(p, ToolCallPart):
					content.append({'type': 'toolCall', 'id': p.tool_call_id, 'name': p.tool_name, 'arguments': p.args_as_dict()})
			u, calls = m.usage, any(isinstance(p, ToolCallPart) for p in m.parts)
			out.append(
				{
					'role': 'assistant',
					'content': content,
					'api': m.provider_name,
					'provider': m.provider_name,
					'model': m.model_name,
					**({'responseId': m.provider_response_id} if m.provider_response_id else {}),
					'usage': {
						'input': max(u.input_tokens - u.cache_read_tokens - u.cache_write_tokens, 0),
						'output': u.output_tokens,
						'cacheRead': u.cache_read_tokens,
						'cacheWrite': u.cache_write_tokens,
						'totalTokens': u.total_tokens,
						'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0, 'total': 0},
					},
					'stopReason': 'toolUse' if calls else 'length' if m.finish_reason == 'length' else 'stop',
					'timestamp': ms(m),
				}
			)
			continue
		for p in m.parts:
			if isinstance(p, UserPromptPart):
				user = p.content if isinstance(p.content, str) else blocks(list(p.content))
				out.append({'role': 'user', 'content': user, 'timestamp': ms(m)})
			elif isinstance(p, ToolReturnPart) or (isinstance(p, RetryPromptPart) and p.tool_name):
				# Pydantic AI 2.x: a rejected call (schema error, ModelRetry) is a ToolReturnPart with outcome 'retried'
				error = isinstance(p, RetryPromptPart) or p.outcome in ('failed', 'retried')
				text = p.model_response() if isinstance(p, RetryPromptPart) else p.model_response_str() if error else None
				out.append(
					{
						'role': 'toolResult',
						'toolCallId': p.tool_call_id,
						'toolName': p.tool_name,
						'content': blocks(p.content if text is None else text),
						'isError': error,
						'timestamp': ms(m),
					}
				)
			elif isinstance(p, (RetryPromptPart, RetryFeedbackPart)):  # 2.x: RetryFeedbackPart, e.g. the delivery repair
				out.append({'role': 'user', 'content': p.model_response(), 'timestamp': ms(m)})
	return out


def _js(value: Any) -> str:  # as JSON.stringify: no spaces, a CJK character counts 1, not 6
	return json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)


def _chars(messages: list[ModelMessage]) -> int:
	"""bu-pi contextChars: the length of JSON.stringify of the messages."""
	return len(_js(_pi(messages)))


def _estimate(messages: list[ModelMessage]) -> int:
	"""pi-coding-agent estimateTokens, summed: content characters / 4 per message, an image 4800 characters."""
	total = 0
	for m in _pi(messages):
		content = m['content']
		if isinstance(content, str):
			n = len(content)
		else:
			n = 0
			for b in content:
				if b['type'] == 'toolCall':
					n += len(b['name']) + len(_js(b['arguments']))
				else:
					n += 4800 if b['type'] == 'image' else len(b.get('text') or b.get('thinking') or '')
		total += -(-n // 4)
	return total


def _tokens(s: Session, messages: list[ModelMessage], fixed: int) -> int:
	"""bu-pi RunContext.tokens: the last response's context (measured after the last checkpoint) plus the estimate of
	what came after it, at least the estimate of the request. fixed: system prompt and tool definition characters."""
	estimate = _estimate(_projected(s, messages)) + -(-fixed // 4)
	for i in range(len(messages) - 1, s.usage_after - 1, -1):
		m = messages[i]
		if isinstance(m, ModelResponse) and m.finish_reason != 'error' and m.usage.total_tokens > 0:
			return max(estimate, m.usage.total_tokens + _estimate(messages[i + 1 :]))
	return estimate


async def _compact(s: Session, messages: list[ModelMessage], request_context: ModelRequestContext) -> None:
	starts = [i for i, m in enumerate(messages) if isinstance(m, ModelResponse) and i >= s.covered]
	# Keep the last two assistant/tool groups (no tool result is orphaned) and summarize at least one more: with only
	# the task before them, the checkpoint repeats the task and cannot be smaller.
	if len(starts) < 3 or starts[-2] <= s.covered:
		return
	cut = starts[-2]
	plain = redact(_plain(([s.checkpoint] if s.checkpoint else []) + messages[s.covered : cut]), s.repl.secrets)
	# bu-pi: 12k output tokens, 120 s, low effort; a cache write for a one-off prompt is never read
	inherited = (request_context.model_settings or {}).items()
	dropped = (
		'tool_choice',
		'parallel_tool_calls',
		'cache',
		'openai_context_management',
		'request_timeout',
		'first_event_timeout',
	)
	settings = {k: v for k, v in inherited if k not in dropped}
	settings['max_tokens'] = 12_000
	model = request_context.model
	_deadlines(s, settings, model, 120)
	for key in ('thinking', 'openai_reasoning_effort'):
		if settings.get(key) and settings[key] != 'none':
			settings[key] = 'low'
	prompt = f'<conversation>\n{json.dumps(plain, ensure_ascii=False)}\n</conversation>\n\n{SUMMARY_PROMPT}'
	response = await model_request(
		StreamedRequest(model) if isinstance(model, OpenAIResponsesModel) else model,  # as StreamResponses
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
	s.checkpoint, s.covered, s.usage_after = checkpoint, cut, len(messages)


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
	"""An OpenAI reasoning model on chat completions that takes reasoning_effort='none' ('openai-chat:gpt-6-luna', or
	ChatOpenAI('gpt-6-luna', base_url=proxy)). Judged by the model name, not the host: a proxy or Azure in front of
	gpt-6-luna turns reasoning on by default too and 400s every request with function tools. Names OpenAI's profile
	does not know (DeepSeek, Grok, OpenRouter's 'openai/...', local models) get nothing. o1, o3, o4-mini and gpt-5
	reject 'none' and run function tools with reasoning on."""
	from pydantic_ai.profiles.openai import openai_model_profile

	name = model.split(':', 1)[1] if isinstance(model, str) else model.model_name
	profile = openai_model_profile(name) or {}
	return bool(profile.get('openai_supports_reasoning')) and bool(profile.get('openai_supports_reasoning_effort_none'))


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
	server-side compaction threshold (default 150k, at most 65% of the window); elsewhere an extra trigger next to
	bu-pi's. max_context_chars: bu-pi's character budget for client-side compaction (Compaction.max_chars; no effect with server-side compaction). reasoning_effort=None
	sends no effort (the gateway then applies the alias's own: bu-fast medium, bu-ultrafast low, bu-smart high)."""
	mode = check_mode(mode)
	model = model_ref(model)
	kind = model_kind(model)
	reasoning = reasoning_supported(model)
	if kind == 'responses':  # the evaluated configuration (reasoning models)
		# store=False as bu-pi: a stored response came back 170-320 ms later (time to first byte, 39k-83k tokens). Nothing
		# reads it back: reasoning and compaction items round-trip encrypted, no previous_response_id (the gateway's rules)
		settings: OpenAIResponsesModelSettings | dict = {
			'openai_store': False,
			'openai_reasoning_effort': reasoning_effort,
			'openai_reasoning_summary': 'auto',
			'openai_reasoning_context': 'auto',  # bu-pi sends no context; Pydantic AI would send all_turns
			'max_tokens': 32_768,
		}
		if reasoning_effort is None:
			del settings['openai_reasoning_effort']
		if not reasoning:  # gpt-4.1, gpt-4o: reasoning params 400, and 32k is above their output cap
			settings = {'openai_store': False}
		# Compaction: the server cannot compact a request already over the window; that 400 gets a checkpoint instead
		overflow = Compaction(overflow_only=True)
		capabilities = [
			BrowserLoop(),
			LazyCompaction(token_threshold=compact_at_tokens),
			StreamResponses(),
			overflow,
			Recording(),
		]
		skip_responses_transform()  # bu-pi's Node SDK sends the body as is
	elif kind == 'chat':  # DeepSeek, vLLM, Ollama: no reasoning settings, no output cap they may reject
		# OpenAI's own reasoning models turn reasoning on by default on chat completions and then reject function tools
		# (400 "use /v1/responses or set reasoning_effort to 'none'")
		settings = {'openai_reasoning_effort': 'none'} if _openai_reasoning_on_chat(model) else {}
		capabilities = [BrowserLoop(), Compaction(compact_at_tokens, max_context_chars), Recording()]
	else:  # other providers: unified thinking (dropped where the profile has none), the provider's own max_tokens
		settings = {'thinking': reasoning_effort or 'medium'} if reasoning else {}
		system = model.split(':', 1)[0] if isinstance(model, str) else str(getattr(model, 'system', ''))
		own = {**(getattr(model, 'settings', None) or {}), **(model_settings or {})}
		if system.startswith('google') and 'max_retries' not in own:
			# google-genai retries nothing unless asked; the OpenAI and Anthropic SDKs retry each request twice. Gemini's
			# second 503 'overloaded' of a run ended it (BrowserLoop's one retry per run was spent).
			settings['max_retries'] = 2
		if system == 'anthropic':
			# Anthropic caches nothing unless asked: every request re-billed the whole prompt (cache_read was always 0).
			# Pydantic AI's unified cache setting caches the system prompt, the tools and the conversation so far, in the
			# mode the client supports; any anthropic_cache* setting the caller gave takes precedence over it there, and
			# a cache setting of the caller's own (on the model or in model_settings) is left alone.
			if 'cache' not in own:
				settings['cache'] = True
			# Claude models with adaptive thinking return no thinking text unless asked (display 'omitted'); bu-pi's pi-ai
			# asks for 'summarized'. Without it every thinking block came back empty (124 of 124 on Haiku bub2-001), the
			# history lacked the reasoning bu-pi's context size counts, and Haiku never compacted (matrix v2: 0, bu-pi 17).
			profile = (anthropic_model_profile(model.split(':', 1)[1]) or {}) if isinstance(model, str) else model.profile
			adaptive = profile.get('anthropic_supports_adaptive_thinking', False)
			if reasoning and adaptive and 'anthropic_thinking' not in own and own.get('thinking') is not False:
				settings = {**settings, 'anthropic_thinking': {'type': 'adaptive', 'display': 'summarized'}}
		capabilities = [BrowserLoop(), Compaction(compact_at_tokens, max_context_chars), Recording()]
	model_own = getattr(model, 'settings', None) or {}
	agent = Agent(
		model,
		deps_type=Session,
		defer_model_check=True,
		output_type=_outputs(output_type),
		instructions=f'{SYSTEM_PROMPT}{AX_PROMPT if mode == "ultrafast" else ""}\n{instructions}'.strip(),
		# sequential: parallel python calls of one response run one after another, each timed from its own start (bu-pi
		# executionMode 'sequential'). Timed at the call, a queued cell waited for the REPL on its stale budget and ran past
		# the delivery point (rc1 Sonnet bub2-002 hit the hard timeout).
		tools=[Tool(python, max_retries=TOOL_RETRIES, sequential=True), *tools],
		# a Model's own settings sit below the Agent's in Pydantic AI: a default here would override them (thinking=False)
		model_settings=cast(Any, {**{k: v for k, v in settings.items() if k not in model_own}, **(model_settings or {})}),
		# 'tools' is the budget Pydantic AI gives a tool name that does not exist, and that name's count never resets:
		# two such calls ended DeepSeek bub2-007 at step 140. bu-pi answers "Tool X not found" and goes on (max_steps
		# bounds it). python and Tools get the same budget (TOOL_RETRIES).
		# 'output' is one budget for the whole run, never reset: six failed deliveries spread over a long run (an
		# expression error, a schema slip, a thinking-only reply, a refused split delivery counts two) ended it with
		# "Exceeded maximum output retries (5)". bu-pi has no such cap; max_steps and the timeout bound a run.
		retries={'tools': TOOL_RETRIES, 'output': TOOL_RETRIES},
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


def described(e: BaseException) -> str:
	"""The run's error line. A connection failure names its transport cause: the OpenAI SDK says only 'Connection
	error.' for a refused connect, a DNS failure and running out of file descriptors alike (gwscale F1: 100 Agents
	on macOS's 256 open files read 'ModelConnectionError: Connection error.')."""
	text = f'{type(e).__name__}: {e}'
	if isinstance(e, ModelConnectionError):
		root, seen = e, {id(e)}
		while (cause := root.__cause__ or root.__context__) is not None and id(cause) not in seen:
			root = cause
			seen.add(id(root))
		if root is not e and str(root) and str(root) not in text:
			text += f' ({type(root).__name__}: {root})'
	return text


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
	recording = CURRENT.set(session.rec)  # this task's context: StreamedRequest reaches the recorder through it
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
			error = (explain_error and explain_error(e)) or described(e)
	except Exception as e:
		name = session.error_type = type(e).__name__
		status = 'max_steps' if name == 'UsageLimitExceeded' else 'error'
		error, messages = (explain_error and explain_error(e)) or described(e), session.messages
	CURRENT.reset(recording)
	partial = session.partial()
	new = messages[len(message_history or []) :]  # an earlier task's text is never this run's fallback
	if output is None and status != 'completed':  # a completed run delivered it: None from a nullable schema is the answer
		# the fallback text is model output that may quote a secret (e.g. read off a screenshot): redact it like .text
		output = json.dumps(partial, ensure_ascii=False) if partial is not None else redact(last_text(new), session.repl.secrets)
	text = redact(as_text(output), session.repl.secrets)
	error = redact(error, session.repl.secrets)  # provider/tool exceptions can quote a secret; Agent.run logs this
	session.rec.loop_ended()
	usage, cost = usage_and_cost(new + session.summaries, model_ref)
	if search:
		session.rec.cost_search = sum(search.charges[searched:])
	if session.summaries:
		session.rec.cost_compaction = usage_and_cost(list(session.summaries), model_ref)[1]
	if cost is not None and search:  # web searches that named a charge; an unknown model cost stays unknown
		cost += sum(search.charges[searched:])
	steps = sum(isinstance(m, ModelResponse) for m in new)
	duration = time.monotonic() - session.started
	success = session.success if status == 'completed' else None
	session.messages = messages  # a follow-up continues the raw transcript: providers reject edited signed thinking
	forms = secret_forms(session.repl.secrets)
	if forms:  # model text, thinking and tool-call args can quote a secret read off a screenshot, and browser-use quotes
		# them back in requests: the delivery repair turn quotes the reply, a schema error echoes the rejected input
		messages = [replace(m, parts=[redact_part(p, forms) for p in m.parts]) for m in messages]
	return AgentHistoryList(status, text, output, steps, duration, usage, cost, partial, error, messages, success)


def redact_part(part: Any, forms: list[tuple[str, str]]) -> Any:
	# content of text, thinking, retry and tool-return parts (str, or a list of str, error dicts and images), tool-call args
	fields = ('content', 'args')
	return replace(
		part,
		**{k: redact_forms(getattr(part, k), forms) for k in fields if isinstance(getattr(part, k, None), (str, dict, list))},
	)


def thinking_and_text(m: ModelResponse) -> list[tuple[str, str]]:
	return [
		('thinking' if isinstance(p, ThinkingPart) else 'text', p.content)
		for p in m.parts
		if isinstance(p, (ThinkingPart, TextPart)) and p.content
	]
