#!/usr/bin/env node
/** Private versioned stdio bridge. stdout is protocol-only; no shell or HTTP server. */
import { BrowserUse, exportRecording, type BrowserUseOptions } from './index.js';
import type { SessionEvent } from './events.js';
import { builtinModels } from '@earendil-works/pi-ai/providers/all';
import { Type, type TSchema } from 'typebox';
import type { AgentToolResult } from '@earendil-works/pi-agent-core';
import type { Context, Models } from '@earendil-works/pi-ai';

// A gateway that re-serializes Responses events can add null fields such as
// `"status": null` to reasoning items; Pi replays them verbatim and OpenAI rejects them.
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

// Such a gateway also re-encodes Gemini thought signatures as URL-safe base64, which
// Pi drops as invalid on replay, and Gemini then refuses the call.
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

// A history is bound to one model, but a gateway may answer under another name for it
// (an alias, or Bedrock's id); Pi then treats its own thinking as foreign on replay.
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
type ModelInfo = {
  template?: string;
  contextWindow?: number;
  maxTokens?: number;
  compat?: Record<string, unknown>;
  thinkingLevelMap?: Record<string, string | null>;
};

// A gateway may serve models newer than Pi's catalog: they borrow a catalog entry's
// capabilities, and the host's limits, supported thinking levels, and compat overrides
// (e.g. provider betas the gateway does not forward) apply either way.
function withHostModel(models: Models, name: string, info: ModelInfo): Models {
  const split = (ref: string): [string, string] => [
    ref.slice(0, ref.indexOf('/')),
    ref.slice(ref.indexOf('/') + 1),
  ];
  if (
    info.template !== undefined &&
    (typeof info.template !== 'string' || !split(info.template)[0])
  )
    throw new Error('modelInfo.template must be provider/model.');
  for (const key of ['contextWindow', 'maxTokens'] as const)
    if (info[key] !== undefined && !(Number.isSafeInteger(info[key]) && info[key] > 0))
      throw new Error(`modelInfo.${key} must be a positive integer.`);
  for (const key of ['compat', 'thinkingLevelMap'] as const)
    if (info[key] !== undefined && (typeof info[key] !== 'object' || info[key] === null))
      throw new Error(`modelInfo.${key} must be an object.`);
  const [provider, id] = split(name);
  const template = info.template ? split(info.template) : undefined;
  const base = models.getModel(provider, id) ?? (template && models.getModel(...template));
  if (!base) return models;
  const model = {
    ...base,
    id,
    name: base.id === id ? base.name : id,
    ...(info.contextWindow ? { contextWindow: info.contextWindow } : {}),
    ...(info.maxTokens ? { maxTokens: info.maxTokens } : {}),
    ...(info.compat ? { compat: { ...base.compat, ...info.compat } } : {}),
    ...(info.thinkingLevelMap ? { thinkingLevelMap: info.thinkingLevelMap } : {}),
  };
  const getModel = models.getModel.bind(models);
  models.getModel = (p, i) => (p === provider && i === id ? model : getModel(p, i));
  return models;
}

const toolCalls = new Map<
  string,
  { resolve: (value: AgentToolResult<unknown>) => void; reject: (error: Error) => void }
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
      void send({ method: 'tool_cancel', params: { id } }).catch(() => {});
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
    void send({ method: 'tool_call', params: { id, name, args } }).catch((error) =>
      finish(undefined, error),
    );
  });
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
  'tools',
  'apiKey',
  'baseUrl',
  'modelId',
  'modelInfo',
  'streamDeltas',
]);
async function dispatch(method: string, params: Record<string, unknown>): Promise<unknown> {
  if (method === 'ping') return { protocol: 1, node: process.versions.node };
  if (method === 'tool_result') {
    const pending = toolCalls.get(String(params.id));
    if (!pending) return null; // Late cancelled callback; never reexecute it.
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
      if (typeof params.model !== 'string') throw new Error('model must be provider/model.');
      const {
        apiKey,
        baseUrl,
        modelId,
        modelInfo,
        streamDeltas,
        tools: rawTools,
        ...options
      } = params;
      if (apiKey !== undefined && typeof apiKey !== 'string')
        throw new Error('apiKey must be a string.');
      if (baseUrl !== undefined && typeof baseUrl !== 'string')
        throw new Error('baseUrl must be a string.');
      // A gateway may serve a model under another name than the catalog entry that
      // supplies its capabilities; only the id sent upstream changes.
      if (modelId !== undefined && (typeof modelId !== 'string' || !modelId))
        throw new Error('modelId must be a non-empty string.');
      if (modelInfo !== undefined && (typeof modelInfo !== 'object' || modelInfo === null))
        throw new Error('modelInfo must be an object.');
      const models = modelInfo
        ? withHostModel(builtinModels(), params.model as string, modelInfo as ModelInfo)
        : builtinModels();
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
        ...(modelInfo ? { models } : {}),
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
      const current = agent;
      void (async () => {
        // streamDeltas: false drops per-token updates and agent_end's full transcript,
        // which can exceed the stream bounds on image-heavy runs; the run result carries it.
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
          ].includes(key)
        )
          throw new Error(`Unsupported run option: ${key}`);
      return method === 'run'
        ? agent.run(params.task, options)
        : agent.followUp(params.task, options);
    }
    case 'execute':
      if (typeof params.code !== 'string') throw new Error('code must be a string.');
      return agent.execute(params.code, (params.options ?? {}) as { timeoutMs?: number });
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
      agent.cancel();
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
    case 'close':
      closing = true;
      await agent.close({ keepTabs: params.keepTabs === true });
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
