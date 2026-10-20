import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
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
import { RunContext, contextChars } from '../dist/context.js';
import { runAgent } from '../dist/agent.js';
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
const failure = (text) =>
  done(fauxAssistantMessage('', { stopReason: 'error', errorMessage: text }));
const finish = () =>
  done(
    fauxAssistantMessage(fauxToolCall('finish', { result: 'verified' }), { stopReason: 'toolUse' }),
  );
const history = () => [
  { role: 'user', content: 'Inspect only. Never submit.', timestamp: 1 },
  ...Array.from({ length: 6 }, () => fauxAssistantMessage('old observation '.repeat(1500))),
];
async function workspace(fn) {
  const path = await mkdtemp(join(tmpdir(), 'bu-retention-'));
  try {
    return await fn(path);
  } finally {
    await rm(path, { recursive: true, force: true });
  }
}
async function run(path, messages, streamFn, options = {}, config = {}) {
  let saved;
  const result = await runAgent(
    {
      beginRun() {},
      execute() {
        throw new Error('Browser actions must not replay');
      },
    },
    model,
    { model: 'faux/faux', streamFn, compactionTimeoutMs: 20, compactionRetryDelayMs: 1, ...config },
    path,
    'Continue inspection.',
    Type.String(),
    { timeoutMs: 3000, ...options },
    {
      messages,
      control: new RunControl(() => {}),
      save(value) {
        saved = value;
      },
    },
  );
  return { result, saved };
}

test('two oversized recent tool groups compact completely; original evidence remains retrievable', () =>
  workspace(async (path) => {
    const messages = [{ role: 'user', content: 'Inspect only. Never submit.', timestamp: 1 }];
    for (let turn = 0; turn < 2; turn++) {
      const calls = Array.from({ length: 8 }, (_, i) => ({
        type: 'toolCall',
        id: turn + '-' + i,
        name: 'observe',
        arguments: {},
      }));
      messages.push(fauxAssistantMessage(calls, { stopReason: 'toolUse' }));
      for (const call of calls)
        messages.push({
          role: 'toolResult',
          toolCallId: call.id,
          toolName: call.name,
          content: [{ type: 'text', text: 'captured observation '.repeat(1000) }],
          isError: false,
          timestamp: 2,
        });
    }
    const original = structuredClone(messages);
    const ctx = new RunContext(
      model,
      () => done(fauxAssistantMessage('Observations collected. Never submit.')),
      path,
      240000,
      true,
    );
    await ctx.prepare(messages, '');
    assert.equal(ctx.compactions, 1);
    assert(ctx.fits(messages, ''));
    assert(!ctx.project(messages).some((m) => m.role === 'assistant' || m.role === 'toolResult'));
    const checkpoint = ctx
      .project(messages)
      .find(
        (m) => typeof m.content === 'string' && m.content.includes('Evidence archive (JSON path):'),
      );
    const archive = JSON.parse(
      await readFile(
        join(
          path,
          JSON.parse(checkpoint.content.match(/^Evidence archive \(JSON path\): (.+)$/m)[1]),
        ),
        'utf8',
      ),
    );
    assert.deepEqual(
      archive.messages.filter((m) => m.role === 'toolResult').map((m) => m.toolCallId),
      original.filter((m) => m.role === 'toolResult').map((m) => m.toolCallId),
    );
    assert.equal(
      archive.messages.find((m) => m.toolCallId === '1-7').content[0].text,
      'captured observation '.repeat(1000),
    );
    assert.deepEqual(messages, original);
  }));

test('retained user text is bounded instead of accumulating every old user request', () =>
  workspace(async (path) => {
    const messages = Array.from({ length: 12 }, (_, i) => ({
      role: 'user',
      content: 'old-' + i + ' ' + 'x'.repeat(20000),
      timestamp: i,
    }));
    messages.push(
      { role: 'user', content: 'LATEST: never purchase.', timestamp: 20 },
      ...history().slice(1),
    );
    const ctx = new RunContext(
      model,
      () => done(fauxAssistantMessage('Keep the purchase restriction.')),
      path,
      150000,
      true,
    );
    await ctx.prepare(messages, '');
    assert(ctx.fits(messages, ''));
    assert.match(JSON.stringify(ctx.project(messages)), /LATEST: never purchase/);
    const retained = ctx
      .project(messages)
      .filter((m) => m.role === 'user' && !String(m.content).includes('Conversation checkpoint:'));
    assert(contextChars(retained) < 85000);
    assert(!JSON.stringify(ctx.project(messages)).includes('old-0 '));
  }));

