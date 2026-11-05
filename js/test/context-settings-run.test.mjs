import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { Type } from 'typebox';
import { runAgent } from '../dist/agent.js';
import { RunControl } from '../dist/control.js';

const image = { type: 'image', data: 'AAAA', mimeType: 'image/png' };
const call = (name, args) =>
  fauxAssistantMessage(fauxToolCall(name, args), { stopReason: 'toolUse' });
const finish = () => call('finish', { result: 'done' });
const history = () => [
  { role: 'user', content: 'initial', timestamp: 1 },
  ...Array.from({ length: 6 }, (_, i) => [
    fauxAssistantMessage(fauxToolCall('javascript', { code: '1' }), {
      stopReason: 'toolUse',
      timestamp: 2 + i,
    }),
    {
      role: 'toolResult',
      toolCallId: 't' + i,
      toolName: 'javascript',
      content: [{ type: 'text', text: 'x'.repeat(40000) }, image],
      isError: false,
      timestamp: 10 + i,
    },
  ]).flat(),
];

async function run(options, responses) {
  const path = await mkdtemp(join(tmpdir(), 'bu-context-settings-'));
  try {
    const faux = fauxProvider({ tokensPerSecond: 1e6 });
    const models = createModels();
    models.setProvider(faux.provider);
    const requests = [];
    const control = new RunControl(() => {});
    faux.setResponses(responses.map((r) => (typeof r === 'function' ? () => r(control) : r)));
    const streamFn = (model, context, settings) => {
      requests.push(structuredClone(context));
      return models.streamSimple(model, context, settings);
    };
    const runtime = {
      beginRun() {},
      async execute() {
        return { text: 'ok', images: [image] };
      },
    };
    const result = await runAgent(
      runtime,
      { ...faux.getModel(), contextWindow: 250000 },
      { streamFn },
      path,
      'task',
      Type.String(),
      { maxSteps: 10, ...options },
      { messages: history(), control, save() {} },
    );
    return { requests, result };
  } finally {
    await rm(path, { recursive: true, force: true });
  }
}
const result = (request, timestamp) =>
  request.messages.find((m) => m.role === 'toolResult' && m.timestamp === timestamp);
const hasImage = (message) => message.content.some((c) => c.type === 'image');

test('a run keeps its trimmed prefix unchanged between trims', async () => {
  const { requests } = await run({ context: { trimAtTokens: 20000, keepScreenshots: 2 } }, [
    call('javascript', { code: '1' }),
    call('javascript', { code: '1' }),
    finish(),
  ]);
  assert.equal(hasImage(result(requests[0], 10)), false);
  assert.equal(hasImage(result(requests[2], 10)), false);
  assert.deepEqual(result(requests[2], 10), result(requests[0], 10));
});

test('compact() summarizes before the next model call', async () => {
  const { requests, result: outcome } = await run({}, [
    (control) => {
      control.compact();
      return call('javascript', { code: '1' });
    },
    fauxAssistantMessage('checkpoint'),
    finish(),
  ]);
  assert.equal(outcome.status, 'completed');
  assert.ok(JSON.stringify(requests.at(-1)).includes('Conversation checkpoint:'));
});

test('compact() refuses when compaction is disabled for the run', async () => {
  let refused;
  await run({ compaction: false }, [
    (control) => {
      try {
        control.compact();
      } catch (error) {
        refused = error;
      }
      return finish();
    },
  ]);
  assert.match(refused.message, /disabled/);
});
