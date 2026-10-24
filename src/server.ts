#!/usr/bin/env node
import { BrowserUse, exportRecording, type BrowserUseOptions } from './index.js';
import type { SessionEvent } from './events.js';
import { builtinModels } from '@earendil-works/pi-ai/providers/all';
import { Type, type TSchema } from 'typebox';
import type { AgentToolResult } from '@earendil-works/pi-agent-core';
import type { Context } from '@earendil-works/pi-ai';
import { bounded } from './control.js';
function withoutNullReasoningFields(context: Context): Context {
  return {
    ...context,
    messages: context.messages.map((message) => {
      if (message.role !== 'assistant') return message;
      return {
        ...message,
        content: message.content.map((block) => {
          if (block.type !== 'thinking' || !block.thinkingSignature?.startsWith('{')) return block;
          try {
            const item = JSON.parse(block.thinkingSignature) as Record<string, unknown>;
            const kept = Object.entries(item).filter(([, value]) => value !== null);
            return { ...block, thinkingSignature: JSON.stringify(Object.fromEntries(kept)) };
          } catch {
            return block;
          }
        }),
      };
    }),
  };
}
function withStandardSignatures(context: Context): Context {
  const standard = (value: unknown) =>
    typeof value === 'string' ? value.replace(/-/g, '+').replace(/_/g, '/') : value;
  return {
    ...context,
    messages: context.messages.map((message) => {
      if (message.role !== 'assistant') return message;
      return {
        ...message,
        content: message.content.map((block) => {
          if (block.type === 'thinking')
            return { ...block, thinkingSignature: standard(block.thinkingSignature) as string };
          if (block.type === 'text')
            return { ...block, textSignature: standard(block.textSignature) as string };
          if (block.type === 'toolCall')
            return { ...block, thoughtSignature: standard(block.thoughtSignature) as string };
          return block;
        }),
      };
    }),
  };
}
function withModelId(context: Context, provider: string, id: string): Context {
  return {
    ...context,
    messages: context.messages.map((message) =>
      message.role === 'assistant' && message.provider === provider
        ? { ...message, model: id }
        : message,
    ),
  };
}
let agent: BrowserUse | undefined;
let creating = false;
let closing = false;
let nextTool = 0;
let queuedBytes = 0;
const toolCalls = new Map<
  string,
  {
    resolve: (value: AgentToolResult<unknown>) => void;
    reject: (error: Error) => void;
  }
