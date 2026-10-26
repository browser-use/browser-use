import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { rm } from 'node:fs/promises';
import { streamSimple } from '@earendil-works/pi-ai/api/openai-responses';
import { BrowserUse, builtinModels as sdkModels } from '../dist/index.js';
import { DEFAULT_MODEL, resolveModel } from '../dist/models.js';
import { builtinModels } from '@earendil-works/pi-ai/providers/all';

test(
  'stalled real SSE responses abort their connections and retry inference only once',
  { timeout: 10000 },
  async () => {
    let requests = 0,
      closed = 0;
    const server = createServer(async (req, res) => {
      for await (const _chunk of req) {
      }
      requests++;
      res.on('close', () => closed++);
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      res.write(
        'event: response.created\ndata: {"type":"response.created","response":{"id":"stalled","status":"in_progress","output":[]}}\n\n',
      );
      // The fixture leaves the response open until the client closes it.
    });
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    let agent;
    try {
      agent = await BrowserUse.create({
        model: 'openai/gpt-5.4',
        browser: { kind: 'pending' },
        researchTools: false,
        modelTimeoutMs: 200,
        streamFn: (model, context, options) =>
          streamSimple(
            { ...model, baseUrl: `http://127.0.0.1:${server.address().port}/v1` },
            context,
            { ...options, apiKey: 'fixture-key', transport: 'sse' },
          ),
      });
      const result = await agent.run('Inspect', { timeoutMs: 5000 });
      assert.equal(result.status, 'error');
      assert.match(result.error, /Model stream exceeded/);
      assert.equal(result.providerRetries, 1);
      for (let i = 0; i < 50 && closed < 2; i++)
        await new Promise((resolve) => setTimeout(resolve, 10));
      assert.equal(requests, 2);
      assert.equal(closed, 2);
    } finally {
      await agent?.close();
      if (agent) await rm(agent.workspace, { recursive: true, force: true });
      server.closeAllConnections();
      await new Promise((resolve) => server.close(resolve));
    }
  },
);

