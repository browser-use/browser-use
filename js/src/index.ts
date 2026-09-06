import { mkdir, mkdtemp, open } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { builtinModels } from '@earendil-works/pi-ai/providers/all';
import { randomUUID } from 'node:crypto';
import type { AgentMessage, StreamFn } from '@earendil-works/pi-agent-core';
import type { Api, Model, Usage } from '@earendil-works/pi-ai';
import { Type, type Static, type TSchema } from 'typebox';
import { openBrowser } from './browser.js';
import { BrowserRuntime } from './runtime.js';
import { runAgent, zeroUsage } from './agent.js';
import { Recorder } from './recording.js';
import { RunControl } from './control.js';
import {
  loadHistory,
  saveHistory,
  workspaceFiles,
  redact,
  type SessionHistory,
} from './history.js';
import { EventStream, formatEvent, type SessionEvent, type SessionEventData } from './events.js';
import { positiveInteger } from './protocol.js';
import type { BrowserUseOptions, RunOptions, RunResult } from './types.js';

export type { BrowserUseOptions, RunOptions, RunResult, StopReason, RunMetrics } from './types.js';
export type { BrowserOptions } from './browser.js';
export type { CellResult, Image } from './protocol.js';
export type { AgentTool, AgentEvent, StreamFn } from '@earendil-works/pi-agent-core';
export { Type, type Static, type TSchema } from 'typebox';
export { builtinModels } from '@earendil-works/pi-ai/providers/all';

/** One browser, workspace and JavaScript namespace. run() resets context; followUp() retains it. */
export class BrowserUse {
  private active = false;
  private closed = false;
  private controller: AbortController | undefined;
  private closing: Promise<void> | undefined;
  private messages: AgentMessage[] = [];
  private totalUsage = zeroUsage();
  private runs = 0;
  private control: RunControl | undefined;
  private streams = new Set<EventStream>();
  private sequence = 0;
  private activeRun: Promise<RunResult<unknown>> | undefined;
  private manualCell: Promise<unknown> | undefined;
  private runId = '';
  private hasConversation = false;

  private constructor(
    private readonly config: BrowserUseOptions & { streamFn: StreamFn },
    private readonly model: Model<Api>,
    private readonly runtime: BrowserRuntime,
    private readonly browser: Awaited<ReturnType<typeof openBrowser>>,
    readonly workspace: string,
  ) {}

