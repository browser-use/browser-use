import type { AgentEvent } from '@earendil-works/pi-agent-core';
import { bounded } from './control.js';

/** One active observation and one latest pending event. Never queues unbounded work. */
export class Observer {
  private pending: AgentEvent | undefined;
  private running: Promise<void> | undefined;
  private controller = new AbortController();
  private closed = false;
  private dropped = 0;
  readonly warnings: string[] = [];
  constructor(
    private callback: (event: AgentEvent, signal: AbortSignal) => void | Promise<void>,
    private timeoutMs: number,
  ) {}
  push(event: AgentEvent) {
    if (this.closed) return;
    if (this.pending) this.dropped++;
    this.pending = event;
    if (!this.running)
      this.running = this.drain().finally(() => {
        this.running = undefined;
      });
  }
  private async drain() {
    while (this.pending && !this.closed) {
      const event = this.pending;
      this.pending = undefined;
      const controller = new AbortController();
      const signal = AbortSignal.any([controller.signal, this.controller.signal]);
      try {
        await bounded(() => this.callback(event, signal), this.timeoutMs, signal);
      } catch (error) {
        if (this.warnings.length < 5) this.warnings.push(`Observer failed: ${String(error)}`);
      } finally {
        controller.abort();
      }
    }
  }
  async close(abort = false) {
    this.closed = true;
    this.pending = undefined;
    if (abort) this.controller.abort();
    await this.running;
    this.controller.abort();
    if (this.dropped)
      this.warnings.push(
        `Observer coalesced ${this.dropped} events. Use onEvent for lossless backpressure.`,
      );
  }
}
