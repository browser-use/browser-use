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
import type { DomainOptions, SensitiveData } from './policy.js';
import type { BrowserOptions } from './browser.js';

export interface BrowserUseOptions extends DomainOptions {
  /** 'ultrafast' adds the `bu` helpers (page state and actions by accessibility-tree id, short page-settle waits) to the REPL. */
  mode?: 'default' | 'ultrafast';
  /**
   * A search endpoint with Browser Use Cloud's /api/v4/search contract; the prompt teaches the model to fetch it.
   * The model's code can read the token (as the cloud agent's shell can), so pass a run-scoped one.
   */
  webSearch?: { url: string; token: string };
  sensitiveData?: SensitiveData;
  /** Anonymous run counters. Disable with false, DO_NOT_TRACK=1 or ANONYMIZED_TELEMETRY=false. */
  telemetry?: boolean;
  /**
   * provider/model ID, e.g. openai/gpt-5.4. Default browser-use/bu-4.0 (Python 1.0.6): the Browser Use gateway with
   * BROWSER_USE_API_KEY (or the Browser.cloud apiKey). A bare bu-* name means the gateway too.
   */
  model?: string;
  /**
   * After each run that took steps, one low-effort request to the run's own model judges it (Python 1.0.5 judge.py):
   * result.judgement, its cost added to usage. Default true; false turns it off (set it in matched cost evals).
   */
  judge?: boolean;
  /** The user's own success criteria for the judge (Python judge_context). */
  judgeContext?: string;
  browser?: BrowserOptions;
  /** Persistent output directory. Defaults to a new OS temporary directory. */
  workspace?: string;
  /** Supply a Pi collection for custom providers or freshly released model definitions. */
  models?: Models;
  reasoning?: ThinkingLevel;
  /** Opt-in Pi read/write/edit/bash tools. Not a filesystem sandbox. */
  researchTools?: boolean;
  /** Extra environment for the research bash tool, e.g. a host's API credentials. */
  shellEnv?: Record<string, string>;
  /** Longest a research bash command may run; commands default to two minutes within it. */
  shellTimeoutMs?: number;
  /** Let the agent move to another browser with reconnect(cdpUrl), e.g. one the host provisioned. */
  browserSwitching?: boolean;
  /** The browser is the agent's alone (e.g. a host-provisioned cloud browser): its empty tab is taken over instead of opening another. */
  dedicatedBrowser?: boolean;
  /** Activate the tab the agent drives after each cell, for hosts that act on the focused tab. */
  focusTab?: boolean;
  tools?: AgentState['tools'];
  instructions?: string;
  /** One CDP command. Default 20000 ms (Python browser-use). */
  operationTimeoutMs?: number;
  /** One JavaScript cell. Default 120000 ms (Python browser-use). */
  cellTimeoutMs?: number;
  /** Connection setup until the model's first stream event. Default 300000 ms. A timeout starts a new step. */
  modelTimeoutMs?: number;
  /** Whole model response while events flow. Default 930000 ms (Python browser-use). */
  modelStreamTimeoutMs?: number;
  /** Whole compaction response. Default 120000 ms; original context survives failure. */
  compactionTimeoutMs?: number;
  /** Initial context-recovery backoff; doubles up to 30 seconds within the run deadline. */
  compactionRetryDelayMs?: number;
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
  /** Show temporary orange corner brackets on the element just clicked or typed into. Default false. */
  highlightActions?: boolean;
}
/** Per-run context controls. Unset fields use the defaults below. */
export interface ContextSettings {
  /** Screenshots kept when old ones are pruned. Default 2. */
  keepScreenshots?: number;
  /**
   * Old screenshots are pruned in one batch once more than this many tool results carry one, so the cached
   * prompt prefix stays unchanged between prunes. Default 20 (Python browser-use). Set it to keepScreenshots to
   * prune on every new screenshot.
   */
  pruneScreenshotsAt?: number;
  /** Trim old screenshots and long tool output in one batch when the context reaches this many tokens. */
  trimAtTokens?: number;
  /** Compact when the context reaches this many tokens. Default 65% of the model window. */
  compactAtTokens?: number;
}
export interface RunOptions {
  /** Model turns. Default 100 (Python browser-use run(max_steps=100)). */
  maxSteps?: number;
  context?: ContextSettings;
  /** Whole run. Default 1700000 ms (Python browser-use run(timeout=1700)). */
  timeoutMs?: number;
  /** Soft threshold: checked between model turns. May exceed by one response. */
  maxCostUsd?: number;
  /** Automatically summarize older context with Pi; false retains hard-stop behavior. */
  compaction?: boolean;
  /** Explicit character cap; defaults to four characters per model context token. */
  maxContextChars?: number;
  /** Durability barrier after the local checkpoint; failures retry within run budgets before inference. */
  onContextRecovery?: (
    event: { state: 'waiting' | 'resumed'; context: ContextMetrics },
    signal?: AbortSignal,
  ) => void | Promise<void>;
  signal?: AbortSignal;
  /** Best-effort nonblocking observations. Coalesces under load; honor the abort signal. */
  observe?: (event: AgentEvent, signal: AbortSignal) => void | Promise<void>;
  observerTimeoutMs?: number;
  /** Pi lifecycle events. Async listeners apply backpressure; keep them bounded. */
  onEvent?: (event: AgentEvent, signal: AbortSignal) => void | Promise<void>;
}
export type StopReason =
  'max_steps' | 'timeout' | 'cancelled' | 'cost_limit' | 'context_limit' | 'incomplete' | 'error';
export interface ContextMetrics {
  chars: number;
  tokens: number;
  maxChars: number;
  maxTokens: number;
  compactionFailures: number;
  lastCompactionFailure?: 'timeout' | 'not_reduced' | 'error';
  beforeCompaction?: { chars: number; tokens: number };
}
export interface RunMetrics {
  context?: ContextMetrics;
  /** Delivery repair turns taken within the original budgets: zero, one, or two. */
  finishRepairs: number;
  compactions?: number;
  providerRetries?: number;
  /** The agent's own verdict from finish/finish_from_js({success}), when it gave one. Not verification. */
  success?: boolean;
  /** The judge's verdict on the run (Python result.judgement), when judge is on and it answered. */
  judgement?: import('./judge.js').Judgement;
  steps: number;
  durationMs: number;
  usage: Usage;
  /** usage.cost.total in USD (Python cost_usd): judge and compaction included; on the gateway, what it charged. */
  costUsd?: number;
  /** Absolute paths of files the browser saved in workspace/downloads during this run (Python result.downloads). */
  downloads?: string[];
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
    | {
        status: StopReason;
        output?: never;
        text: string;
        error?: string;
        partial?: { path?: string; value: unknown };
      }
  );