>();
function send(value: unknown): Promise<void> {
  const line = JSON.stringify(value) + '\n';
  if (line.length > 16000000 || queuedBytes + line.length > 32000000)
    return Promise.reject(new Error('Bridge output exceeded 32 MB; consumer must drain events.'));
  queuedBytes += line.length;
  return new Promise((resolve, reject) =>
    process.stdout.write(line, (error) => {
      queuedBytes -= line.length;
      error ? reject(error) : resolve();
    }),
  );
}
function invokePython(
  name: string,
  args: unknown,
  signal?: AbortSignal,
  callback = false,
): Promise<AgentToolResult<unknown>> {
  const id = `tool-${++nextTool}`;
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (value?: AgentToolResult<unknown>, error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      toolCalls.delete(id);
      error ? reject(error) : resolve(value!);
    };
    const abort = () => {
      void send({ method: callback ? 'callback_cancel' : 'tool_cancel', params: { id } }).catch(
        () => {},
      );
      finish(undefined, new Error('Python tool cancelled.'));
    };
    const timer = setTimeout(abort, 120000);
    toolCalls.set(id, {
      resolve: (value) => finish(value),
      reject: (error) => finish(undefined, error),
    });
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) {
      abort();
      return;
    }
    void send({
      method: callback ? 'callback_call' : 'tool_call',
      params: { id, name, args },
    }).catch((error) => finish(undefined, error));
  });
}
async function invokeCallback(name: string, args: unknown, signal?: AbortSignal): Promise<any> {
  const response = await invokePython(name, args, signal, true);
  return response.details;
}
function callbackOptions(value: unknown): Partial<BrowserUseOptions> {
  if (value === undefined) return {};
  if (!Array.isArray(value) || value.some((name) => typeof name !== 'string'))
    throw new Error('callbacks must contain callback names.');
  const callbacks: Partial<BrowserUseOptions> = {};
  for (const name of value) {
    if (!['beforeToolCall', 'afterToolCall', 'validateResult', 'onBrowserReady'].includes(name))
      throw new Error(`Unsupported callback: ${name}`);
    if (name === 'onBrowserReady') continue;
    else
      (callbacks as Record<string, unknown>)[name] = (args: unknown, signal?: AbortSignal) =>
        invokeCallback(name, args, signal);
  }
  return callbacks;
}
const CREATE_KEYS = new Set([
  'model',
  'browser',
  'workspace',
  'reasoning',
  'instructions',
  'operationTimeoutMs',
  'cellTimeoutMs',
  'modelTimeoutMs',
  'compactionTimeoutMs',
  'compactionRetryDelayMs',
  'maxOutputChars',
  'hookTimeoutMs',
  'redact',
  'log',
  'historyFile',
  'recording',
  'highlightActions',
  'allowedDomains',
  'prohibitedDomains',
  'sensitiveData',
  'telemetry',
  'researchTools',
  'shellEnv',
  'focusTab',
  'browserSwitching',
  'dedicatedBrowser',
  'shellTimeoutMs',
  'tools',
  'apiKey',
  'baseUrl',
  'modelId',
  'modelInfo',
  'streamDeltas',
  'mode',
  'webSearch',
  'callbacks',
  'clientLanguage',
  'entrypoint',
  'controller',
  'initScripts',
]);
async function dispatch(method: string, params: Record<string, unknown>): Promise<unknown> {
  if (method === 'ping') return { protocol: 1, node: process.versions.node };
  if (method === 'tool_result' || method === 'callback_result') {
    const pending = toolCalls.get(String(params.id));
    if (!pending) return null;
    if (typeof params.error === 'string') pending.reject(new Error(params.error));
    else
      pending.resolve({
        content: [
          {
            type: 'text',
            text:
              typeof params.result === 'string'
                ? params.result
                : JSON.stringify(params.result ?? null),
          },
        ],
        details: params.result,
      });
    return null;
  }
  if (method === 'create') {
    if (agent || creating || closing) throw new Error('One session per bridge process.');
    for (const key of Object.keys(params))
      if (!CREATE_KEYS.has(key)) throw new Error(`Unsupported create option: ${key}`);
    creating = true;
    try {
      if (params.model !== undefined && typeof params.model !== 'string')
        throw new Error('model must be provider/model.');
      const {
        apiKey,
        baseUrl,
        modelId,
        modelInfo,
        streamDeltas,
        tools: rawTools,
        callbacks,
        ...options
      } = params;
      if (apiKey !== undefined && typeof apiKey !== 'string')
        throw new Error('apiKey must be a string.');
      if (baseUrl !== undefined && typeof baseUrl !== 'string')
        throw new Error('baseUrl must be a string.');
      if (modelId !== undefined && (typeof modelId !== 'string' || !modelId))
        throw new Error('modelId must be a non-empty string.');
      if (modelInfo !== undefined && (typeof modelInfo !== 'object' || modelInfo === null))
        throw new Error('modelInfo must be an object.');
      const models = builtinModels();
      const toolSpecs = (rawTools ?? []) as {
        name: string;
        description: string;
        parameters: TSchema;
      }[];
      if (
        !Array.isArray(toolSpecs) ||
        toolSpecs.some(
          (t) =>
            typeof t.name !== 'string' ||
            typeof t.description !== 'string' ||
            !t.parameters ||
            typeof t.parameters !== 'object',
        )
      )
        throw new Error('Invalid Python tool specifications.');
      agent = await BrowserUse.create({
        ...(options as unknown as BrowserUseOptions),
        models,
        ...(typeof modelId === 'string' &&
        !(modelInfo && typeof modelInfo === 'object' && 'cost' in modelInfo)
          ? { pricingKnown: false }
          : {}),
        ...(modelInfo
          ? { modelInfo: modelInfo as NonNullable<BrowserUseOptions['modelInfo']> }
          : {}),
        ...callbackOptions(callbacks),
        tools: toolSpecs.map((tool) => ({
          ...tool,
          label: tool.name,
          parameters: Type.Unsafe(tool.parameters),
          executionMode: 'sequential' as const,
          execute: async (_id: string, args: unknown, signal?: AbortSignal) =>
            invokePython(tool.name, args, signal),
        })),
        streamFn: (model, context, settings) => {
          const sent = {
            ...model,
            ...(typeof baseUrl === 'string' ? { baseUrl } : {}),
            ...(typeof modelId === 'string' ? { id: modelId } : {}),
          };
          const replay =
            typeof modelId === 'string' ? withModelId(context, sent.provider, sent.id) : context;
          return models.streamSimple(
            sent,
            sent.api === 'openai-responses'
              ? withoutNullReasoningFields(replay)
              : sent.api === 'google-generative-ai'
                ? withStandardSignatures(replay)
                : replay,
            { ...settings, ...(typeof apiKey === 'string' ? { apiKey } : {}) },
          );
        },
      });
      if (Array.isArray(callbacks) && callbacks.includes('onBrowserReady')) {
        const controller = new AbortController();
        try {
          await bounded(
            () => invokeCallback('onBrowserReady', null, controller.signal),
            typeof options.hookTimeoutMs === 'number' ? options.hookTimeoutMs : 30000,
            controller.signal,
          );
        } catch (error) {
          controller.abort();
          try {
            await agent.close();
          } catch (cleanupError) {
            throw new AggregateError([error, cleanupError], 'Browser setup and cleanup failed.');
          }
          throw error;
        } finally {
          controller.abort();
        }
      }
      const current = agent;
      void (async () => {
        const settled = (event: SessionEvent) =>
          !(
            event.type === 'agent_event' &&
            (event.event.type === 'message_update' || event.event.type === 'agent_end')
          );
        for await (const event of current.events(streamDeltas === false ? settled : undefined))
          await send({ method: 'event', params: event });
      })().catch((error) => {
        current.cancel();
        void send({ method: 'stream_error', params: { message: String(error) } }).catch(() => {});
      });
      return { workspace: agent.workspace };
    } finally {
      creating = false;
    }
  }
  if (!agent && method === 'close') return null;
  if (!agent) throw new Error('Create a session first.');
  switch (method) {
    case 'run':
    case 'followUp': {
      if (typeof params.task !== 'string') throw new Error('task must be a string.');
      const options = (params.options ?? {}) as Record<string, unknown>;
      for (const key of Object.keys(options))
        if (
          ![
            'maxSteps',
            'timeoutMs',
            'maxCostUsd',
            'maxContextChars',
            'compaction',
            'schema',
            'validateResult',
          ].includes(key)
        )
          throw new Error(`Unsupported run option: ${key}`);
      const validate = options.validateResult === true;
      delete options.validateResult;
      if (validate)
        options.validateResult = (output: unknown, signal?: AbortSignal) =>
          invokeCallback('validateResult', output, signal);
      return method === 'run'
        ? agent.run(params.task, options)
        : agent.followUp(params.task, options);
    }
    case 'executeJson':
      if (typeof params.expression !== 'string') throw new Error('expression must be a string.');
      return agent.executeJson(
        params.expression,
        (params.options ?? {}) as {
          timeoutMs?: number;
        },
      );
    case 'execute':
      if (typeof params.code !== 'string') throw new Error('code must be a string.');
      return agent.execute(
        params.code,
        (params.options ?? {}) as {
          timeoutMs?: number;
        },
      );
    case 'pause':
      await agent.pause();
      return { paused: agent.isPaused };
    case 'resume':
      await agent.resume();
      return null;
    case 'steer':
      if (typeof params.text !== 'string') throw new Error('text must be a string.');
      agent.steer(params.text);
      return null;
    case 'cancel':
      await agent.cancelAndWait();
      return null;
    case 'files':
      return agent.files();
    case 'history':
      return agent.history;
    case 'saveHistory':
      return agent.saveHistory(typeof params.path === 'string' ? params.path : undefined);
    case 'exportRecording':
      return exportRecording(
        String(params.path),
        params.options as Parameters<typeof exportRecording>[1],
      );
    case 'currentTarget':
      return agent.currentTarget ?? null;
    case 'connectBrowser':
      if (typeof params.cdpUrl !== 'string') throw new Error('cdpUrl must be a string.');
      agent.connectBrowser(params.cdpUrl, {
        ...(typeof params.targetId === 'string' ? { targetId: params.targetId } : {}),
        ...(params.cdpOptions
          ? { cdpOptions: params.cdpOptions as import('./browser.js').CdpConnectionOptions }
          : {}),
      });
      return null;
    case 'close':
      closing = true;
      await agent.close({
        keepTabs: params.keepTabs === 'current' ? 'current' : params.keepTabs === true,
      });
      return null;
    default:
      throw new Error(`Unknown bridge method: ${method}`);
  }
}
async function handle(line: string) {
  let id: string | number | undefined;
  try {
    const request = JSON.parse(line);
    id = request.id;
    if (
      !['string', 'number'].includes(typeof id) ||
      typeof request.method !== 'string' ||
      (request.params && (typeof request.params !== 'object' || Array.isArray(request.params)))
    )
      throw new Error('Invalid RPC request.');
    const result = await dispatch(request.method, request.params ?? {});
    await send({ id, result });
  } catch (error) {
    await send({
      id: id ?? null,
      error: { message: error instanceof Error ? error.message : String(error) },
    }).catch(() => {});
  }
}
let buffer = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk: string) => {
  buffer += chunk;
  if (buffer.length > 16000000) {
    process.stdin.destroy();
    agent?.cancel();
    return;
  }
  let end: number;
  while ((end = buffer.indexOf('\n')) >= 0) {
    const line = buffer.slice(0, end);
    buffer = buffer.slice(end + 1);
    if (line.trim()) void handle(line);
  }
});
process.stdin.on('end', () => {
  void agent?.close().finally(() => process.exit(0));
  if (!agent) process.exit(0);
});
process.on('SIGTERM', () => {
  void agent?.close().finally(() => process.exit(0));
  if (!agent) process.exit(0);
});
