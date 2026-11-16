import {
  Agent,
  type AgentMessage,
  type AgentTool,
  type StreamFn,
} from '@earendil-works/pi-agent-core';
import {
  validateToolArguments,
  type Model,
  type Api,
  type ToolChoice,
  type ToolCall,
  type Usage,
} from '@earendil-works/pi-ai';
import { Type, type TSchema } from 'typebox';
import { Check, Errors } from 'typebox/value';
import { CellError, type BrowserRuntime } from './runtime.js';
import { Observer } from './observer.js';
import { RunContext, contextSettings, conversation, contextWindowError } from './context.js';
import { deadlineStream } from './model-stream.js';
import { researchTools } from './research-tools.js';
import type {
  BrowserUseOptions,
  RunOptions,
  RunResult,
  StopReason,
  ContextMetrics,
} from './types.js';
import { redact } from './history.js';
import { SEARCH_PROMPT, SYSTEM_PROMPT, captchaPrompt, downloadsPrompt } from './prompt.js';
import { launchesBrowser } from './browser.js';
import { AX_PROMPT } from './ax.js';
import {
  positiveInteger,
  DEFAULT_CELL_TIMEOUT_MS,
  DEFAULT_MAX_STEPS,
  DEFAULT_RUN_TIMEOUT_MS,
} from './protocol.js';
import { bounded, type RunControl } from './control.js';
import { setTimeout as delay } from 'node:timers/promises';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

export const zeroUsage = (): Usage => ({
  input: 0,
  output: 0,
  cacheRead: 0,
  cacheWrite: 0,
  totalTokens: 0,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
});
// Failures worth one more inference call. Anchored where a trailing access denial must not retry.
const TRANSIENT_MODEL_ERRORS = [
  /^OpenAI API error \(5\d{2}\): /,
  /^Connection error\.$/,
  /stream ended before a terminal|Model stream exceeded|terminated|ECONNRESET|socket hang up|Unable to verify model access right now\. Please retry\./i,
  /^(?:(?:server_error|unknown): )?Sorry, something went wrong\.$/,
  /^An error occurred while processing your request\. You can retry your request,/,
  /^The server had an error while processing your request\./,
  /^The service is temporarily unavailable\.$/,
  /^Rate limit reached for .* Please try again in [\d.]+m?s\./,
  /^peer closed connection without sending complete message body/,
  /^Server disconnected without sending a response\.$/,
  /^(?:\[Errno \d+\] )?Connection reset by peer$/,
  /^Request timed out\.$/,
  /^stream inactive >\d+s$/,
];
/** Python DELIVER_NOW, with this SDK's tool names. */
const DELIVER_NOW =
  'Budget nearly exhausted. Deliver the verified result now with finish/finish_from_js. Reference saved files; explicitly list missing evidence. Do not perform more browser actions. If the task is not fully finished as requested, set success=false; else success=true.';
/** Python agent/loop.py LINK and FILE: markdown link targets and `file.ext` names an answer points to. */
const LINK = /\]\(<?([^)\s>]+)>?\)/g;
const FILE = /`([\w./-]+\.(?:md|csv|json|jsonl|txt|tsv|xlsx|html|zip|pdf|png|jpe?g))`/g;
const ALNUM = /[\p{L}\p{N}]/u;
/** JSON with no value: empty arrays, objects and strings, null. A number or a boolean is a value. */
function holdsNothing(value: unknown): boolean {
  if (Array.isArray(value)) return value.every(holdsNothing);
  if (value !== null && typeof value === 'object') return Object.values(value).every(holdsNothing);
  return value === null || value === undefined || (typeof value === 'string' && !ALNUM.test(value));
}
/** Python's finish(success=...) verdict: the 0.x done(success) rule. */
const VERDICT = Type.Optional(
  Type.Boolean({
    description:
      'true only when the result delivers what the task asked for, every value observed in this session; false when blocked, refused, partial, or a requested value was not found (never fill it from memory)',
  }),
);
const MODEL_TIMEOUT = /^Model stream exceeded (\d+) ms/;
/** Python TRANSIENT_FAILED_CODES: a Responses failure inside an HTTP 200 with one of these codes is transient. */
const TRANSIENT_FAILED_CODES =
  /^(?:server_error|overloaded|request_timeout|upstream_stream_failed|model_request_failed)(?::|$)/;
/** Python TRANSIENT: rate limit, request timeout, 5xx; pi-ai reports them as "<Provider> API error (<status>): ...". */
const TRANSIENT_STATUS = /API error \((?:408|429|5\d\d)\)/;
/** Retry-After or retry-after-ms, in milliseconds. */
export function retryAfter(headers: Headers): number | undefined {
  const ms = Number.parseFloat(headers.get('retry-after-ms') ?? '');
  if (Number.isFinite(ms)) return Math.max(0, ms);
  const value = headers.get('retry-after');
  if (!value) return undefined;
  const seconds = Number.parseFloat(value);
  const delay = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(value) - Date.now();
  return Number.isFinite(delay) ? Math.max(0, delay) : undefined;
}
/** A rate-limit message's own hint ("Please try again in 1.5s"), when no header was seen. */
function retryHint(message: string): number | undefined {
  const hint = /try again in ([\d.]+)(ms|s)\b/i.exec(message);
  if (!hint) return undefined;
  const value = Number.parseFloat(hint[1]!);
  return Number.isFinite(value) ? value * (hint[2] === 'ms' ? 1 : 1000) : undefined;
}
const NO_TIME =
  'Not run: the time budget is spent. The next turn is delivery-only: finish or finish_from_js with what you have.';
