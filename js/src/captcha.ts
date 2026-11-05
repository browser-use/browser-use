import type { CDP } from './cdp.js';

interface Solve {
  vendor?: string;
  url?: string;
  startedAt: number;
}
interface Finish {
  success: boolean;
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

const where = ({ vendor, url }: { vendor?: string; url?: string }) =>
  `${vendor ? ` (${vendor})` : ''}${url ? ` on ${url.slice(0, 200)}` : ''}`;

/**
 * Browser Use Cloud's captcha solver, through the BrowserUse CDP domain the cloud browser adds.
 * Its events are not replayed, so one watch follows them for the whole connection.
 * Other CDP endpoints reject the methods, which reads as "solver unavailable".
 */
export class CaptchaWatch {
  /** Solves started without a finished event, by target. */
  private active = new Map<string, Solve>();
  /** The latest finish the agent has not seen yet, in cell output or a solve() result. */
  private fresh: Finish | undefined;
  private unreported: string[] = [];
  private wake = new Set<() => void>();
  /** solveCaptcha() turned the solver on; it goes back off once nothing is being solved. */
  private switchedOn = false;

  constructor(private cdp: CDP) {
    const previous = cdp.observeEvent;
    cdp.observeEvent = (method, raw, session) => {
      previous?.(method, raw, session);
      if (method.startsWith('BrowserUse.captchaSolver')) this.event(method, raw);
    };
  }

  private event(method: string, raw: unknown) {
    const event = (raw ?? {}) as Partial<Solve & Finish & { targetId: string }>;
    const solve = {
      ...(typeof event.vendor === 'string' && event.vendor ? { vendor: event.vendor } : {}),
      ...(typeof event.url === 'string' && event.url ? { url: event.url } : {}),
    };
    const key = String(event.targetId ?? '');
    if (method === 'BrowserUse.captchaSolverStarted')
      this.active.set(key, { ...solve, startedAt: Date.now() });
    else if (method === 'BrowserUse.captchaSolverFinished') {
      this.active.delete(key);
      this.fresh = { success: event.success === true, ...solve };
      this.unreported.push(
        `[Captcha solver finished: ${this.fresh.success ? 'solved' : 'not solved'}${where(solve)}.]`,
      );
      if (this.switchedOn && !this.active.size) void this.switchOff();
    } else return;
    for (const wake of [...this.wake]) wake();
  }

  /** Lines for the cell output: every cell while a solve runs, a finished solve once. */
  note() {
    this.fresh = undefined;
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
  private async switchOff() {
    this.switchedOn = false;
    await this.send('BrowserUse.setCaptchaSolverEnabled', { enabled: false }).catch(() => {});
  }

  /** Wait for a solve to start (startMs) and finish (timeoutMs overall). Never throws for a missing solver. */
  async solve({
    timeoutMs,
    startMs = 20_000,
    signal,
  }: {
    timeoutMs: number;
    startMs?: number;
    signal?: AbortSignal;
  }): Promise<CaptchaResult> {
    const began = Date.now();
    const done = (result: Omit<CaptchaResult, 'seconds'>): CaptchaResult => ({
      ...result,
      seconds: Math.round((Date.now() - began) / 100) / 10,
    });
    signal?.throwIfAborted();
    if (!this.active.size && !this.fresh) {
      try {
        const state = (await this.send('BrowserUse.getCaptchaSolverEnabled')) as {
          enabled?: unknown;
        };
        if (state?.enabled !== true) {
          await this.send('BrowserUse.setCaptchaSolverEnabled', { enabled: true });
          this.switchedOn = true;
        }
      } catch (error) {
        signal?.throwIfAborted();
        const message = error instanceof Error ? error.message : String(error);
        return done({ solved: false, detail: `solver unavailable: ${message.slice(0, 300)}` });
      }
    }
    try {
      for (;;) {
        signal?.throwIfAborted();
        // Also a solve that finished earlier in this cell, e.g. during the navigation.
        if (this.fresh && !this.active.size) {
          const { success, ...rest } = this.fresh;
          this.fresh = undefined;
          return done({
            solved: success,
            detail: success ? 'solved' : 'the solver failed',
            ...rest,
          });
        }
        const solving = [...this.active.values()].at(-1);
        const { vendor, url } = solving ?? {};
        const limit = began + (solving ? timeoutMs : Math.min(startMs, timeoutMs));
        if (Date.now() >= limit) {
          if (solving)
            return done({
              solved: false,
              detail: 'still solving',
              ...(vendor ? { vendor } : {}),
              ...(url ? { url } : {}),
              next: 'call solveCaptcha() again',
            });
          if (this.switchedOn) await this.switchOff();
          return done({ solved: false, detail: 'the solver found no captcha on the page' });
        }
        await this.changed(limit - Date.now(), signal);
      }
    } catch (error) {
      if (this.switchedOn && !this.active.size) await this.switchOff();
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
