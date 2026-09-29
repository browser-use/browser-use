import {
  Agent,
  type AgentMessage,
  type AgentTool,
  type StreamFn,
} from '@earendil-works/pi-agent-core';
import type { Model, Api, ToolChoice, Usage } from '@earendil-works/pi-ai';
import { Type, type TSchema } from 'typebox';
import { Check, Errors } from 'typebox/value';
import { CellError, type BrowserRuntime } from './runtime.js';
import { Observer } from './observer.js';
import { RunContext, conversation } from './context.js';
import { deadlineStream } from './model-stream.js';
import { researchTools } from './research-tools.js';
import type { BrowserUseOptions, RunOptions, RunResult, StopReason } from './types.js';
import { redact } from './history.js';
import { SEARCH_PROMPT, SYSTEM_PROMPT } from './prompt.js';
import { AX_PROMPT } from './ax.js';
import { positiveInteger } from './protocol.js';
import { bounded, type RunControl } from './control.js';

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
    TRANSIENT_MODEL_ERRORS.some((pattern) => pattern.test(detail))
  );
}

function sumUsage(messages: AgentMessage[]): Usage {
  const result = zeroUsage();
  for (const message of messages) {
    if (message.role !== 'assistant') continue;
    for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens'] as const)
      result[key] += message.usage[key];
    for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'total'] as const)
      result.cost[key] += message.usage.cost[key];
  }
  return result;
}

