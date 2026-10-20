import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Type } from 'typebox';
import {
  createAssistantMessageEventStream,
  fauxAssistantMessage,
  fauxProvider,
  fauxToolCall,
  getCurrentTools,
} from '@earendil-works/pi-ai';
import { runAgent } from '../dist/agent.js';
import { RunContext, contextChars } from '../dist/context.js';
import { RunControl } from '../dist/control.js';

const model = { ...fauxProvider().getModel(), contextWindow: 250000 };
const done = (message) => {
  const stream = createAssistantMessageEventStream();
  stream.push(
    message.stopReason === 'error'
      ? { type: 'error', reason: 'error', error: message }
      : { type: 'done', reason: message.stopReason, message },
  );
  stream.end();
  return stream;
};
const finish = () =>
  done(
    fauxAssistantMessage(fauxToolCall('finish', { result: 'verified' }), { stopReason: 'toolUse' }),
  );
const history = () => [
  { role: 'user', content: 'Never submit. Preserve all evidence.', timestamp: 1 },
  ...Array.from({ length: 6 }, () => fauxAssistantMessage('x'.repeat(12000))),
];
async function run(
  messages,
  streamFn,
  options = {},
  config = {},
  selectedModel = model,
  control = new RunControl(() => {}),
) {
  const path = await mkdtemp(join(tmpdir(), 'bu-context-budget-'));
  let saved;
  try {
    const result = await runAgent(
      {
        beginRun() {},
        execute() {
          throw new Error('Prior actions must never be replayed');
        },
      },
      selectedModel,
      { model: 'faux/faux', streamFn, compactionTimeoutMs: 20, ...config },
      path,
      'Continue inspection.',
      Type.String(),
      { timeoutMs: 3000, ...options },
      {
        messages,
        control,
        save(value) {
          saved = value;
        },
      },
    );
    return { result, saved };
  } finally {
    await rm(path, { recursive: true, force: true });
  }
}
function recentGroups() {
  const groups = [];
  for (let turn = 0; turn < 2; turn++) {
    const calls = Array.from({ length: 8 }, (_, tool) => ({
      type: 'toolCall',
      id: `observed-${turn}-${tool}`,
      name: 'javascript',
      arguments: { code: `inspect(${turn}, ${tool})` },
    }));
    groups.push(fauxAssistantMessage(calls, { stopReason: 'toolUse' }));
    for (const call of calls)
      groups.push({
        role: 'toolResult',
        toolCallId: call.id,
        toolName: call.name,
        content: [{ type: 'text', text: 'x'.repeat(18000) }],
        isError: false,
        timestamp: 2,
      });
  }
  groups[1].content[0].text += 'x'.repeat(311336 - contextChars(groups));
  assert.equal(contextChars(groups), 311336);
  return groups;
}

test('model-sized default preserves both 311336-character recent turns verbatim', async () => {
  const recent = recentGroups();
  let requests = 0;
  const { result, saved } = await run(
    [{ role: 'user', content: 'Never submit.', timestamp: 1 }, ...recent],
    (_model, request) => {
      requests++;
      const from = request.messages.findIndex((m) => m.role === 'assistant');
      assert.deepEqual(request.messages.slice(from, from + recent.length), recent);
      return finish();
    },
  );
  assert.equal(result.status, 'completed', result.error?.slice(0, 1000));
  assert.equal(requests, 1);
  assert.deepEqual(saved.slice(1, recent.length + 1), recent);
});

test('timed-out compaction recovers, retains user constraints and counts partial usage once', async () => {
  let summaries = 0,
    inference = 0,
    aborted = false,
    late;
  const messages = history();
  const { result } = await run(
    messages,
    (_model, request, settings) => {
      if (getCurrentTools(request.messages).length) {
        inference++;
        assert(!request.messages.some((m) => m.role === 'assistant'));
        assert.match(JSON.stringify(request.messages), /Never submit/);
        return finish();
      }
      summaries++;
      if (summaries === 1) {
        settings.signal.addEventListener('abort', () => {
          aborted = true;
        });
        late = createAssistantMessageEventStream();
        const partial = fauxAssistantMessage('partial summary');
        partial.usage = structuredClone(partial.usage);
        partial.usage.cost.total = 0.125;
        late.push({ type: 'start', partial });
        return late;
      }
      return done(fauxAssistantMessage('Evidence archived. Never submit.'));
    },
    { maxContextChars: 50000 },
  );
  assert.equal(result.status, 'completed', result.error?.slice(0, 1000));
  assert.equal(summaries, 2);
  assert.equal(inference, 1);
  assert.equal(aborted, true);
  assert.equal(result.compactions, 1);
  assert.equal(result.usage.cost.total, 0.125);
  assert.equal(result.context.compactionFailures, 1);
  assert.equal(result.context.lastCompactionFailure, 'timeout');
  late.push({
    type: 'done',
    reason: 'stop',
    message: fauxAssistantMessage('late incorrect summary'),
  });
  late.end();
});

test('repeated timeouts wait until the original run deadline and retain history', async () => {
  let calls = 0;
  const messages = history(),
    original = structuredClone(messages);
  const { result, saved } = await run(
    messages,
    () => {
      calls++;
      return createAssistantMessageEventStream();
    },
    { maxContextChars: 50000, timeoutMs: 300 },
  );
  assert.equal(result.status, 'timeout');
  assert.equal(calls, 1);
  assert.equal(result.compactions, 0);
  assert.deepEqual(saved.slice(0, original.length), original);
  assert.equal(result.context.compactionFailures, 1);
  assert.equal(result.context.lastCompactionFailure, 'timeout');
  assert(result.context.chars > result.context.maxChars);
});