test('an oversized first user message can compact without a prior assistant turn', () =>
  workspace(async (path) => {
    const messages = [
      { role: 'user', content: 'CURRENT TASK: ' + 'x'.repeat(500000), timestamp: 1 },
    ];
    const ctx = new RunContext(
      { ...model, contextWindow: 50000 },
      () =>
        done(fauxAssistantMessage('Continue current task; inspect archived request for details.')),
      path,
      100000,
      true,
    );
    await ctx.prepare(messages, '');
    assert.equal(ctx.compactions, 1);
    assert(ctx.fits(messages, ''));
    assert.match(JSON.stringify(ctx.project(messages)), /CURRENT TASK/);
  }));

test('summary context overflow retries with a smaller working copy and intact call/result pairs', () =>
  workspace(async (path) => {
    const messages = history();
    let calls = 0,
      first;
    const ctx = new RunContext(
      model,
      (_model, request) => {
        calls++;
        if (calls === 1) {
          first = JSON.stringify(request).length;
          return failure('maximum context length exceeded');
        }
        assert(JSON.stringify(request).length < first);
        return done(fauxAssistantMessage('Continue inspection.'));
      },
      path,
      50000,
      true,
    );
    const original = structuredClone(messages);
    await ctx.prepare(messages, '');
    assert.equal(calls, 2);
    assert(ctx.fits(messages, ''));
    assert.deepEqual(messages, original);
  }));

test('failed or oversized summaries never replace the last working history', () =>
  workspace(async (path) => {
    const messages = history(),
      original = structuredClone(messages);
    const ctx = new RunContext(
      model,
      () => done(fauxAssistantMessage('x'.repeat(100000))),
      path,
      50000,
      true,
    );
    await assert.rejects(ctx.prepare(messages, ''), /reduce|fit|budget/i);
    assert.equal(ctx.compactions, 0);
    assert.deepEqual(ctx.project(messages), original);
  }));

test('required compaction survives more than two summary failures and reports waiting then resumed', () =>
  workspace(async (path) => {
    let summaries = 0,
      inference = 0;
    const states = [];
    const { result } = await run(
      path,
      history(),
      (_model, request) => {
        if (!getCurrentTools(request.messages).length) {
          summaries++;
          return summaries < 4
            ? failure('Connection error.')
            : done(fauxAssistantMessage('Inspection evidence archived.'));
        }
        inference++;
        return finish();
      },
      { maxContextChars: 50000, onContextRecovery: (state) => states.push(state.state) },
    );
    assert.equal(result.status, 'completed', result.error);
    assert.equal(summaries, 4);
    assert.equal(inference, 1);
    assert.equal(result.context.compactionFailures, 3);
    assert.deepEqual(states, ['waiting', 'resumed']);
  }));

test('separate compactions have separate retry budgets; completed actions execute once', () =>
  workspace(async (path) => {
    let summaries = 0,
      inference = 0,
      actions = 0;
    const { result } = await run(
      path,
      history(),
      (_model, request) => {
        if (!getCurrentTools(request.messages).length) {
          summaries++;
          return summaries % 2
            ? failure('Connection error.')
            : done(fauxAssistantMessage('Completed observations archived; do not replay.'));
        }
        inference++;
        return inference <= 3
          ? done(fauxAssistantMessage(fauxToolCall('observe', {}), { stopReason: 'toolUse' }))
          : finish();
      },
      { maxContextChars: 50000 },
      {
        tools: [
          {
            name: 'observe',
            label: 'observe',
            description: 'Observe once',
            parameters: Type.Object({}),
            async execute() {
              actions++;
              return { content: [{ type: 'text', text: 'captured '.repeat(10000) }], details: {} };
            },
          },
        ],
      },
    );
    assert.equal(result.status, 'completed', result.error);
    assert.equal(actions, 3);
    assert.equal(inference, 4);
    assert.equal(result.compactions, 4);
    assert.equal(result.context.compactionFailures, 4);
  }));

test('cancelling context recovery retains original evidence and makes no further requests', () =>
  workspace(async (path) => {
    const controller = new AbortController(),
      messages = history();
    let calls = 0,
      waiting = false;
    const { result, saved } = await run(
      path,
      messages,
      () => {
        calls++;
        return failure('Connection error.');
      },
      {
        maxContextChars: 50000,
        signal: controller.signal,
        onContextRecovery: (event) => {
          if (event.state === 'waiting') {
            waiting = true;
            controller.abort();
          }
        },
      },
    );
    assert(waiting);
    assert.equal(result.status, 'cancelled');
    assert.equal(calls, 1);
    assert.deepEqual(saved.slice(0, messages.length), messages);
  }));

