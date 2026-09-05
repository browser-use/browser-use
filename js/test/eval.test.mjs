import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseOptions, resultEnvelope } from '../eval/run.mjs';

test('eval options reject unknown settings, invalid budgets and browser expiry', () => {
  assert.equal(parseOptions({}).reasoning_effort, 'medium');
  assert.equal(parseOptions({}).max_context_chars, 800000);
  for (const options of [
    { typo: true },
    { max_context_chars: NaN },
    { max_context_chars: 0 },
    { max_context_chars: 3000001 },
    { task_timeout_seconds: NaN },
    { browser_timeout_minutes: 1 },
    { reasoning_effort: 'wat' },
    { proxy_country_code: 'USA' },
    null,
    [],
  ])
    assert.throws(() => parseOptions(options));
});
test('partial agent outcomes remain judgeable; provider errors remain failures', () => {
  const usage = {
    input: 1,
    output: 2,
    cacheRead: 3,
    cacheWrite: 4,
    totalTokens: 10,
    cost: { total: 0.01 },
  };
  const partial = {
    status: 'max_steps',
    text: 'Partial evidence',
    steps: 35,
    durationMs: 1000,
    usage,
    model: 'openai/gpt-5.5',
  };
  const envelope = resultEnvelope(partial, [], {});
  assert.equal(envelope.status, 'completed');
  assert.equal(envelope.metadata.stop_reason, 'max_steps');
  assert.equal(envelope.self_reported_success, null);
  assert.equal(envelope.metrics.total_cost, 0.01);
  assert.equal(
    resultEnvelope({ ...partial, status: 'error', error: 'Provider failed' }, [], {}).status,
    'failed',
  );
});

test('adapter uses real CDP with stubbed cloud/model/telemetry and cleans up', async () => {
  const { main } = await import('../eval/run.mjs');
  const { openBrowser } = await import('../dist/browser.js');
  const { startFixture } = await import('../examples/fixture.mjs');
  const { mkdtemp, writeFile, readFile, rm } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const { fileURLToPath } = await import('node:url');
  const { createRequire } = await import('node:module');
  const { Laminar } = createRequire(import.meta.url)('@lmnr-ai/lmnr');
  const { mock } = await import('node:test');
  const chrome = await openBrowser(),
    fixture = await startFixture();
  const dir = await mkdtemp(join(tmpdir(), 'bu-eval-contract-'));
  const originalFetch = globalThis.fetch,
    saved = { ...process.env },
    telemetry = [];
  let requests = 0,
    stops = 0;
  const patches = [
    mock.method(Laminar, 'initialize', () => {}),
    mock.method(Laminar, 'startSpan', (options) => {
      const record = { ...options, attributes: {}, ended: false };
      telemetry.push(record);
      return {
        setAttributes: (a) => Object.assign(record.attributes, a),
        setStatus() {},
        end() {
          record.ended = true;
        },
      };
    }),
    mock.method(Laminar, 'withSpan', (_s, fn) => fn()),
    ...['setSpanOutput', 'flush', 'shutdown'].map((name) => mock.method(Laminar, name, () => {})),
  ];
  try {
    await writeFile(
      join(dir, 'task.json'),
      JSON.stringify({ task_id: 'fixture', confirmed_task: 'Read catalog; save once.' }),
    );
    await writeFile(join(dir, 'dependencies.sha256'), 'fixture-hash');
    Object.assign(process.env, {
      EVAL_WORKSPACE: dir,
      EVAL_RESULT_PATH: join(dir, 'result.json'),
      EVAL_TASK_PATH: join(dir, 'task.json'),
      EVAL_TARGET_DIR: fileURLToPath(new URL('../', import.meta.url)),
      EVAL_MODEL: 'gpt-5.5',
      EVAL_MAX_STEPS: '4',
      EVAL_OPTIONS_JSON: '{}',
      EVAL_TIMEOUT_MINUTES: '30',
      EVAL_MODEL_API_KEY: 'fixture-only',
      BROWSER_USE_API_KEY: 'fixture-only',
      LMNR_PROJECT_API_KEY: 'fixture-only',
      LMNR_SPAN_CONTEXT: 'fixture-parent',
    });
    globalThis.fetch = async (input, options) => {
      const url = String(input instanceof Request ? input.url : input);
      if (url === 'https://api.browser-use.com/api/v3/browsers')
        return Response.json({ id: 'fixture-browser', cdpUrl: chrome.endpoint });
      if (url.endsWith('/api/v3/browsers/fixture-browser')) {
        stops++;
        assert.equal(options.method, 'PATCH');
        return Response.json({});
      }
      if (url.startsWith('https://api.openai.com/')) {
        requests++;
        const name = requests === 1 ? 'javascript' : 'finish';
        const args =
          requests === 1
            ? {
                code: `await page.goto(${JSON.stringify(fixture.url)});await page.click({role:'button',name:'Save selection'});await artifact('proof.txt',await page.text({role:'status'}));await page.text({role:'status'})`,
              }
            : { result: 'Saved exactly once; see proof.txt' };
        const item = {
          id: `fc_${requests}`,
          call_id: `call_${requests}`,
          type: 'function_call',
          name,
          arguments: JSON.stringify(args),
          status: 'completed',
        };
        const events = [
          [
            'response.created',
            { response: { id: `r${requests}`, status: 'in_progress', output: [] } },
          ],
          [
            'response.output_item.added',
            { output_index: 0, item: { ...item, arguments: '', status: 'in_progress' } },
          ],
          [
            'response.function_call_arguments.delta',
            { item_id: item.id, output_index: 0, delta: item.arguments },
          ],
          ['response.output_item.done', { output_index: 0, item }],
          [
            'response.completed',
            {
              response: {
                id: `r${requests}`,
                status: 'completed',
                output: [item],
                usage: {
                  input_tokens: 10,
                  output_tokens: 5,
                  total_tokens: 15,
                  input_tokens_details: { cached_tokens: 0 },
                },
              },
            },
          ],
        ];
        return new Response(
          events
            .map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`)
            .join(''),
          { headers: { 'content-type': 'text/event-stream' } },
        );
      }
      if (url.startsWith('http://127.0.0.1:')) return originalFetch(input, options);
      throw new Error('Unexpected external request in contract test: ' + new URL(url).hostname);
    };
    assert.equal(await main(), 0);
    const result = JSON.parse(await readFile(join(dir, 'result.json'), 'utf8'));
    assert.equal(result.metadata.stop_reason, 'completed');
    assert.equal(result.metrics.steps, 2);
    assert.equal(result.metadata.screenshot_errors, 0);
    assert.ok(result.artifacts.some((path) => path.endsWith('.jpg')));
    assert.equal(await readFile(join(dir, 'agent_outputs/proof.txt'), 'utf8'), 'Saved 1 time(s)');
    assert.equal(stops, 1);
    assert.equal(requests, 2);
    assert.equal(telemetry[0].parentSpanContext, 'fixture-parent');
    assert.equal(telemetry.filter((s) => s.spanType === 'LLM').length, 2);
    assert.ok(telemetry.every((s) => s.ended));
  } finally {
    globalThis.fetch = originalFetch;
    for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key];
    Object.assign(process.env, saved);
    for (const patch of patches) patch.mock.restore();
    await chrome.close();
    await fixture.close();
    await rm(dir, { recursive: true, force: true });
  }
});