for (const stop of ['cancelled', 'timeout', 'cost_limit', 'deterministic']) {
  test(`compaction recovery respects ${stop} and makes no extra requests`, async () => {
    const controller = new AbortController();
    let calls = 0;
    const { result } = await run(
      history(),
      (_model, _request, settings) => {
        calls++;
        const stream = createAssistantMessageEventStream();
        if (stop === 'cancelled') controller.abort();
        if (stop === 'deterministic' || stop === 'cost_limit') {
          const message = fauxAssistantMessage('', {
            stopReason: 'error',
            errorMessage:
              stop === 'deterministic' ? 'Access denied: private-token' : 'Connection error.',
          });
          if (stop === 'cost_limit') {
            message.usage = structuredClone(message.usage);
            message.usage.cost.total = 1;
          }
          stream.push({ type: 'error', reason: 'error', error: message });
          stream.end();
        }
        if (stop === 'timeout') assert(settings.signal);
        return stream;
      },
      {
        maxContextChars: 50000,
        signal: controller.signal,
        ...(stop === 'timeout'
          ? { timeoutMs: 300 }
          : stop === 'deterministic'
            ? { timeoutMs: 300 }
            : {}),
        ...(stop === 'cost_limit' ? { maxCostUsd: 0.5 } : {}),
      },
      stop === 'timeout' ? { compactionTimeoutMs: 1000 } : {},
    );
    assert.equal(result.status, stop === 'deterministic' ? 'timeout' : stop);
    assert.equal(calls, 1);
    if (stop === 'deterministic') {
      assert.equal(result.context.lastCompactionFailure, 'error');
      assert(!JSON.stringify(result.context).includes('private-token'));
    }
  });
}

test('tool schemas count against the model budget before a provider request', async () => {
  let requests = 0;
  const { result } = await run(
    [],
    () => {
      requests++;
      return finish();
    },
    {},
    {
      tools: [
        {
          name: 'huge',
          label: 'huge',
          description: 'x'.repeat(900000),
          parameters: Type.Object({}),
          execute() {
            throw new Error('must not execute');
          },
        },
      ],
    },
  );
  assert.equal(result.status, 'context_limit');
  assert.equal(requests, 0);
});

test('non-reducing summaries retain original evidence and have a sanitized diagnostic', async () => {
  const messages = history(),
    original = structuredClone(messages);
  const { result, saved } = await run(
    messages,
    () => done(fauxAssistantMessage('x'.repeat(100000))),
    { maxContextChars: 50000, timeoutMs: 300 },
  );
  assert.equal(result.status, 'timeout');
  assert.equal(result.compactions, 0);
  assert.equal(result.context.lastCompactionFailure, 'not_reduced');
  assert.deepEqual(saved.slice(0, original.length), original);
});

test('successful compaction cannot spend past the cost limit and then start inference', async () => {
  let calls = 0;
  const { result } = await run(
    history(),
    () => {
      calls++;
      const summary = fauxAssistantMessage('Evidence archived.');
      summary.usage = structuredClone(summary.usage);
      summary.usage.cost.total = 1;
      return done(summary);
    },
    { maxContextChars: 50000, maxCostUsd: 0.5 },
  );
  assert.equal(result.status, 'cost_limit');
  assert.equal(calls, 1);
  assert.equal(result.compactions, 1);
  assert.equal(result.usage.cost.total, 1);
});

for (const compaction of [true, false]) {
  test(`delivery repair budgets its reduced tool schemas; compaction=${compaction}`, async () => {
    let requests = 0;
    const { result } = await run(
      [],
      (_model, request) => {
        if (!getCurrentTools(request.messages).length)
          return done(fauxAssistantMessage('Continue the task.'));
        requests++;
        const names = getCurrentTools(request.messages).map((tool) => tool.name);
        if (requests === 1) {
          assert(names.includes('huge'));
          return done(fauxAssistantMessage('answer'.repeat(1000)));
        }
        assert.deepEqual(names, ['finish', 'finish_from_js']);
        return finish();
      },
      { compaction },
      {
        tools: [
          {
            name: 'huge',
            label: 'huge',
            description: 'x'.repeat(23000),
            parameters: Type.Object({}),
            execute() {
              throw new Error('must not execute');
            },
          },
        ],
      },
      { ...model, contextWindow: 10000 },
    );
    assert.equal(result.status, 'completed', result.error?.slice(0, 1000));
    assert.equal(result.finishRepairs, 1);
    assert.equal(requests, 2);
  });
}

test('steering after a text-only stop retains ordinary tools until delivery', async () => {
  const control = new RunControl(() => {});
  let requests = 0;
  const { result } = await run(
    [],
    (_model, request) => {
      requests++;
      if (requests === 1) return done(fauxAssistantMessage('Continuing the inspection.'));
      if (requests === 2)
        return done(
          fauxAssistantMessage('', { stopReason: 'error', errorMessage: 'Connection error.' }),
        );
      assert(
        getCurrentTools(request.messages).some((tool) => tool.name === 'javascript'),
        'steered continuation must retain browser tools',
      );
      return finish();
    },
    {
      onEvent(event) {
        if (
          event.type === 'message_end' &&
          event.message.role === 'assistant' &&
          event.message.stopReason === 'stop'
        )
          control.steer('Continue inspecting before delivery.');
      },
    },
    {},
    model,
    control,
  );
  assert.equal(result.status, 'completed', result.error);
  assert.equal(result.finishRepairs, 0);
  assert.equal(result.providerRetries, 1);
  assert.equal(requests, 3);
});
