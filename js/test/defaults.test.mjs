import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getCurrentTools } from '@earendil-works/pi-ai';
import { scripted, call } from './run-helper.mjs';
import {
  DEFAULT_CELL_TIMEOUT_MS,
  DEFAULT_MAX_STEPS,
  DEFAULT_OPERATION_TIMEOUT_MS,
  DEFAULT_RUN_TIMEOUT_MS,
} from '../dist/protocol.js';

test('defaults match Python browser-use 1.0.5', () => {
  assert.equal(DEFAULT_MAX_STEPS, 100);
  assert.equal(DEFAULT_RUN_TIMEOUT_MS, 1_700_000);
  assert.equal(DEFAULT_CELL_TIMEOUT_MS, 120_000);
  assert.equal(DEFAULT_OPERATION_TIMEOUT_MS, 20_000);
});

test('a run without limits uses 120 s cells and is not near its delivery turn', async () => {
  const seen = [];
  const { result, requests } = await scripted(
    [call('javascript', { code: '1' }), call('finish', { result: 'ok' })],
    {
      options: { maxSteps: undefined },
      runtime: {
        async execute(code, timeoutMs, signal, capMs) {
          seen.push({ timeoutMs, capMs });
          return { text: 'ok', images: [] };
        },
      },
    },
  );
  assert.equal(result.status, 'completed');
  assert.equal(seen[0].timeoutMs, 120_000);
  // 1700 s run: the delivery turn starts at 1530 s, so the cap is far above the cell deadline.
  assert.ok(seen[0].capMs > 1_500_000);
  const tool = getCurrentTools(requests[0].messages).find((t) => t.name === 'javascript');
  assert.match(tool.description, /Cell deadline: 120000 ms/);
  assert.doesNotMatch(JSON.stringify(requests[1].messages), /Budget nearly exhausted/);
});
