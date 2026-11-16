import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Type } from 'typebox';
import {
  createAssistantMessageEventStream,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { deadlineStream } from '../dist/model-stream.js';
import { runAgent } from '../dist/agent.js';
import { RunContext } from '../dist/context.js';

const model = fauxProvider().getModel();
const request = { messages: [] };
test('response deadline bounds hung setup and a stream with no terminal event', async () => {
  for (const phase of ['setup', 'stream']) {
    let signal;
    const bounded = deadlineStream((_m, _c, opts) => {
      signal = opts.signal;
      return phase === 'setup' ? new Promise(() => {}) : createAssistantMessageEventStream();
    }, 20);
    const result = await bounded(model, request).result();
    assert.equal(result.stopReason, 'error');
    assert.match(result.errorMessage, /exceeded 20 ms/);
    assert.equal(signal.aborted, true);
  }
});

test('abort wins immediately and late provider completion cannot mutate partial evidence', async () => {
  const upstream = createAssistantMessageEventStream();
  const partial = fauxAssistantMessage(fauxToolCall('javascript', { code: 'mutate()' }), {
    stopReason: 'toolUse',
  });
  partial.usage.cost.total = 0.25;
  const controller = new AbortController();
  const stream = deadlineStream(() => upstream, 1000)(model, request, {
    signal: controller.signal,
  });
  upstream.push({ type: 'start', partial });
  await new Promise((resolve) => setImmediate(resolve));
  controller.abort();
  const result = await stream.result();
  partial.usage.cost.total = 99;
  upstream.push({ type: 'done', reason: 'toolUse', message: partial });
  upstream.end();
  assert.equal(result.stopReason, 'aborted');
  assert.equal(result.usage.cost.total, 0.25);
  assert.equal((await Array.fromAsync(stream)).filter((e) => e.type === 'done').length, 0);
});

test('pre-abort makes no provider request; terminal responses preserve signatures and usage', async () => {
  let calls = 0;
  const message = fauxAssistantMessage([
    { type: 'thinking', thinking: 'ok', thinkingSignature: 'opaque' },
  ]);
  const bounded = deadlineStream(() => {
    calls++;
    const stream = createAssistantMessageEventStream();
    stream.push({ type: 'done', reason: 'stop', message });
    stream.end();
    return stream;
  }, 20);
  assert.equal(
    (await bounded(model, request, { signal: AbortSignal.abort() }).result()).stopReason,
    'aborted',
  );
  assert.equal(calls, 0);
  assert.equal(await bounded(model, request).result(), message);
});

test('a timed-out inference starts a new step without executing partial tools or resetting budgets', async () => {
  const path = await mkdtemp(join(tmpdir(), 'bu-stream-'));
  try {
    for (const mode of ['recover', 'repeat', 'deadline']) {
      let calls = 0,
        tools = 0;
      const result = await runAgent(
        {
          beginRun() {},
          execute: async () => {
            tools++;
            throw new Error('unsafe');
          },
        },
        model,
        {
          model: 'faux/faux',
          modelTimeoutMs: mode === 'deadline' ? 1000 : 20,
          modelStreamTimeoutMs: mode === 'deadline' ? 1000 : 20,
          streamFn: () => {
            calls++;
            const stream = createAssistantMessageEventStream();
            if (mode === 'recover' && calls === 2) {
              const message = fauxAssistantMessage(
                fauxToolCall('finish', { result: 'recovered' }),
                { stopReason: 'toolUse' },
              );
              stream.push({ type: 'done', reason: 'toolUse', message });
              stream.end();
            } else {
              const partial = fauxAssistantMessage(
                fauxToolCall('javascript', { code: 'mutate()' }),
                { stopReason: 'toolUse' },
              );
              stream.push({ type: 'start', partial });
            }
            return stream;
          },
        },
        path,
        'Inspect',
        Type.String(),
        // repeat: steps 1 and 2 time out, step 2 starts the delivery turn, step 3 is the last (maxSteps).
        { timeoutMs: mode === 'deadline' ? 30 : 2000, maxSteps: 3 },
      );
      assert.equal(
        result.status,
        { recover: 'completed', repeat: 'max_steps', deadline: 'timeout' }[mode],
      );
      assert.equal(result.providerRetries, { recover: 1, repeat: 2, deadline: 0 }[mode]);
      assert.equal(calls, { recover: 2, repeat: 3, deadline: 1 }[mode]);
      assert.equal(tools, 0);
    }
  } finally {
    await rm(path, { recursive: true, force: true });
  }
});

test('timed-out compaction retains original context and never commits a late summary', async () => {
  const path = await mkdtemp(join(tmpdir(), 'bu-summary-'));
  try {
    const upstream = createAssistantMessageEventStream();
    const context = new RunContext(
      model,
      deadlineStream(() => upstream, 20),
      path,
      3000,
      true,
    );
    const messages = [{ role: 'user', content: 'Never submit.', timestamp: 1 }];
    for (let i = 0; i < 6; i++) messages.push(fauxAssistantMessage('evidence '.repeat(100)));
    await assert.rejects(context.prepare(messages, ''), /exceeded/);
    const late = fauxAssistantMessage('incorrect late summary');
    upstream.push({ type: 'done', reason: 'stop', message: late });
    upstream.end();
    assert.equal(context.compactions, 0);
    assert.deepEqual(context.project(messages), messages);
  } finally {
    await rm(path, { recursive: true, force: true });
  }
});
