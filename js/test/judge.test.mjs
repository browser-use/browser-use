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
import { JUDGE_PROMPT, judgeRun, screenshots, trace, MAX_TRACE_CHARS } from '../dist/judge.js';
import { BrowserUse } from '../dist/index.js';

const verdict = {
  success: true,
  failureReason: null,
  description: 'Found the title.',
  promptInjectionDetected: false,
  botBlockOrCaptchaDetected: false,
  gotchas: ['a', 'b', 'c', 'd', 'e', 'f'],
};
const judged = (args = verdict) =>
  fauxAssistantMessage(fauxToolCall('judgement', args), { stopReason: 'toolUse' });
const image = (n) => ({
  type: 'image',
  data: Buffer.from(`img${n}`).toString('base64'),
  mimeType: 'image/png',
});
const shotResult = (n) => ({
  role: 'toolResult',
  toolCallId: `c${n}`,
  toolName: 'javascript',
  content: [{ type: 'text', text: `cell ${n}` }, image(n)],
  isError: false,
  timestamp: n,
});

function faux(input = ['text', 'image']) {
  const provider = fauxProvider({ tokensPerSecond: 1e6, models: [{ id: 'judge-test', input }] });
  const models = createModels();
  models.setProvider(provider.provider);
  const requests = [];
  const streamFn = (model, context, options) => {
    requests.push({ context: structuredClone(context), options });
    return models.streamSimple(model, context, options);
  };
  return { provider, models, model: provider.getModel(), streamFn, requests };
}

test('trace drops reasoning and images and keeps start and end; screenshots are the last 4 distinct, oldest first', () => {
  const messages = [
    { role: 'user', content: 'task', timestamp: 0 },
    {
      role: 'assistant',
      content: [
        { type: 'thinking', thinking: 'secret plan' },
        { type: 'toolCall', id: 'c1', name: 'javascript', arguments: { code: 'x'.repeat(6000) } },
      ],
      timestamp: 1,
    },
    shotResult(1),
    shotResult(2),
    shotResult(2),
    shotResult(3),
    shotResult(4),
  ];
  const text = trace(messages);
  assert.doesNotMatch(text, /secret plan/);
  assert.match(text, /\[Image omitted from text archive\]/);
  assert.match(text, /\.\.\. \[6000 chars\]/);
  const long = trace(
    Array.from({ length: 60 }, (_, i) => ({
      role: 'user',
      content: `${i} ${'y'.repeat(4000)}`,
      timestamp: i,
    })),
  );
  assert.ok(long.length <= MAX_TRACE_CHARS + 100);
  assert.match(long, /^\{"role":"user","content":\["0 /);
  assert.match(long, /chars cut/);
  assert.match(long, /"59 y+"\]\}$/);
  const shots = screenshots(messages, image(5));
  assert.deepEqual(
    shots.map((s) => Buffer.from(s.data, 'base64').toString()),
    ['img2', 'img3', 'img4', 'img5'],
  );
});

test('judgeRun: one low-effort request with the trace and screenshots; 5 gotchas; secrets redacted', async () => {
  const { provider, model, streamFn, requests } = faux();
  provider.setResponses([judged({ ...verdict, description: 'typed hunter2 into the form' })]);
  const out = await judgeRun({
    model,
    streamFn,
    run: {
      task: 'log in with hunter2',
      status: 'completed',
      success: true,
      text: 'done',
      output: 'done',
    },
    messages: [{ role: 'user', content: 'log in with hunter2', timestamp: 0 }, shotResult(1)],
    final: image(9),
    judgeContext: 'title must match',
    redact: ['hunter2'],
  });
  assert.equal(out.error, undefined);
  assert.equal(out.judgement.success, true);
  assert.equal(out.judgement.gotchas.length, 5);
  assert.doesNotMatch(out.judgement.description, /hunter2/);
  assert.equal(out.usage.length, 1);
  assert.equal(requests.length, 1);
  const { context, options } = requests[0];
  assert.equal(options.reasoning, 'low');
  assert.equal(options.keepEffort, true);
  const sent = JSON.stringify(context);
  assert.ok(sent.includes(JSON.stringify(JUDGE_PROMPT).slice(1, 60)));
  assert.match(sent, /<judge_context>\\ntitle must match/);
  assert.match(sent, /success reported by the agent: True/);
  assert.doesNotMatch(sent, /hunter2/);
  assert.match(sent, /Screenshot 2 of 2, oldest first\./);
  assert.match(sent, /"name":"judgement"/);
});

test('judgeRun: a model that rejects images is asked again with text; a bad answer is no judgement', async () => {
  const { provider, model, streamFn, requests } = faux();
  provider.setResponses([
    fauxAssistantMessage('', {
      stopReason: 'error',
      errorMessage: '400 image input is not supported',
    }),
    judged(),
  ]);
  const run = { task: 't', status: 'completed', text: 'x' };
  const out = await judgeRun({ model, streamFn, run, messages: [shotResult(1)], redact: [] });
  assert.equal(out.judgement.success, true);
  assert.equal(requests.length, 2);
  assert.doesNotMatch(JSON.stringify(requests[1].context), /Screenshot 1 of/);
  assert.equal(out.usage.length, 2);
  provider.setResponses([judged({ success: 'yes' })]);
  const bad = await judgeRun({ model, streamFn, run, messages: [], redact: [] });
  assert.equal(bad.judgement, undefined);
  assert.match(bad.error, /did not fit the schema/);
});

test('judgeRun: a cancelled run ends the judge request at once, not at the 180 s deadline', async () => {
  const { model } = faux();
  const { createAssistantMessageEventStream } = await import('@earendil-works/pi-ai');
  const hung = () => createAssistantMessageEventStream(); // never answers
  const controller = new AbortController();
  setTimeout(() => controller.abort(), 50);
  const started = Date.now();
  const run = { task: 't', status: 'completed', text: 'x' };
  const out = await judgeRun({
    model,
    streamFn: hung,
    run,
    messages: [],
    redact: [],
    signal: controller.signal,
  });
  assert.ok(Date.now() - started < 5000);
  assert.equal(out.judgement, undefined);
  assert.match(out.error, /cancelled/);
});

test('a run is judged by default (result.judgement, usage added); judge: false sends no judge request', async (t) => {
  const workspace = await mkdtemp(join(tmpdir(), 'bu-judge-'));
  t.after(() => rm(workspace, { recursive: true, force: true }));
  for (const judge of [undefined, false]) {
    const { provider, models, model } = faux(['text']);
    const finish = fauxAssistantMessage(fauxToolCall('finish', { result: 'Paris' }), {
      stopReason: 'toolUse',
    });
    provider.setResponses(judge === false ? [finish] : [finish, judged()]);
    const agent = await BrowserUse.create({
      model: `${model.provider}/${model.id}`,
      models,
      browser: { cdpUrl: 'http://127.0.0.1:9' },
      workspace,
      telemetry: false,
      ...(judge === false ? { judge } : {}),
    });
    try {
      const result = await agent.run('What is the capital of France?');
      assert.equal(result.output, 'Paris');
      assert.equal(provider.getPendingResponseCount(), 0);
      if (judge === false) assert.equal(result.judgement, undefined);
      else {
        assert.equal(result.judgement.success, true);
        assert.equal(result.judgement.gotchas.length, 5);
      }
    } finally {
      await agent.close();
    }
  }
});
