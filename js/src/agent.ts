import {
  Agent,
  type AgentMessage,
  type AgentTool,
  type StreamFn,
} from '@earendil-works/pi-agent-core';
import type { Model, Api, Usage } from '@earendil-works/pi-ai';
import { Type, type TSchema } from 'typebox';
import type { BrowserRuntime } from './runtime.js';
import type { BrowserUseOptions, RunOptions, RunResult, StopReason } from './types.js';
import { SYSTEM_PROMPT } from './prompt.js';
import { positiveInteger } from './protocol.js';

const zeroUsage = (): Usage => ({
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

/** Preserve the transcript; omit old images only in the provider-facing projection. */
function recentImages(messages: AgentMessage[]): AgentMessage[] {
  const imageMessages = messages.filter(
    (m) => m.role === 'toolResult' && m.content.some((c) => c.type === 'image'),
  );
  const keep = new Set(imageMessages.slice(-2));
  return messages.map((message) =>
    message.role === 'toolResult' && !keep.has(message)
      ? { ...message, content: message.content.filter((c) => c.type !== 'image') }
      : message,
  );
}

function contextSize(messages: AgentMessage[]): number {
  // Image bytes travel as media, not text tokens. Do not charge base64 against the text guard.
  return JSON.stringify(messages, (_key: string, value: unknown) => {
    if (value && typeof value === 'object' && 'type' in value && value.type === 'image') {
      return { type: 'image' };
    }
    return value;
  }).length;
}

export async function runAgent(
  runtime: BrowserRuntime,
  model: Model<Api>,
  config: BrowserUseOptions & { streamFn: StreamFn },
  workspace: string,
  task: string,
  schema: TSchema,
  options: RunOptions,
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
  const start = Date.now();
  let steps = 0;
  let completion: { output: unknown; text: string } | undefined;
  let stopped: StopReason | undefined;
  const codeParameters = Type.Object({ code: Type.String({ minLength: 1 }) });
  const javascript: AgentTool<typeof codeParameters> = {
    name: 'javascript',
    label: 'Browser JavaScript',
    description:
      'Execute JavaScript in the persistent browser REPL. Top-level await and normal variables persist. Return a focused value or console.log it. Use screenshot() for native images.',
    parameters: codeParameters,
    executionMode: 'sequential',
    replay: 'never',
    execute: async (_id, params: { code: string }, signal) => {
      const result = await runtime.execute(params.code, config.cellTimeoutMs ?? 30_000, signal);
      return {
        content: [{ type: 'text', text: result.text }, ...result.images],
        details: { outputFile: result.outputFile },
      };
    },
  };
  const resultParameters = Type.Object({ result: schema });
  const finish: AgentTool<typeof resultParameters> = {
    name: 'finish',
    label: 'Deliver result',
    description: 'Submit the verified final result, matching this schema. This ends the task.',
    parameters: resultParameters,
    executionMode: 'sequential',
    execute: async (_id, params: { result: unknown }) => {
      const text =
        typeof params.result === 'string' ? params.result : JSON.stringify(params.result);
      if (text === undefined) throw new Error('The final result must be JSON serializable.');
      completion = { output: params.result, text };
      return {
        content: [{ type: 'text', text: 'Result accepted.' }],
        details: {},
        terminate: true,
      };
    },
  };
  const agent = new Agent({
    streamFn: config.streamFn,
    initialState: {
      model,
      systemPrompt: `${SYSTEM_PROMPT}\n${config.instructions ?? ''}`,
      thinkingLevel: config.reasoning ?? 'medium',
      tools: [javascript, finish, ...(config.tools ?? [])],
    },
    toolExecution: 'sequential',
    transformContext: async (messages) => recentImages(messages),
    beforeToolCall: async (call, signal) => {
      if (completion || stopped || signal?.aborted)
        return { block: true, reason: 'The run has ended.', terminate: true };
      return config.beforeToolCall?.(call, signal);
    },
    shouldStopAfterTurn: ({ context }) => {
      if (completion || stopped) return true;
      if (steps >= maxSteps) stopped = 'max_steps';
      if (
        options.maxCostUsd !== undefined &&
        sumUsage(context.messages).cost.total >= options.maxCostUsd
      )
        stopped = 'cost_limit';
      if (
        context.systemPrompt.length + contextSize(recentImages(context.messages)) >
        maxContextChars
      )
        stopped = 'context_limit';
      return stopped !== undefined;
    },
  });
  agent.subscribe((event) => {
    if (event.type === 'turn_start') steps++;
  });
  if (options.onEvent) agent.subscribe(options.onEvent);
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
    else await agent.prompt(task);
  } catch (cause) {
    error = cause instanceof Error ? cause.message : String(cause);
    stopped ??= 'error';
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', cancel);
  }
  const last = agent.state.messages.findLast((m) => m.role === 'assistant');
  const text =
    last?.role === 'assistant'
      ? last.content
          .filter((c) => c.type === 'text')
          .map((c) => c.text)
          .join('\n')
      : '';
  const metrics = {
    steps,
    durationMs: Date.now() - start,
    usage: sumUsage(agent.state.messages),
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