for (const recovery of ['none', 'unknown-model', 'uncoded', 'server_error', 'failed-cell-image']) {
  const recover = ['uncoded', 'server_error'].includes(recovery);
  const imageFailure = recovery === 'failed-cell-image';
  const modelId = recovery === 'unknown-model' ? 'brand-new-model-not-in-the-catalog' : 'gpt-5.4';
  test(`real OpenAI Responses transport parses SSE completion; scenario=${recovery}`, async () => {
    let request;
    let requests = 0;
    const server = createServer(async (req, res) => {
      let body = '';
      for await (const chunk of req) body += chunk;
      request = { url: req.url, body: JSON.parse(body) };
      requests++;
      const fail = recover && requests === 1;
      const captureThenFail = imageFailure && requests === 1;
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      const event = (type, body) =>
        res.write(`event: ${type}\ndata: ${JSON.stringify({ type, ...body })}\n\n`);
      const item = {
        id: 'fc_fixture',
        type: 'function_call',
        call_id: 'call_fixture',
        name: fail || captureThenFail ? 'javascript' : 'finish',
        arguments: captureThenFail
          ? JSON.stringify({
              code: "await page.goto('data:text/html,<title>Captured before error</title>'); await screenshot(); throw new Error('failure after real capture')",
            })
          : fail
            ? JSON.stringify({ code: "throw new Error('failed response tool executed')" })
            : '{"result":"transport verified"}',
        status: 'completed',
      };
      event('response.created', {
        response: { id: 'resp_fixture', status: 'in_progress', output: [] },
      });
      event('response.output_item.added', {
        output_index: 0,
        item: { ...item, arguments: '', status: 'in_progress' },
      });
      event('response.function_call_arguments.delta', {
        item_id: item.id,
        output_index: 0,
        delta: item.arguments,
      });
      event('response.function_call_arguments.done', {
        item_id: item.id,
        output_index: 0,
        arguments: item.arguments,
      });
      event('response.output_item.done', { output_index: 0, item });
      event(fail ? 'response.failed' : 'response.completed', {
        response: {
          id: 'resp_fixture',
          status: fail ? 'failed' : 'completed',
          ...(fail
            ? {
                error: {
                  ...(recovery === 'server_error' ? { code: 'server_error' } : {}),
                  message: 'Sorry, something went wrong.',
                },
              }
            : {}),
          output: [item],
          usage: {
            input_tokens: 10,
            output_tokens: 5,
            total_tokens: 15,
            input_tokens_details: { cached_tokens: 0 },
          },
        },
      });
      res.end();
    });
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    const agent = await BrowserUse.create({
      model: `openai/${modelId}`,
      browser: { kind: imageFailure ? 'chromium' : 'pending' },
      researchTools: false,
      streamFn: (model, context, options) =>
        streamSimple(
          { ...model, baseUrl: `http://127.0.0.1:${server.address().port}/v1` },
          context,
          {
            ...options,
            apiKey: 'fixture-key',
            transport: 'sse',
          },
        ),
    });
    try {
      const tools = [];
      const result = await agent.run('Return a transport check.', {
        onEvent: (e) => {
          if (e.type === 'tool_execution_start') tools.push(e.toolName);
        },
      });
      assert.equal(result.status, 'completed', result.error);
      assert.equal(result.output, 'transport verified');
      assert.equal(request.url, '/v1/responses');
      assert.equal(request.body.model, modelId);
      assert.equal(result.pricingKnown, recovery !== 'unknown-model');
      if (recovery === 'unknown-model') {
        assert.equal(result.estimatedCostUsd, null);
        await assert.rejects(
          agent.run('Check the cost limit.', { maxCostUsd: 1 }),
          /requires explicit pricing/,
        );
      }
      assert.deepEqual(
        request.body.tools.map((t) => t.name),
        ['javascript', 'finish', 'finish_from_js'],
      );
      assert.equal(requests, recover || imageFailure ? 2 : 1);
      assert.equal(result.providerRetries, recover ? 1 : 0);
      assert.deepEqual(tools, imageFailure ? ['javascript', 'finish'] : ['finish']);
      assert.equal(result.usage.input, imageFailure ? 20 : 10);
      assert.equal(result.usage.output, imageFailure ? 10 : 5);
      if (imageFailure) {
        const output = request.body.input.find(
          (item) => item.type === 'function_call_output',
        ).output;
        assert.match(
          output.find((part) => part.type === 'input_text').text,
          /failure after real capture/,
        );
        const image = output.find((part) => part.type === 'input_image');
        assert.match(image.image_url, /^data:image\/jpeg;base64,/);
        assert.equal(Buffer.from(image.image_url.split(',')[1], 'base64').readUInt16BE(0), 0xffd8);
        assert.equal(
          agent.history.messages.find((message) => message.role === 'toolResult').isError,
          true,
        );
      }
    } finally {
      await agent.close();
      await rm(agent.workspace, { recursive: true, force: true });
      await new Promise((resolve) => server.close(resolve));
    }
  });
}

