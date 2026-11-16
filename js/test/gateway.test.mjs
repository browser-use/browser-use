import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { builtinModels } from '@earendil-works/pi-ai/providers/all';
import { streamSimple as responsesStream } from '@earendil-works/pi-ai/api/openai-responses';
import {
  DEFAULT_MODEL,
  GATEWAY_URL,
  gatewayModel,
  gatewayModelName,
  gatewayPreflight,
  gatewayStream,
} from '../dist/gateway.js';
import { BrowserUse } from '../dist/index.js';

const realFetch = globalThis.fetch;
const savedKey = process.env.BROWSER_USE_API_KEY;
afterEach(() => {
  globalThis.fetch = realFetch;
  if (savedKey === undefined) delete process.env.BROWSER_USE_API_KEY;
  else process.env.BROWSER_USE_API_KEY = savedKey;
});
/** Replace fetch: handler(url, init) -> Response. Records every call. */
function mockFetch(handler) {
  const calls = [];
  globalThis.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const body = init?.body ?? (input instanceof Request ? await input.clone().text() : undefined);
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : {}));
    calls.push({ url, body: typeof body === 'string' ? body : undefined, headers });
    return handler(url, init);
  };
  return calls;
}
const json = (status, value) =>
  new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } });
const MODELS = json(200, {
  data: [{ id: 'bu-4.0' }, { id: 'bu-fast' }, { id: 'bu-ultrafast' }, { id: 'bu-smart' }],
});

test('no model means browser-use/bu-4.0; a bare bu-* name is the gateway (Python 1.0.6 DEFAULT_MODEL)', () => {
  assert.equal(DEFAULT_MODEL, 'browser-use/bu-4.0');
  assert.equal(gatewayModelName(undefined), 'browser-use/bu-4.0');
  assert.equal(gatewayModelName('bu-ultrafast'), 'browser-use/bu-ultrafast');
  assert.equal(gatewayModelName('openai/gpt-5.4'), 'openai/gpt-5.4');
  const model = gatewayModel('bu-fast', builtinModels().getModel('openai', 'gpt-6-luna'));
  assert.equal(model.baseUrl, 'https://api.browser-use.com/api/v4/llm/v1');
  assert.equal(model.api, 'openai-responses');
  assert.deepEqual(model.cost, { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 });
  assert.equal(model.compat.supportsAdditionalTools, false);
});

test('preflight GET /models: listed passes; unlisted, 401, 402 and unreachable name the cause', async () => {
  let calls = mockFetch(() => MODELS.clone());
  assert.equal(await gatewayPreflight('bu-fast', 'bu_key'), undefined);
  assert.equal(calls[0].url, `${GATEWAY_URL}/models`);
  assert.equal(calls[0].headers.get('authorization'), 'Bearer bu_key');
  assert.match(
    await gatewayPreflight('bu-nope', 'bu_key'),
    /^bu-nope is not on the Browser Use gateway\. Listed: bu-4.0, bu-fast, bu-smart, bu-ultrafast\.$/,
  );
  mockFetch(() => json(401, { error: { code: 'unauthorized' } }));
  assert.match(await gatewayPreflight('bu-fast', 'bad'), /API key rejected \(401\)/);
  mockFetch(() => json(402, {}));
  assert.match(await gatewayPreflight('bu-fast', 'k'), /Out of Browser Use credits \(402\)/);
  mockFetch(() => {
    throw new TypeError('fetch failed');
  });
  assert.match(await gatewayPreflight('bu-fast', 'k'), /is not reachable: fetch failed/);
});

