import {
  Agent,
  type AgentMessage,
  type AgentTool,
  type StreamFn,
} from '@earendil-works/pi-agent-core';
import type { Model, Api, Usage } from '@earendil-works/pi-ai';
import { Type, type TSchema } from 'typebox';
import { Check, Errors } from 'typebox/value';
import { CellError, type BrowserRuntime } from './runtime.js';
import { Observer } from './observer.js';
import { RunContext } from './context.js';
import { deadlineStream } from './model-stream.js';
import { researchTools } from './research-tools.js';
import type { BrowserUseOptions, RunOptions, RunResult, StopReason } from './types.js';
import { SYSTEM_PROMPT } from './prompt.js';
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
  const start = Date.now();
  const previousMessages = session?.messages.length ?? 0;
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
    deadlineStream(config.streamFn, config.compactionTimeoutMs ?? 120_000),
    workspace,
    maxContextChars,
    options.compaction !== false,
    config.redact ?? [],
  );
  let completion: { output: unknown; text: string } | undefined;
  let stopped: StopReason | undefined;
  const codeParameters = Type.Object({ code: Type.String({ minLength: 1 }) });
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
        // Pi marks thrown tools as errors. Preserve evidence in the error text as well.
        throw new Error(
          `${error.message}\nState reset: ${error.stateReset}. Actions may already have happened.\nPartial output: ${error.result.text}\nCaptured output file: ${error.result.outputFile ?? '(none)'}`,
        );
      }
      return {
        content: [{ type: 'text', text: result.text }, ...result.images],
        details: { outputFile: result.outputFile, targetId: result.targetId },
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
  const agent = new Agent({
    streamFn: deadlineStream(
      (selected, request, settings) =>
        config.streamFn(selected, request, {
          ...settings,
          maxTokens: Math.min(selected.maxTokens, 32768, Math.floor(selected.contextWindow * 0.15)),
        }),
      config.modelTimeoutMs ?? 300_000,
    ),
    initialState: {
      model,
      messages: session?.messages ?? [],
      systemPrompt: `${SYSTEM_PROMPT}\n${config.instructions ?? ''}`,
      thinkingLevel: config.reasoning ?? 'medium',
      tools: [
        javascript,
        finish,
        finishFromJs,
        ...(config.researchTools ? researchTools(workspace, config.cellTimeoutMs ?? 30_000) : []),
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
        ((maxSteps >= 10 && steps >= maxSteps - 2) || Date.now() - start >= timeoutMs * 0.9)
      ) {
        finalizing = true;
        current.messages.push({
          role: 'user',
          content:
            'Budget nearly exhausted. Deliver the verified result now with finish/finish_from_js. Reference saved files; explicitly list missing evidence. Do not perform more browser actions.',
          timestamp: Date.now(),
        });
        agent.state.tools = [finish, finishFromJs];
        return { context: { ...current, tools: [finish, finishFromJs] } };
      }
      return undefined;
    },
    beforeToolCall: async (call, signal) => {
      await session?.control.checkpoint(signal);
      if (completion || stopped || signal?.aborted)
        return { block: true, reason: 'The run has ended.', terminate: true };
      return config.beforeToolCall
        ? bounded(() => config.beforeToolCall!(call, signal), hookTimeout, signal)
        : undefined;
    },
    afterToolCall: async (call, signal) => {
      // Completion validation belongs in validateResult, not a post-effect override.
      if (
        !config.afterToolCall ||
        call.toolCall.name === 'finish' ||
        call.toolCall.name === 'finish_from_js'
      )
        return undefined;
      return bounded(() => config.afterToolCall!(call, signal), hookTimeout, signal);
    },
    shouldStopAfterTurn: ({ context }) => {
      if (completion || stopped) return true;
      return checkBudgets(context.messages, context.systemPrompt) || finishRepairs > 0;
    },
  });
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
      agent.state.messages.length === 0
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
        /stream ended before a terminal|Model stream exceeded|terminated|ECONNRESET|socket hang up/i.test(
          failed.errorMessage ?? '',
        ) &&
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
          agent.state.tools = [finish, finishFromJs];
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
    session?.save(context.project(agent.state.messages));
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
  return { ...metrics, status: stopped ?? 'incomplete', text, ...(error ? { error } : {}) };
}
