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

// BU Bench v2.1: 31 Pi cells ended on "Page condition exceeded 20000 ms" thrown by goto (often inside tabs.open loops
// or Promise.all); Python 1.0.5's goto_url never fails on a slow load.
test('goto returns the page info when the document is still loading after the wait', async () => {
  const socket = new EventTarget();
  socket.readyState = WebSocket.OPEN;
  socket.close = () => {};
  socket.send = (data) => {
    const { id, method, params } = JSON.parse(data);
    // Only info() reads location; every waited condition stays false.
    const value = /location\.href/.test(params?.expression ?? '')
      ? { url: 'https://slow.example/', title: '' }
      : false;
    const result = method === 'Runtime.evaluate' ? { result: { value } } : { frameId: 'f' };
    queueMicrotask(() =>
      socket.dispatchEvent(
        Object.assign(new Event('message'), { data: JSON.stringify({ id, result }) }),
      ),
    );
  };
  const cdp = new CDP(socket, 300);
  const page = Page.deferred(cdp, async () => ({ targetId: 't1', sessionId: 's1' }));
  assert.deepEqual(await page.goto('https://slow.example/'), {
    url: 'https://slow.example/',
    title: '',
  });
  // waitFor itself still throws for an explicit condition.
  await assert.rejects(
    page.waitFor(() => false),
    /Page condition exceeded 300 ms/,
  );
  cdp.close();
});
