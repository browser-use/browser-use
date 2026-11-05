"""Browser agent = Pydantic AI loop + one persistent Python REPL running browser-harness.

Learnings carried from browser-use-pi: deliver existing values (finish_from_repl), native screenshots
with only the last two kept, server-side compaction, one delivery turn near budget, partial results
that survive timeouts, and a killable worker so a hung cell never kills the run.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, cast

from genai_prices import calc_price
from pydantic import TypeAdapter, ValidationError
from pydantic_ai import Agent, BinaryContent, ModelRetry, RunContext, TextOutput, ToolOutput
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ToolRetryError
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ThinkingPart, ToolReturnPart
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.models.openai import OpenAIChatModel, OpenAICompaction, OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.settings import ToolOrOutput
from pydantic_ai.usage import UsageLimits
from pydantic_core import to_json, to_jsonable_python

from browser_use.agent.prompt import SYSTEM_PROMPT, secrets_prompt
from browser_use.agent.views import AgentHistoryList
from browser_use.ax import AX_PROMPT
from browser_use.llm import model_ref
from browser_use.repl import Repl, check_mode, redact
from browser_use.repl.session import redact_forms, secret_forms
from browser_use.telemetry.stats import RunStats

KEEP_IMAGE_RESULTS = 2
DELIVER_NOW = (
	'Budget nearly exhausted. Deliver the verified result now with finish/finish_from_repl. '
	'Reference saved files; explicitly list missing evidence. Do not perform more browser actions.'
)
DELIVERY_REPAIR = (  # bu-pi src/agent.ts:560, verbatim except tool names
	'The run ended without a validated delivery. Use finish_from_repl for an existing result or finish for a concise '
	'answer. Preserve all verified records; report missing evidence honestly. Do not repeat browser actions. This is '
	'the single delivery repair turn.'
)
DELIVERY_TOOLS = ['finish_from_repl', 'finish']
LINK = re.compile(r'\]\(<?([^)\s>]+)>?\)')  # markdown link targets
PARTIAL = re.compile(
	r'\b(partial(ly)?|incomplete|not (fully |yet |individually )?(verified|checked|opened|covered)|subset|sample of|'
	r'first page only|only \d+ of|remaining \d+|did not (check|cover|open|verify|reach))\b',
	re.I,
)
FILE = re.compile(r'`([\w./-]+\.(?:md|csv|json|jsonl|txt|tsv|xlsx|html|zip|pdf|png|jpe?g))`')  # `basket_brief.md`


@dataclass
class Session:
	"""Per-run state (Pydantic AI deps)."""

	repl: Repl
	timeout_s: float = 1700
	max_steps: int = 1000
	cell_timeout_s: float = 120
	started: float = field(default_factory=time.monotonic)
	finalizing: bool = False
	checked_delivery: bool = False  # the delivery guard fires once; a second identical finish is accepted
	checked_partial: bool = False  # the early-partial guard fires once
	success: bool = True  # finish(..., success=False): the agent delivered but could not do the task
	messages: list[ModelMessage] = field(default_factory=list)
	after_tool: Callable[[str, dict, dict], Awaitable[None]] | None = None  # observer hook (evals)
	stats: RunStats = field(default_factory=RunStats)  # telemetry counts (TELEMETRY.md)
	finish_via: str | None = None  # finish | finish_from_repl | text: how the result was delivered
	error_type: str | None = None  # class of the exception that ended the run

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
	r = await ctx.deps.repl.call('exec', code, ctx.deps.cell_timeout_s)
	ctx.deps.stats.add_cell(r, code, time.monotonic() - started)
	text = r['output']  # already cut to MAX_OUTPUT_CHARS by the worker
	if r['error']:
		text = f'{text}\nError: {r["error"]}'.strip()
	if ctx.deps.after_tool:
		await ctx.deps.after_tool('python', {'code': code}, r)
	shots = [BinaryContent(base64.b64decode(i['data']), media_type=i['media_type']) for i in r['images']]
	return [text or '(no output)', *shots]


def as_text(value: Any) -> str:
	"""A result as text: strings unchanged; models, dataclasses and lists of them as JSON (0.x model_dump_json)."""
	return value if isinstance(value, str) else to_json(value, fallback=str).decode()


def check_delivery(ctx: RunContext[Session], value: Any) -> None:
	"""One-shot repairs: a placeholder or links to unwritten files; a self-declared partial result with budget left."""
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
	left = s.timeout_s - (time.monotonic() - s.started)
	if not s.finalizing and not s.checked_partial and left > 0.4 * s.timeout_s and PARTIAL.search(text):
		# v1b stopped by choice with most of the budget left (2vxyzx top-5 of 37, bub2-007 40 of 404, bub2-014 at 7%).
		s.checked_partial = True
		raise ModelRetry(
			f'Your result says it is partial, and {left / 60:.0f} of {s.timeout_s / 60:.0f} minutes '
			'remain. If coverage is limited by choice, not by a blocker you already tried to get around, '
			'continue the missing items now, checkpoint progress, then finish. If a real blocker remains, '
			'finish again with the same result.'
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

	async def finish_from_repl(ctx: RunContext[Session], expression: str, success: bool = True):
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

	def finish(ctx: RunContext[Session], result, success: bool = True):
		check_delivery(ctx, result)
		ctx.deps.success, ctx.deps.finish_via = success, 'finish'
		return clean(ctx, result)

	def on_text(ctx: RunContext[Session], text: str):
		# Plain text keeps tool_choice=auto (as in bu-pi); a forced tool call every turn made finish() the only way to
		# stop and talk. A text-only reply ends the work: one delivery-only repair turn, then text is accepted.
		if not ctx.deps.finalizing:
			ctx.deps.finalizing = True
			raise ModelRetry(DELIVERY_REPAIR)
		ctx.deps.finish_via = 'text'
		if output_type is str:
			check_delivery(ctx, text)
			return clean(ctx, text)
		try:
			return clean(ctx, adapter.validate_json(text))
		except ValidationError as e:
			raise ModelRetry(f'Deliver with finish or finish_from_repl; text does not match the result schema: {str(e)[:2000]}')

	finish.__annotations__ = {'ctx': RunContext[Session], 'result': output_type, 'success': bool, 'return': output_type}
	finish_from_repl.__annotations__ = {
		'ctx': RunContext[Session],
		'expression': str,
		'success': bool,
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
				'existing text variable. Evaluated once; ends the task after validation. success=false when the task '
				'could not be done (blocked, not found, refused); the result says why.'
			),
		),
		ToolOutput(
			finish,
			name='finish',
			description=(
				'Submit the verified final result. For data already in the REPL, prefer finish_from_repl to avoid '
				'rewriting it. This ends the task. success=false when the task could not be done (blocked, not found, '
				'refused); the result says why.'
			),
		),
	]


class BrowserLoop(AbstractCapability[Session]):
	"""Keep only recent screenshots; one delivery-only turn near the time/step budget or after a text reply."""

	async def before_model_request(self, ctx: RunContext[Session], request_context: ModelRequestContext):
		s = ctx.deps
		s.messages = ctx.messages
		pruned = _prune_images(ctx.messages)
		if pruned is not None:  # same pattern as ProcessHistory: new objects, persisted
			ctx.messages[:] = pruned
			request_context.messages = pruned.copy()
		if not s.finalizing and (ctx.run_step >= s.max_steps - 1 or time.monotonic() - s.started >= 0.9 * s.timeout_s):
			s.finalizing = True
			ctx.enqueue(DELIVER_NOW)
		if s.finalizing:  # step settings were resolved before this hook: restrict this very request
			settings = dict(request_context.model_settings or {})
			settings['tool_choice'] = delivery_tool_choice(request_context.model, settings)
			request_context.model_settings = cast(Any, settings)
		return request_context

	async def wrap_tool_execute(self, ctx: RunContext[Session], *, call, tool_def, args, handler) -> Any:
		"""Custom tools (Tools) run in this process, so the worker's redaction never saw their results: redact them
		(strings, ActionResult and other models, nested values) and their retry messages before the model does."""
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


def build_agent(
	model: Any = 'openai-responses:gpt-6-luna',
	*,
	output_type: Any = str,
	reasoning_effort: str | None = 'medium',
	instructions: str = '',
	compact_at_tokens: int = 150_000,
	mode: str | None = 'default',
	tools: Sequence[Any] = (),
	model_settings: dict | None = None,
) -> Agent[Session, Any]:
	"""mode='ultrafast' appends AX_PROMPT (the `bu` helpers) to the system prompt; the Repl needs the same mode.
	tools: extra Pydantic AI tools (Tools().functions). model_settings: merged over the defaults. reasoning_effort=None
	sends no effort (the gateway then applies the alias's own: bu-ultrafast low, bu-auto medium, bu-smart high)."""
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
		capabilities = [BrowserLoop(), OpenAICompaction(token_threshold=compact_at_tokens)]
	elif kind == 'chat':  # DeepSeek, vLLM, Ollama: no reasoning settings, no output cap they may reject
		settings, capabilities = {}, [BrowserLoop()]
	else:  # other providers: unified thinking (dropped where the profile has none), the provider's own max_tokens
		settings = {'thinking': reasoning_effort or 'medium'} if reasoning else {}
		capabilities = [BrowserLoop()]
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
	charge = ((m.provider_details or {}).get('browser_use') or {}).get('charge_usd')
	try:
		value = float(charge) if isinstance(charge, (str, int, float)) and not isinstance(charge, bool) else None
	except ValueError:
		return None
	return value if value is not None and math.isfinite(value) and value >= 0 else None


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
			try:
				cost += float(calc_price(u, model_ref=model_ref, provider_id=provider).total_price)  # cache writes too
			except Exception:  # - unknown price: report tokens, not a made-up cost
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
	budget = asyncio.timeout(session.timeout_s)
	task = redact(task, session.repl.secrets)  # 0.x: a secret written into the task reaches the model as its name only
	try:
		async with budget:
			result = await agent.run(
				task, deps=session, message_history=message_history, usage_limits=UsageLimits(request_limit=session.max_steps)
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
	usage, cost = usage_and_cost(new, model_ref)
	steps = sum(isinstance(m, ModelResponse) for m in new)
	duration = time.monotonic() - session.started
	success = session.success if status == 'completed' else None
	return AgentHistoryList(status, text, output, steps, duration, usage, cost, partial, error, messages, success)


def thinking_and_text(m: ModelResponse) -> list[tuple[str, str]]:
	return [
		('thinking' if isinstance(p, ThinkingPart) else 'text', p.content)
		for p in m.parts
		if isinstance(p, (ThinkingPart, TextPart)) and p.content
	]
