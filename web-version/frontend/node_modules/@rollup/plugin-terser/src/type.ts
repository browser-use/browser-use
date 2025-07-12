import type { AsyncResource } from 'async_hooks';
import type { Worker } from 'worker_threads';

import type { MinifyOptions } from 'terser';

import type { taskInfo } from './constants';

export interface Options extends MinifyOptions {
  nameCache?: Record<string, any>;
  maxWorkers?: number;
}

export interface WorkerContext {
  code: string;
  options: Options;
}

export type WorkerCallback = (err: Error | null, output?: WorkerOutput) => void;

interface WorkerPoolTaskInfo extends AsyncResource {
  done(err: Error | null, result: any): void;
}

export type WorkerWithTaskInfo = Worker & { [taskInfo]?: WorkerPoolTaskInfo | null };

export interface WorkerContextSerialized {
  code: string;
  options: string;
}

export interface WorkerOutput {
  code: string;
  nameCache?: Options['nameCache'];
  sourceMap?: Record<string, any>;
}

export interface WorkerPoolOptions {
  filePath: string;
  maxWorkers?: number;
}

export interface WorkerPoolTask {
  context: WorkerContext;
  cb: WorkerCallback;
}
