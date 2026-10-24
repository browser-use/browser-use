import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createTelemetry } from '../dist/telemetry.js';

const environmentNames = [
  'NODE_TEST_CONTEXT',
  'DO_NOT_TRACK',
  'ANONYMIZED_TELEMETRY',
  'BH_TELEMETRY',
  'BROWSER_HARNESS_TELEMETRY',
];

function environment() {
  const saved = Object.fromEntries(environmentNames.map((name) => [name, process.env[name]]));
  for (const name of environmentNames) delete process.env[name];
  return () => {
    for (const [name, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  };
}

const model = {
  id: 'future-model-2099',
  provider: 'compatible-gateway',
  api: 'openai-completions',
  baseUrl: 'https://SECRET.invalid/?token=PASSWORD',
  headers: { Authorization: 'PASSWORD' },
  contextWindow: 200000,
  maxTokens: 12000,
  reasoning: true,
  input: ['text', 'image'],
  cost: { input: 2, output: 10, cacheRead: 0.2, cacheWrite: 3 },
};
const result = {
  status: 'completed',
  steps: 3,
  finishRepairs: 1,
  compactions: 1,
  providerRetries: 2,
  context: { compactionFailures: 1 },
  durationMs: 42,
  usage: {
    input: 100,
    output: 20,
    cacheRead: 30,
    cacheWrite: 5,
    totalTokens: 155,
    cost: { input: 0.02, output: 0.01, cacheRead: 0.01, cacheWrite: 0, total: 0.04 },
  },
  task: 'SECRET TASK',
  model: 'SECRET RESULT MODEL',
  text: 'SECRET OUTPUT',
  output: 'PASSWORD',
  workspace: '/SECRET/path',
  error: 'SECRET EXCEPTION',
};

test('lifecycle payload preserves scoped usage and excludes content outside its typed fields', async () => {
  const restore = environment();
  const requests = [];
  const patch = mock.method(globalThis, 'fetch', async (url, options) => {
    requests.push({ url, options, body: JSON.parse(options.body) });
    return new Response();
  });
  try {
    const telemetry = createTelemetry({
      browser: { kind: 'pending', timeoutMs: 1000 },
      browserSelection: 'explicit',
      model,
      modelMetadataSource: 'explicit',
      pricingKnown: true,
      clientLanguage: 'python',
      configuration: {
        allowedDomains: ['SECRET.invalid'],
        sensitiveData: { SECRET: { value: 'PASSWORD', domains: ['SECRET.invalid'] } },
        researchTools: true,
        tools: [{ name: 'SECRET_TOOL' }],
        log: 'json',
        task: 'SECRET TASK',
      },
    });
    const operation = telemetry.start('agent_run', {
      parentOperationId: '00000000-0000-4000-8000-000000000001',
      childId: 'SECRET',
      run: { schema: true, compaction: true, maxSteps: 10, task: 'SECRET TASK' },
    });
    operation.count('tool_calls', 2);
    operation.count('uploads', 0);
    operation.count('tool_calls', NaN);
    operation.count('SECRET');
    operation.browser('cdp');
    operation.finish({
      result,
      summaryUsage: { input: 10, output: 2, cost: { total: 0.01 } },
      pausedDurationMs: 4,
      modelDurationMs: 15,
      coverage: 'partial',
    });
    operation.finish({ result });
    await telemetry.flush();
    assert.deepEqual(
      requests.map((request) => request.body.event),
      ['bu_operation_started', 'bu_operation_finished'],
    );
    const start = requests[0].body.properties;
    const finish = requests[1].body.properties;
    assert.equal(start.operation_id, finish.operation_id);
    assert.equal(start.session_id, finish.session_id);
    assert.notEqual(start.event_id, finish.event_id);
    assert.equal(start.distinct_id, start.session_id);
    assert.equal(start.model_id, 'future-model-2099');
    assert.equal(start.model_provider, 'compatible-gateway');
    assert.equal(start.model_context_window, 200000);
    assert.equal(start.model_metadata_source, 'explicit');
    assert.equal(start.client_language, 'python');
    assert.equal(start.architecture, process.arch);
    assert.equal(start.browser_requested, 'pending');
    assert.equal(start.configured_features.allowlist_configured, true);
    assert.equal(start.configured_features.secrets_configured, true);
    assert.equal(start.structured_output, true);
    assert.equal(start.child_id, null);
    assert.equal(start.$process_person_profile, false);
    assert.equal(start.$geoip_disable, true);
    assert.equal(start.subagent_tracking, 'unsupported');
    assert.equal(finish.browser_effective, 'cdp');
    assert.equal(finish.feature_usage.tool_calls, 2);
    assert.equal(finish.feature_usage.uploads, 0);
    assert.equal(finish.feature_usage.downloads, null);
    assert.equal(finish.feature_coverage, 'partial');
    assert.equal(finish.usage.input_tokens, 100);
    assert.equal(finish.usage.cache_read_tokens, 30);
    assert.equal(finish.usage.estimated_cost_usd, 0.04);
    assert.equal(finish.summary_usage.estimated_cost_usd, 0.01);
    assert.equal(finish.compactions, 1);
    assert.equal(finish.compaction_failures, 1);
    assert.equal(finish.provider_retries, 2);
    assert.equal(finish.usage_completeness, 'unknown');
    assert.equal(finish.aggregation, 'direct');
    assert.equal(finish.descendant_usage, null);
    assert.equal(finish.task_verification, 'unknown');
    assert.ok(finish.operation_duration_ms >= 0);
    assert.doesNotMatch(JSON.stringify(requests), /SECRET|PASSWORD/);
    const metadata = JSON.parse(await readFile(new URL('../package.json', import.meta.url)));
    assert.equal(start.engine_version, metadata.version);
    for (const request of requests) {
      assert.equal(request.url, 'https://eu.i.posthog.com/i/v0/e/');
      assert.equal(request.options.redirect, 'error');
      assert.ok(request.options.signal instanceof AbortSignal);
    }
  } finally {
    patch.mock.restore();
    restore();
  }
});

test('all opt-outs suppress both lifecycle events and override explicit enablement', async () => {
  const restore = environment();
  const requests = [];
  const patch = mock.method(globalThis, 'fetch', async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return new Response();
  });
  const rows = [
    ['DO_NOT_TRACK', '1'],
    ['ANONYMIZED_TELEMETRY', 'false'],
    ['BH_TELEMETRY', 'off'],
    ['BROWSER_HARNESS_TELEMETRY', '0'],
    ['NODE_TEST_CONTEXT', 'child-v8'],
  ];
  try {
    for (const [name, value] of rows) {
      process.env[name] = value;
      const telemetry = createTelemetry({ enabled: true });
      telemetry.start('browser_session').finish({ status: 'closed' });
      await telemetry.flush();
      assert.equal(requests.length, 0, name);
      delete process.env[name];
    }
    const changed = createTelemetry({ enabled: true });
    process.env.DO_NOT_TRACK = '1';
    const deniedOperation = changed.start('browser_session');
    delete process.env.DO_NOT_TRACK;
    deniedOperation.finish({ status: 'closed' });
    await changed.flush();
    assert.equal(requests.length, 0);
    const disabled = createTelemetry({ enabled: false });
    disabled.start('agent_run').finish({ result });
    const enabled = createTelemetry({ enabled: true });
    enabled.start('browser_session').finish({ status: 'closed' });
    await enabled.flush();
    assert.equal(requests.length, 2);
  } finally {
    patch.mock.restore();
    restore();
  }
});

test('unpriced and malformed metadata remain unknown without changing operation results', async () => {
  const restore = environment();
  const requests = [];
  const patch = mock.method(globalThis, 'fetch', async (_url, options) => {
    requests.push(JSON.parse(options.body));
    throw new Error('SECRET TRANSPORT ERROR');
  });
  try {
    const telemetry = createTelemetry({
      model: { ...model, id: 'https://SECRET.invalid', cost: undefined },
      browser: 'SECRET',
      configuration: { researchTools: 'SECRET' },
      controller: 'anthropic_toolset',
      backend: 'pi_runtime',
    });
    telemetry.start('browser_session', { aggregation: 'cumulative_rollup' }).finish({ result });
    await telemetry.flush();
    assert.equal(requests[0].properties.model_id, null);
    assert.equal(requests[0].properties.browser_requested, 'unknown');
    assert.equal(requests[0].properties.pricing_known, false);
    assert.equal(requests[0].properties.configured_features.research_tools, null);
    assert.equal(requests[1].properties.usage.estimated_cost_usd, null);
    assert.equal(requests[1].properties.usage.input_tokens, 100);
    assert.equal(requests[1].properties.aggregation, 'cumulative_rollup');
    assert.equal(requests[1].properties.model_duration_ms_sum, null);
    assert.doesNotMatch(JSON.stringify(requests), /SECRET/);
    const unmeasuredCost = createTelemetry({ model, pricingKnown: true });
    unmeasuredCost.start('agent_run').finish({
      result: { ...result, usage: { ...result.usage, cost: undefined } },
      usageCompleteness: 'complete',
    });
    await unmeasuredCost.flush();
    assert.equal(requests.at(-1).properties.usage.estimated_cost_usd, null);
    assert.equal(requests.at(-1).properties.cost_completeness, 'unknown');
  } finally {
    patch.mock.restore();
    restore();
  }
});

test('transport buffering stays bounded while requests remain pending', async () => {
  const restore = environment();
  const releases = [];
  const patch = mock.method(
    globalThis,
    'fetch',
    () => new Promise((resolve) => releases.push(resolve)),
  );
  try {
    const telemetry = createTelemetry();
    const operations = Array.from({ length: 40 }, () => telemetry.start('cli_command'));
    assert.equal(releases.length, 16);
    for (const operation of operations) operation.finish({ status: 'completed' });
    assert.equal(releases.length, 32);
    for (const release of releases) release(new Response());
    await telemetry.flush();
    const syncFailure = mock.method(globalThis, 'fetch', () => {
      throw new Error('offline');
    });
    try {
      assert.doesNotThrow(() => telemetry.start('cli_command').finish({ status: 'error' }));
      await telemetry.flush();
    } finally {
      syncFailure.mock.restore();
    }
  } finally {
    patch.mock.restore();
    restore();
  }
});

test('CDP endpoint classification never sends connection credentials or addresses', async () => {
  const restore = environment();
  const requests = [];
  const patch = mock.method(globalThis, 'fetch', async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return new Response();
  });
  const rows = [
    ['ws://user:PASSWORD@127.0.0.1:9222/SECRET?key=PASSWORD', 'loopback', 'ws'],
    ['http://192.168.2.3:9222/SECRET', 'private', 'http'],
    ['wss://[::1]/SECRET', 'loopback', 'wss'],
    ['wss://[fd00::1]/SECRET', 'private', 'wss'],
    ['https://8.8.8.8/SECRET', 'public', 'https'],
    ['wss://SECRET.invalid/SECRET', 'hostname', 'wss'],
    ['SECRET', 'unknown', null],
  ];
  try {
    for (const [cdpUrl, category, protocol] of rows) {
      const telemetry = createTelemetry({ browser: { cdpUrl } });
      telemetry.start('browser_session').finish({ status: 'closed' });
      await telemetry.flush();
      const start = requests.at(-2).properties;
      assert.equal(start.cdp_endpoint_category, category, cdpUrl);
      assert.equal(start.cdp_protocol, protocol, cdpUrl);
    }
    assert.doesNotMatch(
      JSON.stringify(requests),
      /SECRET|PASSWORD|127\.0\.0\.1|192\.168|8\.8\.8\.8/,
    );
  } finally {
    patch.mock.restore();
    restore();
  }
});