test('explicit OpenRouter transport metadata uses completions across follow-ups without configuration_update', async () => {
  const { mock } = await import('node:test');
  const originalFetch = globalThis.fetch;
  const previous = process.env.OPENROUTER_API_KEY;
  process.env.OPENROUTER_API_KEY = 'fixture-only';
  const requests = [];
  const patch = mock.method(globalThis, 'fetch', async (input, options) => {
    const url = String(input instanceof Request ? input.url : input);
    if (!url.startsWith('https://openrouter.ai/')) return originalFetch(input, options);
    const body = JSON.parse(options.body);
    requests.push({ url, body });
    const delta = {
      role: 'assistant',
      tool_calls: [
        {
          index: 0,
          id: `call_${requests.length}`,
          type: 'function',
          function: { name: 'finish', arguments: '{"result":"route verified"}' },
        },
      ],
    };
    const event = (d, finish_reason = null) =>
      `data: ${JSON.stringify({ id: 'fixture', object: 'chat.completion.chunk', created: 1, model: body.model, choices: [{ index: 0, delta: d, finish_reason }] })}\n\n`;
    return new Response(event(delta) + event({}, 'tool_calls') + 'data: [DONE]\n\n', {
      headers: { 'content-type': 'text/event-stream' },
    });
  });
  let agent;
  try {
    agent = await BrowserUse.create({
      model: 'openrouter/anthropic/claude-opus-5',
      modelInfo: { api: 'openai-completions', baseUrl: 'https://openrouter.ai/api/v1' },
      browser: { kind: 'pending' },
      researchTools: false,
      reasoning: 'medium',
    });
    for (const result of [await agent.run('Check.'), await agent.followUp('Again.')]) {
      assert.equal(result.status, 'completed', result.error);
      assert.equal(result.output, 'route verified');
    }
    assert.equal(requests.length, 2);
    for (const { url, body } of requests) {
      assert.equal(url, 'https://openrouter.ai/api/v1/chat/completions');
      assert.equal(body.model, 'anthropic/claude-opus-5');
      assert.doesNotMatch(JSON.stringify(body), /configuration_update/);
    }
    assert.ok(requests[1].body.messages.some((m) => m.role === 'tool'));
  } finally {
    patch.mock.restore();
    if (previous === undefined) delete process.env.OPENROUTER_API_KEY;
    else process.env.OPENROUTER_API_KEY = previous;
    await agent?.close();
    if (agent) await rm(agent.workspace, { recursive: true, force: true });
  }
});

test('public gateway aliases preserve their wire IDs without physical model mappings', () => {
  for (const alias of ['bu-recommended', 'bu-balanced', 'bu-smart']) {
    for (const prefix of ['', 'browser-use/']) {
      const { model, priceKnown } = resolveModel({ model: prefix + alias });
      assert.equal(model.provider, 'browser-use');
      assert.equal(model.id, alias);
      assert.equal(model.reasoning, true);
      assert.deepEqual(model.input, ['text', 'image']);
      assert.equal(priceKnown, false);
    }
  }
});

test('BU2 requests report the supported alias and old-package option', () => {
  for (const model of [
    'BU2',
    'bu-2',
    'bu-2-0',
    'bu-2.0',
    'bu-2-0-mini-preview',
    'browser-use/bu-2-0',
    'openai/BU2',
  ]) {
    assert.throws(() => resolveModel({ model }), /BU2.*Pi.*bu-recommended.*browser-use<1/, model);
  }
});

test('known models preserve exact catalog metadata', () => {
  const models = builtinModels();
  const expected = models.getModel('openai', 'gpt-5.4');
  const resolved = resolveModel({ model: 'openai/gpt-5.4', models });
  assert.deepEqual(resolved.model, expected);
  assert.equal(resolved.priceKnown, true);
});

for (const provider of ['openai', 'anthropic', 'openrouter']) {
  test(`unknown model IDs use conservative capabilities without borrowed prices; provider=${provider}`, () => {
    const id = 'vendor/model-released-today';
    const { model, priceKnown } = resolveModel({ model: `${provider}/${id}` });
    assert.equal(model.provider, provider);
    assert.equal(model.id, id);
    assert.equal(model.name, id);
    assert.deepEqual(model.input, ['text']);
    assert.equal(model.reasoning, false);
    assert.equal(model.contextWindow, 32768);
    assert.equal(model.maxTokens, 8192);
    assert.equal(priceKnown, false);
    if (provider === 'openrouter') assert.equal(model.api, 'openai-completions');
  });
}

