import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { scripted, call } from './run-helper.mjs';
import { deadlineStream } from '../dist/model-stream.js';

// timeoutMs 2000: Python delivery_at = 2000 - max(200, min(30000, 1000)) = 1000 ms.
test('cells are capped at the time left before the delivery turn, which then still runs', async () => {
  const caps = [];
  const { result, requests } = await scripted(
    [
      {
        ...call('javascript', { code: 'slow' }),
        content: [
          { type: 'toolCall', id: 'a', name: 'javascript', arguments: { code: 'slow' } },
          { type: 'toolCall', id: 'b', name: 'javascript', arguments: { code: 'late' } },
        ],
      },
      call('finish', { result: 'delivered' }),
    ],
    {
      options: { timeoutMs: 2000 },
      runtime: {
        async execute(code, timeoutMs, signal, capMs) {
          caps.push({ code, timeoutMs, capMs });
          await delay(1100);
          return { text: 'ok', images: [] };
        },
      },
    },
  );
  assert.equal(result.status, 'completed');
  assert.equal(result.output, 'delivered');
  assert.equal(caps.length, 1, 'the second cell of the same response is not run');
  assert.ok(caps[0].capMs <= 1000 && caps[0].capMs >= 900, `cap ${caps[0].capMs}`);
  const second = requests[1].messages.filter((m) => m.role === 'toolResult');
  assert.match(second.at(-1).content[0].text, /^Not run: the time budget is spent/);
  assert.match(JSON.stringify(requests[1].messages.at(-1)), /Budget nearly exhausted/);
});

test('a function deadline is read when each request starts', async () => {
  let budget = 50;
  const hang = () => ({
    async *[Symbol.asyncIterator]() {
      await new Promise(() => {});
    },
  });
  const stream = deadlineStream(hang, () => budget);
  const started = Date.now();
  const first = await stream({ api: 'x', provider: 'p', id: 'm' }, { messages: [] }, {}).result();
  assert.equal(first.stopReason, 'error');
  assert.match(first.errorMessage, /exceeded 50 ms/);
  budget = 20;
  const second = await stream({ api: 'x', provider: 'p', id: 'm' }, { messages: [] }, {}).result();
  assert.match(second.errorMessage, /exceeded 20 ms/);
  assert.ok(Date.now() - started < 2000);
});
