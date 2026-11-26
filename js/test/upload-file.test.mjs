import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { CDP } from '../dist/cdp.js';
import { Page } from '../dist/page.js';
import { uploadFile, UPLOAD_PART } from '../dist/upload.js';
import { SYSTEM_PROMPT } from '../dist/prompt.js';
import { AX_PROMPT } from '../dist/ax.js';

/** A page over a fake socket; answer(method, params) gives each command's result, or {error}. */
function fakePage(answer) {
  const socket = new EventTarget();
  socket.readyState = WebSocket.OPEN;
  socket.sent = [];
  socket.close = () => {};
  socket.send = (data) => {
    const message = JSON.parse(data);
    socket.sent.push(message);
    const reply = answer(message.method, message.params ?? {});
    queueMicrotask(() =>
      socket.dispatchEvent(
        Object.assign(new Event('message'), {
          data: JSON.stringify(
            reply?.error
              ? { id: message.id, error: reply.error }
              : { id: message.id, result: reply ?? {} },
          ),
        }),
      ),
    );
  };
  const page = Page.deferred(new CDP(socket, 5000), async () => ({
    targetId: 't1',
    sessionId: 's1',
  }));
  return { page, sent: socket.sent };
}

/** A file input in a remote page: path calls are refused, bytes arrive through callFunctionOn. */
function remoteInput({ refusePath = true } = {}) {
  const parts = {};
  let meta;
  const fake = fakePage((method, params) => {
    if (method === 'DOM.resolveNode') return { object: { objectId: 'input-1' } };
    if (method === 'Runtime.evaluate') return { result: { type: 'object', objectId: 'input-2' } };
    if (method === 'DOM.setFileInputFiles')
      return refusePath
        ? { error: { code: -32000, message: 'Files must exist in the downloads directory' } }
        : {};
    if (method === 'Runtime.callFunctionOn') {
      const args = (params.arguments ?? []).map((a) => a.value);
      if (params.functionDeclaration.includes('f.size'))
        return { result: { value: refusePath ? [] : fake.localSizes } };
      if (params.functionDeclaration.includes('atob')) {
        const [, i, n, b64] = args;
        (parts[i] ||= [])[n] = Buffer.from(b64, 'base64');
        return { result: {} };
      }
      if (params.functionDeclaration.includes('DataTransfer')) {
        meta = args[1];
        return { result: { value: meta.length } };
      }
      return { result: {} };
    }
    return {};
  });
  fake.received = () => ({ meta, files: Object.values(parts).map((p) => Buffer.concat(p)) });
  return fake;
}

test('uploadFile sends the bytes of an existing file to a remote browser, name and type kept', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'bu-upload-file-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const big = Buffer.alloc(UPLOAD_PART + 10, 7);
  await writeFile(join(dir, 'scan.pdf'), big);
  await writeFile(join(dir, 'empty.txt'), '');
  const fake = remoteInput();
  assert.equal(
    await uploadFile(fake.page, 812, [join(dir, 'scan.pdf'), join(dir, 'empty.txt')], true),
    2,
  );
  const { meta, files } = fake.received();
  assert.deepEqual(meta, [
    ['scan.pdf', 'application/pdf'],
    ['empty.txt', 'text/plain'],
  ]);
  assert.ok(files[0].equals(big));
  assert.equal(files[1].length, 0); // an empty file still arrives, as one empty part
  // Cloud: no path call at all.
  assert.ok(!fake.sent.some((m) => m.method === 'DOM.setFileInputFiles'));
  assert.ok(
    fake.sent.some((m) => m.method === 'DOM.resolveNode' && m.params.backendNodeId === 812),
  );
});

test('uploadFile tries the path call first off cloud and falls back to bytes when it is refused', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'bu-upload-file-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await writeFile(join(dir, 'cv.txt'), 'hello');
  const refused = remoteInput();
  assert.equal(await uploadFile(refused.page, '#cv', join(dir, 'cv.txt'), false), 1);
  assert.equal(refused.received().files[0].toString(), 'hello');
  // A local browser that takes the path with the right sizes gets no bytes.
  const local = remoteInput({ refusePath: false });
  local.localSizes = [5];
  assert.equal(await uploadFile(local.page, '#cv', join(dir, 'cv.txt'), false), 1);
  assert.equal(local.received().files.length, 0);
  const call = local.sent.find((m) => m.method === 'DOM.setFileInputFiles');
  assert.deepEqual(call.params, { objectId: 'input-2', files: [join(dir, 'cv.txt')] });
});

test('uploadFile never uploads a missing file; prompts say to upload the existing file', async () => {
  const fake = remoteInput();
  await assert.rejects(uploadFile(fake.page, 1, '/nonexistent/cv.pdf', true), /is not a file/);
  assert.equal(fake.sent.length, 0);
  assert.match(
    SYSTEM_PROMPT,
    /Uploads: await uploadFile\(idOrSelector, path\) with the path of an existing file .*never create or overwrite it, and if it is missing, report that\. Verify the input holds it\./,
  );
  assert.doesNotMatch(AX_PROMPT, /artifact\(name, textOrBytes\) makes one/);
});