test('provider context rejection triggers compaction and retries inference without replaying actions', () =>
  workspace(async (path) => {
    let inference = 0,
      summaries = 0;
    const { result } = await run(path, history(), (_model, request) => {
      if (!getCurrentTools(request.messages).length) {
        summaries++;
        return done(fauxAssistantMessage('Evidence archived.'));
      }
      inference++;
      return inference === 1 ? failure('maximum context length exceeded') : finish();
    });
    assert.equal(result.status, 'completed', result.error);
    assert.equal(summaries, 1);
    assert.equal(inference, 2);
  }));

test('waiting saves a restartable checkpoint before notifying the host; restart does not replay actions', () =>
  workspace(async (path) => {
    const { BrowserUse } = await import('../dist/index.js');
    const { createModels } = await import('@earendil-works/pi-ai');
    const provider = fauxProvider(),
      models = createModels();
    models.setProvider(provider.provider);
    models.getModel(provider.getModel().provider, provider.getModel().id).contextWindow = 50000;
    let actions = 0,
      inference = 0,
      waitingHistory;
    const controller = new AbortController();
    const agent = await BrowserUse.create({
      model: provider.getModel().provider + '/' + provider.getModel().id,
      models,
      workspace: path,
      browser: { kind: 'pending' },
      telemetry: false,
      compactionRetryDelayMs: 1,
      tools: [
        {
          name: 'observe',
          label: 'observe',
          description: 'Record one completed observation',
          parameters: Type.Object({}),
          async execute() {
            actions++;
            return {
              content: [{ type: 'text', text: 'EXACT_OBSERVATION_73 '.repeat(16000) }],
              details: {},
            };
          },
        },
      ],
      streamFn: (_model, request) => {
        if (!getCurrentTools(request.messages).length) return failure('Connection error.');
        inference++;
        return done(fauxAssistantMessage(fauxToolCall('observe', {}), { stopReason: 'toolUse' }));
      },
    });
    let restored;
    try {
      const result = await agent.run('Inspect once. Never submit.', {
        signal: controller.signal,
        onContextRecovery: async (event) => {
          assert.equal(event.state, 'waiting');
          waitingHistory = JSON.parse(
            await readFile(join(path, '.browser-use/session.json'), 'utf8'),
          );
          assert.match(JSON.stringify(waitingHistory), /EXACT_OBSERVATION_73/);
          controller.abort();
        },
      });
      assert.equal(result.status, 'cancelled');
      assert.equal(actions, 1);
      assert.equal(inference, 1);
      await agent.close();
      restored = await BrowserUse.create({
        model: agent.history.model,
        models,
        workspace: path,
        historyFile: join(path, '.browser-use/session.json'),
        browser: { kind: 'pending' },
        telemetry: false,
        streamFn: async (_model, request) => {
          if (!getCurrentTools(request.messages).length)
            return done(
              fauxAssistantMessage(
                'A prior observation completed; inspect its archive before continuing.',
              ),
            );
          const checkpoint = request.messages.find(
            (m) =>
              typeof m.content === 'string' && m.content.startsWith('Conversation checkpoint:'),
          );
          assert(checkpoint);
          const archivePath = JSON.parse(
            checkpoint.content.match(/^Evidence archive \(JSON path\): (.+)$/m)[1],
          );
          assert.match(await readFile(join(path, archivePath), 'utf8'), /EXACT_OBSERVATION_73/);
          return finish();
        },
      });
      const next = await restored.followUp('Continue with the saved observation.', {
        timeoutMs: 3000,
      });
      assert.equal(next.status, 'completed', next.error);
      assert.equal(actions, 1);
      assert(waitingHistory.messages.some((m) => m.toolName === 'observe'));
    } finally {
      await restored?.close();
      await agent.close();
    }
  }));

test('each overflow-shrinking summary request honors the remaining cost budget', () =>
  workspace(async (path) => {
    let calls = 0;
    const { result } = await run(
      path,
      history(),
      () => {
        calls++;
        const error = fauxAssistantMessage('', {
          stopReason: 'error',
          errorMessage: 'maximum context length exceeded',
        });
        error.usage = structuredClone(error.usage);
        error.usage.cost.total = 1;
        return done(error);
      },
      { maxContextChars: 50000, maxCostUsd: 0.5 },
    );
    assert.equal(result.status, 'cost_limit');
    assert.equal(calls, 1);
    assert.equal(result.usage.cost.total, 1);
  }));

