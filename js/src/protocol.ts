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
  /** Current tab after this cell, for observers. */
  targetId?: string;
  /** JSON delivery channel; never clipped to the observation budget. */
  valueJson?: string;
  /** Full output is written to the workspace when the model-facing output is truncated. */
  outputFile?: string;
}
export interface WorkerConfig {
  endpoint: string;
  recording?: boolean;
  workspace: string;
  targetId?: string;
  operationTimeoutMs: number;
  maxOutputChars: number;
}
export type WorkerRequest =
  { type: 'execute'; code: string; captureJson?: boolean } | { type: 'close' };
export type WorkerResponse =
  | { type: 'action'; action: BrowserAction }
  | { type: 'owned'; targetId: string }
  | { type: 'ready'; targetId: string }
  | { type: 'result'; result: CellResult }
  | { type: 'error'; message: string }
  | { type: 'closed' };

export function positiveInteger(name: string, value: number): number {
  if (!Number.isSafeInteger(value) || value <= 0 || value > 2_147_483_647) {
    throw new Error(`${name} must be a positive integer below 2147483648.`);
  }
  return value;
}
