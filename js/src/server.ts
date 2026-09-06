#!/usr/bin/env node
/** Private versioned stdio bridge. stdout is protocol-only; no shell or HTTP server. */
import { BrowserUse, exportRecording, type BrowserUseOptions } from './index.js';
import { builtinModels } from '@earendil-works/pi-ai/providers/all';
import { Type, type TSchema } from 'typebox';
import type { AgentToolResult } from '@earendil-works/pi-agent-core';

let agent: BrowserUse | undefined;
let creating = false;
let closing = false;
let nextTool = 0;
let queuedBytes = 0;
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
  'maxOutputChars',
  'hookTimeoutMs',
  'redact',
  'log',
  'historyFile',
  'recording',
  'tools',
  'apiKey',
  'baseUrl',
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
      const { apiKey, baseUrl, tools: rawTools, ...options } = params;
      if (apiKey !== undefined && typeof apiKey !== 'string')
        throw new Error('apiKey must be a string.');
      if (baseUrl !== undefined && typeof baseUrl !== 'string')
        throw new Error('baseUrl must be a string.');
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
        tools: toolSpecs.map((tool) => ({
          ...tool,
          label: tool.name,
          parameters: Type.Unsafe(tool.parameters),
          executionMode: 'sequential' as const,
          execute: async (_id: string, args: unknown, signal?: AbortSignal) =>
            invokePython(tool.name, args, signal),
        })),
        streamFn: (model, context, settings) =>
          models.streamSimple(
            typeof baseUrl === 'string' ? { ...model, baseUrl } : model,
            context,
            { ...settings, ...(typeof apiKey === 'string' ? { apiKey } : {}) },
          ),
      });
      const current = agent;
      void (async () => {
        for await (const event of current.events()) await send({ method: 'event', params: event });
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
        if (!['maxSteps', 'timeoutMs', 'maxCostUsd', 'maxContextChars', 'schema'].includes(key))
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
    case 'close':
      closing = true;
      await agent.close();
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
