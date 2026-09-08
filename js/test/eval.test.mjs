import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseOptions, resultEnvelope } from '../eval/run.mjs';

test('eval options reject unknown settings, invalid budgets and browser expiry', () => {
  assert.equal(parseOptions({}).reasoning_effort, 'medium');
  assert.equal(parseOptions({}).max_context_chars, 800000);
  assert.equal(parseOptions({}).delivery_review, undefined);
  assert.equal(parseOptions({ delivery_review: true }).delivery_review, true);
  assert.equal(parseOptions({ delivery_review: false }).delivery_review, false);
  assert.equal(
    parseOptions({
      task_timeout_seconds: 3600,
      browser_timeout_minutes: 70,
      evidence_format: 'findings',
    }).task_timeout_seconds,
    3600,
  );
  for (const options of [
    { typo: true },
    { evidence_format: 'other' },
    { delivery_review: 'true' },
    { delivery_review: 1 },
    { task_timeout_seconds: 7201 },
    { task_timeout_seconds: 3600, browser_timeout_minutes: 60 },
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

for (const [evidenceFormat, cleanScreenshots, deliveryReview, maxSteps] of [
  [undefined, false],
  ['findings', false],
  ['findings', true],
  ['findings', false, true, 4],
  ['findings', false, true, 2],
])
  test(`adapter uses real CDP and cleans up (${evidenceFormat ?? 'default'} evidence${cleanScreenshots ? ', agent screenshot cleanup' : ''}${deliveryReview ? ', delivery review budget ' + maxSteps : ''})`, async () => {
    const { main } = await import('../eval/run.mjs');
    const { openBrowser } = await import('../dist/browser.js');
    const { startFixture } = await import('../examples/fixture.mjs');
    const { mkdtemp, writeFile, readFile, rm, mkdir, symlink } = await import('node:fs/promises');
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
    let firstCapture;
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
      if (evidenceFormat) {
        const { execFileSync } = await import('node:child_process');
        await mkdir(join(dir, '.venv/bin'), { recursive: true });
        await symlink(
          process.env.BU_EVAL_PYTHON ??
            execFileSync('which', ['python3'], { encoding: 'utf8' }).trim(),
          join(dir, '.venv/bin/python'),
        );
      }
      await writeFile(
        join(dir, 'task.json'),
        JSON.stringify({ task_id: 'fixture', confirmed_task: 'Read catalog; save once.' }),
      );
      await writeFile(join(dir, 'dependencies.sha256'), 'fixture-hash');
      await mkdir(join(dir, 'agent_outputs/.browser-use/context'), { recursive: true });
      await writeFile(
        join(dir, 'agent_outputs/.browser-use/context/fixture.json'),
        '{"saved":true}',
      );
      await writeFile(join(dir, '.unrelated-secret'), 'fixture-private');
      await symlink(
        join(dir, '.unrelated-secret'),
        join(dir, 'agent_outputs/.browser-use/context/skip.txt'),
      );
      Object.assign(process.env, {
        EVAL_WORKSPACE: dir,
        EVAL_RESULT_PATH: join(dir, 'result.json'),
        EVAL_TASK_PATH: join(dir, 'task.json'),
        EVAL_TARGET_DIR: fileURLToPath(new URL('../', import.meta.url)),
        EVAL_MODEL: evidenceFormat ? 'gpt-5.6-luna' : 'gpt-5.5',
        EVAL_MAX_STEPS: String(maxSteps ?? 4),
        EVAL_OPTIONS_JSON: JSON.stringify({
          ...(evidenceFormat ? { evidence_format: evidenceFormat, reasoning_effort: 'xhigh' } : {}),
          ...(deliveryReview ? { delivery_review: true } : {}),
        }),
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
          const requestBody = JSON.parse(options.body);
          assert.equal(requestBody.model, evidenceFormat ? 'gpt-5.6-luna' : 'gpt-5.5');
          assert.equal(requestBody.reasoning.effort, evidenceFormat ? 'xhigh' : 'medium');
          requests++;
          if (deliveryReview && requests === 3)
            assert.match(JSON.stringify(requestBody.input), /Delivery review checkpoint/);
          const cleanup = cleanScreenshots && requests === 2;
          if (cleanup) {
            // Observers are nonblocking. Wait until a real capture exists before
            // issuing cleanup, so this tests retention, not a capture race.
            for (let attempt = 0; attempt < 100 && !firstCapture; attempt++) {
              firstCapture = await Promise.any([
                readFile(join(dir, 'judge_screenshots/001.png')),
                readFile(join(dir, 'agent_outputs/screenshots/001.png')),
              ]).catch(() => undefined);
              if (!firstCapture) await new Promise((resolve) => setTimeout(resolve, 20));
            }
            assert.ok(firstCapture, 'capture must exist before agent cleanup');
          }
          const name = requests === 1 || cleanup ? 'javascript' : 'finish';
          const args =
            requests === 1
              ? {
                  code: `await page.goto(${JSON.stringify(fixture.url)});await page.click({role:'button',name:'Save selection'});await artifact('proof.txt',await page.text({role:'status'}));await page.text({role:'status'})`,
                }
              : cleanup
                ? {
                    code: "await require('node:fs/promises').rm(require('node:path').join(workspace,'screenshots'),{recursive:true,force:true}); await page.text({role:'status'})",
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
              .map(
                ([type, data]) => `event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`,
              )
              .join(''),
            { headers: { 'content-type': 'text/event-stream' } },
          );
        }
        if (url.startsWith('http://127.0.0.1:')) return originalFetch(input, options);
        throw new Error('Unexpected external request in contract test: ' + new URL(url).hostname);
      };
      assert.equal(await main(), 0);
      const result = JSON.parse(await readFile(join(dir, 'result.json'), 'utf8'));
      const reviewExhausted = deliveryReview && maxSteps === 2;
      assert.equal(result.metadata.stop_reason, reviewExhausted ? 'max_steps' : 'completed');
      const expectedRequests = cleanScreenshots || (deliveryReview && !reviewExhausted) ? 3 : 2;
      assert.equal(result.metrics.steps, expectedRequests);
      assert.equal(
        result.metadata.delivery_review_submissions,
        deliveryReview ? (reviewExhausted ? 1 : 2) : 0,
      );
      assert.equal(result.metadata.screenshot_errors, 0);
      assert.equal(result.metadata.screenshot_detach_errors, 0);
      assert.equal(result.metadata.sdk_audit_archive, 'sdk-audit.tar.gz');
      assert.ok(result.artifacts.includes('sdk-audit.tar.gz'));
      const { execFileSync } = await import('node:child_process');
      const archive = join(dir, 'sdk-audit.tar.gz');
      const archivedPaths = execFileSync('tar', ['-tzf', archive], { encoding: 'utf8' });
      assert.match(archivedPaths, /\.browser-use\/context\/fixture\.json/);
      assert.match(archivedPaths, /\.browser-use\/cells\//);
      assert.match(archivedPaths, /\.browser-use\/runs\//);
      assert.doesNotMatch(archivedPaths, /unrelated-secret|skip\.txt/);
      assert.equal(
        execFileSync('tar', ['-xOzf', archive, '.browser-use/context/fixture.json'], {
          encoding: 'utf8',
        }),
        '{"saved":true}',
      );
      assert.ok(result.metadata.screenshot_time_ms > 0);
      assert.ok(result.artifacts.some((path) => path.endsWith(evidenceFormat ? '.png' : '.jpg')));
      if (evidenceFormat) {
        assert.equal(result.metadata.output_files.length, 1);
        assert.equal(result.metadata.output_files[0].name, 'proof.txt');
        assert.equal(result.metadata.output_files[0].text, 'Saved 1 time(s)');
        assert.ok(result.metadata.steps.some((s) => s.includes('Save selection')));
        if (cleanScreenshots) assert.ok(result.metadata.judge_screenshots.length >= 1);
        else assert.equal(result.metadata.judge_screenshots.length, 1);
        assert.equal(result.metadata.judge_screenshot_steps[0], 1);
        if (cleanScreenshots)
          assert.deepEqual(
            await readFile(join(dir, result.metadata.judge_screenshots[0])),
            firstCapture,
          );
        for (const path of result.metadata.judge_screenshots) {
          assert.ok(result.artifacts.includes(path));
          const shot = await readFile(join(dir, path));
          assert.equal(shot.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
        }
        assert.deepEqual(result.metadata.staged_outputs, ['agent_outputs/proof.txt']);
      }
      assert.equal(await readFile(join(dir, 'agent_outputs/proof.txt'), 'utf8'), 'Saved 1 time(s)');
      assert.equal(stops, 1);
      assert.equal(requests, expectedRequests);
      assert.equal(telemetry[0].parentSpanContext, 'fixture-parent');
      assert.equal(telemetry.filter((s) => s.spanType === 'LLM').length, requests);
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