export async function runAgent(
  runtime: BrowserRuntime,
  model: Model<Api>,
  config: BrowserUseOptions & { streamFn: StreamFn },
  workspace: string,
  task: string,
  schema: TSchema,
  options: RunOptions,
  session?: {
    messages: AgentMessage[];
    control: RunControl;
    save: (messages: AgentMessage[]) => void;
    eventsPath?: string;
  },
): Promise<RunResult<unknown>> {
  const maxSteps = positiveInteger('maxSteps', options.maxSteps ?? 40);
  const timeoutMs = positiveInteger('timeoutMs', options.timeoutMs ?? 300_000);
  const maxContextChars = positiveInteger('maxContextChars', options.maxContextChars ?? 240_000);
  if (
    options.maxCostUsd !== undefined &&
    (!Number.isFinite(options.maxCostUsd) || options.maxCostUsd <= 0)
  ) {
    throw new Error('maxCostUsd must be a finite positive number.');
  }
  if (options.compaction !== undefined && typeof options.compaction !== 'boolean')
    throw new Error('compaction must be boolean.');
  runtime.beginRun();
  const start = Date.now();
  let previousMessages = session?.messages.length ?? 0;
  const hookTimeout = config.hookTimeoutMs ?? 30_000;
  let steps = 0;
  let finishRepairs = 0;
  let providerRetries = 0;
  let retriedUsage = zeroUsage();
  let finalizing = false;
  let compactionFailed = false;
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
  );
  let completion: { output: unknown; text: string } | undefined;
  let stopped: StopReason | undefined;
  const codeParameters = Type.Object({ code: Type.String({ minLength: 1 }) });
  const cellFailures = new Map<string, CellError>();
  const javascript: AgentTool<typeof codeParameters> = {
    name: 'javascript',
    label: 'Browser JavaScript',
    description: `Execute JavaScript in a persistent Node REPL with raw CDP. Cell deadline: ${config.cellTimeoutMs ?? 30_000} ms. Checkpoint small batches before the deadline. Use screenshot() for native images.`,
    parameters: codeParameters,
    executionMode: 'sequential',
    replay: 'never',
    execute: async (_id, params: { code: string }, signal) => {
      let result;
      try {
        result = await runtime.execute(params.code, config.cellTimeoutMs ?? 30_000, signal);
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
  const acceptResult = async (output: unknown, signal?: AbortSignal) => {
    if (!Check(schema, output))
      throw new Error(
        `Final result does not match schema: ${JSON.stringify(Errors(schema, output).slice(0, 5)).slice(0, 2000)}`,
      );
    if (config.validateResult) {
      const feedback = await bounded(
        () => config.validateResult!(output, signal),
        hookTimeout,
        signal,
      );
      if (feedback) throw new Error(`Result rejected: ${feedback}`);
    }
    signal?.throwIfAborted();
    const text = typeof output === 'string' ? output : JSON.stringify(output);
    if (text === undefined) throw new Error('The final result must be JSON serializable.');
    completion = { output, text };
    return {
      content: [{ type: 'text' as const, text: 'Result accepted.' }],
      details: {},
      terminate: true,
    };
  };
  const resultParameters = Type.Object({ result: schema });
  const finish: AgentTool<typeof resultParameters> = {
    name: 'finish',
    label: 'Deliver result',
    description:
      'Submit the verified final result, matching this schema. For data already in JavaScript, prefer finish_from_js to avoid rewriting it. This ends the task.',
    parameters: resultParameters,
    executionMode: 'sequential',
    execute: async (_id, params: { result: unknown }, signal) =>
      acceptResult(params.result, signal),
  };
  const expressionParameters = Type.Object({ expression: Type.String({ minLength: 1 }) });
  const finishFromJs: AgentTool<typeof expressionParameters> = {
    name: 'finish_from_js',
    label: 'Deliver JavaScript value',
    description:
      'Deliver an existing value from the persistent REPL without printing or rewriting it. Expression must match the result schema of finish. For a string result use JSON.stringify(records) or an existing text variable. Evaluated once; ends the task after validation.',
    parameters: expressionParameters,
    executionMode: 'sequential',
    replay: 'never',
    execute: async (_id, params: { expression: string }, signal) =>
      acceptResult(
        await runtime.readResult(params.expression, config.cellTimeoutMs ?? 30_000, signal),
        signal,
      ),
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
  const checkBudgets = (messages: AgentMessage[], systemPrompt: string) => {
    if (steps >= maxSteps) stopped = 'max_steps';
    if (
      options.maxCostUsd !== undefined &&
      sumUsage(messages.slice(previousMessages)).cost.total +
        retriedUsage.cost.total +
        context.usage.reduce((sum, usage) => sum + usage.cost.total, 0) >=
        options.maxCostUsd
    )
      stopped = 'cost_limit';
    if (options.compaction === false && !context.fits(messages, systemPrompt))
      stopped = 'context_limit';
    return stopped !== undefined;
  };
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
    streamFn: deadlineStream(
      (selected, request, settings) =>
        config.streamFn(selected, redact(request, config.redact ?? []), {
          ...settings,
          maxTokens: Math.min(selected.maxTokens, 32768, Math.floor(selected.contextWindow * 0.15)),
          ...(delivering() && keepTools ? { toolChoice: deliveryChoice } : {}),
        }),
      config.modelTimeoutMs ?? 300_000,
    ),
    initialState: {
      model,
      messages: session?.messages ?? [],
      systemPrompt: `${SYSTEM_PROMPT}${config.mode === 'ultrafast' ? AX_PROMPT : ''}${config.webSearch ? SEARCH_PROMPT : ''}\nWorkspace directory (JSON string): ${JSON.stringify(workspace)}. Relative file-tool paths and the JavaScript working directory start here. Save deliverables inside this directory; files outside it are not included by BrowserUse.files(). Use relative paths or the exact workspace value, not a guessed parent directory.\n${journalGuidance}${config.sensitiveData ? `Named secrets (values withheld): ${JSON.stringify(Object.fromEntries(Object.entries(config.sensitiveData).map(([name, entry]) => [name, entry.domains])))}. Use await fillSecret(name, backendNodeId, page) on an input found in the AX tree. Never read back, print or save credentials.\n` : ''}${config.instructions ?? ''}`,
      thinkingLevel: config.reasoning ?? 'medium',
      tools: [
        javascript,
        finish,
        finishFromJs,
        ...(config.researchTools
          ? researchTools(
              workspace,
              config.shellTimeoutMs ?? config.cellTimeoutMs ?? 30_000,
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
      try {
        if (!compactionFailed) await context.prepare(messages, agent.state.systemPrompt, signal);
      } catch (error) {
        compactionFailed = true;
        warnings.push(`Compaction unavailable: ${String(error)}`);
      }
      signal?.throwIfAborted();
      if (!context.fits(messages, agent.state.systemPrompt)) {
        stopped = 'context_limit';
        throw new Error('Context limit reached; checkpoint files and transcript retained.');
      }
      if (
        options.maxCostUsd !== undefined &&
        sumUsage(messages.slice(previousMessages)).cost.total +
          retriedUsage.cost.total +
          context.usage.reduce((sum, u) => sum + u.cost.total, 0) >=
          options.maxCostUsd
      ) {
        stopped = 'cost_limit';
        throw new Error('Cost limit reached during context preparation.');
      }
      return context.project(messages);
    },
    prepareNextTurnWithContext: ({ context: current }) => {
      if (
        !finalizing &&
        ((maxSteps >= 2 && steps >= maxSteps - 1) ||
          Date.now() - start >= timeoutMs * 0.9 ||
          (options.maxCostUsd !== undefined &&
            sumUsage(current.messages.slice(previousMessages)).cost.total +
              retriedUsage.cost.total +
              context.usage.reduce((sum, usage) => sum + usage.cost.total, 0) >=
              options.maxCostUsd * 0.9))
      ) {
        finalizing = true;
        current.messages.push({
          role: 'user',
          content:
            'Budget nearly exhausted. Deliver the verified result now with finish/finish_from_js. Reference saved files; explicitly list missing evidence. Do not perform more browser actions.',
          timestamp: Date.now(),
        });
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
    finishTurn: ({ message, context }): { action: 'end' } | undefined => {
      // Error and aborted responses are hard exits; the old shouldStopAfterTurn never saw them.
      if (message.stopReason === 'error' || message.stopReason === 'aborted') return undefined;
      if (completion || stopped) return { action: 'end' };
      return checkBudgets(context.messages, agent.state.systemPrompt) || finishRepairs > 0
        ? { action: 'end' }
        : undefined;
    },
  });
  // Pi prepends the prompt as a system message; this run's messages start after it and the history.
  previousMessages = agent.state.messages.length;
  if (session)
    session.control.steer = (text) =>
      agent.steer({ role: 'user', content: text, timestamp: Date.now() });
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
  let error: string | undefined;
  try {
    if (options.signal?.aborted) stopped = 'cancelled';
    else if (
      !context.fits(
        [...agent.state.messages, { role: 'user', content: task, timestamp: Date.now() }],
        agent.state.systemPrompt,
      ) &&
      conversation(agent.state.messages).length === 0
    )
      stopped = 'context_limit';
    else if (
      !checkBudgets(
        [...agent.state.messages, { role: 'user', content: task, timestamp: Date.now() }],
        agent.state.systemPrompt,
      )
    ) {
      await agent.prompt(task);
      const failed = agent.state.messages.at(-1);
      if (
        failed?.role === 'assistant' &&
        failed.stopReason === 'error' &&
        transientModelError(failed.errorMessage) &&
        !checkBudgets(agent.state.messages, agent.state.systemPrompt) &&
        !options.signal?.aborted
      ) {
        // Pi never executes tool calls from an error response. Retry inference once, not actions.
        providerRetries = 1;
        retriedUsage = failed.usage;
        agent.state.messages = agent.state.messages.slice(0, -1);
        await agent.continue();
      }
      const ending = agent.state.messages.findLast((m) => m.role === 'assistant');
      // One delivery-only repair. The original timer, transcript and budgets remain in force.
      if (!completion && !stopped && ending?.role === 'assistant' && ending.stopReason === 'stop') {
        const repair: AgentMessage = {
          role: 'user',
          content: [
            {
              type: 'text',
              text: 'The run ended without a validated delivery. Use finish_from_js for an existing result or finish for a concise answer. Preserve all verified records; report missing evidence honestly. Do not repeat browser actions. This is the single delivery repair turn.',
            },
          ],
          timestamp: Date.now(),
        };
        if (!checkBudgets([...agent.state.messages, repair], agent.state.systemPrompt)) {
          finishRepairs = 1;
          if (!keepTools) agent.state.tools = [finish, finishFromJs];
          await agent.prompt(repair);
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
    providerRetries,
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
