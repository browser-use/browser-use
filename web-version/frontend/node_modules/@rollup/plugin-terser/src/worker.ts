import { isMainThread, parentPort, workerData } from 'worker_threads';

import { hasOwnProperty, isObject } from 'smob';

import { minify } from 'terser';

import { workerPoolWorkerFlag } from './constants';

import type { WorkerContextSerialized, WorkerOutput } from './type';

/**
 * Duck typing worker context.
 *
 * @param input
 */
function isWorkerContextSerialized(input: unknown): input is WorkerContextSerialized {
  return (
    isObject(input) &&
    hasOwnProperty(input, 'code') &&
    typeof input.code === 'string' &&
    hasOwnProperty(input, 'options') &&
    typeof input.options === 'string'
  );
}

export function runWorker() {
  if (isMainThread || !parentPort || workerData !== workerPoolWorkerFlag) {
    return;
  }

  // eslint-disable-next-line no-eval
  const eval2 = eval;

  parentPort.on('message', async (data: WorkerContextSerialized) => {
    if (!isWorkerContextSerialized(data)) {
      return;
    }

    const options = eval2(`(${data.options})`);

    const result = await minify(data.code, options);

    const output: WorkerOutput = {
      code: result.code || data.code,
      nameCache: options.nameCache
    };

    if (typeof result.map === 'string') {
      output.sourceMap = JSON.parse(result.map);
    }

    if (isObject(result.map)) {
      output.sourceMap = result.map;
    }

    parentPort?.postMessage(output);
  });
}
