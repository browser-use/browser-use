import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { showLiveView } from '../dist/browser.js';
import { JUDGE_PROMPT } from '../dist/judge.js';
import { DEFAULT_MODEL } from '../dist/gateway.js';

test('Python 1.0.6: default model is bu-4.0', () => {
  assert.equal(DEFAULT_MODEL, 'browser-use/bu-4.0');
});

test('Python 1.0.6: live view link is printed, not opened, unless asked', () => {
  const lines = [];
  showLiveView('https://live.example/abc', false, (line) => lines.push(line));
  assert.deepEqual(lines, ['Live view: https://live.example/abc\n']);
  // A failing writer never fails the browser.
  assert.doesNotThrow(() =>
    showLiveView('https://live.example/abc', false, () => {
      throw new Error('EPIPE');
    }),
  );
});

test('Python 1.0.6: judge prompt grounds gotchas in observed evidence', () => {
  assert.match(JUDGE_PROMPT, /Base every factual claim on the visible trace or screenshots\./);
  assert.match(
    JUDGE_PROMPT,
    /Distinguish website responses from model, tool, and environment errors\./,
  );
  assert.doesNotMatch(JUDGE_PROMPT, /Write the lesson, not the event/);
  assert.match(
    readFileSync(new URL('../src/judge.ts', import.meta.url), 'utf8'),
    /Lessons from observed website/,
  );
});