/** A Responses SSE stream: one text message, then response.completed with usage and the gateway's charge. */
function sse(charge) {
  const response = {
    id: 'resp_1',
    object: 'response',
    status: 'completed',
    model: 'bu-fast',
    output: [
      {
        id: 'msg_1',
        type: 'message',
        role: 'assistant',
        status: 'completed',
        content: [{ type: 'output_text', text: 'done', annotations: [] }],
      },
    ],
    usage: {
      input_tokens: 1000,
      output_tokens: 10,
      total_tokens: 1010,
      input_tokens_details: { cached_tokens: 0 },
      output_tokens_details: { reasoning_tokens: 0 },
    },
    ...(charge !== undefined
      ? { browser_use: { resolved_model: 'gpt-6-luna', charge_usd: charge } }
      : {}),
  };
  const events = [
    { type: 'response.created', response: { ...response, status: 'in_progress', output: [] } },
    {
      type: 'response.output_item.added',
      output_index: 0,
      item: { ...response.output[0], content: [], status: 'in_progress' },
    },
    {
      type: 'response.content_part.added',
      output_index: 0,
      item_id: 'msg_1',
      content_index: 0,
      part: { type: 'output_text', text: '', annotations: [] },
    },
    {
      type: 'response.output_text.delta',
      output_index: 0,
      item_id: 'msg_1',
      content_index: 0,
      delta: 'done',
    },
    { type: 'response.output_item.done', output_index: 0, item: response.output[0] },
    { type: 'response.completed', response },
  ];
  const text = events.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join('');
  return new Response(text, { status: 200, headers: { 'content-type': 'text/event-stream' } });
}

test('gateway requests: Browser Use key, no effort for a bu-* alias, cost is charge_usd', async () => {
  const models = builtinModels();
  const model = gatewayModel('bu-fast', models.getModel('openai', 'gpt-6-luna'));
  const stream = gatewayStream(responsesStream, 'bu_key', { aliasEffort: true });
  const context = { systemPrompt: 'x', messages: [{ role: 'user', content: 'hi', timestamp: 1 }] };
  let calls = mockFetch(() => sse('0.0123'));
  const message = await stream(model, context, { reasoning: 'medium' }).result();
  assert.equal(message.stopReason, 'stop', message.errorMessage);
  assert.equal(calls[0].url, `${GATEWAY_URL}/responses`);
  assert.equal(calls[0].headers.get('authorization'), 'Bearer bu_key');
  const body = JSON.parse(calls[0].body);
  assert.equal(body.model, 'bu-fast');
  assert.equal(body.store, false);
  // No effort (the alias's own applies), but the summary stays, as Python's openai_reasoning_summary 'auto'.
  assert.deepEqual(body.reasoning, { summary: 'auto' });
  assert.deepEqual(body.include, ['reasoning.encrypted_content']);
  assert.equal(message.usage.cost.total, 0.0123);
  // An explicit reasoning level is sent; no charge in the response costs 0, never a retail estimate.
  const explicit = gatewayStream(responsesStream, 'bu_key', { aliasEffort: false });
  calls = mockFetch(() => sse(undefined));
  const second = await explicit(model, context, { reasoning: 'high' }).result();
  assert.equal(JSON.parse(calls[0].body).reasoning.effort, 'high');
  assert.equal(second.usage.cost.total, 0);
});

test('create: no key fails before a browser; a failed preflight fails before a browser; bu-fast runs ultrafast, the bu-4.0 default does not (Python 1.0.6)', async (t) => {
  delete process.env.BROWSER_USE_API_KEY;
  await assert.rejects(BrowserUse.create({}), /needs BROWSER_USE_API_KEY/);
  process.env.BROWSER_USE_API_KEY = 'bu_key';
  mockFetch(() => json(401, {}));
  await assert.rejects(
    BrowserUse.create({ browser: { cdpUrl: 'http://127.0.0.1:9' } }),
    /API key rejected \(401\)/,
  );
  const workspace = await mkdtemp(join(tmpdir(), 'bu-gateway-'));
  t.after(() => rm(workspace, { recursive: true, force: true }));
  mockFetch(() => MODELS.clone());
  const agent = await BrowserUse.create({
    model: 'bu-fast',
    browser: { cdpUrl: 'http://127.0.0.1:9' },
    workspace,
  });
  try {
    assert.equal((await agent.execute('console.log(typeof bu)')).text.trim(), 'object');
  } finally {
    await agent.close();
  }
  const plain = await BrowserUse.create({
    browser: { cdpUrl: 'http://127.0.0.1:9' },
    workspace,
  });
  try {
    assert.equal((await plain.execute('console.log(typeof bu)')).text.trim(), 'undefined');
  } finally {
    await plain.close();
  }
});
