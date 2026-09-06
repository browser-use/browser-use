import type { AgentEvent } from '@earendil-works/pi-agent-core';
import type { RunResult } from './types.js';

export type SessionEventData =
  | { type: 'run_start'; task: string; followUp: boolean }
  | { type: 'agent_event'; event: AgentEvent }
  | { type: 'run_end'; result: RunResult<unknown> }
  | { type: 'paused' | 'resumed' }
  | { type: 'warning'; message: string };
export type SessionEvent = SessionEventData & {
  sequence: number;
  timestamp: number;
  runId: string;
};

/** Slow consumers fail explicitly. They never stall the agent or grow an unbounded queue. */
export class EventStream implements AsyncIterableIterator<SessionEvent> {
  private queue: SessionEvent[] = [];
  private bytes = 0;
  private wake: (() => void) | undefined;
  private ended = false;
  private error: Error | undefined;
  constructor(
    private readonly dispose: () => void,
    private readonly capacity = 256,
  ) {}
  push(event: SessionEvent) {
    if (this.ended) return;
    const size = JSON.stringify(event).length;
    if (this.queue.length >= this.capacity || this.bytes + size > 8_000_000) {
      this.error = new Error(
        'Event consumer fell behind. Read the persisted run log; resubscribe for live events.',
      );
      this.end();
      return;
    }
    this.queue.push(structuredClone(event));
    this.bytes += size;
    this.wake?.();
  }
  end() {
    this.ended = true;
    this.dispose();
    this.wake?.();
  }
  async next(): Promise<IteratorResult<SessionEvent>> {
    while (!this.queue.length && !this.ended)
      await new Promise<void>((resolve) => {
        this.wake = resolve;
      });
    this.wake = undefined;
    if (this.error) {
      this.queue = [];
      this.bytes = 0;
      throw this.error;
    }
    const event = this.queue.shift();
    if (event) {
      this.bytes -= JSON.stringify(event).length;
      return { value: event, done: false };
    }
    return { value: undefined, done: true };
  }
  async return(): Promise<IteratorResult<SessionEvent>> {
    this.queue = [];
    this.bytes = 0;
    this.end();
    return { value: undefined, done: true };
  }
  [Symbol.asyncIterator]() {
    return this;
  }
}

export function formatEvent(event: SessionEvent): string | undefined {
  const prefix = new Date(event.timestamp).toISOString().slice(11, 19);
  if (event.type === 'run_start')
    return `${prefix} ${event.followUp ? 'Continue' : 'Run'} ${event.runId}`;
  if (event.type === 'paused' || event.type === 'resumed') return `${prefix} ${event.type}`;
  if (event.type === 'warning') return `${prefix} warning: ${event.message}`;
  if (event.type === 'run_end')
    return `${prefix} ${event.result.status} · ${event.result.steps} turns · ${(event.result.durationMs / 1000).toFixed(1)}s · ~$${event.result.usage.cost.total.toFixed(4)} · ${event.result.workspace}`;
  if (event.type === 'agent_event') {
    const e = event.event;
    if (e.type === 'tool_execution_start') return `${prefix} → ${e.toolName}`;
    if (e.type === 'tool_execution_end') return `${prefix} ${e.isError ? '✗' : '✓'} ${e.toolName}`;
  }
  return undefined;
}