/** Python agent/loop.py TOOL_CALL_MARKUP: a tool call written as text ran nothing and is no answer. */
const TOOL_CALL_MARKUP = /<\/?tool_call>/;
// httpx and openai transport failures, relayed bare ("ReadError") or with their message.
const TRANSIENT_TRANSPORT_ERRORS =
  /^(?:ReadError|ReadTimeout|RemoteProtocolError|APITimeoutError)(?::|$)/;
/** A proxy that relays a mid-stream upstream failure prefixes it with the exception class
 * ("APIError: ..."); the message after that prefix decides. */
export function transientModelError(message: string | undefined): boolean {
  const text = message ?? '';
  const detail = text.replace(/^[A-Za-z]+(?:Error|Exception|Timeout): /, '');
  return (
    TRANSIENT_TRANSPORT_ERRORS.test(text) ||
    TRANSIENT_STATUS.test(text) ||
    TRANSIENT_FAILED_CODES.test(detail) ||
    TRANSIENT_MODEL_ERRORS.some((pattern) => pattern.test(detail))
  );
}

function addUsage(total: Usage, extra: Usage): Usage {
  for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens'] as const)
    total[key] += extra[key];
  for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'total'] as const)
    total.cost[key] += extra.cost[key];
  return total;
}
function sumUsage(messages: AgentMessage[]): Usage {
  const result = zeroUsage();
  for (const message of messages) if (message.role === 'assistant') addUsage(result, message.usage);
  return result;
}

