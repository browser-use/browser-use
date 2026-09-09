import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { promisify } from 'node:util';
import { CDP } from './cdp.js';
import { execFile, fork, type ChildProcess } from 'node:child_process';
import type { BrowserAction, CellResult, WorkerConfig, WorkerResponse } from './protocol.js';
import { positiveInteger } from './protocol.js';

/** Bun hosts use the same V8 worker as Node hosts, including its cancellation boundary. */
export async function workerExecutable(): Promise<string> {
  if (!process.versions.bun && !process.env.BROWSER_USE_NODE) return process.execPath;
  try {
    const { stdout } = await promisify(execFile)(
      process.env.BROWSER_USE_NODE || 'node',
      [
        '-p',
        'JSON.stringify({path:process.execPath,node:process.versions.node,bun:!!process.versions.bun})',
      ],
      { env: { PATH: process.env.PATH ?? '' }, timeout: 5_000 },
    );
    const runtime = JSON.parse(stdout);
    const [major, minor] = runtime.node.split('.').map(Number);
    if (!runtime.bun && isAbsolute(runtime.path) && (major > 22 || (major === 22 && minor >= 19)))
      return runtime.path;
  } catch {
    // Do not expose subprocess output or inherit provider keys and preload flags.
  }
  throw new Error(
    'Browser Use JS needs Node.js 22.19+ for its JavaScript worker, including when your app runs in Bun. Install Node on PATH or set BROWSER_USE_NODE to its absolute executable path.',
  );
}

export class CellError extends Error {
  constructor(
    message: string,
    readonly result: CellResult,
    readonly stateReset: boolean,
  ) {
    super(message);
    this.name = 'CellError';
  }
}

/** One worker, one active cell. Termination is the cancellation boundary. */
export class BrowserRuntime {
  onAction: ((event: BrowserAction) => void) | undefined;
  private runId: string | undefined;
  partial: { path: string; value: unknown } | undefined;
  beginRun() {
    this.runId = randomUUID();
    this.partial = undefined;
  }
  get currentTarget() {
    return this.targetId;
  }
  async initialize(signal?: AbortSignal) {
    await this.execute('await page.info()', 4 * this.config.operationTimeoutMs, signal);
    return this.targetId!;
  }
  private worker: ChildProcess | undefined;
  private owned = new Set<string>();
  private targetId: string | undefined;
  private busy = false;
  private workerLoss: Error | undefined;
  private closed = false;
  private settled: Promise<void> = Promise.resolve();
  private release: (() => void) | undefined;
  private pending: ((error: Error) => void) | undefined;

  constructor(
    private readonly config: WorkerConfig,
    private readonly executable?: string,
  ) {}

  private async start(signal?: AbortSignal): Promise<ChildProcess> {
    if (this.worker) return this.worker;
    const execPath = this.executable ?? (await workerExecutable());
    const worker = fork(new URL('./worker.js', import.meta.url), [], {
      execPath,
      execArgv: ['--max-old-space-size=256'], // Never inherit host loaders/preloads/inspectors.
      env: {}, // Provider keys stay in the agent process; this is not an OS sandbox.
      stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
      serialization: 'json', // Node and Bun use different advanced IPC formats.
    });
    this.worker = worker;
    worker.on('message', (message: WorkerResponse) => {
      if (message.type === 'partial' && this.runId && message.runId === this.runId)
        this.partial = { path: message.path, value: JSON.parse(message.valueJson) };
      if (message.type === 'action') this.onAction?.(message.action);
      if (message.type === 'owned') this.owned.add(message.targetId);
    });
    worker.on('error', (error) => this.pending?.(error));
    worker.on('exit', (code, signal) => {
      if (this.worker !== worker) return;
      this.worker = undefined;
      const error = new Error(
        `Browser worker exited (${signal ?? code}). JavaScript state was reset; check browser state before retrying an action.`,
      );
      if (this.pending) this.pending(error);
      else this.workerLoss = error;
    });
    try {
      const response = this.receive(worker, 20_000, signal);
      worker.send(
        { ...this.config, ...(this.targetId ? { targetId: this.targetId } : {}) },
        (error) => {
          if (error) this.pending?.(error);
        },
      );
      const ready = await response;
      if (ready.type !== 'ready') throw new Error('Browser worker did not initialize.');
      this.targetId = ready.targetId;
      return worker;
    } catch (error) {
      await this.terminate();
      throw error;
    }
  }

  private receive(
    worker: ChildProcess,
    timeoutMs: number,
    signal?: AbortSignal,
  ): Promise<WorkerResponse> {
    return new Promise((resolve, reject) => {
      const finish = (value: WorkerResponse | Error) => {
        clearTimeout(timer);
        signal?.removeEventListener('abort', abort);
        worker.off('message', message);
        this.pending = undefined;
        if (value instanceof Error) reject(value);
        else resolve(value);
      };
      const message = (value: WorkerResponse) => {
        if (value.type !== 'owned' && value.type !== 'action' && value.type !== 'partial')
          finish(value);
      };
      const abort = () =>
        finish(
          new Error(
            'Execution cancelled. JavaScript state was reset; browser actions may already have happened.',
          ),
        );
      const timer = setTimeout(
        () =>
          finish(
            new Error(
              `Cell exceeded ${timeoutMs} ms. JavaScript state was reset; inspect the page before retrying actions.`,
            ),
          ),
        timeoutMs,
      );
      this.pending = (error) => finish(error);
      worker.on('message', message);
      signal?.addEventListener('abort', abort, { once: true });
      if (signal?.aborted) abort();
    });
  }