test('an unrecovered outage waits within the original deadline and retains evidence', () =>
  workspace(async (path) => {
    let waiting = false,
      calls = 0;
    const messages = history();
    const { result, saved } = await run(
      path,
      messages,
      () => {
        calls++;
        return failure('Connection error.');
      },
      {
        maxContextChars: 50000,
        timeoutMs: 80,
        onContextRecovery: (e) => {
          waiting ||= e.state === 'waiting';
        },
      },
      { compactionRetryDelayMs: 1000 },
    );
    assert(waiting);
    assert.equal(calls, 1);
    assert.equal(result.status, 'timeout');
    assert.deepEqual(saved.slice(0, messages.length), messages);
  }));

test('checkpoint upload failures wait and retry before any further inference', () =>
  workspace(async (path) => {
    let callbacks = 0,
      summaries = 0,
      inference = 0;
    const { result } = await run(
      path,
      history(),
      (_model, request) => {
        if (!getCurrentTools(request.messages).length) {
          summaries++;
          return summaries === 1
            ? failure('Connection error.')
            : done(fauxAssistantMessage('Evidence archived.'));
        }
        inference++;
        return finish();
      },
      {
        maxContextChars: 50000,
        onContextRecovery: (event) => {
          callbacks++;
          if (callbacks === 1) throw new Error('Checkpoint upload temporarily unavailable');
        },
      },
    );
    assert.equal(result.status, 'completed', result.error);
    assert.equal(callbacks, 3);
    assert.equal(inference, 1);
  }));

test('multiple context-rejected inference responses preserve all reported costs even with zero token counts', () =>
  workspace(async (path) => {
    let inference = 0,
      summaries = 0;
    const { result } = await run(path, history(), (_model, request) => {
      if (!getCurrentTools(request.messages).length)
        return done(
          fauxAssistantMessage(++summaries === 1 ? 'Evidence '.repeat(150) : 'Evidence archived.'),
        );
      if (++inference === 3) return finish();
      const error = fauxAssistantMessage('', {
        stopReason: 'error',
        errorMessage: 'maximum context length exceeded',
      });
      error.usage = structuredClone(error.usage);
      error.usage.cost.total = 1;
      return done(error);
    });
    assert.equal(result.status, 'completed', result.error);
    assert.equal(result.usage.cost.total, 2);
    assert.equal(inference, 3);
  }));

test('shrinking the final oversized tool group keeps completed-action evidence in the summary input', () =>
  workspace(async (path) => {
    const messages = [
      { role: 'user', content: 'Inspect the existing order.', timestamp: 1 },
      fauxAssistantMessage(fauxToolCall('observe', {}), { stopReason: 'toolUse' }),
    ];
    messages.push({
      role: 'toolResult',
      toolCallId: messages[1].content[0].id,
      toolName: 'observe',
      content: [
        {
          type: 'text',
          text: 'ORDER_ALREADY_SUBMITTED ' + 'details '.repeat(50000) + ' CONFIRMATION_ID=73',
        },
      ],
      isError: false,
      timestamp: 2,
    });
    let summaries = 0;
    const ctx = new RunContext(
      { ...model, contextWindow: 10000 },
      (_model, request) => {
        summaries++;
        assert.match(JSON.stringify(request), /ORDER_ALREADY_SUBMITTED/);
        assert.match(JSON.stringify(request), /CONFIRMATION_ID=73/);
        assert.match(JSON.stringify(request), /observe/);
        return done(
          fauxAssistantMessage('Order already submitted; confirmation 73. Do not submit again.'),
        );
      },
      path,
      30000,
      true,
    );
    await ctx.prepare(messages, '');
    assert.equal(ctx.compactions, 1);
    assert.equal(summaries, 1);
  }));

test('evidence archive references survive a different workspace root', () =>
  workspace(async (path) => {
    const ctx = new RunContext(
      model,
      () => done(fauxAssistantMessage('Observations archived.')),
      path,
      50000,
      true,
    );
    const messages = history();
    await ctx.prepare(messages, '');
    const checkpoint = ctx
      .project(messages)
      .find(
        (m) => typeof m.content === 'string' && m.content.startsWith('Conversation checkpoint:'),
      );
    const archivePath = JSON.parse(
      checkpoint.content.match(/^Evidence archive \(JSON path\): (.+)$/m)[1],
    );
    assert.equal(archivePath.startsWith('/'), false);
    assert.match(await readFile(join(path, archivePath), 'utf8'), /old observation/);
  }));