export async function runAgent(
  runtime: BrowserRuntime,
  model: Model<Api>,
  config: BrowserUseOptions & { model: string; streamFn: StreamFn },
  workspace: string,
  task: string,
  schema: TSchema,
  options: RunOptions,
  session?: {
    messages: AgentMessage[];
    control: RunControl;
    save: (messages: AgentMessage[]) => void;
    checkpoint?: (messages: AgentMessage[], usage: Usage) => Promise<void>;
    eventsPath?: string;
  },
): Promise<RunResult<unknown>> {
  const maxSteps = positiveInteger('maxSteps', options.maxSteps ?? DEFAULT_MAX_STEPS);
  const timeoutMs = positiveInteger('timeoutMs', options.timeoutMs ?? DEFAULT_RUN_TIMEOUT_MS);
  const maxContextChars = positiveInteger(
    'maxContextChars',
    options.maxContextChars ?? model.contextWindow * 4,
  );
  if (
    options.maxCostUsd !== undefined &&
    (!Number.isFinite(options.maxCostUsd) || options.maxCostUsd <= 0)
  ) {
    throw new Error('maxCostUsd must be a finite positive number.');
  }
  if (options.compaction !== undefined && typeof options.compaction !== 'boolean')
    throw new Error('compaction must be boolean.');
  const settings = contextSettings(options.context, model);
  runtime.beginRun();
  const start = Date.now();
  /** Python Session.delivery_at: the delivery-only turn starts at 90% of the budget, or earlier on a short budget so
   * the delivery request has up to 30 s. */
  const deliveryAt = timeoutMs - Math.max(0.1 * timeoutMs, Math.min(30_000, 0.5 * timeoutMs));
  /** Milliseconds until the delivery-only turn starts, or on a delivery turn until the run's end. */
  const timeLeft = () => (delivering() ? timeoutMs : deliveryAt) - (Date.now() - start);
  let previousMessages = session?.messages.length ?? 0;
  const hookTimeout = config.hookTimeoutMs ?? 30_000;
  let steps = 0;
  let finishRepairs = 0;
  let providerRetries = 0;
  let providerRetried = false;
  let retryAfterMs: number | undefined;
  let retriedUsage = zeroUsage();
  let finalizing = false;
  let compactionFailures = 0;
  let lastCompactionFailure: ContextMetrics['lastCompactionFailure'];
  let beforeCompaction: ContextMetrics['beforeCompaction'];
  const warnings: string[] = [];
  const context = new RunContext(
    model,
    deadlineStream(
      (selected, request, settings) =>
        config.streamFn(selected, redact(request, config.redact ?? []), settings),
      config.compactionTimeoutMs ?? 120_000,
    ),
    workspace,
    maxContextChars,
    options.compaction !== false,
    config.redact ?? [],
    settings,
  );
  let completion: { output: unknown; text: string } | undefined;
  let stopped: StopReason | undefined;
  const codeParameters = Type.Object({ code: Type.String({ minLength: 1 }) });
  const cellFailures = new Map<string, CellError>();
  const javascript: AgentTool<typeof codeParameters> = {
    name: 'javascript',
    label: 'Browser JavaScript',
    description: `Execute JavaScript in a persistent Node REPL with raw CDP. Cell deadline: ${config.cellTimeoutMs ?? DEFAULT_CELL_TIMEOUT_MS} ms. Checkpoint small batches before the deadline. Use screenshot() for native images.`,
    parameters: codeParameters,
    executionMode: 'sequential',
    replay: 'never',
    execute: async (_id, params: { code: string }, signal) => {
      // A cell never runs into the delivery turn's time (Python agent/loop.py python()).
      const left = deliveryAt - (Date.now() - start);
      if (left <= 0)
        return {
          content: [{ type: 'text', text: NO_TIME }],
          details: {},
        };
      let result;
      try {
        result = await runtime.execute(
          params.code,
          config.cellTimeoutMs ?? DEFAULT_CELL_TIMEOUT_MS,
          signal,
          Math.max(left, 1000),
        );
      } catch (error) {
        if (!(error instanceof CellError)) throw error;
        // Pi converts thrown tools to text-only errors. Restore their native evidence
        // in afterToolCall while retaining Pi's error flag and application hook control.
        cellFailures.set(_id, error);
        throw new Error(
          `${error.message}\nState reset: ${error.stateReset}. Actions may already have happened.\nPartial output: ${error.result.text}\nCaptured output file: ${error.result.outputFile ?? '(none)'}`,
        );
      }
      return {
        content: [{ type: 'text', text: result.text }, ...result.images],
        details: {
          outputFile: result.outputFile,
          targetId: result.targetId,
          observationTargetId: result.observationTargetId,
        },
      };
    },
  };
  const rejectedDelivery = (reason: string, rejected: unknown) => {
    let value: string | undefined;
    try {
      value = JSON.stringify(rejected)?.slice(0, 2000);
    } catch {
      value = '[Non-JSON value; provide a JSON-serializable result.]';
    }
    return new Error(
      `Final delivery rejected: ${reason}\nOriginal result schema: ${JSON.stringify(schema)}\nRejected value or arguments: ${value}\nFor finish, put every result field inside the single result property: {"result": <value matching the schema>}. For finish_from_js, return that value directly. Repair this delivery in the current session; do not repeat completed browser actions.`,
    );
  };
  const stringSchema = (schema as { type?: unknown }).type === 'string';
  let checkedDelivery = false;
  let verdict: boolean | undefined;
  /** Python check_delivery: one repair for a placeholder or links to files that do not exist. Not on the run's
   * last request, where nothing can follow it: there the result is delivered and the problem noted. */
  const deliveryProblem = (output: unknown, text: string, last = false): string | undefined => {
    if (checkedDelivery) return undefined;
    let problem: string | undefined;
    if (!ALNUM.test(text) || (typeof output !== 'string' && holdsNothing(output)))
      problem = `The result ${JSON.stringify(text.slice(0, 20))} is a placeholder, not the answer.`;
    else {
      const targets = [...text.matchAll(LINK), ...text.matchAll(FILE)].map((m) => m[1]!);
      const missing = [...new Set(targets)]
        .filter(
          (target) =>
            !/^([a-z][\w+.-]*:|#|\/\/)/i.test(target) &&
            // Downloads land in workspace/downloads; an answer names them by file name.
            ![workspace, resolve(workspace, 'downloads')].some((directory) =>
              existsSync(resolve(directory, target.split('#')[0]!)),
            ),
        )
        .sort();
      if (missing.length)
        problem = `These linked files do not exist in the workspace: ${missing.slice(0, 10).join(', ')}.`;
    }
    if (!problem) return undefined;
    if (last || steps >= maxSteps || finishRepairs >= 2) {
      if (warnings.length < 32) warnings.push(`Delivered as it is on the last request: ${problem}`);
      return undefined;
    }
    checkedDelivery = true;
    return `${problem} Deliver the actual result: finish_from_js with the existing records, or finish with the full answer inline. Do not repeat browser actions.`;
  };
  let splitResponse: string | undefined;
  /** Python check_split_delivery: a delivery that shares its response with another delivery call, or with any call
   * after it, is not the final answer (Sonnet sent a stub finish and then the real one). Refused in one response per
   * run, never on a delivery turn. */
  const splitDelivery = (message: AgentMessage, id: string, name: string): string | undefined => {
    if (delivering() || message.role !== 'assistant') return undefined;
    const calls = message.content.filter((c) => c.type === 'toolCall');
    const key = calls.map((c) => c.id).join(' ');
    if (splitResponse !== undefined && splitResponse !== key) return undefined;
    const at = calls.findIndex((c) => c.id === id);
    if (at < 0) return undefined;
    const others = calls
      .filter((c, i) => i > at || (i < at && deliveryTools.includes(c.name)))
      .map((c) => c.name);
    if (!others.length) return undefined;
    splitResponse = key;
    return `Not delivered: ${others.join(', ')} came in the same response as this ${name}, so it was not the final answer. Deliver once, in a response with no tool call after the delivery: finish_from_js with the existing records, or finish with the full answer.`;
  };
  /** last: nothing can follow this delivery (a text reply on a spent budget, or after the repair turn), so a delivery
   * problem is noted instead of refused: refusing it there lost the answer (Python check_delivery). */
  const acceptResult = async (
    output: unknown,
    signal?: AbortSignal,
    success?: boolean,
    last = false,
  ) => {
    if (!Check(schema, output))
      throw rejectedDelivery(
        `Final result does not match schema: ${JSON.stringify(Errors(schema, output).slice(0, 5)).slice(0, 2000)}`,
        output,
      );
    const serialized = typeof output === 'string' ? output : JSON.stringify(output);
    const problem =
      serialized === undefined ? undefined : deliveryProblem(output, serialized, last);
    if (problem) throw new Error(problem);
    if (config.validateResult) {
      const feedback = await bounded(
        () => config.validateResult!(output, signal),
        hookTimeout,
        signal,
      );
      if (feedback) throw rejectedDelivery(`Result rejected: ${feedback}`, output);
    }
    signal?.throwIfAborted();
    const text = serialized;
    if (text === undefined) throw new Error('The final result must be JSON serializable.');
    completion = { output, text };
    verdict = success;
    return {
      content: [{ type: 'text' as const, text: 'Result accepted.' }],
      details: {},
      terminate: true,
    };
  };
  const resultParameters = Type.Object({ result: schema, success: VERDICT });
  const finish: AgentTool<typeof resultParameters> = {
    name: 'finish',
    label: 'Deliver result',
    description:
      'Submit the verified final result, matching this schema. For data already in JavaScript, prefer finish_from_js to avoid rewriting it. This ends the task.',
    parameters: resultParameters,
    // Argument validation failures bypass afterToolCall in Pi's loop.
    prepareArguments: (args) => {
      try {
        return validateToolArguments(finish, {
          type: 'toolCall',
          id: 'finish-validation',
          name: 'finish',
          arguments: args as ToolCall['arguments'],
        });
      } catch (error) {
        // Pi appends the full arguments; rejectedDelivery already echoes them, capped.
        const reason = (error instanceof Error ? error.message : String(error)).replace(
          /\n\nReceived arguments:[\s\S]*$/,
          '',
        );
        throw rejectedDelivery(reason, args);
      }
    },
    executionMode: 'sequential',
    execute: async (_id, params: { result: unknown; success?: boolean }, signal) =>
      acceptResult(params.result, signal, params.success),
  };
  const expressionParameters = Type.Object({
    expression: Type.String({ minLength: 1 }),
    success: VERDICT,
  });
  const finishFromJs: AgentTool<typeof expressionParameters> = {
    name: 'finish_from_js',
    label: 'Deliver JavaScript value',
    description:
      'Deliver an existing value from the persistent REPL without printing or rewriting it. Expression must match the result schema of finish. For a string result use JSON.stringify(records) or an existing text variable. Evaluated once; ends the task after validation.',
    parameters: expressionParameters,
    executionMode: 'sequential',
    replay: 'never',
    execute: async (_id, params: { expression: string; success?: boolean }, signal) => {
      let output;
      try {
        output = await runtime.readResult(
          params.expression,
          config.cellTimeoutMs ?? DEFAULT_CELL_TIMEOUT_MS,
          signal,
        );
      } catch (error) {
        signal?.throwIfAborted();
        throw rejectedDelivery(error instanceof Error ? error.message : String(error), params);
      }
      return acceptResult(output, signal, params.success);
    },
  };
  // OpenAI restricts delivery turns with allowed_tools, so the tool list (part of the cached prompt prefix) stays.
  // Other providers on this api (xAI, gateways) reject allowed_tools; a baseUrl proxy for openai must pass it through.
  const keepTools = model.provider === 'openai' && model.api === 'openai-responses';
  const delivering = () => finalizing || finishRepairs > 0;
  const deliveryTools = ['finish', 'finish_from_js'];
  // pi-ai forwards toolChoice verbatim. 'required': under 'auto' a model can answer with text again and end incomplete.
  const deliveryChoice = {
    type: 'allowed_tools',
    mode: 'required',
    tools: deliveryTools.map((name) => ({ type: 'function', name })),
  } as unknown as ToolChoice;
  const refreshToolBudget = () => {
    context.toolChars = JSON.stringify(
      agent.state.tools.map(({ name, description, parameters }) => ({
        name,
        description,
        parameters,
      })),
    ).length;
  };
  const checkBudgets = (messages: AgentMessage[], systemPrompt: string, checkContext = true) => {
    refreshToolBudget();
    if (steps >= maxSteps) stopped = 'max_steps';
    if (
      options.maxCostUsd !== undefined &&
      sumUsage(messages.slice(previousMessages)).cost.total +
        retriedUsage.cost.total +
        context.usage.reduce((sum, usage) => sum + usage.cost.total, 0) >=
        options.maxCostUsd
    )
      stopped = 'cost_limit';
    if (checkContext && options.compaction === false && !context.fits(messages, systemPrompt))
      stopped = 'context_limit';
    return stopped !== undefined;
  };
  const deliveryDue = (messages: AgentMessage[]) =>
    (maxSteps >= 2 && steps >= maxSteps - 1) ||
    Date.now() - start >= deliveryAt ||
    (options.maxCostUsd !== undefined &&
      sumUsage(messages.slice(previousMessages)).cost.total +
        retriedUsage.cost.total +
        context.usage.reduce((sum, usage) => sum + usage.cost.total, 0) >=
        options.maxCostUsd * 0.9);
  const observer = options.observe
    ? new Observer(
        options.observe,
        positiveInteger('observerTimeoutMs', options.observerTimeoutMs ?? 3000),
      )
    : undefined;
  const journalGuidance = session?.eventsPath
    ? `Run journal (JSON path): ${JSON.stringify(session.eventsPath)}\nRead relevant JSONL events to recover original tool execution times and observations. Event timestamps are not simultaneous page snapshots; never replace missing capture times with report time.\n`
    : '';
  const agent = new Agent({
    // No sessionId, as Python 1.0.5 sends none: pi-ai turns it into OpenAI prompt_cache_key plus session_id and
    // x-client-request-id headers. With it (a4e738d), 123 of 199 BU Bench runs had one full cache miss mid-run and then
    // alternated between the old and new cache (25.9k re-written tokens per run, +$0.03); without it, 0 of 197.
    streamFn: deadlineStream(
      (selected, request, settings) => {
        retryAfterMs = undefined;
        const base = settings?.fetch ?? globalThis.fetch;
        return config.streamFn(selected, redact(request, config.redact ?? []), {
          ...settings,
          // The provider's Retry-After for the one provider retry; pi-ai keeps response headers of failures to itself.
          fetch: async (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
            const response = await base(input, init);
            if (!response.ok) retryAfterMs = retryAfter(response.headers);
            return response;
          },
          maxTokens: Math.min(selected.maxTokens, 32768, Math.floor(selected.contextWindow * 0.15)),
          ...(delivering() && keepTools ? { toolChoice: deliveryChoice } : {}),
        });
      },
      // Python _deadlines: the first event within modelTimeoutMs, the whole stream within modelStreamTimeoutMs,
      // neither past the delivery turn's start (on that turn, the run's end).
      () => {
        const left = Math.max(1000, timeLeft());
        return {
          firstEventMs: Math.min(config.modelTimeoutMs ?? 300_000, left),
          totalMs: Math.min(config.modelStreamTimeoutMs ?? 930_000, left),
        };
      },
    ),
    initialState: {
      model,
      messages: session?.messages ?? [],
      systemPrompt: `${SYSTEM_PROMPT}${downloadsPrompt(launchesBrowser(config.browser) ? 'local' : config.browser?.kind === 'chrome' ? undefined : 'remote')}${config.browser?.kind === 'cloud' ? captchaPrompt(config.browser.captchaSolver !== false) : ''}${config.mode === 'ultrafast' ? AX_PROMPT : ''}${config.webSearch ? SEARCH_PROMPT : ''}\nWorkspace directory (JSON string): ${JSON.stringify(workspace)}. Relative file-tool paths and the JavaScript working directory start here. Save deliverables inside this directory; files outside it are not included by BrowserUse.files(). Use relative paths or the exact workspace value, not a guessed parent directory.\n${journalGuidance}${config.sensitiveData ? `Named secrets (values withheld): ${JSON.stringify(Object.fromEntries(Object.entries(config.sensitiveData).map(([name, entry]) => [name, entry.domains])))}. Use await fillSecret(name, backendNodeId, page) on an input found in the AX tree. Never read back, print or save credentials.\n` : ''}${config.instructions ?? ''}`,
      thinkingLevel: config.reasoning ?? 'medium',
      tools: [
        javascript,
        finish,
        finishFromJs,
        ...(config.researchTools
          ? researchTools(
              workspace,
              config.shellTimeoutMs ?? config.cellTimeoutMs ?? DEFAULT_CELL_TIMEOUT_MS,
              config.shellEnv,
              // Like common coding agents: two minutes unless the command asks for longer.
              config.shellTimeoutMs ? Math.min(config.shellTimeoutMs, 120_000) : undefined,
            )
          : []),
        ...(config.tools ?? []),
      ],
    },
    toolExecution: 'sequential',
    transformContext: async (messages, signal) => {
      refreshToolBudget();
      let failures = 0;
      let recovering = false;
      const usage = () =>
        [retriedUsage, ...context.usage].reduce(
          addUsage,
          sumUsage(messages.slice(previousMessages)),
        );
      const recovery = async (state: 'waiting' | 'resumed') => {
        let attempts = 0;
        while (true) {
          signal?.throwIfAborted();
          context.beforeSummary?.();
          try {
            await bounded(
              () => session?.checkpoint?.(conversation(context.project(messages)), usage()),
              hookTimeout,
              signal,
            );
            await bounded(
              () =>
                options.onContextRecovery?.(
                  {
                    state,
                    context: {
                      ...context.measure(messages, agent.state.systemPrompt),
                      compactionFailures,
                      ...(lastCompactionFailure ? { lastCompactionFailure } : {}),
                    },
                  },
                  signal,
                ),
              hookTimeout,
              signal,
            );
            return;
          } catch {
            signal?.throwIfAborted();
            if (warnings.length < 32)
              warnings.push('Context recovery checkpoint unavailable; retrying.');
            await delay(
              Math.min(
                30000,
                (config.compactionRetryDelayMs ?? 1000) * 2 ** Math.min(attempts++, 5),
              ),
              undefined,
              { signal },
            );
          }
        }
      };
      context.beforeSummary = () => {
        signal?.throwIfAborted();
        if (options.maxCostUsd !== undefined && usage().cost.total >= options.maxCostUsd) {
          stopped = 'cost_limit';
          throw new Error('Cost limit reached during context preparation.');
        }
      };
      context.prune(messages);
      context.trim(messages, agent.state.systemPrompt);
      while (options.compaction !== false && context.baseFits(agent.state.systemPrompt)) {
        signal?.throwIfAborted();
        if (options.maxCostUsd !== undefined && usage().cost.total >= options.maxCostUsd) {
          stopped = 'cost_limit';
          throw new Error('Cost limit reached during context preparation.');
        }
        try {
          if (context.needsCompaction(messages, agent.state.systemPrompt)) {
            const { chars, tokens } = context.measure(messages, agent.state.systemPrompt);
            beforeCompaction = { chars, tokens };
          }
          await context.prepare(messages, agent.state.systemPrompt, signal);
          if (options.maxCostUsd !== undefined && usage().cost.total >= options.maxCostUsd) {
            stopped = 'cost_limit';
            throw new Error('Cost limit reached during context preparation.');
          }
          break;
        } catch (error) {
          signal?.throwIfAborted();
          if (stopped) throw error;
          const message = error instanceof Error ? error.message : String(error);
          compactionFailures++;
          failures++;
          lastCompactionFailure = /Model stream exceeded/.test(message)
            ? 'timeout'
            : /reduce|fit the context budget/.test(message)
              ? 'not_reduced'
              : 'error';
          if (warnings.length < 32)
            warnings.push('Compaction unavailable; original evidence retained.');
          if (!context.force && context.fits(messages, agent.state.systemPrompt)) break;
          if (options.maxCostUsd !== undefined && usage().cost.total >= options.maxCostUsd) {
            stopped = 'cost_limit';
            throw new Error('Cost limit reached during context preparation.');
          }
          if (!recovering) {
            recovering = true;
            await recovery('waiting');
          }
          await delay(
            Math.min(
              30000,
              (config.compactionRetryDelayMs ?? 1000) * 2 ** Math.min(failures - 1, 5),
            ),
            undefined,
            { signal },
          );
        }
      }
      if (recovering) await recovery('resumed');
      signal?.throwIfAborted();
      if (!context.fits(messages, agent.state.systemPrompt)) {
        stopped = 'context_limit';
        throw new Error('Context limit reached; checkpoint files and transcript retained.');
      }
      return context.project(messages);
    },
    prepareNextTurnWithContext: ({ context: current }) => {
      if (!finalizing && deliveryDue(current.messages)) {
        finalizing = true;
        current.messages.push({ role: 'user', content: DELIVER_NOW, timestamp: Date.now() });
        if (!keepTools) {
          agent.state.tools = [finish, finishFromJs];
          return { context: { ...current, tools: [finish, finishFromJs] } };
        }
      }
      return undefined;
    },
    beforeToolCall: async (call, signal) => {
      await session?.control.checkpoint(signal);
      if (completion || stopped || signal?.aborted)
        return { block: true, reason: 'The run has ended.', terminate: true };
      if (delivering() && !deliveryTools.includes(call.toolCall.name))
        return { block: true, reason: 'Only finish or finish_from_js can run now.' };
      const split = deliveryTools.includes(call.toolCall.name)
        ? splitDelivery(call.assistantMessage, call.toolCall.id, call.toolCall.name)
        : undefined;
      if (split) return { block: true, reason: split };
      return config.beforeToolCall
        ? bounded(() => config.beforeToolCall!(call, signal), hookTimeout, signal)
        : undefined;
    },
    afterToolCall: async (call, signal) => {
      const failure = cellFailures.get(call.toolCall.id);
      cellFailures.delete(call.toolCall.id);
      const evidence = failure
        ? {
            content: [...call.result.content, ...failure.result.images],
            details: {
              outputFile: failure.result.outputFile,
              targetId: failure.result.targetId,
              observationTargetId: failure.result.observationTargetId,
              stateReset: failure.stateReset,
            },
          }
        : undefined;
      // Completion validation belongs in validateResult, not a post-effect override.
      if (
        !config.afterToolCall ||
        call.toolCall.name === 'finish' ||
        call.toolCall.name === 'finish_from_js'
      )
        return evidence;
      const observed = evidence ? { ...call, result: { ...call.result, ...evidence } } : call;
      const override = await bounded(
        () => config.afterToolCall!(observed, signal),
        hookTimeout,
        signal,
      );
      return { ...evidence, ...override };
    },
    finishTurn: ({ message, context, toolResults }): { action: 'end' } | undefined => {
      // Error and aborted responses are hard exits; the old shouldStopAfterTurn never saw them.
      if (message.stopReason === 'error' || message.stopReason === 'aborted') return undefined;
      if (completion || stopped) return { action: 'end' };
      if (checkBudgets(context.messages, agent.state.systemPrompt, message.stopReason !== 'stop'))
        return { action: 'end' };
      if (
        finishRepairs === 1 &&
        toolResults.some((result) => result.isError && deliveryTools.includes(result.toolName))
      ) {
        finishRepairs++;
        return undefined;
      }
      return finishRepairs > 0 ? { action: 'end' } : undefined;
    },
  });
  refreshToolBudget();
  // Pi prepends the prompt as a system message; this run's messages start after it and the history.
  previousMessages = agent.state.messages.length;
  if (session) {
    session.control.steer = (text) =>
      agent.steer({ role: 'user', content: text, timestamp: Date.now() });
    session.control.compact = () => {
      if (options.compaction === false) throw new Error('Compaction is disabled for this run.');
      context.force = true;
    };
  }
  agent.subscribe((event) => {
    if (event.type === 'turn_start') steps++;
  });
  if (options.onEvent)
    agent.subscribe((event, signal) =>
      bounded(() => options.onEvent!(event, signal), hookTimeout, signal),
    );
  agent.subscribe((event) => {
    if (event.type === 'tool_execution_end') observer?.push(event);
  });
  const cancel = () => {
    stopped = 'cancelled';
    agent.abort();
  };
  options.signal?.addEventListener('abort', cancel, { once: true });
  const timer = setTimeout(() => {
    stopped = 'timeout';
    agent.abort();
  }, timeoutMs);
  /** One failed model response: retry the inference (never its tool calls). Returns whether the run went on. */
  const recover = async (): Promise<boolean> => {
    const failed = agent.state.messages.at(-1);
    if (completion || stopped || options.signal?.aborted) return false;
    if (failed?.role !== 'assistant' || failed.stopReason !== 'error') return false;
    const message = failed.errorMessage ?? '';
    const drop = () => {
      addUsage(retriedUsage, failed.usage);
      agent.state.messages = agent.state.messages.slice(0, -1);
    };
    if (
      options.compaction !== false &&
      contextWindowError(message) &&
      !checkBudgets(agent.state.messages, agent.state.systemPrompt)
    ) {
      drop();
      context.force = true;
      providerRetries++;
      await agent.continue();
      return true;
    }
    // Python on_model_request_error: a model timeout starts a new step (the delivery turn when its time has come)
    // instead of ending the run. The deadline never runs past the delivery turn, so this is bounded by the budgets.
    const timedOut = MODEL_TIMEOUT.exec(message);
    if (timedOut && !checkBudgets(agent.state.messages, agent.state.systemPrompt)) {
      drop();
      providerRetries++;
      let note = `The model request got no answer within ${(Number(timedOut[1]) / 1000).toFixed(1)} s.`;
      if (!delivering() && deliveryDue(agent.state.messages)) {
        finalizing = true;
        note += `\n\n${DELIVER_NOW}`;
        if (!keepTools) agent.state.tools = [finish, finishFromJs];
      }
      await agent.prompt({ role: 'user', content: note, timestamp: Date.now() });
      return true;
    }
    // One retry per run of a transient provider error, after its Retry-After (at most 60 s and the time left).
    if (
      !providerRetried &&
      transientModelError(message) &&
      !checkBudgets(agent.state.messages, agent.state.systemPrompt)
    ) {
      providerRetried = true;
      providerRetries++;
      drop();
      const wait = Math.min(
        retryAfterMs ?? retryHint(message) ?? 0,
        60_000,
        Math.max(0, timeLeft()),
      );
      if (wait > 0) await delay(wait, undefined, { signal: options.signal });
      if (stopped || options.signal?.aborted) return false;
      await agent.continue();
      return true;
    }
    return false;
  };
  let error: string | undefined;
  try {
    if (options.signal?.aborted) stopped = 'cancelled';
    else if (!context.baseFits(agent.state.systemPrompt)) stopped = 'context_limit';
    else if (
      !checkBudgets(
        [...agent.state.messages, { role: 'user', content: task, timestamp: Date.now() }],
        agent.state.systemPrompt,
      )
    ) {
      await agent.prompt(task);
      while (await recover());
      // A budget that ran out on this very reply does not discard it: the reply is the delivery.
      const spent = () =>
        stopped === undefined || stopped === 'max_steps' || stopped === 'cost_limit';
      const replyText = () => {
        const ending = agent.state.messages.at(-1);
        return !completion &&
          spent() &&
          ending?.role === 'assistant' &&
          ending.stopReason === 'stop'
          ? ending.content
              .filter((c) => c.type === 'text')
              .map((c) => c.text)
              .join('\n')
          : undefined;
      };
      /** A text reply as a result value: the text for a string schema, else its JSON; undefined when not JSON. Text
       * with no letter or digit is no answer where nothing can follow it (an empty reply never completes a run). */
      const textValue = (text: string, last: boolean): unknown => {
        if (last && !ALNUM.test(text)) return undefined;
        if (stringSchema) return text;
        try {
          return JSON.parse(text);
        } catch {
          return undefined;
        }
      };
      // Python on_text: for a string schema a plain-text reply is the answer (the repair cost one extra request on
      // ~95% of gpt-6-luna runs), and on the delivery-only turn JSON text is for a structured one. Otherwise a
      // structured schema, or a tool call written as text, gets the delivery repair.
      const reply = replyText();
      const replyValue =
        reply !== undefined && !TOOL_CALL_MARKUP.test(reply) && (stringSchema || finalizing)
          ? textValue(reply, stopped !== undefined)
          : undefined;
      let problem = '';
      if (replyValue !== undefined) {
        try {
          await acceptResult(replyValue, options.signal, undefined, stopped !== undefined);
          stopped = undefined;
        } catch (cause) {
          if (options.signal?.aborted) throw cause;
          problem = `\n${cause instanceof Error ? cause.message : String(cause)}`;
        }
      }
      // One delivery-only repair. The original timer, transcript and budgets remain in force.
      if (reply !== undefined && !completion && !stopped) {
        const note = TOOL_CALL_MARKUP.test(reply)
          ? 'That reply wrote a tool call as text; it was not run. '
          : '';
        const repair: AgentMessage = {
          role: 'user',
          content: [
            {
              type: 'text',
              text: `${note}The run ended without a validated delivery. Use finish_from_js for an existing result or finish for a concise answer. Preserve all verified records; report missing evidence honestly. Do not repeat browser actions. This is the single delivery repair; one correction may follow a rejected delivery.${problem}`,
            },
          ],
          timestamp: Date.now(),
        };
        if (!keepTools) agent.state.tools = [finish, finishFromJs];
        if (!checkBudgets([...agent.state.messages, repair], agent.state.systemPrompt)) {
          finishRepairs = 1;
          await agent.prompt(repair);
          while (await recover());
          // Python: after the repair turn, text is accepted when it is a valid result (JSON for a structured schema).
          const late = replyText();
          const value =
            late !== undefined && !TOOL_CALL_MARKUP.test(late) ? textValue(late, true) : undefined;
          // Nothing follows the repair turn: a delivery problem is noted, not refused.
          if (value !== undefined)
            await acceptResult(value, options.signal, undefined, true).then(
              () => (stopped = undefined),
              () => {},
            );
        }
      }
    }
  } catch (cause) {
    error = cause instanceof Error ? cause.message : String(cause);
    stopped ??= 'error';
  } finally {
    clearTimeout(timer);
    await observer?.close(stopped === 'cancelled' || stopped === 'timeout');
    warnings.push(...(observer?.warnings ?? []));
    options.signal?.removeEventListener('abort', cancel);
    // Saved history excludes the system message so a restored run gets the current prompt.
    session?.save(conversation(context.project(agent.state.messages)));
    session?.control.finish();
  }
  const last = agent.state.messages.slice(previousMessages).findLast((m) => m.role === 'assistant');
  // A failed delivery repair must not erase useful text from the original ending.
  const text =
    agent.state.messages
      .slice(previousMessages)
      .filter((m) => m.role === 'assistant')
      .map((m) =>
        m.content
          .filter((c) => c.type === 'text')
          .map((c) => c.text)
          .join('\n'),
      )
      .findLast((value) => value.trim().length > 0) ?? '';
  const usage = sumUsage(agent.state.messages.slice(previousMessages));
  for (const extra of [retriedUsage, ...context.usage]) {
    for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens'] as const)
      usage[key] += extra[key];
    for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'total'] as const)
      usage.cost[key] += extra.cost[key];
  }
  const metrics = {
    steps,
    finishRepairs,
    durationMs: Date.now() - start,
    usage,
    compactions: context.compactions,
    context: {
      ...context.measure(agent.state.messages, agent.state.systemPrompt),
      compactionFailures,
      ...(lastCompactionFailure ? { lastCompactionFailure } : {}),
      ...(beforeCompaction ? { beforeCompaction } : {}),
    },
    providerRetries,
    ...(completion && verdict !== undefined ? { success: verdict } : {}),
    ...(warnings.length ? { warnings } : {}),
    workspace,
    model: config.model,
  };
  if (completion && !stopped) return { ...metrics, status: 'completed', ...completion };
  if (
    last?.role === 'assistant' &&
    (last.stopReason === 'error' || last.stopReason === 'aborted')
  ) {
    stopped ??= 'error';
    error ??= last.errorMessage ?? 'Model request failed.';
  }
  const observation = agent.state.messages
    .slice(previousMessages)
    .findLast((m) => m.role === 'toolResult');
  const fallback =
    observation?.role === 'toolResult'
      ? observation.content
          .filter((c) => c.type === 'text')
          .map((c) => c.text)
          .join('\n')
      : '';
  return {
    ...metrics,
    status: stopped ?? 'incomplete',
    text: text || (fallback ? `Last tool observation (unfinished):\n${fallback}` : ''),
    ...(completion
      ? { partial: { value: completion.output } }
      : runtime.partial
        ? { partial: structuredClone(runtime.partial) }
        : {}),
    ...(error ? { error } : {}),
  };
}