  static async create(options: BrowserUseOptions): Promise<BrowserUse> {
    if (options.recording && typeof options.recording === 'object') {
      positiveInteger('recording.intervalMs', options.recording.intervalMs ?? 750);
      positiveInteger('recording.maxFrames', options.recording.maxFrames ?? 400);
      if (
        (options.recording.intervalMs ?? 750) < 100 ||
        (options.recording.maxFrames ?? 400) > 10000
      )
        throw new Error('Recording requires intervalMs >= 100 and maxFrames <= 10000.');
    }
    const restored = options.historyFile
      ? await loadHistory(options.historyFile, options.model)
      : undefined;
    positiveInteger('hookTimeoutMs', options.hookTimeoutMs ?? 30_000);
    const separator = options.model.indexOf('/');
    if (separator < 1) throw new Error('model must be provider/model, for example openai/gpt-5.4.');
    const models = options.models ?? builtinModels();
    const provider = options.model.slice(0, separator);
    const model = models.getModel(provider, options.model.slice(separator + 1));
    if (!model)
      throw new Error(
        `Unknown model ${options.model}. Supply a Pi models collection with this model registered.`,
      );
    const names = new Set(['javascript', 'finish', 'finish_from_js']);
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
      recording: !!options.recording,
      ...(options.browser?.targetId ? { targetId: options.browser.targetId } : {}),
      workspace,
      operationTimeoutMs,
      maxOutputChars,
    });
    const config = { ...options, streamFn: options.streamFn ?? models.streamSimple.bind(models) };
    const instance = new BrowserUse(config, model, runtime, browser, workspace);
    if (restored) {
      instance.messages = restored.messages;
      instance.totalUsage = restored.usage;
      instance.runs = restored.runs;
      instance.hasConversation = true;
      instance.messages.push({
        role: 'user',
        content:
          'This conversation was restored from disk. JavaScript bindings and connections were reset. Inspect browser state and workspace before continuing. Never replay uncertain actions automatically.',
        timestamp: Date.now(),
      });
    }
    return instance;
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
    return this.startRun(task, options, false);
  }

  followUp(task: string, options?: RunOptions): Promise<RunResult<string>>;
  followUp<S extends TSchema>(
    task: string,
    options: RunOptions & { schema: S },
  ): Promise<RunResult<Static<S>>>;
  async followUp(
    task: string,
    options: RunOptions & { schema?: TSchema } = {},
  ): Promise<RunResult<unknown>> {
    if (!this.hasConversation) throw new Error('Run a task or restore history before followUp().');
    return this.startRun(task, options, true);
  }

  private startRun(
    task: string,
    options: RunOptions & { schema?: TSchema },
    followUp: boolean,
  ): Promise<RunResult<unknown>> {
    this.assertIdle();
    if (!task.trim()) throw new Error('Provide a nonempty task.');
    this.active = true;
    if (!followUp) this.messages = [];
    this.runId = randomUUID();
    this.controller = new AbortController();
    this.control = new RunControl((paused) => this.emit({ type: paused ? 'paused' : 'resumed' }));
    this.activeRun = this.performRun(task, options, followUp);
    return this.activeRun;
  }

  private async performRun(
    task: string,
    options: RunOptions & { schema?: TSchema },
    followUp: boolean,
  ): Promise<RunResult<unknown>> {
    const controller = this.controller!;
    const control = this.control!;
    const signal = options.signal
      ? AbortSignal.any([options.signal, controller.signal])
      : controller.signal;
    const directory = join(this.workspace, '.browser-use', 'runs');
    const historyPath = join(directory, `${this.runId}.json`);
    const eventsPath = join(directory, `${this.runId}.jsonl`);
    let recorder: Recorder | undefined;
    let journal: Awaited<ReturnType<typeof open>> | undefined;
    try {
      await mkdir(directory, { recursive: true, mode: 0o700 });
      journal = await open(eventsPath, 'wx', 0o600);
      const record = async (data: SessionEventData) => {
        const event = this.emit(data);
        // Deltas stream live. Persist finalized messages, not a full transcript for every token.
        if (
          data.type === 'agent_event' &&
          ['message_update', 'agent_end'].includes(data.event.type)
        )
          return;
        const serialized = JSON.stringify(event, (key, value: unknown) =>
          key === 'data' && typeof value === 'string' && value.length > 10000
            ? '[image omitted from event log]'
            : value,
        );
        await journal!.writeFile(
          serialized.length > 256000
            ? JSON.stringify({
                sequence: event.sequence,
                timestamp: event.timestamp,
                runId: event.runId,
                type: event.type,
                truncated: true,
              }) + '\n'
            : serialized + '\n',
        );
      };
      await record({ type: 'run_start', task, followUp });
      if (this.config.recording && !signal.aborted) {
        recorder = new Recorder(
          join(this.workspace, '.browser-use', 'recordings', this.runId),
          task,
          typeof this.config.recording === 'object' ? this.config.recording : {},
        );
        try {
          const targetId = await this.runtime.initialize(signal);
          await recorder.start(this.browser.endpoint, targetId);
          this.runtime.onAction = (action) => recorder?.action(action);
        } catch (error) {
          await record({ type: 'warning', message: `Recording unavailable: ${String(error)}` });
        }
      }
      const result = await runAgent(
        this.runtime,
        this.model,
        this.config,
        this.workspace,
        task,
        options.schema ?? Type.String(),
        {
          ...options,
          signal,
          onEvent: async (event, eventSignal) => {
            await record({ type: 'agent_event', event });
            await options.onEvent?.(event, eventSignal);
          },
        },
        {
          messages: this.messages,
          control,
          save: (messages) => {
            this.messages = messages;
            this.hasConversation = true;
          },
        },
      );
      this.runs++;
      for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens'] as const)
        this.totalUsage[key] += result.usage[key];
      for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'total'] as const)
        this.totalUsage.cost[key] += result.usage.cost[key];
      this.runtime.onAction = undefined;
      const warnings: string[] = [];
      let recordingPath: string | undefined;
      if (recorder) {
        try {
          recordingPath = await recorder.stop(result.status, this.runtime.currentTarget);
        } catch (error) {
          warnings.push(`Recording could not be saved: ${String(error)}`);
        }
      }
      recorder = undefined;
      const delivered: RunResult<unknown> = {
        ...result,
        ...(recordingPath ? { recordingPath } : {}),
        runId: this.runId,
        eventsPath,
      };
      try {
        await saveHistory(historyPath, this.history, this.config.redact);
        delivered.historyPath = historyPath;
      } catch (error) {
        warnings.push(`History could not be saved: ${String(error)}`);
      }
      if (warnings.length) delivered.warnings = warnings;
      try {
        await record({ type: 'run_end', result: delivered });
      } catch (error) {
        delivered.warnings = [
          ...(delivered.warnings ?? []),
          `Event log could not be finalized: ${String(error)}`,
        ];
      }
      return delivered;
    } finally {
      this.runtime.onAction = undefined;
      await this.manualCell?.catch(() => {});
      if (recorder) await recorder.stop('error', this.runtime.currentTarget).catch(() => {});
      try {
        await journal?.close();
      } finally {
        control.finish();
        this.active = false;
        this.controller = undefined;
        this.control = undefined;
      }
    }
  }

  private emit(data: SessionEventData): SessionEvent {
    const event = redact(
      { ...data, sequence: ++this.sequence, timestamp: Date.now(), runId: this.runId },
      this.config.redact ?? [],
    );
    for (const stream of this.streams) stream.push(event);
    const line =
      this.config.log === 'json'
        ? JSON.stringify(event)
        : this.config.log === 'pretty'
          ? formatEvent(event)
          : undefined;
    if (line) process.stderr.write(line + '\n');
    return event;
  }

  /** Subscribe before starting work. Iterators finish when the session closes. */
  events(): EventStream {
    if (this.closed) throw new Error('BrowserUse is closed.');
    const stream = new EventStream(() => this.streams.delete(stream));
    this.streams.add(stream);
    return stream;
  }

  get history(): SessionHistory {
    return redact(
      {
        version: 1,
        model: this.config.model,
        messages: this.messages,
        usage: this.totalUsage,
        runs: this.runs,
      },
      [],
    );
  }
  get usage(): Usage {
    return structuredClone(this.totalUsage);
  }
  get isPaused() {
    return this.control?.paused ?? false;
  }
  files() {
    return workspaceFiles(this.workspace);
  }
  async saveHistory(path = join(this.workspace, '.browser-use', 'session.json')) {
    this.assertIdle();
    await saveHistory(path, this.history, this.config.redact);
    return path;
  }
  pause(): Promise<void> {
    if (!this.control) throw new Error('No active run to pause.');
    return this.control.pause();
  }
  async resume() {
    await this.manualCell?.catch(() => {});
    this.control?.resume();
  }
  steer(text: string) {
    if (!text.trim()) throw new Error('Provide nonempty steering text.');
    if (!this.control?.steer)
      throw new Error('No active agent to steer; use followUp() after a run.');
    this.control.steer(text);
  }
  cancel() {
    this.controller?.abort();
    this.control?.resume();
  }

  /** Direct browser code. Use the same page and variables as the agent. */
  async execute(code: string, options: { timeoutMs?: number; signal?: AbortSignal } = {}) {
    const duringPause = this.isPaused;
    if (!duringPause) this.assertIdle();
    if (this.closed) throw new Error('BrowserUse is closed.');
    if (duringPause && this.manualCell)
      throw new Error('A manual browser cell is already running.');
    if (!duringPause) this.active = true;
    try {
      const signal =
        duringPause && this.controller
          ? options.signal
            ? AbortSignal.any([options.signal, this.controller.signal])
            : this.controller.signal
          : options.signal;
      const cell = this.runtime.execute(
        code,
        options.timeoutMs ?? this.config.cellTimeoutMs ?? 30_000,
        signal,
      );
      if (duringPause) this.manualCell = cell;
      return await cell;
    } finally {
      if (duringPause) this.manualCell = undefined;
      else this.active = false;
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
    this.cancel();
    this.closing = (async () => {
      try {
        await this.activeRun?.catch(() => {});
        await this.runtime.close();
      } finally {
        try {
          await this.browser.close();
        } finally {
          for (const stream of [...this.streams]) stream.end();
        }
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

export type { SessionHistory, WorkspaceFile } from './history.js';
export type { SessionEvent } from './events.js';
export { formatEvent } from './events.js';

export { exportRecording, type VideoOptions } from './video.js';
export type { RecordingOptions } from './recording.js';
