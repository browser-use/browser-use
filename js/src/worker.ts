import { Writable } from 'node:stream';
import { Session, type Runtime } from 'node:inspector';
import { createRequire } from 'node:module';
import { createContext, constants } from 'node:vm';
import { inspect } from 'node:util';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { CDP } from './cdp.js';
import { Page } from './page.js';
import { Tabs } from './tabs.js';
import type { Image, WorkerConfig, WorkerRequest, WorkerResponse } from './protocol.js';

// IPC initialization keeps connection details out of argv and environment.
process.on('disconnect', () => process.exit(0));
const config = await new Promise<WorkerConfig>((resolve) => process.once('message', resolve));
const send = (message: WorkerResponse) => process.send!(message);
const browser = await CDP.connect(config.endpoint, config.operationTimeoutMs);
const tabs = new Tabs(browser, (id) => send({ type: 'owned', targetId: id }));
const page = config.targetId
  ? await tabs.get(config.targetId).catch(() => tabs.open())
  : await tabs.open();
let output = '';
let images: Image[] = [];
let overflow = false;
// Bound memory even when generated code writes an unbounded amount of output.
const hardLimit = 1_000_000;
const sink = new Writable({
  write(chunk: Buffer, _encoding, callback) {
    const text = chunk.toString();
    if (output.length + text.length > hardLimit) overflow = true;
    output += text.slice(0, Math.max(0, hardLimit - output.length));
    callback();
  },
});
const evaluator = new Session();
evaluator.connect();
let executionContextId: number | undefined;
evaluator.on('Runtime.executionContextCreated', ({ params }) => {
  if (params.context.name === 'browser-use') executionContextId = params.context.id;
});
evaluator.post('Runtime.enable');
const realm = createContext(
  {},
  {
    name: 'browser-use',
    importModuleDynamically: constants.USE_MAIN_CONTEXT_DEFAULT_LOADER,
  },
);
if (executionContextId === undefined)
  throw new Error('Could not initialize the JavaScript context.');
Object.assign(realm, {
  process,
  Buffer,
  URL,
  URLSearchParams,
  fetch,
  AbortController,
  AbortSignal,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  queueMicrotask,
  structuredClone,
  TextEncoder,
  TextDecoder,
  browser,
  tabs,
  page,
  workspace: config.workspace,
  require: createRequire(import.meta.url),
  async screenshot() {
    const current = Reflect.get(realm, 'page') as Page;
    const bytes = await current.screenshot({ quality: 70 });
    if (images.length >= 4) throw new Error('At most four screenshots per cell.');
    if (bytes.length > 8_000_000)
      throw new Error('Screenshot exceeds 8 MB; use a smaller viewport.');
    images.push({ type: 'image', data: bytes.toString('base64'), mimeType: 'image/jpeg' });
    return 'Screenshot attached.';
  },
  async snapshot() {
    const current = Reflect.get(realm, 'page') as Page;
    return current.snapshot();
  },
  async artifact(name: string, data: string | Uint8Array) {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$/.test(name))
      throw new Error('Use a plain filename, max 120 characters.');
    const path = join(config.workspace, name);
    await writeFile(path, data, { flag: 'wx' });
    return path;
  },
});
realm.console = new (await import('node:console')).Console(sink, sink);

async function evaluate(code: string): Promise<void> {
  try {
    // V8 supports replMode; Node 22's generated protocol types omit this field.
    const parameters = {
      expression: code,
      contextId: executionContextId,
      awaitPromise: true,
      replMode: true,
      objectGroup: 'cell',
    };
    const { result, exceptionDetails } = await new Promise<Runtime.EvaluateReturnType>(
      (resolve, reject) => {
        evaluator.post(
          'Runtime.evaluate',
          parameters,
          (error: Error | null, response: Runtime.EvaluateReturnType) => {
            if (error) reject(error);
            else resolve(response);
          },
        );
      },
    );
    if (exceptionDetails)
      throw new Error(exceptionDetails.exception?.description ?? exceptionDetails.text);
    if (result.objectId) {
      await new Promise<void>((resolve, reject) =>
        evaluator.post(
          'Runtime.callFunctionOn',
          {
            objectId: result.objectId,
            functionDeclaration: 'function() { console.log(this); }',
            returnByValue: true,
          },
          (error) => {
            if (error) reject(error);
            else resolve();
          },
        ),
      );
    } else if (result.type !== 'undefined') {
      sink.write(result.unserializableValue ?? inspect(result.value, { maxStringLength: 20_000 }));
    }
  } finally {
    evaluator.post('Runtime.releaseObjectGroup', { objectGroup: 'cell' });
  }
}

process.on('message', async (message: WorkerRequest) => {
  if (message.type === 'close') {
    browser.close();
    evaluator.disconnect();
    send({ type: 'closed' });
    return;
  }
  output = '';
  images = [];
  overflow = false;
  try {
    await evaluate(message.code);
    if (overflow) output += '\n[Output exceeded the 1 MB capture limit.]';
    let outputFile: string | undefined;
    if (output.length > config.maxOutputChars) {
      outputFile = join(config.workspace, `output-${randomUUID()}.txt`);
      await writeFile(outputFile, output, { flag: 'wx' });
      output = `${output.slice(0, config.maxOutputChars)}\n[Truncated. Full captured output: ${outputFile}]`;
    }
    send({
      type: 'result',
      result: { text: output || '(no output)', images, ...(outputFile ? { outputFile } : {}) },
    });
  } catch (error) {
    send({ type: 'error', message: error instanceof Error ? error.message : String(error) });
  }
});
send({ type: 'ready', targetId: page.targetId });
