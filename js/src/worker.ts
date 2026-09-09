import { Writable } from 'node:stream';
import { Session, type Runtime } from 'node:inspector';
import { createRequire } from 'node:module';
import { createContext, constants } from 'node:vm';
import { inspect } from 'node:util';
import { writeFile, rename } from 'node:fs/promises';
import { appendFileSync } from 'node:fs';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { CDP } from './cdp.js';
import { Page, Tabs } from './page.js';
import type { Image, WorkerConfig, WorkerRequest, WorkerResponse } from './protocol.js';
import { installDomainPolicy, fillSecret } from './policy.js';
import { redact } from './history.js';
import { actionHighlighter } from './highlight.js';
import { prepareModelImages } from './images.js';

// IPC initialization keeps connection details out of argv and environment.
process.on('disconnect', () => process.exit(0));
const config = await new Promise<WorkerConfig>((resolve) => process.once('message', resolve));
const clean = <T>(value: T): T => redact(value, config.redact ?? []);
const send = (message: WorkerResponse) => process.send!(clean(message));
process.chdir(config.workspace);
let browser = CDP.lazy(config.endpoint, config.operationTimeoutMs, config.approveConnection);
installDomainPolicy(browser, config, (id) => send({ type: 'owned', targetId: id }));
let highlight = config.highlightActions ? actionHighlighter(browser) : undefined;
let tabs = new Tabs(browser, (id) => send({ type: 'owned', targetId: id }));
function deferredPage(targetId?: string) {
  return Page.deferred(
    browser,
    async () => {
      if (targetId) {
        // Only create a replacement when the target is actually absent, not on an attach timeout.
        const existing = await tabs.list();
        if (existing.some((t) => t.targetId === targetId)) return tabs.get(targetId);
      }
      return tabs.open();
    },
    targetId,
  );
}
const page = deferredPage(config.targetId);
let outputFile: string | undefined;
let runId: string | undefined;
let output = '';
let images: Image[] = [];
let captureResponse: CDP['observeResponse'];
let overflow = false;
// Bound memory even when generated code writes an unbounded amount of output.
const hardLimit = 1_000_000;
let pendingText = '';
const tailLength = Math.max(0, ...(config.redact ?? []).map((value) => value.length));
function captureText(text: string) {
  if (output.length + text.length > hardLimit) overflow = true;
  const captured = text.slice(0, Math.max(0, hardLimit - output.length));
  output += captured;
  if (outputFile && captured) appendFileSync(outputFile, captured);
}
const sink = new Writable({
  write(chunk: Buffer, _encoding, callback) {
    pendingText += chunk.toString();
    // Redact before splitting, and retain the raw suffix across chunk boundaries.
    const cut = Math.max(0, pendingText.length - tailLength);
    let safeCut = cut;
    for (const secret of config.redact ?? []) {
      if (!secret) continue;
      let at = pendingText.indexOf(secret);
      while (at >= 0 && at < cut) {
        if (at + secret.length > cut) safeCut = Math.min(safeCut, at);
        at = pendingText.indexOf(secret, at + 1);
      }
    }
    captureText(clean(pendingText.slice(0, safeCut)));
    pendingText = pendingText.slice(safeCut);
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
  global: realm, // Node's global alias refers to this REPL realm, not the worker host.
  // Reject values JSON would silently drop or change. Dates/toJSON use normal JSON semantics.
  __serializeResult(value: unknown) {
    const json = JSON.stringify(value, (_key, item: unknown) => {
      if (
        ['undefined', 'function', 'symbol', 'bigint'].includes(typeof item) ||
        (typeof item === 'number' && !Number.isFinite(item))
      )
        throw new Error(
          'Result must contain JSON values: no undefined, functions, symbols, bigint, or non-finite numbers.',
        );
      return item;
    });
    if (json === undefined) throw new Error('Result must be JSON serializable.');
    if (Buffer.byteLength(json) > 16_000_000)
      throw new Error('Result exceeds 16 MB; save an artifact and return its path.');
    return json;
  },
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
  async reconnect() {
    const targetId = (Reflect.get(realm, 'page') as Page)?.targetId;
    browser.close();
    browser = CDP.lazy(config.endpoint, config.operationTimeoutMs, config.approveConnection);
    installDomainPolicy(browser, config, (id) => send({ type: 'owned', targetId: id }));
    highlight = config.highlightActions ? actionHighlighter(browser) : undefined;
    browser.observeResponse = captureResponse;
    tabs = new Tabs(browser, (id) => send({ type: 'owned', targetId: id }));
    Object.assign(realm, { browser, tabs, page: deferredPage(targetId) });
    observe();
    return 'Connection reset. Inspect the page; no browser action was replayed. Reacquire other page/frame handles.';
  },
  async fillSecret(
    name: string,
    backendNodeId: number,
    target: Page = Reflect.get(realm, 'page') as Page,
  ) {
    await target.info();
    const result = await fillSecret(
      browser,
      target.sessionId,
      name,
      backendNodeId,
      config.sensitiveData ?? {},
    );
    void highlight?.('DOM.focus', { backendNodeId }, target.sessionId);
    return result;
  },
  async checkpoint(name: string, value: unknown, options: { partial?: boolean } = {}) {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$/.test(name))
      throw new Error('Use a plain checkpoint filename.');
    const checkpointRun = runId;
    const valueJson = JSON.stringify(clean(value));
    if (typeof valueJson !== 'string') throw new Error('Checkpoint must be JSON serializable.');
    if (options.partial && Buffer.byteLength(valueJson) > 16_000_000)
      throw new Error(
        'Partial result exceeds 16 MB; checkpoint smaller batches or return file paths.',
      );
    const path = join(config.workspace, name);
    const temporary = `${path}.${randomUUID()}.tmp`;
    await writeFile(temporary, valueJson, { flag: 'wx', mode: 0o600 });
    await rename(temporary, path);
    if (options.partial)
      await new Promise<void>((resolve, reject) =>
        process.send!(
          {
            type: 'partial',
            ...(checkpointRun ? { runId: checkpointRun } : {}),
            path,
            valueJson,
          } satisfies WorkerResponse,
          (error) => (error ? reject(error) : resolve()),
        ),
      );
    return path;
  },
  require: createRequire(join(config.workspace, 'package.json')),
  async screenshot() {
    const current = Reflect.get(realm, 'page') as Page;
    if (images.length >= 4) throw new Error('At most four screenshots per cell.');
    const count = images.length;
    await current.screenshot({ quality: 70 });
    return images.length > count ? 'Screenshot captured.' : 'Screenshot omitted; see warning.';
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
function observe() {
  if (config.recording)
    browser.observeCommand = (method, raw, sessionId) => {
      const params = raw as { type?: string; x?: number; y?: number };
      const protocolTarget = sessionId ? browser.targetForSession(sessionId) : undefined;
      const targetId = protocolTarget ? browser.observationTargetId : undefined;
      if (!targetId) return;
      if (
        method === 'Input.dispatchMouseEvent' &&
        ['mouseReleased', 'mouseWheel'].includes(params.type ?? '')
      )
        send({
          type: 'action',
          action: {
            kind: params.type === 'mouseReleased' ? 'Click' : 'Scroll',
            targetId,
            ...(protocolTarget === targetId && params.x !== undefined ? { x: params.x } : {}),
            ...(protocolTarget === targetId && params.y !== undefined ? { y: params.y } : {}),
          },
        });
      else if (method === 'Input.insertText' || method === 'Page.navigate')
        send({
          type: 'action',
          action: { kind: method === 'Page.navigate' ? 'Navigate' : 'Type', targetId },
        });
    };
}
observe();
realm.console = new (await import('node:console')).Console(sink, sink);

async function evaluate(code: string, captureJson = false): Promise<string | undefined> {
  try {
    // V8 supports replMode; Node 22's generated protocol types omit this field.
    const parameters = {
      expression: captureJson ? `__serializeResult(await (${code}\n))` : code,
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
    if (captureJson) {
      if (typeof result.value !== 'string')
        throw new Error('Result serialization returned no JSON.');
      return JSON.stringify(clean(JSON.parse(result.value)));
    }
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
  runId = message.runId;
  output = '';
  pendingText = '';
  images = [];
  const cellImages = images;
  let active = true;
  let warned = false;
  captureResponse = (method, params, result, sessionId) => {
    if (active) void highlight?.(method, params, sessionId);
    if (!active || method !== 'Page.captureScreenshot') return;
    const data = (result as { data?: unknown })?.data;
    if (typeof data !== 'string') return;
    if (cellImages.length >= 4 || Buffer.byteLength(data, 'base64') > 8_000_000) {
      if (!warned) sink.write('[Screenshot omitted from model vision: four-image/8 MB limit.]\n');
      warned = true;
      return;
    }
    const format = (params as { format?: string })?.format ?? 'png';
    const mimeType =
      format === 'jpeg' ? 'image/jpeg' : format === 'webp' ? 'image/webp' : 'image/png';
    cellImages.push({ type: 'image', data, mimeType });
  };
  browser.observeResponse = captureResponse;
  overflow = false;
  outputFile = message.outputFile;
  let valueJson: string | undefined;
  let failure: string | undefined;
  try {
    valueJson = await evaluate(message.code, message.captureJson);
  } catch (error) {
    failure = error instanceof Error ? error.message : String(error);
  } finally {
    active = false;
    browser.observeResponse = undefined;
    captureResponse = undefined;
  }
  captureText(clean(pendingText));
  pendingText = '';
  if (overflow) output += '\n[Output exceeded the 1 MB capture limit.]';
  if (output.length > config.maxOutputChars)
    output = `${output.slice(0, config.maxOutputChars)}\n[Truncated. Full captured output: ${outputFile}]`;
  const previews = await prepareModelImages(images);
  const result = {
    text: [output, ...previews.notes].filter(Boolean).join('\n') || '(no output)',
    images: previews.images,
    targetId: (Reflect.get(realm, 'page') as Page)?.targetId,
    ...(browser.observationTargetId ? { observationTargetId: browser.observationTargetId } : {}),
    ...(valueJson !== undefined ? { valueJson } : {}),
    ...(outputFile ? { outputFile } : {}),
  };
  if (failure) send({ type: 'error', message: failure, result });
  else send({ type: 'result', result });
});
send({ type: 'ready', targetId: page.targetId });