  async readResult(expression: string, timeoutMs = 30_000, signal?: AbortSignal): Promise<unknown> {
    const result = await this.executeCell(expression, timeoutMs, signal, true);
    if (result.valueJson === undefined) throw new Error('Worker returned no result value.');
    return JSON.parse(result.valueJson);
  }

  execute(code: string, timeoutMs = 30_000, signal?: AbortSignal): Promise<CellResult> {
    return this.executeCell(code, timeoutMs, signal, false);
  }

  private async executeCell(
    code: string,
    timeoutMs: number,
    signal: AbortSignal | undefined,
    captureJson: boolean,
  ): Promise<CellResult> {
    positiveInteger('timeoutMs', timeoutMs);
    if (this.closed) throw new Error('BrowserUse is closed.');
    if (this.busy)
      throw new Error('A browser cell is already running. Await it before starting another.');
    if (signal?.aborted) throw new Error('Execution cancelled.');
    if (!code.trim()) throw new Error('Provide JavaScript code to execute.');
    if (this.workerLoss) {
      const error = this.workerLoss;
      this.workerLoss = undefined;
      // No new cell ran. Expose the same reset contract as a crash during execution.
      throw new CellError(error.message, { text: '', images: [] }, true);
    }
    this.busy = true;
    this.settled = new Promise((resolve) => {
      this.release = resolve;
    });
    try {
      const worker = await this.start(signal);
      if (signal?.aborted) throw new Error('Execution cancelled.');
      const directory = join(this.config.workspace, '.browser-use', 'cells');
      await mkdir(directory, { recursive: true, mode: 0o700 });
      const outputFile = join(directory, `${randomUUID()}.txt`);
      await writeFile(outputFile, '', { flag: 'wx', mode: 0o600 });
      const response = this.receive(worker, timeoutMs, signal);
      worker.send(
        { type: 'execute', code, captureJson, outputFile, runId: this.runId },
        (error) => {
          if (error) this.pending?.(error);
        },
      );
      let message: WorkerResponse;
      try {
        message = await response;
      } catch (error) {
        await this.terminate();
        const text = (await readFile(outputFile, 'utf8')).slice(0, this.config.maxOutputChars);
        throw new CellError(
          String(error instanceof Error ? error.message : error),
          { text, images: [], outputFile },
          true,
        );
      }
      if ((message.type === 'result' || message.type === 'error') && message.result?.targetId)
        this.targetId = message.result.targetId;
      if (message.type === 'error')
        throw new CellError(message.message, message.result ?? { text: '', images: [] }, false);
      if (message.type !== 'result') throw new Error('Unexpected browser worker response.');
      return message.result;
    } finally {
      this.busy = false;
      this.release?.();
      this.release = undefined;
    }
  }

  private async terminate() {
    const worker = this.worker;
    this.worker = undefined;
    if (worker && worker.exitCode === null && worker.signalCode === null) {
      const exited = new Promise<void>((resolve) => worker.once('exit', () => resolve()));
      worker.kill('SIGKILL');
      await exited;
    }
  }

  async close() {
    if (this.closed) return;
    this.closed = true;
    if (this.busy) {
      this.pending?.(new Error('BrowserUse closed during execution.'));
      await this.terminate();
      await this.settled;
    }
    if (this.worker) {
      const response = this.receive(this.worker, 2_000);
      this.worker.send({ type: 'close' }, (error) => {
        if (error) this.pending?.(error);
      });
      await response.catch(() => {});
    }
    await this.terminate();
    if (this.owned.size) {
      const cdp = await CDP.connect(
        this.config.endpoint,
        this.config.operationTimeoutMs,
        this.config.approveConnection,
      );
      try {
        const { targetInfos } = await cdp.send('Target.getTargets');
        // Include popups recursively, but never a pre-existing caller tab.
        let previous = -1;
        while (previous !== this.owned.size) {
          previous = this.owned.size;
          for (const target of targetInfos)
            if (target.openerId && this.owned.has(target.openerId)) this.owned.add(target.targetId);
        }
        for (const targetId of this.owned) {
          if (targetInfos.some((t) => t.targetId === targetId))
            await cdp.send('Target.closeTarget', { targetId });
        }
        // closeTarget acknowledges the request before Chrome necessarily removes the tab.
        // Verify only; never replay closure or touch a caller-owned target.
        const deadline = Date.now() + this.config.operationTimeoutMs;
        for (;;) {
          const { targetInfos: current } = await cdp.send('Target.getTargets');
          const remaining = current.filter((target) => this.owned.has(target.targetId));
          if (!remaining.length) break;
          if (Date.now() >= deadline)
            throw new Error(
              `SDK-owned tabs remain after cleanup deadline: ${remaining.map((target) => target.targetId).join(', ')}`,
            );
          await new Promise((resolve) =>
            setTimeout(resolve, Math.min(50, Math.max(0, deadline - Date.now()))),
          );
        }
      } finally {
        cdp.close();
      }
    }
  }
}
