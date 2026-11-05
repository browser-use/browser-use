import type { CDP } from './cdp.js';

interface Solve {
  vendor?: string;
  url?: string;
  startedAt: number;
}
interface Finish {
  success: boolean;
  /** No finished event came within lostAfterMs, e.g. the connection dropped mid-solve. */
  lost?: boolean;
  vendor?: string;
  url?: string;
}
export interface CaptchaResult {
  solved: boolean;
  detail: string;
  seconds: number;
  vendor?: string;
  url?: string;
  next?: string;
}

/** The solver gives up after at most 120 s; a solve still open well past that has no finish coming. */
const lostAfterMs = 150_000;

const where = ({ vendor, url }: { vendor?: string; url?: string }) =>
  `${vendor ? ` (${vendor})` : ''}${url ? ` on ${url.slice(0, 200)}` : ''}`;

/** Reject after ms; the command itself may still run. */
const within = <T>(promise: Promise<T>, ms: number) =>
  new Promise<T>((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`no answer within ${Math.max(0, Math.round(ms))} ms`)),
      Math.max(0, ms),
    );
    promise.then(resolve, reject).finally(() => clearTimeout(timer));
  });

/**
 * Browser Use Cloud's captcha solver, through the BrowserUse CDP domain the cloud browser adds.
 * Its events are not replayed, so one watch follows them for the whole connection.
 * Other CDP endpoints reject the methods, which reads as "solver unavailable".
 */
export class CaptchaWatch {
  /** Solves started without a finished event, by target. */
  private active = new Map<string, Solve>();
  /** Finishes the agent has not seen yet, in cell output or a solve() result, by target. */
  private finished = new Map<string, Finish>();
  private unreported: string[] = [];
  private wake = new Set<() => void>();
  /** solveCaptcha() turned the solver on and owns turning it back off. Set before the command goes out. */
  private switchedOn = false;
  /** Toggles run one after another, so a pending switch-off cannot land under the next call. */
  private toggling: Promise<unknown> = Promise.resolve();
  /** Concurrent callers share one wait instead of taking each other's result. */
  private running: Promise<CaptchaResult> | undefined;

  constructor(private cdp: CDP) {
    const previous = cdp.observeEvent;
    cdp.observeEvent = (method, raw, session) => {
      previous?.(method, raw, session);
      if (method.startsWith('BrowserUse.captchaSolver')) this.event(method, raw);
    };
  }

  private event(method: string, raw: unknown) {
    const event = (raw ?? {}) as Partial<Solve & Finish & { targetId: string; enabled: boolean }>;
    const solve = {
      ...(typeof event.vendor === 'string' && event.vendor ? { vendor: event.vendor } : {}),
      ...(typeof event.url === 'string' && event.url ? { url: event.url } : {}),
    };
    const key = String(event.targetId ?? '');
    if (method === 'BrowserUse.captchaSolverStarted') {
      this.finished.delete(key);
      this.active.set(key, { ...solve, startedAt: Date.now() });
    } else if (method === 'BrowserUse.captchaSolverFinished') {
      this.active.delete(key);
      this.finish(key, { success: event.success === true, ...solve });
    } else if (method === 'BrowserUse.captchaSolverStateChanged') {
      // Someone switched it off: nothing left to restore, and a later switch-on is theirs.
      if (event.enabled === false) this.switchedOn = false;
      return;
    } else return;
    for (const wake of [...this.wake]) wake();
  }

  private finish(key: string, finish: Finish) {
    this.finished.delete(key);
    this.finished.set(key, finish);
    const outcome = finish.lost
      ? `no result after ${lostAfterMs / 1000} s`
      : finish.success
        ? 'solved'
        : 'not solved';
    this.unreported.push(`[Captcha solver finished: ${outcome}${where(finish)}.]`);
    if (this.switchedOn && !this.active.size) void this.switchOff();
  }

  /** Close solves whose finished event will not come. */
  private prune() {
    for (const [key, solve] of this.active)
      if (Date.now() - solve.startedAt > lostAfterMs) {
        this.active.delete(key);
        const { startedAt: _, ...rest } = solve;
        this.finish(key, { success: false, lost: true, ...rest });
      }
  }

  /** Lines for the cell output: every cell while a solve runs, a finished solve once. */
  note() {
    this.prune();
    this.finished.clear();
    const lines = this.unreported.splice(0);
    for (const solve of this.active.values())
      lines.push(
        `[Captcha solver running${where(solve)} for ${Math.round((Date.now() - solve.startedAt) / 1000)} s. Wait with await solveCaptcha(); do not reload, navigate or switch browsers.]`,
      );
    return lines.join('\n');
  }

