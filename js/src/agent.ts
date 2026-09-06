import {
  Agent,
  type AgentMessage,
  type AgentTool,
  type StreamFn,
} from '@earendil-works/pi-agent-core';
import type { Model, Api, Usage } from '@earendil-works/pi-ai';
import { Type, type TSchema } from 'typebox';
import { Check, Errors } from 'typebox/value';
import type { BrowserRuntime } from './runtime.js';
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
    if (value && typeof value === 'object' && 'role' in value && value.role === 'toolResult') {
      const { details: _details, ...message } = value as Record<string, unknown>;
      return message; // Application metadata is not model-visible content.
    }
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
  const start = Date.now();
  const previousMessages = session?.messages.length ?? 0;
  const hookTimeout = config.hookTimeoutMs ?? 30_000;
  let steps = 0;
  let finishRepairs = 0;
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
      sumUsage(messages.slice(previousMessages)).cost.total >= options.maxCostUsd
    )
      stopped = 'cost_limit';
    if (systemPrompt.length + contextSize(recentImages(messages)) > maxContextChars)
      stopped = 'context_limit';
    return stopped !== undefined;
  };
  const agent = new Agent({
    streamFn: config.streamFn,
    initialState: {
      model,
      messages: session?.messages ?? [],
      systemPrompt: `${SYSTEM_PROMPT}\n${config.instructions ?? ''}`,
      thinkingLevel: config.reasoning ?? 'medium',
      tools: [javascript, finish, finishFromJs, ...(config.tools ?? [])],
    },
    toolExecution: 'sequential',
    transformContext: async (messages) => recentImages(messages),
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
      !checkBudgets(
        [...agent.state.messages, { role: 'user', content: task, timestamp: Date.now() }],
        agent.state.systemPrompt,
      )
    ) {
      await agent.prompt(task);
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
    options.signal?.removeEventListener('abort', cancel);
    session?.save(agent.state.messages);
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
  const metrics = {
    steps,
    finishRepairs,
    durationMs: Date.now() - start,
    usage: sumUsage(agent.state.messages.slice(previousMessages)),
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
