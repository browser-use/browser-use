import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CDP } from '../dist/cdp.js';
import { Page } from '../dist/page.js';

/** A fake socket: attach answers, Page.enable never answers, Runtime.enable fails. */
function fakeBrowser() {
  const socket = new EventTarget();
  socket.readyState = WebSocket.OPEN;
  socket.sent = [];
  socket.close = () => {};
  const reply = (body) =>
    queueMicrotask(() =>
      socket.dispatchEvent(Object.assign(new Event('message'), { data: JSON.stringify(body) })),
    );
  socket.send = (data) => {
    const { id, method } = JSON.parse(data);
    socket.sent.push(method);
    if (method === 'Target.attachToTarget') reply({ id, result: { sessionId: 's1' } });
    else if (method === 'Runtime.enable') reply({ id, error: { code: -32000, message: 'busy' } });
    else if (method !== 'Page.enable') reply({ id, result: {} });
  };
  return { cdp: new CDP(socket, 20000), socket };
}

// BU Bench v2.1: 32 Pi cells failed with "Page.enable exceeded 20000 ms" (tabs.get on a background tab); Python's
// daemon enables in parallel, waits at most 4 s for each and never fails the attach.
test('Page.attach sends both enables at once, waits at most 4 s and ignores their failures', async () => {
  const { cdp, socket } = fakeBrowser();
  const started = Date.now();
  const page = await Page.attach(cdp, 't1');
  const elapsed = Date.now() - started;
  assert.equal(page.sessionId, 's1');
  assert.deepEqual(socket.sent, ['Target.attachToTarget', 'Page.enable', 'Runtime.enable']);
  assert(elapsed >= 3900 && elapsed < 6000, `attach took ${elapsed} ms`);
  cdp.close();
});
