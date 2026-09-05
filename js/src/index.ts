import { mkdir, mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { builtinModels } from '@earendil-works/pi-ai/providers/all';
import type { StreamFn } from '@earendil-works/pi-agent-core';
import type { Api, Model } from '@earendil-works/pi-ai';
import { Type, type Static, type TSchema } from 'typebox';
import { openBrowser } from './browser.js';
import { BrowserRuntime } from './runtime.js';
import { runAgent } from './agent.js';
import { positiveInteger } from './protocol.js';
import type { BrowserUseOptions, RunOptions, RunResult } from './types.js';

export type { BrowserUseOptions, RunOptions, RunResult, StopReason, RunMetrics } from './types.js';
export type { BrowserOptions } from './browser.js';
export type { CellResult, Image } from './protocol.js';
export type { AgentTool, AgentEvent, StreamFn } from '@earendil-works/pi-agent-core';
export { Type, type Static, type TSchema } from 'typebox';
export { builtinModels } from '@earendil-works/pi-ai/providers/all';

/** One browser session and one JavaScript namespace. Runs share the browser, not transcripts. */
export class BrowserUse {
  private active = false;
  private closed = false;
  private controller: AbortController | undefined;
  private closing: Promise<void> | undefined;

  private constructor(
    private readonly config: BrowserUseOptions & { streamFn: StreamFn },
    private readonly model: Model<Api>,
    private readonly runtime: BrowserRuntime,
    private readonly browser: Awaited<ReturnType<typeof openBrowser>>,
    readonly workspace: string,
  ) {}

  static async create(options: BrowserUseOptions): Promise<BrowserUse> {
    const separator = options.model.indexOf('/');
    if (separator < 1) throw new Error('model must be provider/model, for example openai/gpt-5.4.');
    const models = options.models ?? builtinModels();
    const provider = options.model.slice(0, separator);
    const model = models.getModel(provider, options.model.slice(separator + 1));
    if (!model)
      throw new Error(
        `Unknown model ${options.model}. Supply a Pi models collection with this model registered.`,
      );
    const names = new Set(['javascript', 'finish']);
    for (const tool of options.tools ?? []) {
      if (names.has(tool.name)) throw new Error(`Duplicate or reserved tool name: ${tool.name}`);
      names.add(tool.name);
    }
    const operationTimeoutMs = positiveInteger(
      'operationTimeoutMs',
      options.operationTimeoutMs ?? 15_000,
    );
    positiveInteger('cellTimeoutMs', options.cellTimeoutMs ?? 30_000);
    const maxOutputChars = positiveInteger('maxOutputChars', options.maxOutputChars ?? 12_000);
    const workspace = options.workspace
      ? resolve(options.workspace)
      : await mkdtemp(join(tmpdir(), 'browser-use-artifacts-'));
    await mkdir(workspace, { recursive: true });
    const browser = await openBrowser(options.browser);
    const runtime = new BrowserRuntime({
      endpoint: browser.endpoint,
      workspace,
      operationTimeoutMs,
      maxOutputChars,
    });
    const config = { ...options, streamFn: options.streamFn ?? models.streamSimple.bind(models) };
    return new BrowserUse(config, model, runtime, browser, workspace);
  }

  run(task: string, options?: RunOptions): Promise<RunResult<string>>;
  run<S extends TSchema>(
    task: string,
    options: RunOptions & { schema: S },
  ): Promise<RunResult<Static<S>>>;
  async run(
    task: string,
    options: RunOptions & { schema?: TSchema } = {},
  ): Promise<RunResult<unknown>> {
    this.assertIdle();
    if (!task.trim()) throw new Error('Provide a nonempty task.');
    this.active = true;
    const controller = new AbortController();
    this.controller = controller;
    const signal = options.signal
      ? AbortSignal.any([options.signal, controller.signal])
      : controller.signal;
    try {
      return await runAgent(
        this.runtime,
        this.model,
        this.config,
        this.workspace,
        task,
        options.schema ?? Type.String(),
        { ...options, signal },
      );
    } finally {
      this.active = false;
      this.controller = undefined;
    }
  }

  /** Direct browser code. Use the same page and variables as the agent. */
  async execute(code: string, options: { timeoutMs?: number; signal?: AbortSignal } = {}) {
    this.assertIdle();
    this.active = true;
    try {
      return await this.runtime.execute(
        code,
        options.timeoutMs ?? this.config.cellTimeoutMs ?? 30_000,
        options.signal,
      );
    } finally {
      this.active = false;
    }
  }

  private assertIdle() {
    if (this.closed) throw new Error('BrowserUse is closed. Create a new session.');
    if (this.active)
      throw new Error(
        'This session is busy. Await the active operation or create a separate session.',
      );
  }

  /** Idempotent. Cancels execution, closes our tab, and shuts down only browsers we launched. */
  close(): Promise<void> {
    if (this.closing) return this.closing;
    this.closed = true;
    this.controller?.abort();
    this.closing = (async () => {
      try {
        await this.runtime.close();
      } finally {
        await this.browser.close();
      }
    })();
    return this.closing;
  }

  async [Symbol.asyncDispose]() {
    await this.close();
  }
}

export { CDP } from './cdp.js';
export { Page, type Target, type AXNode } from './page.js';
export { Tabs } from './tabs.js';
