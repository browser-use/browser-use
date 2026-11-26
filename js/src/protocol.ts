import type { DomainOptions as importPolicy } from './policy.js';
export interface BrowserAction {
  kind: string;
  targetId: string;
  x?: number;
  y?: number;
}
export interface Image {
  type: 'image';
  data: string;
  mimeType: string;
}
export interface CellResult {
  text: string;
  images: Image[];
  /** Primary page binding after this cell, retained for worker recovery. */
  targetId?: string;
  /** Most recently used protocol target, independent of the primary page binding. */
  observationTargetId?: string;
  /** The tab this cell's own code last sent a command to, e.g. a `const page = await tabs.open()`. */
  activeTargetId?: string;
  /** JSON delivery channel; never clipped to the observation budget. */
  valueJson?: string;
  /** Full output is written to the workspace when the model-facing output is truncated. */
  outputFile?: string;
}
/** Python browser-use 1.0.5 defaults: run(max_steps=100, timeout=1700), 120 s cells, 20 s CDP calls. */
export const DEFAULT_MAX_STEPS = 100;
export const DEFAULT_RUN_TIMEOUT_MS = 1_700_000;
export const DEFAULT_CELL_TIMEOUT_MS = 120_000;
export const DEFAULT_OPERATION_TIMEOUT_MS = 20_000;
/** How cell output prints objects. Node's default depth 2 printed nested data as [Object] and models re-queried it;
 * the cell output cap (maxOutputChars, full text in a file) still bounds what the model sees. */
export const CELL_INSPECT_OPTIONS = { depth: 6, maxArrayLength: 500, breakLength: 160 } as const;
export interface WorkerConfig extends importPolicy {
  mode?: 'default' | 'ultrafast';
  webSearch?: { url: string; token: string };
  sensitiveData?: import('./policy.js').SensitiveData;
  redact?: string[];
  endpoint: string;
  /** Pending browser only: how long a cell waits for it, apart from the cell's own deadline. */
  browserWaitMs?: number;
  recording?: boolean;
  highlightActions?: boolean;
  approveConnection?: boolean;
  workspace: string;
  /** A browser this SDK launched: where its downloads are saved (workspace/downloads). */
  downloadPath?: string;
  targetId?: string;
  focusTab?: boolean;
  browserSwitching?: boolean;
  dedicatedBrowser?: boolean;
  /** Browser.cloud({captchaSolver: false}): the solver is switched off on connect and solveCaptcha() keeps it off. */
  captchaSolver?: false;
  /** Browser.cloud: uploadFile() sends bytes at once instead of trying a local path first. */
  browserKind?: 'cloud';
  operationTimeoutMs: number;
  maxOutputChars: number;
}
export type WorkerRequest =
  | {
      type: 'execute';
      code: string;
      captureJson?: boolean;
      outputFile?: string;
      runId?: string;
      /** The cell deadline, so long helpers can return before it. */
      timeoutMs?: number;
    }
  | { type: 'close' };
export type WorkerResponse =
  | { type: 'action'; action: BrowserAction }
  | { type: 'owned'; targetId: string }
  | { type: 'endpoint'; endpoint: string }
  | { type: 'partial'; runId?: string; path: string; valueJson: string }
  | { type: 'ready'; targetId: string }
  | { type: 'result'; result: CellResult }
  | { type: 'error'; message: string; result?: CellResult }
  | { type: 'closed' };

export function positiveInteger(name: string, value: number): number {
  if (!Number.isSafeInteger(value) || value <= 0 || value > 2_147_483_647) {
    throw new Error(`${name} must be a positive integer below 2147483648.`);
  }
  return value;
}
