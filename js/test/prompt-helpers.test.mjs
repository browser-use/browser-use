import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CDP } from '../dist/cdp.js';
import { SYSTEM_PROMPT, downloadsPrompt } from '../dist/prompt.js';
import { launchesBrowser } from '../dist/browser.js';

test('the prompt carries Python 1.0.5 select and download guidance', () => {
  assert.match(SYSTEM_PROMPT, /Native <select>: never click it/);
  assert.match(SYSTEM_PROMPT, /never call Browser\.setDownloadBehavior/);
  assert.doesNotMatch(SYSTEM_PROMPT, /Browser\.setDownloadBehavior plus/);
  assert.match(
    downloadsPrompt('local'),
    /land in downloads\/ in the workspace; await downloads\(\)/,
  );
  assert.match(downloadsPrompt('remote'), /await downloads\(\)/);
  assert.equal(downloadsPrompt(undefined), '');
  assert.equal(launchesBrowser(undefined), true);
  assert.equal(launchesBrowser({ headless: true }), true);
  assert.equal(launchesBrowser({ kind: 'chromium' }), true);
  assert.equal(launchesBrowser({ cdpUrl: 'http://127.0.0.1:9222' }), false);
  assert.equal(launchesBrowser({ kind: 'cloud', apiKey: 'k' }), false);
  assert.equal(launchesBrowser({ kind: 'chrome' }), false);
});

test('the prompt says every call is a full model turn (Python 1.0.5 prompt.py)', () => {
  assert.match(
    SYSTEM_PROMPT,
    /Every call is a full model turn: do not spend one on a lone page\.evaluate\(\)/,
  );
  assert.match(
    SYSTEM_PROMPT,
    /read what you need in the same cell as the action or extraction that uses it\./,
  );
});

test('the prompt reads page text after an action; snapshot() is for control ids', () => {
  assert.match(SYSTEM_PROMPT, /finds control ids, not content/);
  assert.match(
    SYSTEM_PROMPT,
    /after goto or a click in the same cell: await page\.evaluate\(\(\) => document\.body\.innerText\)/,
  );
});

/** A CDP connection over a fake socket: records commands, lets the test emit events. */
function fakeConnection() {
  const socket = new EventTarget();
  socket.readyState = WebSocket.OPEN;
  socket.sent = [];
  socket.send = (data) => socket.sent.push(JSON.parse(data));
  socket.close = () => {};
  const cdp = new CDP(socket, 5000);
  const emit = (message) =>
    socket.dispatchEvent(Object.assign(new Event('message'), { data: JSON.stringify(message) }));
  return { cdp, socket, emit };
}

test('default mode: a click that opens a JS dialog fails at once, naming the dialog', async () => {
  const { cdp, socket, emit } = fakeConnection();
  cdp.nameDialogs = true;
  const started = Date.now();
  const click = cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: 1, y: 1 }, 's1');
  emit({
    method: 'Page.javascriptDialogOpening',
    sessionId: 's1',
    params: { type: 'confirm', message: 'Delete this item?' },
  });
  await assert.rejects(
    click,
    /A JavaScript confirm is open \("Delete this item\?"\): the page is frozen/,
  );
  assert.ok(Date.now() - started < 1000);
  // While it stays open, a page call gets a short probe, then names it.
  const read = cdp.send('Runtime.evaluate', { expression: '1' }, 's1');
  await assert.rejects(read, /A JavaScript confirm is open/);
  // Handling it is not held, and closes it.
  const handle = cdp.send('Page.handleJavaScriptDialog', { accept: true }, 's1');
  const id = socket.sent.at(-1).id;
  emit({ id, result: {} });
  await handle;
  emit({ method: 'Page.javascriptDialogClosed', sessionId: 's1', params: { result: true } });
  const after = cdp.send('Runtime.evaluate', { expression: '2' }, 's1');
  emit({ id: socket.sent.at(-1).id, result: { result: { value: 2 } } });
  assert.deepEqual(await after, { result: { value: 2 } });
  cdp.close();
});

test('without nameDialogs (ultrafast accepts dialogs itself) calls are untouched', async () => {
  const { cdp, socket, emit } = fakeConnection();
  const click = cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: 1, y: 1 }, 's1');
  emit({
    method: 'Page.javascriptDialogOpening',
    sessionId: 's1',
    params: { type: 'alert', message: 'hi' },
  });
  emit({ id: socket.sent.at(-1).id, result: {} });
  assert.deepEqual(await click, {});
  cdp.close();
});
