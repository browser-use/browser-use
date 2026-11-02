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
import { RunContext, conversation, contextWindowError } from './context.js';
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
import { SEARCH_PROMPT, SYSTEM_PROMPT } from './prompt.js';
import { AX_PROMPT } from './ax.js';
import { positiveInteger } from './protocol.js';
import { bounded, type RunControl } from './control.js';
import { performance } from 'node:perf_hooks';
import { setTimeout as delay } from 'node:timers/promises';
export const zeroUsage = (): Usage => ({
  input: 0,
  output: 0,
  cacheRead: 0,
  cacheWrite: 0,
  totalTokens: 0,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
});
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
const TRANSIENT_TRANSPORT_ERRORS =
  /^(?:ReadError|ReadTimeout|RemoteProtocolError|APITimeoutError)(?::|$)/;
export function transientModelError(message: string | undefined): boolean {
  const text = message ?? '';
  const detail = text.replace(/^[A-Za-z]+(?:Error|Exception|Timeout): /, '');
  return (
    TRANSIENT_TRANSPORT_ERRORS.test(text) ||
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
  config: BrowserUseOptions & {
    streamFn: StreamFn;
  },
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
  const maxSteps = positiveInteger('maxSteps', options.maxSteps ?? 40);
  const timeoutMs = positiveInteger('timeoutMs', options.timeoutMs ?? 300000);
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
  runtime.beginRun();
  const start = Date.now();
  let previousMessages = session?.messages.length ?? 0;
  const hookTimeout = config.hookTimeoutMs ?? 30000;
  const invokeHook = async <T>(
    work: (hookSignal: AbortSignal) => T | Promise<T>,
    signal?: AbortSignal,
  ) => {
    const controller = new AbortController();
    const hookSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
    config.onCounter?.('callback_calls');
    try {
      return await bounded(() => work(hookSignal), hookTimeout, signal);
    } catch (error) {
      config.onCounter?.('callback_errors');
      if (String(error).includes('Hook exceeded')) config.onCounter?.('callback_timeouts');
      throw error;
    } finally {
      controller.abort();
    }
  };
  let modelDurationMs = 0;
  let toolDurationMs = 0;
  let modelStarted = 0;
  const toolStarted = new Map<string, number>();
  let steps = 0;
  let finishRepairs = 0;
  let providerRetries = 0;
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
      config.compactionTimeoutMs ?? 120000,
    ),
    workspace,
    maxContextChars,
    options.compaction !== false,
    config.redact ?? [],
  );
  let completion:
    | {
        output: unknown;
        text: string;
      }
    | undefined;
  let stopped: StopReason | undefined;
  const codeParameters = Type.Object({ code: Type.String({ minLength: 1 }) });
  const cellFailures = new Map<string, CellError>();
  const javascript: AgentTool<typeof codeParameters> = {
    name: 'javascript',
    label: 'Browser JavaScript',
    description: `Execute JavaScript in a persistent Node REPL with raw CDP. Cell deadline: ${config.cellTimeoutMs ?? 30000} ms. Checkpoint small batches before the deadline. Use screenshot() for native images.`,
    parameters: codeParameters,
    executionMode: 'sequential',
    replay: 'never',
    execute: async (
      _id,
      params: {
        code: string;
      },
      signal,
    ) => {
      let result;
      try {
        result = await runtime.execute(params.code, config.cellTimeoutMs ?? 30000, signal);
      } catch (error) {
        if (!(error instanceof CellError)) throw error;
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
    const validateResult = options.validateResult ?? config.validateResult;
    if (validateResult) {
      config.onCounter?.('validator_calls');
      const feedback = await invokeHook((hookSignal) => validateResult(output, hookSignal), signal);
      if (feedback) {
        config.onCounter?.('validator_rejections');
        throw new Error(`Result rejected: ${feedback}`);
      }
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
    execute: async (
      _id,
      params: {
        result: unknown;
      },
      signal,
    ) => acceptResult(params.result, signal),
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
    execute: async (
      _id,
      params: {
        expression: string;
      },
      signal,
    ) =>
      acceptResult(
        await runtime.readResult(params.expression, config.cellTimeoutMs ?? 30000, signal),
        signal,
      ),
  };
  const keepTools = model.provider === 'openai' && model.api === 'openai-responses';
  const delivering = () => finalizing || finishRepairs > 0;
  const deliveryTools = ['finish', 'finish_from_js'];
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
      config.modelTimeoutMs ?? 300000,
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
        ...(config.researchTools !== false
          ? researchTools(
              workspace,
              config.shellTimeoutMs ?? config.cellTimeoutMs ?? 30000,
              config.shellEnv,
              config.shellTimeoutMs ? Math.min(config.shellTimeoutMs, 120000) : undefined,
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
        ? invokeHook((hookSignal) => config.beforeToolCall!(call, hookSignal), signal)
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
      if (
        !config.afterToolCall ||
        call.toolCall.name === 'finish' ||
        call.toolCall.name === 'finish_from_js'
      )
        return evidence;
      const observed = evidence ? { ...call, result: { ...call.result, ...evidence } } : call;
      const override = await invokeHook(
        (hookSignal) => config.afterToolCall!(observed, hookSignal),
        signal,
      );
      return { ...evidence, ...override };
    },
    finishTurn: ({
      message,
      context,
    }):
      | {
          action: 'end';
        }
      | undefined => {
      if (message.stopReason === 'error' || message.stopReason === 'aborted') return undefined;
      if (completion || stopped) return { action: 'end' };
      return checkBudgets(
        context.messages,
        agent.state.systemPrompt,
        message.stopReason !== 'stop',
      ) || finishRepairs > 0
        ? { action: 'end' }
        : undefined;
    },
  });
  refreshToolBudget();
  previousMessages = agent.state.messages.length;
  if (session)
    session.control.steer = (text) =>
      agent.steer({ role: 'user', content: text, timestamp: Date.now() });
  agent.subscribe((event) => {
    if (event.type === 'message_start' && event.message.role === 'assistant')
      modelStarted = performance.now();
    if (event.type === 'message_end' && event.message.role === 'assistant' && modelStarted) {
      modelDurationMs += performance.now() - modelStarted;
      modelStarted = 0;
    }
    if (event.type === 'tool_execution_start') toolStarted.set(event.toolCallId, performance.now());
    if (event.type === 'tool_execution_end') {
      const started = toolStarted.get(event.toolCallId);
      if (started !== undefined) toolDurationMs += performance.now() - started;
      toolStarted.delete(event.toolCallId);
    }
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
    else if (!context.baseFits(agent.state.systemPrompt)) stopped = 'context_limit';
    else if (
      !checkBudgets(
        [...agent.state.messages, { role: 'user', content: task, timestamp: Date.now() }],
        agent.state.systemPrompt,
      )
    ) {
      await agent.prompt(task);
      let overflow = agent.state.messages.at(-1);
      while (
        !completion &&
        !stopped &&
        options.compaction !== false &&
        overflow?.role === 'assistant' &&
        overflow.stopReason === 'error' &&
        contextWindowError(overflow.errorMessage ?? '') &&
        !checkBudgets(agent.state.messages, agent.state.systemPrompt)
      ) {
        addUsage(retriedUsage, overflow.usage);
        agent.state.messages = agent.state.messages.slice(0, -1);
        context.force = true;
        providerRetries++;
        await agent.continue();
        overflow = agent.state.messages.at(-1);
      }
      const failed = agent.state.messages.at(-1);
      if (
        failed?.role === 'assistant' &&
        failed.stopReason === 'error' &&
        transientModelError(failed.errorMessage) &&
        !checkBudgets(agent.state.messages, agent.state.systemPrompt) &&
        !options.signal?.aborted
      ) {
        providerRetries++;
        addUsage(retriedUsage, failed.usage);
        agent.state.messages = agent.state.messages.slice(0, -1);
        await agent.continue();
      }
      const ending = agent.state.messages.findLast((m) => m.role === 'assistant');
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
        if (!keepTools) agent.state.tools = [finish, finishFromJs];
        if (!checkBudgets([...agent.state.messages, repair], agent.state.systemPrompt)) {
          finishRepairs = 1;
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
    session?.save(conversation(context.project(agent.state.messages)));
    session?.control.finish();
  }
  const last = agent.state.messages.slice(previousMessages).findLast((m) => m.role === 'assistant');
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
    summaryUsage: context.usage.reduce(addUsage, zeroUsage()),
    modelDurationMs,
    toolDurationMs,
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
    ...(warnings.length ? { warnings } : {}),
    workspace,
    model: config.model ?? `${model.provider}/${model.id}`,
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
