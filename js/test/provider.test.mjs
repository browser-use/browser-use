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

test('real OpenAI Responses transport serializes tools and parses a local SSE completion', async () => {
  let request;
  const server = createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    request = { url: req.url, body: JSON.parse(body) };
    res.writeHead(200, { 'content-type': 'text/event-stream' });
    const event = (type, body) =>
      res.write(`event: ${type}\ndata: ${JSON.stringify({ type, ...body })}\n\n`);
    const item = {
      id: 'fc_fixture',
      type: 'function_call',
      call_id: 'call_fixture',
      name: 'finish',
      arguments: '{"result":"transport verified"}',
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
    event('response.completed', {
      response: {
        id: 'resp_fixture',
        status: 'completed',
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
      streamSimple({ ...model, baseUrl: `http://127.0.0.1:${server.address().port}/v1` }, context, {
        ...options,
        apiKey: 'fixture-key',
        transport: 'sse',
      }),
  });
  try {
    const result = await agent.run('Return a transport check.');
    assert.equal(result.status, 'completed');
    assert.equal(result.output, 'transport verified');
    assert.equal(request.url, '/v1/responses');
    assert.equal(request.body.model, 'gpt-5.4');
    assert.deepEqual(
      request.body.tools.map((t) => t.name),
      ['javascript', 'finish', 'finish_from_js'],
    );
    assert.equal(result.usage.input, 10);
    assert.equal(result.usage.output, 5);
  } finally {
    await agent.close();
    await rm(agent.workspace, { recursive: true, force: true });
    await new Promise((resolve) => server.close(resolve));
  }
});
