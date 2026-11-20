import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CDP } from '../dist/cdp.js';
import { Page } from '../dist/page.js';
import { SYSTEM_PROMPT } from '../dist/prompt.js';

/** A page over a fake socket that answers every command with {} and records it. */
function fakePage() {
  const socket = new EventTarget();
  socket.readyState = WebSocket.OPEN;
  socket.sent = [];
  socket.close = () => {};
  socket.send = (data) => {
    const message = JSON.parse(data);
    socket.sent.push(message);
    queueMicrotask(() =>
      socket.dispatchEvent(
        Object.assign(new Event('message'), {
          data: JSON.stringify({ id: message.id, result: {} }),
        }),
      ),
    );
  };
  const cdp = new CDP(socket, 5000);
  const page = Page.deferred(cdp, async () => ({ targetId: 't1', sessionId: 's1' }));
  const sent = () =>
    socket.sent.map(({ method, params, sessionId }) => ({ method, params, sessionId }));
  return { page, sent };
}

test('pressKey sends the key, code and key code a US keyboard sends (browser-harness press_key)', async () => {
  const { page, sent } = fakePage();
  await page.pressKey('Enter');
  await page.pressKey('A');
  await page.pressKey('!');
  await page.pressKey('a', 2);
  const events = sent().map(({ params }) => params);
  assert.deepEqual(events.slice(0, 2), [
    {
      type: 'keyDown',
      key: 'Enter',
      code: 'Enter',
      modifiers: 0,
      windowsVirtualKeyCode: 13,
      text: '\r',
    },
    {
      type: 'keyUp',
      key: 'Enter',
      code: 'Enter',
      modifiers: 0,
      windowsVirtualKeyCode: 13,
    },
  ]);
  // Printable: keyDown without text, then a char event with it; uppercase adds Shift.
  assert.deepEqual(
    events.slice(2, 5).map((e) => [e.type, e.code, e.modifiers, e.windowsVirtualKeyCode, e.text]),
    [
      ['keyDown', 'KeyA', 8, 65, undefined],
      ['char', 'KeyA', 8, 65, 'A'],
      ['keyUp', 'KeyA', 8, 65, undefined],
    ],
  );
  assert.deepEqual(
    events.slice(5, 8).map((e) => [e.code, e.modifiers, e.windowsVirtualKeyCode]),
    [
      ['Digit1', 8, 49],
      ['Digit1', 8, 49],
      ['Digit1', 8, 49],
    ],
  );
  // Ctrl+a is a shortcut: no char event, no added Shift.
  assert.deepEqual(
    events.slice(8).map((e) => [e.type, e.modifiers, e.text]),
    [
      ['keyDown', 2, 'a'],
      ['keyUp', 2, undefined],
    ],
  );
  assert.ok(sent().every((m) => m.sessionId === 's1'));
  // Python 1.0.5 drops nativeVirtualKeyCode: macOS Chrome read it as a Mac key code (chrome://settings/help).
  assert.ok(events.every((e) => !('nativeVirtualKeyCode' in e)));
});

test('typeText inserts text; scroll sends a mouse wheel, positive dy is down', async () => {
  const { page, sent } = fakePage();
  await page.typeText('héllo');
  await page.scroll(10, 20);
  await page.scroll(10, 20, -300, 5);
  assert.deepEqual(
    sent().map(({ method, params }) => [method, params]),
    [
      ['Input.insertText', { text: 'héllo' }],
      ['Input.dispatchMouseEvent', { type: 'mouseWheel', x: 10, y: 20, deltaX: 0, deltaY: 600 }],
      ['Input.dispatchMouseEvent', { type: 'mouseWheel', x: 10, y: 20, deltaX: 5, deltaY: -300 }],
    ],
  );
  await assert.rejects(page.scroll(Number.NaN, 0), /finite/);
  assert.match(SYSTEM_PROMPT, /await page\.typeText\(text\) inserts text into the focused element/);
  assert.match(SYSTEM_PROMPT, /await page\.pressKey\('Enter'\); await page\.scroll\(x, y, 600\)/);
});
