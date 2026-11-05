import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fauxProvider } from '@earendil-works/pi-ai';
import { RunContext, contextSettings } from '../dist/context.js';

const model = { ...fauxProvider().getModel(), contextWindow: 250000 };
const image = { type: 'image', data: 'AAAA', mimeType: 'image/png' };
const toolResult = (id, text) => ({
  role: 'toolResult',
  toolCallId: String(id),
  toolName: 'browser',
  content: [{ type: 'text', text }, image],
  isError: false,
  timestamp: id,
});
const assistant = (id, tokens = 0) => ({
  role: 'assistant',
  content: [{ type: 'toolCall', id: String(id), name: 'browser', arguments: {} }],
  stopReason: 'toolUse',
  usage: {
    input: tokens,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: tokens,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  },
  timestamp: id,
});
const history = (n, text = 'x'.repeat(40000), tokens = 0) => [
  { role: 'user', content: 'task', timestamp: 0 },
  ...Array.from({ length: n }, (_, i) => [
    assistant(i + 1, tokens),
    toolResult(i + 1, text),
  ]).flat(),
];
const context = (settings) =>
  new RunContext(model, undefined, '/tmp', model.contextWindow * 4, true, [], settings);
const images = (messages) =>
  messages.filter((m) => m.role === 'toolResult' && m.content.some((c) => c.type === 'image'))
    .length;
const texts = (messages) =>
  messages
    .filter((m) => m.role === 'toolResult')
    .map((m) => m.content.find((c) => c.type === 'text').text.length);

test('unset settings keep the last two screenshots and every tool output whole', () => {
  const messages = history(10);
  const projected = context({}).project(messages);
  assert.equal(images(projected), 2);
  assert.deepEqual(new Set(texts(projected)), new Set([40000]));
});

test('keepScreenshots sets how many screenshots stay', () => {
  const messages = history(10);
  assert.equal(images(context({ keepScreenshots: 5 }).project(messages)), 5);
  assert.equal(images(context({ keepScreenshots: 0 }).project(messages)), 0);
});

test('batch trimming keeps every screenshot until the mark, then cuts old ones once', () => {
  const ctx = context({ trimAtTokens: 60000, keepScreenshots: 2 });
  let messages = history(3); // about 30K tokens
  ctx.trim(messages, '');
  assert.equal(images(ctx.project(messages)), 3);
  assert.deepEqual(new Set(texts(ctx.project(messages))), new Set([40000]));

  messages = history(10); // about 100K tokens, past the mark
  ctx.trim(messages, '');
  const cut = ctx.project(messages);
  assert.equal(images(cut), 2);
  const sizes = texts(cut);
  assert.ok(
    sizes.slice(0, -2).every((n) => n < 2100),
    'old outputs shortened',
  );
  assert.ok(
    sizes.slice(-2).every((n) => n === 40000),
    'recent outputs whole',
  );

  messages = history(12); // grows after the cut: the cut prefix must not change
  ctx.trim(messages, '');
  const later = ctx.project(messages);
  assert.deepEqual(later.slice(0, cut.length - 1), cut.slice(0, cut.length - 1));
});

test('a cut that frees too little is skipped', () => {
  const ctx = context({ trimAtTokens: 20000 });
  const messages = history(10, 'x'.repeat(400));
  ctx.trim(messages, '');
  assert.equal(images(ctx.project(messages)), 10);
});

test('compactAtTokens compacts below the default trigger and not above it', () => {
  const messages = history(4, 'x', 100000);
  assert.equal(context({}).needsCompaction(messages, ''), false);
  assert.equal(context({ compactAtTokens: 50000 }).needsCompaction(messages, ''), true);
  assert.equal(context({ compactAtTokens: 100000 }).needsCompaction(messages, ''), true);
  assert.equal(context({ compactAtTokens: 150000 }).needsCompaction(messages, ''), false);
});

test('settings are validated against the model window', () => {
  assert.deepEqual(contextSettings(undefined, model), {});
  assert.throws(() => contextSettings({ keepScreenshots: 11 }, model), /keepScreenshots/);
  assert.throws(() => contextSettings({ trimAtTokens: 1000 }, model), /trimAtTokens/);
  assert.throws(() => contextSettings({ compactAtTokens: 240000 }, model), /compactAtTokens/);
  assert.throws(
    () => contextSettings({ trimAtTokens: 100000, compactAtTokens: 90000 }, model),
    /below/,
  );
  assert.throws(() => contextSettings({ trimAtTokens: 170000 }, model), /below/);
  assert.throws(() => contextSettings(12, model), /object/);
});

test('a trim before the kept screenshots exist never strips one', () => {
  const ctx = context({ trimAtTokens: 20000, keepScreenshots: 3 });
  const messages = history(2);
  ctx.trim(messages, '');
  assert.equal(images(ctx.project(messages)), 2);
  const more = history(6);
  assert.equal(images(ctx.project(more)), images(ctx.project(more.slice(0, messages.length))) + 4);
});

test('keepScreenshots 0 still trims a large context', () => {
  const ctx = context({ trimAtTokens: 60000, keepScreenshots: 0 });
  const messages = history(3, 'x'.repeat(150000));
  ctx.trim(messages, '');
  assert.equal(images(ctx.project(messages)), 1);
  assert.deepEqual(
    texts(ctx.project(messages))
      .slice(0, 2)
      .every((n) => n < 2100),
    true,
  );
});
