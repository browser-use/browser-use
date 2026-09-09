import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { rm } from 'node:fs/promises';
import { streamSimple } from '@earendil-works/pi-ai/api/openai-responses';
import { BrowserUse } from '../dist/index.js';

test(
  'stalled real SSE responses abort their connections and retry inference only once',
  { timeout: 10000 },
  async () => {
    let requests = 0,
      closed = 0;
    const server = createServer(async (req, res) => {
      for await (const _chunk of req) {
        /* consume request before responding */
      }
      requests++;
      res.on('close', () => closed++);
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      res.write(
        'event: response.created\ndata: {"type":"response.created","response":{"id":"stalled","status":"in_progress","output":[]}}\n\n',
      );
      // Intentionally keep the response open. The client must close it on timeout.
    });
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    let agent;
    try {
      agent = await BrowserUse.create({
        model: 'openai/gpt-5.4',
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

for (const recovery of ['none', 'uncoded', 'server_error', 'failed-cell-image']) {
  const recover = ['uncoded', 'server_error'].includes(recovery);
  const imageFailure = recovery === 'failed-cell-image';
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
      model: 'openai/gpt-5.4',
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
      assert.equal(request.body.model, 'gpt-5.4');
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

test('OpenRouter Opus 5 uses completions across follow-ups without configuration_update', async () => {
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