for (const model of ['openai/gpt-5.4', 'openai/model-released-today']) {
  test(`explicit model metadata overrides catalog and default capabilities; model=${model}`, () => {
    const modelInfo = {
      api: 'openai-completions',
      baseUrl: 'http://127.0.0.1:1234/v1',
      vision: true,
      reasoning: true,
      contextWindow: 65536,
      maxTokens: 4096,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      compat: { supportsStore: false },
      thinkingLevelMap: { low: 'small' },
    };
    const resolved = resolveModel({ model, modelInfo });
    for (const key of [
      'api',
      'baseUrl',
      'reasoning',
      'contextWindow',
      'maxTokens',
      'cost',
      'thinkingLevelMap',
    ])
      assert.deepEqual(resolved.model[key], modelInfo[key], `model metadata differs for ${key}`);
    assert.deepEqual(resolved.model.input, ['text', 'image']);
    assert.equal(resolved.model.compat.supportsStore, false);
    assert.equal(resolved.priceKnown, true);
  });
}

test('unknown providers require an explicitly registered provider', () => {
  assert.throws(
    () =>
      resolveModel({
        model: 'unregistered-provider/released-today',
        modelInfo: { api: 'openai-responses', baseUrl: 'http://127.0.0.1:1234/v1' },
      }),
    /Unknown provider unregistered-provider/,
  );
});

test('model prices reject partial and negative rates', () => {
  for (const cost of [{ input: 1 }, { input: -1, output: 1, cacheRead: 0, cacheWrite: 0 }])
    assert.throws(
      () => resolveModel({ model: 'openai/released-today', modelInfo: { cost } }),
      /modelInfo.cost/,
    );
});

