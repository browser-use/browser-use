import { AsyncResource } from 'async_hooks';
import { Worker } from 'worker_threads';
import { cpus } from 'os';
import { EventEmitter } from 'events';

import serializeJavascript from 'serialize-javascript';

import { freeWorker, taskInfo, workerPoolWorkerFlag } from './constants';

import type {
  WorkerCallback,
  WorkerContext,
  WorkerOutput,
  WorkerPoolOptions,
  WorkerPoolTask,
  WorkerWithTaskInfo
} from './type';

class WorkerPoolTaskInfo extends AsyncResource {
  constructor(private callback: WorkerCallback) {
    super('WorkerPoolTaskInfo');
  }

  done(err: Error | null, result: any) {
    this.runInAsyncScope(this.callback, null, err, result);
    this.emitDestroy();
  }
}

export class WorkerPool extends EventEmitter {
  protected maxInstances: number;

  protected filePath: string;

  protected tasks: WorkerPoolTask[] = [];

  protected workers: WorkerWithTaskInfo[] = [];
  protected freeWorkers: WorkerWithTaskInfo[] = [];

  constructor(options: WorkerPoolOptions) {
    super();

    this.maxInstances = options.maxWorkers || cpus().length;
    this.filePath = options.filePath;

    this.on(freeWorker, () => {
      if (this.tasks.length > 0) {
        const { context, cb } = this.tasks.shift()!;
        this.runTask(context, cb);
      }
    });
  }

  get numWorkers(): number {
    return this.workers.length;
  }

  addAsync(context: WorkerContext): Promise<WorkerOutput> {
    return new Promise((resolve, reject) => {
      this.runTask(context, (err, output) => {
        if (err) {
          reject(err);
          return;
        }

        if (!output) {
          reject(new Error('The output is empty'));
          return;
        }

        resolve(output);
      });
    });
  }

  close() {
    for (let i = 0; i < this.workers.length; i++) {
      const worker = this.workers[i];
      worker.terminate();
    }
  }

  private addNewWorker() {
    const worker: WorkerWithTaskInfo = new Worker(this.filePath, {
      workerData: workerPoolWorkerFlag
    });

    worker.on('message', (result) => {
      worker[taskInfo]?.done(null, result);
      worker[taskInfo] = null;
      this.freeWorkers.push(worker);
      this.emit(freeWorker);
    });

    worker.on('error', (err) => {
      if (worker[taskInfo]) {
        worker[taskInfo].done(err, null);
      } else {
        this.emit('error', err);
      }
      this.workers.splice(this.workers.indexOf(worker), 1);
      this.addNewWorker();
    });

    this.workers.push(worker);
    this.freeWorkers.push(worker);
    this.emit(freeWorker);
  }

  private runTask(context: WorkerContext, cb: WorkerCallback) {
    if (this.freeWorkers.length === 0) {
      this.tasks.push({ context, cb });
      if (this.numWorkers < this.maxInstances) {
        this.addNewWorker();
      }
      return;
    }

    const worker = this.freeWorkers.pop();
    if (worker) {
      worker[taskInfo] = new WorkerPoolTaskInfo(cb);
      worker.postMessage({
        code: context.code,
        options: serializeJavascript(context.options)
      });
    }
  }
}
