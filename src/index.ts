import { appendFile, mkdir, mkdtemp, open, type FileHandle } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { randomUUID } from 'node:crypto';
import type { AgentMessage, StreamFn } from '@earendil-works/pi-agent-core';
import type { Api, Model, Usage } from '@earendil-works/pi-ai';
import { Type, type Static, type TSchema } from 'typebox';
import { navigationPolicy, validateSensitiveData } from './policy.js';
import { createTelemetry, type Telemetry, type TelemetryOperation } from './telemetry.js';
import { Browser, openBrowser, validCdpUrl } from './browser.js';
import { BrowserRuntime, workerExecutable } from './runtime.js';
import { runAgent, zeroUsage } from './agent.js';
import { Recorder } from './recording.js';
import { bounded, RunControl } from './control.js';
import {
  loadHistory,
  saveHistory,
  workspaceFiles,
  redact,
  type SessionHistory,
} from './history.js';
import { EventStream, formatEvent, type SessionEvent, type SessionEventData } from './events.js';
import { positiveInteger } from './protocol.js';
import { builtinModels, resolveModel } from './models.js';
import type { BrowserUseOptions, RunOptions, RunResult } from './types.js';
export type {
  BrowserUseOptions,
  RunOptions,
  RunResult,
  StopReason,
  RunMetrics,
  ContextMetrics,
} from './types.js';
export { Browser } from './browser.js';
export type {
  BrowserOptions,
  CloudBrowserOptions,
  ChromeBrowserOptions,
  LocalBrowserOptions,
} from './browser.js';
export type { CellResult, Image } from './protocol.js';
export { CellError } from './runtime.js';
export type { AgentTool, AgentEvent, StreamFn } from '@earendil-works/pi-agent-core';
export { Type, type Static, type TSchema } from 'typebox';
export { builtinModels, DEFAULT_MODEL } from './models.js';
export class BrowserUse {
  private readonly telemetry: Telemetry;
  private readonly sessionOperation: TelemetryOperation;
  private operation: TelemetryOperation | undefined;
  private pausedAt = 0;
  private pausedDurationMs = 0;
  private recordManual: ((data: SessionEventData) => Promise<void>) | undefined;
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
    private readonly config: BrowserUseOptions & {
      streamFn: StreamFn;
    },
    private readonly model: Model<Api> | undefined,
    private readonly runtime: BrowserRuntime,
    private readonly browser: Awaited<ReturnType<typeof openBrowser>>,
    readonly workspace: string,
  ) {
    this.telemetry = createTelemetry({
      ...(config.telemetry !== undefined ? { enabled: config.telemetry } : {}),
      ...(config.browser ? { browser: config.browser } : {}),
      ...(model ? { model } : {}),
      configuration: config,
      browserSelection: config.browserSelection ?? 'default',
      clientLanguage: config.clientLanguage ?? 'javascript',
      entrypoint: config.entrypoint ?? 'sdk',
      controller: config.controller ?? 'pi',
      backend: 'pi_runtime',
      modelMetadataSource: config.modelMetadataSource ?? 'unknown',
      pricingKnown: !!config.pricingKnown,
    });
    this.sessionOperation = this.telemetry.start('browser_session');
    if (config.browser?.kind && config.browser.kind !== 'pending')
      this.sessionOperation.browser(config.browser.kind);
    else if (config.browser && 'cdpUrl' in config.browser) this.sessionOperation.browser('cdp');
    runtime.onFeature = (name) => (this.operation ?? this.sessionOperation).count(name);
  }
  static async create(options: BrowserUseOptions): Promise<BrowserUse> {
    if (options.telemetry !== undefined && typeof options.telemetry !== 'boolean')
      throw new Error('telemetry must be boolean.');
    if (
      options.initScripts !== undefined &&
      (!Array.isArray(options.initScripts) ||
        options.initScripts.some((script) => typeof script !== 'string'))
    )
      throw new Error('initScripts must contain JavaScript strings.');
    navigationPolicy(options);
    validateSensitiveData(options.sensitiveData);
    options = {
      ...options,
      researchTools: options.researchTools ?? true,
      browserSelection: options.browser ? 'explicit' : 'default',
      modelMetadataSource: options.models || options.modelInfo ? 'explicit' : 'unknown',
      browser: options.browser ?? Browser.cloud(),
      redact: [
        ...(options.redact ?? []),
        ...Object.values(options.sensitiveData ?? {}).map((secret) => secret.value),
        ...(options.webSearch ? [options.webSearch.token] : []),
      ],
    };
    if (options.highlightActions !== undefined && typeof options.highlightActions !== 'boolean')
      throw new Error('highlightActions must be boolean.');
    if (options.researchTools !== undefined && typeof options.researchTools !== 'boolean')
      throw new Error('researchTools must be boolean.');
    if (options.shellTimeoutMs !== undefined)
      positiveInteger('shellTimeoutMs', options.shellTimeoutMs);
    if (options.browserSwitching !== undefined && typeof options.browserSwitching !== 'boolean')
      throw new Error('browserSwitching must be boolean.');
    if (options.dedicatedBrowser !== undefined && typeof options.dedicatedBrowser !== 'boolean')
      throw new Error('dedicatedBrowser must be boolean.');
    if (options.focusTab !== undefined && typeof options.focusTab !== 'boolean')
      throw new Error('focusTab must be boolean.');
    if (
      options.shellEnv !== undefined &&
      (typeof options.shellEnv !== 'object' ||
        options.shellEnv === null ||
        Object.values(options.shellEnv).some((value) => typeof value !== 'string'))
    )
      throw new Error('shellEnv must map names to strings.');
    if (options.mode !== undefined && options.mode !== 'default' && options.mode !== 'ultrafast')
      throw new Error("mode must be 'default' or 'ultrafast'.");
    if (
      options.webSearch !== undefined &&
      (typeof options.webSearch?.url !== 'string' || typeof options.webSearch?.token !== 'string')
    )
      throw new Error('webSearch must be {url, token}.');
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
      ? await loadHistory(options.historyFile, options.model ?? '')
      : undefined;
    positiveInteger('hookTimeoutMs', options.hookTimeoutMs ?? 30000);
    positiveInteger('modelTimeoutMs', options.modelTimeoutMs ?? 300000);
    positiveInteger('compactionTimeoutMs', options.compactionTimeoutMs ?? 120000);
    positiveInteger('compactionRetryDelayMs', options.compactionRetryDelayMs ?? 1000);
    const models = options.models ?? builtinModels();
    const resolved = options.model ? resolveModel({ ...options, models }) : undefined;
    const model = resolved?.model;
    if (
      options.modelMetadataSource !== 'explicit' &&
      options.model &&
      models.getModel(model!.provider, model!.id)
    )
      options.modelMetadataSource = 'catalog';
    if (options.onBrowserReady && options.browser?.kind === 'pending')
      throw new Error(
        'onBrowserReady requires a browser endpoint; use execute after connectBrowser for pending browsers.',
      );
    options.pricingKnown = options.pricingKnown !== false && (resolved?.priceKnown ?? false);
    const names = new Set([
      'javascript',
      'finish',
      'finish_from_js',
      ...(options.researchTools ? ['read', 'write', 'edit', 'bash'] : []),
    ]);
    for (const tool of options.tools ?? []) {
      if (names.has(tool.name)) throw new Error(`Duplicate or reserved tool name: ${tool.name}`);
      names.add(tool.name);
    }
    const operationTimeoutMs = positiveInteger(
      'operationTimeoutMs',
      options.operationTimeoutMs ?? 15000,
    );
    positiveInteger('cellTimeoutMs', options.cellTimeoutMs ?? 30000);
    const maxOutputChars = positiveInteger('maxOutputChars', options.maxOutputChars ?? 12000);
    const executable = await workerExecutable();
    const workspace = options.workspace
      ? resolve(options.workspace)
      : await mkdtemp(join(tmpdir(), 'browser-use-artifacts-'));
    await mkdir(workspace, { recursive: true });
    let browser: Awaited<ReturnType<typeof openBrowser>>;
    try {
      browser = await openBrowser(options.browser);
    } catch (error) {
      const failure = createTelemetry({
        ...(options.telemetry !== undefined ? { enabled: options.telemetry } : {}),
        ...(options.browser ? { browser: options.browser } : {}),
        ...(model ? { model } : {}),
        configuration: options,
        clientLanguage: options.clientLanguage ?? 'javascript',
        entrypoint: options.entrypoint ?? 'sdk',
        controller: options.controller ?? 'pi',
        pricingKnown: !!options.pricingKnown,
        browserSelection: options.browserSelection ?? 'default',
      });
      failure
        .start('browser_session')
        .finish({ status: 'error', stage: 'provision', errorClass: 'provisioning' });
      await failure.flush();
      throw error;
    }
    const runtime = new BrowserRuntime(
      {
        mode: options.mode ?? 'default',
        ...(browser.connectionOptions ? { cdpOptions: browser.connectionOptions } : {}),
        ...(options.initScripts ? { initScripts: options.initScripts } : {}),
        ...(options.webSearch ? { webSearch: options.webSearch } : {}),
        endpoint: browser.endpoint,
        ...(options.browser?.kind === 'pending'
          ? {
              browserWaitMs: positiveInteger(
                'browser.timeoutMs',
                options.browser.timeoutMs ?? 60000,
              ),
            }
          : {}),
        ...(options.allowedDomains !== undefined ? { allowedDomains: options.allowedDomains } : {}),
        ...(options.prohibitedDomains !== undefined
          ? { prohibitedDomains: options.prohibitedDomains }
          : {}),
        ...(options.sensitiveData ? { sensitiveData: options.sensitiveData } : {}),
        ...(options.redact ? { redact: options.redact } : {}),
        approveConnection:
          options.browser?.kind === 'chrome' && !!options.browser.approveConnection,
        recording: !!options.recording,
        highlightActions: !!options.highlightActions,
        ...(options.browser && 'targetId' in options.browser && options.browser.targetId
          ? { targetId: options.browser.targetId }
          : {}),
        ...(options.focusTab ? { focusTab: true } : {}),
        ...(options.browserSwitching ? { browserSwitching: true } : {}),
        ...(options.dedicatedBrowser ? { dedicatedBrowser: true } : {}),
        workspace,
        operationTimeoutMs,
        maxOutputChars,
      },
      executable,
    );
    const config = { ...options, streamFn: options.streamFn ?? models.streamSimple.bind(models) };
    const instance = new BrowserUse(config, model, runtime, browser, workspace);
    if (options.onBrowserReady) {
      try {
        await bounded(() => options.onBrowserReady!(instance), options.hookTimeoutMs ?? 30000);
      } catch (error) {
        await instance.close().catch(() => {});
        throw error;
      }
    }
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
    options: RunOptions & {
      schema: S;
    },
  ): Promise<RunResult<Static<S>>>;
  async run(
    task: string,
    options: RunOptions & {
      schema?: TSchema;
    } = {},
  ): Promise<RunResult<unknown>> {
    return this.startRun(task, options, false);
  }
  followUp(task: string, options?: RunOptions): Promise<RunResult<string>>;
  followUp<S extends TSchema>(
    task: string,
    options: RunOptions & {
      schema: S;
    },
  ): Promise<RunResult<Static<S>>>;
  async followUp(
    task: string,
    options: RunOptions & {
      schema?: TSchema;
    } = {},
  ): Promise<RunResult<unknown>> {
    if (!this.hasConversation) throw new Error('Run a task or restore history before followUp().');
    return this.startRun(task, options, true);
  }
  private startRun(
    task: string,
    options: RunOptions & {
      schema?: TSchema;
    },
    followUp: boolean,
  ): Promise<RunResult<unknown>> {
    this.assertIdle();
    if (!this.model) throw new Error('Configure a model before running an agent task.');
    if (options.maxCostUsd !== undefined && !this.config.pricingKnown)
      throw new Error('maxCostUsd requires explicit pricing for an uncatalogued model.');
    if (!task.trim()) throw new Error('Provide a nonempty task.');
    this.active = true;
    if (!followUp) this.messages = [];
    this.runId = randomUUID();
    this.operation = this.telemetry.start('agent_run', {
      operationId: this.runId,
      parentOperationId: this.sessionOperation.operationId,
      run: {
        maxSteps: options.maxSteps ?? 40,
        timeoutMs: options.timeoutMs ?? 300000,
        ...(options.maxCostUsd !== undefined ? { maxCostUsd: options.maxCostUsd } : {}),
        ...(options.maxContextChars !== undefined
          ? { maxContextChars: options.maxContextChars }
          : {}),
        compaction: options.compaction !== false,
        schema: options.schema !== undefined,
        onEvent: options.onEvent !== undefined,
        observe: options.observe !== undefined,
        onContextRecovery: options.onContextRecovery !== undefined,
      },
    });
    this.operation.count('tool_calls', 0);
    this.operation.count('tool_errors', 0);
    this.controller = new AbortController();
    this.pausedAt = 0;
    this.pausedDurationMs = 0;
    this.control = new RunControl((paused) => {
      if (paused) this.pausedAt = performance.now();
      else if (this.pausedAt) {
        this.pausedDurationMs += performance.now() - this.pausedAt;
        this.pausedAt = 0;
      }
      this.operation?.count(paused ? 'pauses' : 'resumes');
      this.emit({ type: paused ? 'paused' : 'resumed' });
    });
    this.activeRun = this.performRun(task, options, followUp);
    return this.activeRun;
  }
  private async performRun(
    task: string,
    options: RunOptions & {
      schema?: TSchema;
    },
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
    let journal: FileHandle | undefined;
    let journalFailure: string | undefined;
    let recoveryCheckpoint = false;
    let journalQueue = Promise.resolve();
    const stopJournal = async (error: unknown) => {
      await journal?.close().catch(() => {});
      journal = undefined;
      journalFailure = `Event log stopped: ${String(error)}`;
      this.emit({ type: 'warning', message: journalFailure });
    };
    const journalWrite = (line: string) =>
      (journalQueue = journalQueue
        .then(async () => {
          if (!journal) return;
          try {
            await journal.writeFile(line);
          } catch {
            try {
              await journal.close().catch(() => {});
              journal = await open(eventsPath, 'a', 0o600);
              await journal.writeFile(line);
            } catch (error) {
              await stopJournal(error);
            }
          }
        })
        .catch(() => {}));
    try {
      let unopened: unknown;
      try {
        await mkdir(directory, { recursive: true, mode: 0o700 });
        journal = await open(eventsPath, 'wx', 0o600);
      } catch (error) {
        unopened = error;
      }
      const journaled = journal !== undefined;
      const record = async (data: SessionEventData) => {
        const event = this.emit(data);
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
        const line =
          serialized.length > 256000
            ? JSON.stringify({
                sequence: event.sequence,
                timestamp: event.timestamp,
                runId: event.runId,
                type: event.type,
                truncated: true,
              }) + '\n'
            : serialized + '\n';
        await journalWrite(line);
      };
      this.recordManual = record;
      await record({ type: 'run_start', task, followUp });
      if (unopened !== undefined) await stopJournal(unopened);
      if (this.config.recording && !signal.aborted) {
        recorder = new Recorder(
          join(this.workspace, '.browser-use', 'recordings', this.runId),
          redact(task, this.config.redact ?? []),
          typeof this.config.recording === 'object' ? this.config.recording : {},
        );
        try {
          const targetId = await this.runtime.initialize(signal);
          await recorder.start(
            this.runtime.endpoint,
            targetId,
            this.config.browser?.kind === 'chrome' && !!this.config.browser.approveConnection,
            this.runtime.cdpOptions,
          );
          this.runtime.onAction = (action) => recorder?.action(action);
        } catch (error) {
          await record({ type: 'warning', message: `Recording unavailable: ${String(error)}` });
        }
      }
      const result = await runAgent(
        this.runtime,
        this.model!,
        { ...this.config, onCounter: (counter) => this.operation?.count(counter) },
        this.workspace,
        task,
        options.schema ?? Type.String(),
        {
          ...options,
          signal,
          onEvent: async (event, eventSignal) => {
            if (event.type === 'tool_execution_start') this.operation?.count('tool_calls');
            if (event.type === 'tool_execution_end' && event.isError)
              this.operation?.count('tool_errors');
            await record({ type: 'agent_event', event });
            await options.onEvent?.(event, eventSignal);
          },
        },
        {
          messages: this.messages,
          control,
          ...(journaled ? { eventsPath } : {}),
          checkpoint: async (messages, usage) => {
            recoveryCheckpoint = true;
            this.messages = messages;
            this.hasConversation = true;
            const history = this.history;
            for (const key of [
              'input',
              'output',
              'cacheRead',
              'cacheWrite',
              'totalTokens',
            ] as const)
              history.usage[key] += usage[key];
            for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'total'] as const)
              history.usage.cost[key] += usage.cost[key];
            await saveHistory(
              join(this.workspace, '.browser-use', 'session.json'),
              history,
              this.config.redact,
            );
          },
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
        this.totalUsage.cost[key] += result.usage.cost?.[key] ?? 0;
      this.runtime.onAction = undefined;
      const warnings: string[] = [
        ...(result.warnings ?? []),
        ...(journalFailure ? [journalFailure] : []),
      ];
      let recordingPath: string | undefined;
      if (recorder) {
        try {
          recordingPath = await recorder.stop(result.status, this.runtime.currentTarget);
          this.operation?.count('recordings_saved');
        } catch (error) {
          warnings.push(`Recording could not be saved: ${String(error)}`);
        }
      }
      recorder = undefined;
      const delivered: RunResult<unknown> = {
        ...result,
        pricingKnown: !!this.config.pricingKnown,
        estimatedCostUsd: this.config.pricingKnown ? (result.usage.cost?.total ?? null) : null,
        usage: { ...result.usage, cost: this.config.pricingKnown ? result.usage.cost : null },
        ...(result.summaryUsage
          ? {
              summaryUsage: {
                ...result.summaryUsage,
                cost: this.config.pricingKnown ? result.summaryUsage.cost : null,
              },
            }
          : {}),
        ...(recordingPath ? { recordingPath } : {}),
        runId: this.runId,
        ...(journaled ? { eventsPath } : {}),
      };
      if (recoveryCheckpoint) {
        try {
          await saveHistory(
            join(this.workspace, '.browser-use', 'session.json'),
            this.history,
            this.config.redact,
          );
        } catch (error) {
          warnings.push(`Recovery checkpoint could not be finalized: ${String(error)}`);
        }
      }
      try {
        await saveHistory(historyPath, this.history, this.config.redact);
        delivered.historyPath = historyPath;
        this.operation?.count('history_saved');
      } catch (error) {
        warnings.push(`History could not be saved: ${String(error)}`);
      }
      if (warnings.length) delivered.warnings = warnings;
      await record({ type: 'run_end', result: delivered });
      if (journalFailure && !delivered.warnings?.includes(journalFailure))
        delivered.warnings = [...(delivered.warnings ?? []), journalFailure];
      this.operation?.finish({
        result: delivered,
        ...(result.summaryUsage ? { summaryUsage: result.summaryUsage as Usage } : {}),
        ...(result.modelDurationMs !== undefined
          ? { modelDurationMs: result.modelDurationMs }
          : {}),
        ...(result.toolDurationMs !== undefined ? { toolDurationMs: result.toolDurationMs } : {}),
        pausedDurationMs:
          this.pausedDurationMs + (this.pausedAt ? performance.now() - this.pausedAt : 0),
        usageCompleteness: 'partial',
      });
      return redact(delivered, this.config.redact ?? []);
    } finally {
      this.runtime.onAction = undefined;
      await this.manualCell?.catch(() => {});
      if (recorder) await recorder.stop('error', this.runtime.currentTarget).catch(() => {});
      await journalQueue.catch(() => {});
      await journal?.close().catch(() => {});
      this.recordManual = undefined;
      control.finish();
      this.active = false;
      this.controller = undefined;
      this.control = undefined;
      this.operation?.finish({ status: 'error', errorClass: 'unknown' });
      this.operation = undefined;
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
  events(accept?: (event: SessionEvent) => boolean): EventStream {
    if (this.closed) throw new Error('BrowserUse is closed.');
    const stream = new EventStream(() => this.streams.delete(stream), 256, accept);
    this.streams.add(stream);
    return stream;
  }
  get history(): SessionHistory {
    return redact(
      {
        version: 1,
        model: this.config.model ?? '',
        messages: this.messages,
        usage: this.totalUsage,
        runs: this.runs,
      },
      this.config.redact ?? [],
    );
  }
  get usage(): RunResult['usage'] {
    return {
      ...structuredClone(this.totalUsage),
      cost: this.config.pricingKnown ? structuredClone(this.totalUsage.cost) : null,
    };
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
    this.operation?.count('pause_requests');
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
    this.operation?.count('steering_accepted');
  }
  cancel() {
    this.controller?.abort();
    this.control?.resume();
  }
  async cancelAndWait() {
    this.cancel();
    if (this.active) await this.activeRun?.catch(() => {});
    await this.manualCell?.catch(() => {});
  }
  execute(code: string, options: { timeoutMs?: number; signal?: AbortSignal } = {}) {
    return this.executeManual(code, false, options) as Promise<import('./protocol.js').CellResult>;
  }

  executeJson(expression: string, options: { timeoutMs?: number; signal?: AbortSignal } = {}) {
    return this.executeManual(expression, true, options);
  }

  private async executeManual(
    code: string,
    captureJson: boolean,
    options: {
      timeoutMs?: number;
      signal?: AbortSignal;
    } = {},
  ) {
    const duringPause = this.isPaused;
    if (!duringPause) this.assertIdle();
    if (this.closed) throw new Error('BrowserUse is closed.');
    if (duringPause && this.manualCell)
      throw new Error('A manual browser cell is already running.');
    if (!duringPause) {
      this.active = true;
      this.controller = new AbortController();
    }
    const executionId = randomUUID();
    const record = async (data: SessionEventData) => {
      if (this.recordManual) return this.recordManual(data);
      const event = this.emit(data);
      const directory = join(this.workspace, '.browser-use');
      await mkdir(directory, { recursive: true, mode: 0o700 });
      await appendFile(join(directory, 'manual.jsonl'), JSON.stringify(event) + '\n', {
        mode: 0o600,
      });
    };
    try {
      await record({ type: 'manual_execution', executionId, phase: 'start', code }).catch(
        (error) => {
          this.emit({ type: 'warning', message: `Manual journal failed: ${String(error)}` });
        },
      );
      const signal = this.controller
        ? options.signal
          ? AbortSignal.any([options.signal, this.controller.signal])
          : this.controller.signal
        : options.signal;
      const timeout = options.timeoutMs ?? this.config.cellTimeoutMs ?? 30000;
      const cell = captureJson
        ? this.runtime.readResult(code, timeout, signal)
        : this.runtime.execute(code, timeout, signal);
      this.manualCell = cell;
      const result = await cell;
      await record({ type: 'manual_execution', executionId, phase: 'end' }).catch((error) => {
        this.emit({ type: 'warning', message: `Manual journal failed: ${String(error)}` });
      });
      return result;
    } catch (error) {
      await record({
        type: 'manual_execution',
        executionId,
        phase: 'error',
        error: String(error),
      }).catch(() => {});
      throw error;
    } finally {
      this.manualCell = undefined;
      if (!duringPause) {
        this.active = false;
        this.controller = undefined;
      }
    }
  }
  private assertIdle() {
    if (this.closed) throw new Error('BrowserUse is closed. Create a new session.');
    if (this.active)
      throw new Error(
        'This session is busy. Await the active operation or create a separate session.',
      );
  }
  connectBrowser(
    cdpUrl: string,
    options: {
      targetId?: string;
      cdpOptions?: import('./browser.js').CdpConnectionOptions;
    } = {},
  ) {
    if (this.config.browser?.kind !== 'pending')
      throw new Error('connectBrowser() needs a session created with Browser.pending().');
    if (options.targetId !== undefined && typeof options.targetId !== 'string')
      throw new Error('targetId must be a string.');
    this.runtime.connect(validCdpUrl(cdpUrl), options.targetId, options.cdpOptions);
  }
  get currentTarget(): string | undefined {
    return this.runtime.currentTarget;
  }
  close(
    options: {
      keepTabs?: boolean | 'current';
    } = {},
  ): Promise<void> {
    if (this.closing) return this.closing;
    this.closed = true;
    this.cancel();
    this.closing = (async () => {
      let failure: unknown;
      try {
        await this.activeRun?.catch(() => {});
        await this.runtime.close(options);
      } catch (error) {
        failure = error;
      }
      try {
        await this.browser.close();
      } catch (error) {
        failure = failure ? new AggregateError([failure, error], 'Browser cleanup failed.') : error;
      } finally {
        this.sessionOperation.finish(
          failure
            ? { status: 'error', stage: 'cleanup', errorClass: 'cleanup' }
            : { status: 'closed' },
        );
        await this.telemetry.flush();
        for (const stream of [...this.streams]) stream.end();
      }
      if (failure) throw failure;
    })().catch((error) => {
      this.closing = undefined;
      throw error;
    });
    return this.closing;
  }
  async [Symbol.asyncDispose]() {
    await this.close();
  }
}
export { CDP } from './cdp.js';
export { Page, Tabs, type AXNode } from './page.js';
export type { SessionHistory, WorkspaceFile } from './history.js';
export type { SessionEvent } from './events.js';
export { formatEvent } from './events.js';
export { exportRecording, type VideoOptions } from './video.js';
export type { RecordingOptions } from './recording.js';
export type { DomainOptions, SensitiveData } from './policy.js';
