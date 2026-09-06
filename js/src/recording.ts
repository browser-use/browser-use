import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { CDP } from './cdp.js';
import { Page } from './page.js';
import type { BrowserAction } from './protocol.js';

export interface RecordingOptions {
  intervalMs?: number;
  maxFrames?: number;
}
export interface RecordedFrame {
  file: string;
  timestamp: number;
  label: string;
  cursor?: { x: number; y: number; click: boolean };
}
export interface RecordingManifest {
  version: 1;
  task: string;
  frames: RecordedFrame[];
  status: string;
  warnings: string[];
  capped: boolean;
}

/** Opt-in sampling through a second CDP connection. Never reexecutes browser actions. */
export class Recorder {
  private connection: CDP | undefined;
  private page: Page | undefined;
  private timer: ReturnType<typeof setInterval> | undefined;
  private pending: Promise<void> | undefined;
  private actionWaiting = false;
  private targetId: string | undefined;
  private label = 'Browser';
  private cursor: RecordedFrame['cursor'];
  readonly manifest: RecordingManifest;
  constructor(
    readonly directory: string,
    task: string,
    private readonly options: RecordingOptions = {},
  ) {
    this.manifest = {
      version: 1,
      task,
      frames: [],
      status: 'running',
      warnings: [],
      capped: false,
    };
  }
  async start(endpoint: string, targetId: string) {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    this.connection = await CDP.connect(endpoint, 3000);
    this.targetId = targetId;
    await this.capture();
    this.timer = setInterval(() => {
      void this.capture();
    }, this.options.intervalMs ?? 750);
  }
  action(event: BrowserAction) {
    this.targetId = event.targetId;
    this.label = event.kind;
    if (event.x !== undefined && event.y !== undefined)
      this.cursor = { x: event.x, y: event.y, click: event.kind === 'Click' };
    else this.cursor = undefined;
    if (this.pending) this.actionWaiting = true;
    else void this.capture();
  }
  setTarget(targetId: string) {
    this.targetId = targetId;
  }
  capture(): Promise<void> {
    if (this.pending) return this.pending;
    if (this.manifest.frames.length >= (this.options.maxFrames ?? 400)) {
      this.manifest.capped = true;
      return Promise.resolve();
    }
    this.pending = this.takeFrame()
      .catch((e: unknown) => {
        if (this.manifest.warnings.length < 10)
          this.manifest.warnings.push(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        this.pending = undefined;
        if (this.actionWaiting) {
          this.actionWaiting = false;
          void this.capture();
        }
      });
    return this.pending;
  }
  private async takeFrame() {
    if (!this.connection || !this.targetId) return;
    if (this.page?.targetId !== this.targetId) {
      if (this.page)
        await this.connection
          .send('Target.detachFromTarget', { sessionId: this.page.sessionId })
          .catch(() => {});
      this.page = await Page.attach(this.connection, this.targetId);
    }
    const file = `${String(this.manifest.frames.length).padStart(5, '0')}.jpg`;
    const frame: RecordedFrame = {
      file,
      timestamp: Date.now(),
      label: this.label,
      ...(this.cursor ? { cursor: { ...this.cursor } } : {}),
    };
    await writeFile(join(this.directory, file), await this.page.screenshot({ quality: 75 }), {
      flag: 'wx',
      mode: 0o600,
    });
    this.manifest.frames.push(frame);
  }
  async stop(status: string, targetId?: string): Promise<string> {
    clearInterval(this.timer);
    while (this.pending) await this.pending;
    if (targetId) this.targetId = targetId;
    this.label = status;
    this.cursor = undefined;
    // Reserve a final frame even when sampling reached its cap.
    try {
      await this.takeFrame();
    } catch (error) {
      this.manifest.warnings.push(String(error));
    }
    this.connection?.close();
    this.manifest.status = status;
    const path = join(this.directory, 'recording.json');
    await writeFile(path, JSON.stringify(this.manifest, null, 2), { mode: 0o600 });
    return path;
  }
}
