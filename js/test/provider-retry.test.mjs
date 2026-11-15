import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createAssistantMessageEventStream, fauxAssistantMessage } from '@earendil-works/pi-ai';
import { scripted, call } from './run-helper.mjs';
import { deadlineStream } from '../dist/model-stream.js';
import { transientModelError, retryAfter } from '../dist/agent.js';

const model = { api: 'faux', provider: 'faux', id: 'faux' };
const failed = (errorMessage) => fauxAssistantMessage('', { stopReason: 'error', errorMessage });
const done = (message) => {
  const stream = createAssistantMessageEventStream();
  stream.push({ type: 'done', reason: message.stopReason, message });
  stream.end();
  return stream;
};

/** A streamFn that answers 429 + Retry-After through the agent's fetch first, then delivers. */
async function rateLimited(retryAfterHeader, options) {
  const original = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response('busy', { status: 429, headers: { 'retry-after': retryAfterHeader } });
  let calls = 0;
  const times = [];
  try {
    const run = await scripted([], {
      options,
      config: {
        streamFn: async (_model, _context, settings) => {
          times.push(Date.now());
          if (++calls === 1) {
            await settings.fetch('http://provider.invalid/v1/responses');
            return done(failed('OpenAI API error (429): busy'));
          }
          return done(call('finish', { result: 'ok' }));
        },
      },
    });
    return { ...run, calls, wait: times[1] - times[0] };
  } finally {
    globalThis.fetch = original;
  }
}

test('one provider retry honours Retry-After', async () => {
  const { result, calls, wait } = await rateLimited('0.4');
  assert.equal(result.status, 'completed');
  assert.equal(result.providerRetries, 1);
  assert.equal(calls, 2);
  assert.ok(wait >= 380, `waited ${wait} ms`);
});

test('Retry-After never runs into the delivery turn', async () => {
  // timeoutMs 3000: the delivery turn starts at 1500 ms; a 120 s Retry-After is cut to the time left.
  const { result, wait } = await rateLimited('120', { timeoutMs: 3000 });
  assert.equal(result.status, 'completed');
  assert.ok(wait < 1600, `waited ${wait} ms`);
});

test('the provider retry is used once per run', async () => {
  const code = 'upstream_stream_failed: The upstream stream failed.';
  const { result } = await scripted([
    failed(code),
    call('javascript', { code: '1' }),
    failed(code),
  ]);
  assert.equal(result.status, 'error');
  assert.equal(result.providerRetries, 1);
});

test('failures are classified by status code and by failure codes inside HTTP 200', () => {
  for (const message of [
    'OpenAI API error (429): Rate limit reached',
    'OpenAI API error (503): unavailable',
    'OpenAI API error (408): timeout',
    'server_error: boom',
    'overloaded',
    'APIError: request_timeout: gateway cut the request at 300 s',
    'model_request_failed: upstream',
  ])
    assert.equal(transientModelError(message), true, message);
  for (const message of [
    'OpenAI API error (400): Invalid request',
    'OpenAI API error (401): Invalid API key',
    'invalid_request: bad',
  ])
    assert.equal(transientModelError(message), false, message);
  assert.equal(retryAfter(new Headers({ 'retry-after-ms': '250' })), 250);
  assert.equal(retryAfter(new Headers({ 'retry-after': '2' })), 2000);
  assert.equal(retryAfter(new Headers()), undefined);
});

test('a model timeout starts a new step instead of ending the run', async () => {
  let calls = 0;
  const contexts = [];
  const { result } = await scripted([], {
    config: {
      modelTimeoutMs: 100,
      streamFn: (_model, context) => {
        contexts.push(structuredClone(context));
        if (++calls <= 2) return createAssistantMessageEventStream(); // never answers
        return done(call('finish', { result: 'ok' }));
      },
    },
  });
  assert.equal(result.status, 'completed');
  assert.equal(calls, 3);
  assert.equal(result.providerRetries, 2);
  assert.match(JSON.stringify(contexts[1].messages.at(-1)), /got no answer within 0\.1 s/);
});

test('the first event has its own deadline; a flowing stream gets the longer one', async () => {
  const slow = () => {
    const stream = createAssistantMessageEventStream();
    const message = fauxAssistantMessage('late but flowing');
    stream.push({ type: 'start', partial: message });
    setTimeout(() => {
      stream.push({ type: 'done', reason: 'stop', message });
      stream.end();
    }, 150);
    return stream;
  };
  const flowing = await deadlineStream(slow, { firstEventMs: 50, totalMs: 1000 })(model, {
    messages: [],
  }).result();
  assert.equal(flowing.stopReason, 'stop');
  const silent = await deadlineStream(() => createAssistantMessageEventStream(), {
    firstEventMs: 50,
    totalMs: 1000,
  })(model, { messages: [] }).result();
  assert.match(silent.errorMessage, /exceeded 50 ms before its first event/);
  const capped = await deadlineStream(slow, { firstEventMs: 50, totalMs: 100 })(model, {
    messages: [],
  }).result();
  assert.match(capped.errorMessage, /exceeded 100 ms\./);
});