for (const scenario of ['complete', 'balanced', 'smart', 'unknown-model', 'unauthorized']) {
  test(`Browser Use gateway sends exact model, auth, tools and usage; scenario=${scenario}`, async () => {
    const previous = process.env.BROWSER_USE_API_KEY;
    process.env.BROWSER_USE_API_KEY = 'fixture-browser-use-key';
    const requests = [];
    const server = createServer(async (req, res) => {
      let raw = '';
      for await (const chunk of req) raw += chunk;
      const body = JSON.parse(raw);
      requests.push({ url: req.url, headers: req.headers, body });
      if (scenario === 'unauthorized') {
        res.writeHead(401, { 'content-type': 'application/json' });
        res.end(
          JSON.stringify({
            error: { message: 'Fixture rejects this key.', type: 'authentication_error' },
          }),
        );
        return;
      }
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      const event = (choices, usage) =>
        `data: ${JSON.stringify({
          id: 'gateway_fixture',
          object: 'chat.completion.chunk',
          created: 1,
          model: body.model,
          choices,
          ...(usage ? { usage } : {}),
        })}\n\n`;
      res.end(
        event([
          {
            index: 0,
            delta: {
              role: 'assistant',
              tool_calls: [
                {
                  index: 0,
                  id: 'gateway_finish',
                  type: 'function',
                  function: { name: 'finish', arguments: '{"result":"gateway verified"}' },
                },
              ],
            },
            finish_reason: null,
          },
        ]) +
          event([{ index: 0, delta: {}, finish_reason: 'tool_calls' }]) +
          event([], {
            prompt_tokens: 10,
            completion_tokens: 5,
            total_tokens: 15,
            prompt_tokens_details: { cached_tokens: 2 },
          }) +
          'data: [DONE]\n\n',
      );
    });
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    let agent;
    const model =
      scenario === 'unknown-model'
        ? 'browser-use/vendor/released-today'
        : scenario === 'balanced'
          ? 'bu-balanced'
          : scenario === 'smart'
            ? 'browser-use/bu-smart'
            : DEFAULT_MODEL;
    try {
      agent = await BrowserUse.create({
        model,
        modelInfo: { baseUrl: `http://127.0.0.1:${server.address().port}/v1` },
        browser: { kind: 'pending' },
        researchTools: false,
        telemetry: false,
      });
      const result = await agent.run('Check the gateway.');
      assert.equal(requests.length, 1);
      const request = requests[0];
      assert.equal(request.url, '/v1/chat/completions');
      assert.equal(request.headers.authorization, 'Bearer fixture-browser-use-key');
      assert.equal(request.headers['x-browser-use-client'], 'pi');
      assert.equal(request.headers['x-browser-use-request-type'], undefined);
      assert.equal(request.body.model, model.replace(/^browser-use\//, ''));
      if (scenario !== 'unknown-model') assert.equal(request.body.reasoning_effort, 'high');
      assert.equal(request.body.stream_options.include_usage, true);
      assert.notEqual(request.body.store, true);
      assert.ok(request.body.tools.some((tool) => tool.function.name === 'finish'));
      if (scenario === 'unauthorized') {
        assert.equal(result.status, 'error');
        assert.match(result.error, /401|Fixture rejects this key/);
        assert.equal(result.providerRetries, 0);
      } else {
        assert.equal(result.status, 'completed', result.error);
        assert.equal(result.output, 'gateway verified');
        assert.equal(result.usage.input, 8);
        assert.equal(result.usage.cacheRead, 2);
        assert.equal(result.usage.output, 5);
        assert.equal(result.pricingKnown, false);
        assert.equal(result.estimatedCostUsd, null);
        assert.equal(result.usage.cost, null);
        await assert.rejects(
          agent.run('Apply an unknown cost limit.', { maxCostUsd: 1 }),
          /requires explicit pricing/,
        );
      }
    } finally {
      if (previous === undefined) delete process.env.BROWSER_USE_API_KEY;
      else process.env.BROWSER_USE_API_KEY = previous;
      await agent?.close();
      if (agent) await rm(agent.workspace, { recursive: true, force: true });
      server.closeAllConnections();
      await new Promise((resolve) => server.close(resolve));
    }
  });
}

test('Browser Use gateway requires its own key and keeps catalog prices unknown', async () => {
  const previous = process.env.BROWSER_USE_API_KEY;
  delete process.env.BROWSER_USE_API_KEY;
  let agent;
  try {
    const models = sdkModels({
      authContext: {
        env: async (name) => (name === 'OPENAI_API_KEY' ? 'fixture-openai-key' : undefined),
        fileExists: async () => false,
      },
    });
    assert.equal(await models.checkAuth('browser-use'), undefined);
    assert.deepEqual(await models.getAvailable('browser-use'), []);
    assert.ok((await models.getAvailable()).some((model) => model.provider === 'openai'));
    const { model, priceKnown } = resolveModel({ model: DEFAULT_MODEL, models });
    assert.equal(model.id, 'bu-recommended');
    assert.equal(model.api, 'openai-completions');
    assert.equal(model.baseUrl, 'https://api.browser-use.com/api/llm/v1');
    assert.equal(model.contextWindow, 250000);
    assert.equal(model.maxTokens, 32000);
    assert.deepEqual(model.input, ['text', 'image']);
    assert.equal(priceKnown, false);
    assert.equal(
      resolveModel({
        model: DEFAULT_MODEL,
        modelInfo: {
          cost: { input: 1, output: 2, cacheRead: 0, cacheWrite: 0 },
        },
      }).priceKnown,
      true,
    );
    agent = await BrowserUse.create({
      model: DEFAULT_MODEL,
      models,
      browser: { kind: 'pending' },
      telemetry: false,
    });
    const result = await agent.run('Reject missing authentication.');
    assert.equal(result.status, 'error');
    assert.match(result.error, /BROWSER_USE_API_KEY/);
    assert.ok(result.error.includes('https://cloud.browser-use.com/settings?tab=api-keys&new=1'));
    assert.equal(result.providerRetries, 0);
  } finally {
    if (previous === undefined) delete process.env.BROWSER_USE_API_KEY;
    else process.env.BROWSER_USE_API_KEY = previous;
    await agent?.close();
    if (agent) await rm(agent.workspace, { recursive: true, force: true });
  }
});
