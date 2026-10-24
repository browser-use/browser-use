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
import type { Api, Models, Usage } from '@earendil-works/pi-ai';
import type { RecordingOptions } from './recording.js';
import type { DomainOptions, SensitiveData } from './policy.js';
import type { TelemetryCounter } from './telemetry.js';
import type { BrowserOptions } from './browser.js';
export interface ModelInfo {
  template?: string;
  api?: Api;
  baseUrl?: string;
  vision?: boolean;
  reasoning?: boolean;
  contextWindow?: number;
  maxTokens?: number;
  cost?: {
    input: number;
    output: number;
    cacheRead: number;
    cacheWrite: number;
  };
  compat?: Record<string, unknown>;
  thinkingLevelMap?: Record<string, string | null>;
}
export interface BrowserUseOptions extends DomainOptions {
  mode?: 'default' | 'ultrafast';
  webSearch?: {
    url: string;
    token: string;
  };
  sensitiveData?: SensitiveData;
  telemetry?: boolean;
  model?: string;
  modelInfo?: ModelInfo;
  pricingKnown?: boolean;
  browserSelection?: 'explicit' | 'default';
  modelMetadataSource?: 'catalog' | 'explicit' | 'unknown';
  onCounter?: (counter: TelemetryCounter) => void;
  onBrowserReady?: (session: {
    execute: (code: string) => Promise<unknown>;
  }) => void | Promise<void>;
  browser?: BrowserOptions;
  initScripts?: string[];
  clientLanguage?: 'python' | 'javascript';
  entrypoint?: 'sdk' | 'cli' | 'adapter';
  controller?: 'pi' | 'openai_toolset' | 'anthropic_toolset' | 'cli_direct' | 'custom';
  workspace?: string;
  models?: Models;
  reasoning?: ThinkingLevel;
  researchTools?: boolean;
  shellEnv?: Record<string, string>;
  shellTimeoutMs?: number;
  browserSwitching?: boolean;
  dedicatedBrowser?: boolean;
  focusTab?: boolean;
  tools?: AgentState['tools'];
  instructions?: string;
  operationTimeoutMs?: number;
  cellTimeoutMs?: number;
  modelTimeoutMs?: number;
  compactionTimeoutMs?: number;
  compactionRetryDelayMs?: number;
  maxOutputChars?: number;
  beforeToolCall?: (
    context: BeforeToolCallContext,
    signal?: AbortSignal,
  ) => Promise<BeforeToolCallResult | undefined>;
  streamFn?: StreamFn;
  redact?: string[];
  log?: false | 'pretty' | 'json';
  hookTimeoutMs?: number;
  afterToolCall?: (
    context: AfterToolCallContext,
    signal?: AbortSignal,
  ) => Promise<AfterToolCallResult | undefined>;
  validateResult?: (output: unknown, signal?: AbortSignal) => Promise<string | void>;
  historyFile?: string;
  recording?: boolean | RecordingOptions;
  highlightActions?: boolean;
}
export interface RunOptions {
  validateResult?: (output: unknown, signal?: AbortSignal) => Promise<string | void>;
  maxSteps?: number;
  timeoutMs?: number;
  maxCostUsd?: number;
  compaction?: boolean;
  maxContextChars?: number;
  onContextRecovery?: (
    event: {
      state: 'waiting' | 'resumed';
      context: ContextMetrics;
    },
    signal?: AbortSignal,
  ) => void | Promise<void>;
  signal?: AbortSignal;
  observe?: (event: AgentEvent, signal: AbortSignal) => void | Promise<void>;
  observerTimeoutMs?: number;
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
  beforeCompaction?: {
    chars: number;
    tokens: number;
  };
}
export interface RunMetrics {
  context?: ContextMetrics;
  modelDurationMs?: number;
  toolDurationMs?: number;
  finishRepairs: number;
  compactions?: number;
  providerRetries?: number;
  steps: number;
  durationMs: number;
  usage: Omit<Usage, 'cost'> & {
    cost: Usage['cost'] | null;
  };
  workspace: string;
  summaryUsage?: Omit<Usage, 'cost'> & { cost: Usage['cost'] | null };
  model: string;
  runId?: string;
  historyPath?: string;
  eventsPath?: string;
  recordingPath?: string;
  warnings?: string[];
  pricingKnown?: boolean;
  estimatedCostUsd?: number | null;
}
export type RunResult<T = string> = RunMetrics &
  (
    | {
        status: 'completed';
        output: T;
        text: string;
      }
    | {
        status: StopReason;
        output?: never;
        text: string;
        error?: string;
        partial?: {
          path?: string;
          value: unknown;
        };
      }
  );
