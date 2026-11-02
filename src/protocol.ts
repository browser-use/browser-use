import type { BrowserPolicyOptions as importPolicy } from './policy.js';
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
  /** Retain the primary page target for worker recovery. */
  targetId?: string;
  /** Track protocol activity independently from the primary page binding. */
  observationTargetId?: string;
  /** Track the target that the current cell last addressed. */
  activeTargetId?: string;
  /** Preserve complete JSON results outside the observation limit. */
  valueJson?: string;
  /** Retain complete output when model observations exceed their character limit. */
  outputFile?: string;
}
export interface WorkerConfig extends importPolicy {
  mode?: 'default' | 'ultrafast';
  webSearch?: { url: string; token: string };
  sensitiveData?: import('./policy.js').SensitiveData;
  redact?: string[];
  endpoint: string;
  cdpOptions?: import('./browser.js').CdpConnectionOptions;
  /** Bound pending browser waits independently from cell execution. */
  browserWaitMs?: number;
  recording?: boolean;
  highlightActions?: boolean;
  approveConnection?: boolean;
  workspace: string;
  targetId?: string;
  focusTab?: boolean;
  browserSwitching?: boolean;
  dedicatedBrowser?: boolean;
  operationTimeoutMs: number;
  maxOutputChars: number;
}
export type WorkerRequest =
  | { type: 'execute'; code: string; captureJson?: boolean; outputFile?: string; runId?: string }
  | { type: 'close' };
export type WorkerResponse =
  | { type: 'action'; action: BrowserAction }
  | {
      type: 'feature';
      name:
        | 'connections'
        | 'reconnects'
        | 'browser_switches'
        | 'domain_checks'
        | 'domain_denials'
        | 'secret_attempts'
        | 'secret_insertions';
    }
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
