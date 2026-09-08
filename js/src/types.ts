import type {
  AgentEvent,
  AgentState,
  StreamFn,
  ThinkingLevel,
  BeforeToolCallContext,
  BeforeToolCallResult,
  AfterToolCallContext,
  AfterToolCallResult,
} from '@earendil-works/pi-agent-core';
import type { Models, Usage } from '@earendil-works/pi-ai';
import type { RecordingOptions } from './recording.js';
import type { BrowserOptions } from './browser.js';

export interface BrowserUseOptions {
  /** provider/model ID, e.g. openai/gpt-5.4. No model is silently substituted. */
  model: string;
  browser?: BrowserOptions;
  /** Persistent output directory. Defaults to a new OS temporary directory. */
  workspace?: string;
  /** Supply a Pi collection for custom providers or freshly released model definitions. */
  models?: Models;
  reasoning?: ThinkingLevel;
  /** Opt-in Pi read/write/edit/bash tools. Not a filesystem sandbox. */
  researchTools?: boolean;
  tools?: AgentState['tools'];
  instructions?: string;
  operationTimeoutMs?: number;
  cellTimeoutMs?: number;
  /** Whole model response, including connection setup. Default 300000 ms. */
  modelTimeoutMs?: number;
  /** Whole compaction response. Default 120000 ms; original context survives failure. */
  compactionTimeoutMs?: number;
  maxOutputChars?: number;
  /** Before each tool call. Return {block:true, reason} to deny it. */
  beforeToolCall?: (
    context: BeforeToolCallContext,
    signal?: AbortSignal,
  ) => Promise<BeforeToolCallResult | undefined>;
  /** Advanced transport override; useful for deterministic tests or a model gateway. */
  streamFn?: StreamFn;
  /** Named values to redact from saved text/events. Does not redact screenshots. */
  redact?: string[];
  log?: false | 'pretty' | 'json';
  hookTimeoutMs?: number;
  afterToolCall?: (
    context: AfterToolCallContext,
    signal?: AbortSignal,
  ) => Promise<AfterToolCallResult | undefined>;
  /** Return feedback to reject a schema-valid result and let the agent correct it. */
  validateResult?: (output: unknown, signal?: AbortSignal) => Promise<string | void>;
  /** Restore a versioned transcript. Browser profile and JS heap are separate. */
  historyFile?: string;
  recording?: boolean | RecordingOptions;
}
export interface RunOptions {
  maxSteps?: number;
  timeoutMs?: number;
  /** Soft threshold: checked between model turns. May exceed by one response. */
  maxCostUsd?: number;
  /** Automatically summarize older context with Pi; false retains hard-stop behavior. */
  compaction?: boolean;
  maxContextChars?: number;
  signal?: AbortSignal;
  /** Best-effort nonblocking observations. Coalesces under load; honor the abort signal. */
  observe?: (event: AgentEvent, signal: AbortSignal) => void | Promise<void>;
  observerTimeoutMs?: number;
  /** Pi lifecycle events. Async listeners apply backpressure; keep them bounded. */
  onEvent?: (event: AgentEvent, signal: AbortSignal) => void | Promise<void>;
}
export type StopReason =
  'max_steps' | 'timeout' | 'cancelled' | 'cost_limit' | 'context_limit' | 'incomplete' | 'error';
export interface RunMetrics {
  /** Additional delivery-only model turns, within the original budgets (0 or 1). */
  finishRepairs: number;
  compactions?: number;
  providerRetries?: number;
  steps: number;
  durationMs: number;
  usage: Usage;
  workspace: string;
  /** Approximate token costs from the configured model catalog, not an invoice. */
  model: string;
  runId?: string;
  historyPath?: string;
  eventsPath?: string;
  recordingPath?: string;
  /** Auxiliary recording/history persistence failures; delivered output remains available. */
  warnings?: string[];
}
export type RunResult<T = string> = RunMetrics &
  (
    | { status: 'completed'; output: T; text: string }
    | { status: StopReason; output?: never; text: string; error?: string }
  );