  private send(method: string, params: object = {}) {
    // The BrowserUse domain is not in Chrome's protocol types.
    return (this.cdp.send as (method: string, params: object) => Promise<unknown>)(method, params);
  }
  private toggle(enabled: boolean) {
    const sent = this.toggling.then(() =>
      this.send('BrowserUse.setCaptchaSolverEnabled', { enabled }),
    );
    this.toggling = sent.catch(() => {});
    return sent;
  }
  private switchOff() {
    this.switchedOn = false;
    return this.toggle(false).catch(() => {});
  }

  /** Wait for a solve to start (startMs) and finish (timeoutMs overall). Never throws for a missing solver. */
  solve(options: { timeoutMs: number; startMs?: number; signal?: AbortSignal }) {
    this.running ??= this.wait(options).finally(() => {
      this.running = undefined;
    });
    return this.running;
  }

  private async wait({
    timeoutMs,
    startMs = 20_000,
    signal,
  }: {
    timeoutMs: number;
    startMs?: number;
    signal?: AbortSignal;
  }): Promise<CaptchaResult> {
    const began = Date.now();
    const deadline = began + timeoutMs;
    const done = (result: Omit<CaptchaResult, 'seconds'>): CaptchaResult => ({
      ...result,
      seconds: Math.round((Date.now() - began) / 100) / 10,
    });
    // Also waits for a switch-off a finished event already sent. Bounded, so it returns inside the cell.
    const release = async () => {
      if (this.switchedOn && !this.active.size) void this.switchOff();
      await within(this.toggling, Math.min(1000, deadline - Date.now())).catch(() => {});
    };
    signal?.throwIfAborted();
    this.prune();
    if (!this.active.size && !this.finished.size) {
      try {
        await within(this.toggling, deadline - Date.now());
        const state = (await within(
          this.send('BrowserUse.getCaptchaSolverEnabled'),
          deadline - Date.now(),
        )) as { enabled?: unknown };
        if (state?.enabled !== true) {
          this.switchedOn = true;
          await within(this.toggle(true), deadline - Date.now());
        }
      } catch (error) {
        signal?.throwIfAborted();
        const message = error instanceof Error ? error.message : String(error);
        // An enable that never answered may still land: try to undo it.
        void release();
        return done({ solved: false, detail: `solver unavailable: ${message.slice(0, 300)}` });
      }
    }
    try {
      for (;;) {
        signal?.throwIfAborted();
        this.prune();
        // Also a solve that finished earlier in this cell, e.g. during the navigation.
        if (this.finished.size && !this.active.size) {
          const finishes = [...this.finished.values()];
          this.finished.clear();
          // Several pages: report the failure, not whichever page finished last.
          const failed = finishes.find(({ success }) => !success);
          const { success: _, lost, ...rest } = failed ?? finishes.at(-1)!;
          await release();
          return done({
            solved: !failed,
            detail: !failed
              ? 'solved'
              : lost
                ? `no result from the solver after ${lostAfterMs / 1000} s`
                : 'the solver failed',
            ...rest,
          });
        }
        const solving = [...this.active.values()].at(-1);
        const { vendor, url } = solving ?? {};
        const limit = solving ? deadline : Math.min(began + startMs, deadline);
        if (Date.now() >= limit) {
          if (solving)
            return done({
              solved: false,
              detail: 'still solving',
              ...(vendor ? { vendor } : {}),
              ...(url ? { url } : {}),
              next: 'call solveCaptcha() again',
            });
          await release();
          return done({
            solved: false,
            detail: `no captcha solve started within ${Math.round((limit - began) / 1000)} s`,
          });
        }
        await this.changed(limit - Date.now(), signal);
      }
    } catch (error) {
      await release();
      throw error;
    }
  }

  private changed(ms: number, signal?: AbortSignal) {
    return new Promise<void>((resolve, reject) => {
      const settle = (error?: Error) => {
        clearTimeout(timer);
        this.wake.delete(wake);
        signal?.removeEventListener('abort', abort);
        if (error) reject(error);
        else resolve();
      };
      const wake = () => settle();
      const abort = () => settle(new Error('solveCaptcha() cancelled.'));
      const timer = setTimeout(wake, ms);
      this.wake.add(wake);
      signal?.addEventListener('abort', abort, { once: true });
    });
  }
}
