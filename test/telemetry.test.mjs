import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { Browser, BrowserUse, Type } from '../dist/index.js';
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

function captureTelemetry() {
  const restoreEnvironment = environment();
  const requests = [];
  const patch = mock.method(globalThis, 'fetch', async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return new Response();
  });
  return {
    requests,
    restore() {
      patch.mock.restore();
      restoreEnvironment();
    },
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
  text: 'Final response',
  warnings: ['Warning PASSWORD'],
  output: 'PASSWORD',
  workspace: '/SECRET/path',
  error: 'SECRET EXCEPTION',
};

test('one final payload retains configuration, scoped usage, and redacted task content', async () => {
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
        redact: ['PASSWORD'],
        task: 'SECRET TASK',
      },
    });
    const runConfiguration = { schema: true, compaction: true, maxSteps: 10 };
    const operation = telemetry.start('agent_run', {
      task: 'Complete the task with PASSWORD',
      parentOperationId: '00000000-0000-4000-8000-000000000001',
      childId: 'SECRET',
      run: runConfiguration,
    });
    assert.equal(requests.length, 0);
    runConfiguration.maxSteps = 99;
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
      ['bu_operation_finished'],
    );
    const finish = requests[0].body.properties;
    assert.equal(finish.operation_id, operation.operationId);
    assert.equal(finish.parent_operation_id, '00000000-0000-4000-8000-000000000001');
    assert.equal(finish.schema_version, 2);
    assert.equal(finish.task, 'Complete the task with [REDACTED]');
    assert.equal(finish.output, 'Final response');
    assert.equal(finish.output_format, 'text');
    assert.equal(finish.content_truncated.output, false);
    assert.equal(finish.warnings, 'Warning [REDACTED]');
    assert.equal(finish.warning_count, 1);
    assert.equal(finish.distinct_id, finish.session_id);
    assert.equal(finish.model_id, 'future-model-2099');
    assert.equal(finish.model_provider, 'compatible-gateway');
    assert.equal(finish.model_context_window, 200000);
    assert.equal(finish.model_metadata_source, 'explicit');
    assert.equal(finish.client_language, 'python');
    assert.equal(finish.architecture, process.arch);
    assert.equal(finish.browser_requested, 'pending');
    assert.equal(finish.configured_features.allowlist_configured, true);
    assert.equal(finish.configured_features.secrets_configured, true);
    assert.equal(finish.structured_output, true);
    assert.equal(finish.max_steps, 10);
    assert.equal(finish.child_id, null);
    assert.equal(finish.$process_person_profile, false);
    assert.equal(finish.$geoip_disable, true);
    assert.equal(finish.subagent_tracking, 'unsupported');
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
    assert.equal(finish.engine_version, metadata.version);
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

test('all opt-outs suppress final events and override explicit enablement', async () => {
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
    assert.equal(requests.length, 1);
    const optedOutAtFinish = enabled.start('agent_run');
    process.env.DO_NOT_TRACK = '1';
    optedOutAtFinish.finish({ result });
    delete process.env.DO_NOT_TRACK;
    await enabled.flush();
    assert.equal(requests.length, 1);
  } finally {
    patch.mock.restore();
    restore();
  }
});

test('unpriced and malformed metadata remain unknown without changing operation results', async () => {
  const restore = environment();
  const workspace = await mkdtemp(join(tmpdir(), 'bu-telemetry-invalid-'));
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
    assert.equal(requests[0].properties.usage.estimated_cost_usd, null);
    assert.equal(requests[0].properties.usage.input_tokens, 100);
    assert.equal(requests[0].properties.aggregation, 'cumulative_rollup');
    assert.equal(requests[0].properties.model_duration_ms_sum, null);
    assert.doesNotMatch(JSON.stringify(requests), /SECRET/);
    const unmeasuredCost = createTelemetry({ model, pricingKnown: true });
    unmeasuredCost.start('agent_run').finish({
      result: { ...result, usage: { ...result.usage, cost: undefined } },
      usageCompleteness: 'complete',
    });
    await unmeasuredCost.flush();
    assert.equal(requests.at(-1).properties.usage.estimated_cost_usd, null);
    assert.equal(requests.at(-1).properties.cost_completeness, 'unknown');
    const requestCount = requests.length;
    for (const enabled of [false, true]) {
      await assert.rejects(
        BrowserUse.create({
          browser: {
            cdpUrl: 'wss://browser.example.test/session',
            headers: { Authorization: 123 },
          },
          telemetry: enabled,
          workspace,
        }),
        /CDP headers must contain valid names/,
      );
      assert.equal(requests.length, requestCount + Number(enabled));
    }
  } finally {
    await rm(workspace, { recursive: true, force: true });
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
    assert.equal(releases.length, 0);
    for (const operation of operations) operation.finish({ status: 'completed' });
    assert.equal(releases.length, 32);
    for (const release of releases) release(new Response());
    await telemetry.flush();
    for (let index = 0; index < 40; index++) telemetry.start('browser_session').discard();
    telemetry.start('agent_run').finish({ result });
    assert.equal(releases.length, 33);
    releases.at(-1)(new Response());
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

test('CDP URLs preserve connection location and remove credentials from every content field', async () => {
  const { requests, restore } = captureTelemetry();
  const content =
    'operator PASSWORD QUERY_SECRET FRAGMENT_SECRET SIGNED_SECRET OPAQUE%2fVALUE OPAQUE/VALUE HEADER_SECRET TLS_SECRET TLS_PASSWORD';
  const rows = [
    [
      'ws://operator:PASSWORD@127.0.0.1:9222/devtools/browser/session?key=QUERY_SECRET&region=eu#FRAGMENT_SECRET',
      'loopback',
      'ws',
      'ws://127.0.0.1:9222/devtools/browser/session?region=eu',
    ],
    [
      'http://192.168.2.3:9222/devtools/browser/session',
      'private',
      'http',
      'http://192.168.2.3:9222/devtools/browser/session',
    ],
    ['wss://[::1]/session', 'loopback', 'wss', 'wss://[::1]/session'],
    ['wss://[fd00::1]/session', 'private', 'wss', 'wss://[fd00::1]/session'],
    ['https://8.8.8.8/session', 'public', 'https', 'https://8.8.8.8/session'],
    [
      'wss://browser.example.test/session?X-Amz-Signature=SIGNED_SECRET',
      'hostname',
      'wss',
      'wss://browser.example.test/session',
    ],
    [
      'wss://browser.example.test/session?token=OPAQUE%2fVALUE',
      'hostname',
      'wss',
      'wss://browser.example.test/session',
    ],
    ...[
      '?&token=OPAQUE%2fVALUE&region=eu',
      '?region=eu&&token=OPAQUE%2fVALUE',
      '?region=eu&token=OPAQUE%2fVALUE&',
    ].map((query) => [
      `wss://browser.example.test/session${query}`,
      'hostname',
      'wss',
      'wss://browser.example.test/session?region=eu',
    ]),
    ['INVALID', 'unknown', null, null],
  ];
  try {
    for (const [cdpUrl, category, protocol, sanitized] of rows) {
      const telemetry = createTelemetry({
        browser: {
          cdpUrl,
          headers: { Authorization: 'Bearer HEADER_SECRET' },
          tls: { key: 'TLS_SECRET', passphrase: 'TLS_PASSWORD' },
        },
      });
      telemetry
        .start('browser_session', {
          task: content,
        })
        .finish({
          status: 'error',
          result: { ...result, text: content, warnings: [content] },
          error: content,
        });
      await telemetry.flush();
      const finish = requests.at(-1).properties;
      assert.equal(finish.cdp_endpoint_category, category, cdpUrl);
      assert.equal(finish.cdp_protocol, protocol, cdpUrl);
      assert.equal(finish.cdp_url, sanitized, cdpUrl);
      assert.doesNotMatch(JSON.stringify(finish), /HEADER_SECRET|TLS_SECRET|TLS_PASSWORD/);
      if (cdpUrl.includes('PASSWORD'))
        assert.doesNotMatch(
          JSON.stringify(finish),
          /operator|PASSWORD|QUERY_SECRET|FRAGMENT_SECRET/,
        );
      if (cdpUrl.includes('OPAQUE')) assert.doesNotMatch(JSON.stringify(finish), /OPAQUE/);
      if (cdpUrl.includes('SIGNED_SECRET'))
        assert.doesNotMatch(JSON.stringify(finish), /SIGNED_SECRET/);
    }
  } finally {
    restore();
  }
});

test('content limits bound UTF-8 payloads and expose truncation without serializing structured results again', async () => {
  const { requests, restore } = captureTelemetry();
  const limits = { task: 32768, output: 65536, error: 8192, warnings: 8192, cdp_url: 4096 };
  const value = '😀'.repeat(100000);
  let serialized = false;
  const output = {
    toJSON() {
      serialized = true;
      throw new Error('Output serialization must not run');
    },
  };
  try {
    const telemetry = createTelemetry({ configuration: { redact: ['BOUNDARY_SECRET'] } });
    telemetry.start('agent_run', { task: value }).finish({
      result: {
        ...result,
        text: 'x'.repeat(limits.output - 5) + 'BOUNDARY_SECRET' + value,
        warnings: [value, 'later warning'],
        output,
      },
      error: value,
      cdpUrl: 'wss://browser.example.test/' + 'x'.repeat(5000),
    });
    await telemetry.flush();
    const finish = requests[0].properties;
    assert.equal(serialized, false);
    assert.equal(finish.output_format, 'json');
    assert.doesNotMatch(finish.output, /BOUNDARY|SECRET/);
    for (const [name, limit] of Object.entries(limits)) {
      assert.equal(finish.content_truncated[name], true, name);
      assert.ok(Buffer.byteLength(finish[name]) <= limit, name);
      assert.ok(finish.content_original_bytes[name] > limit, name);
      assert.equal(Buffer.from(finish[name]).toString(), finish[name], name);
    }
    assert.ok(Buffer.byteLength(JSON.stringify(requests[0])) < 768000);
    const escaped = '\u0000'.repeat(100000);
    telemetry
      .start('agent_run', { task: escaped })
      .finish({ result: { ...result, text: escaped, warnings: [escaped] }, error: escaped });
    await telemetry.flush();
    assert.ok(Buffer.byteLength(JSON.stringify(requests[1])) < 768000);
  } finally {
    restore();
  }
});

test('task completion, model failure, and cancellation each send one final event without a session duplicate', async () => {
  const { requests, restore } = captureTelemetry();
  const workspace = await mkdtemp(join(tmpdir(), 'bu-telemetry-'));
  const faux = fauxProvider({ tokensPerSecond: 1000000 });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses([
    fauxAssistantMessage(
      fauxToolCall('finish', {
        result: { answer: 'Result PASSWORD ENDPOINT_TOKEN QUOTED\"SECRET\nVALUE' },
      }),
      { stopReason: 'toolUse' },
    ),
    fauxAssistantMessage('', {
      stopReason: 'error',
      errorMessage: 'Provider failed PASSWORD ENDPOINT_TOKEN',
    }),
  ]);
  let agent;
  try {
    agent = await BrowserUse.create({
      model: `${faux.getModel().provider}/${faux.getModel().id}`,
      models,
      browser: Browser.pending(),
      sensitiveData: { password: { value: 'PASSWORD', domains: ['example.test'] } },
      redact: ['QUOTED\"SECRET\nVALUE'],
      workspace,
      log: false,
    });
    agent.connectBrowser(
      'wss://operator:ENDPOINT_PASSWORD@browser.example.test/session?token=ENDPOINT_TOKEN&region=eu',
    );
    assert.equal(requests.length, 0);
    const success = await agent.run('First PASSWORD ENDPOINT_TOKEN', {
      schema: Type.Object({ answer: Type.String() }),
      maxSteps: 10,
      timeoutMs: 10000,
      compaction: true,
    });
    assert.equal(success.status, 'completed');
    const failure = await agent.run('Second PASSWORD');
    assert.equal(failure.status, 'error');
    assert.equal(
      (await agent.run('Third PASSWORD', { signal: AbortSignal.abort() })).status,
      'cancelled',
    );
    await assert.rejects(agent.run('Invalid budget PASSWORD', { maxSteps: 0 }), /positive integer/);
    await agent.close();
    assert.equal(requests.length, 4);
    assert.deepEqual(
      requests.map((request) => request.properties.status),
      ['completed', 'error', 'cancelled', 'error'],
    );
    for (const request of requests) {
      assert.equal(request.event, 'bu_operation_finished');
      assert.equal(request.properties.operation_kind, 'agent_run');
      assert.equal(request.properties.cdp_url, 'wss://browser.example.test/session?region=eu');
    }
    const first = requests[0].properties;
    assert.equal(first.task, 'First [REDACTED] [REDACTED]');
    assert.equal(first.browser_effective, 'cdp');
    assert.equal(first.cdp_protocol, 'wss');
    assert.equal(first.cdp_endpoint_category, 'hostname');
    assert.deepEqual(JSON.parse(first.output), {
      answer: 'Result [REDACTED] [REDACTED] [REDACTED]',
    });
    assert.equal(first.max_steps, 10);
    assert.equal(first.timeout_ms, 10000);
    assert.equal(first.compaction_enabled, true);
    assert.equal(first.structured_output, true);
    assert.equal(first.configured_features.secrets_configured, true);
    assert.match(requests[1].properties.error, /Provider failed/);
    assert.match(requests[3].properties.error, /positive integer/);
    assert.doesNotMatch(
      JSON.stringify(requests),
      /PASSWORD|ENDPOINT_TOKEN|ENDPOINT_PASSWORD|operator/,
    );
  } finally {
    await agent?.close();
    await rm(workspace, { recursive: true, force: true });
    restore();
  }
});

test('provisioning and browser-ready failures send one final session event', async () => {
  const { requests, restore } = captureTelemetry();
  const workspace = await mkdtemp(join(tmpdir(), 'bu-telemetry-startup-'));
  const apiKey = process.env.BROWSER_USE_API_KEY;
  delete process.env.BROWSER_USE_API_KEY;
  try {
    const rows = [
      {
        options: { browser: Browser.cloud() },
        expected: /BROWSER_USE_API_KEY/,
        stage: 'provision',
      },
      {
        options: {
          browser: { cdpUrl: 'wss://browser.example.test/session?token=READY_TOKEN' },
          onBrowserReady: async () => {
            throw new Error('Browser initialization failed READY_TOKEN');
          },
        },
        expected: /Browser initialization failed/,
        stage: 'configure',
      },
    ];
    for (const [index, row] of rows.entries()) {
      await assert.rejects(BrowserUse.create({ ...row.options, workspace }), row.expected);
      assert.equal(requests.length, index + 1);
      const finish = requests[index].properties;
      assert.equal(finish.operation_kind, 'browser_session');
      assert.equal(finish.status, 'error');
      assert.equal(finish.error_stage, row.stage);
      assert.match(finish.error, row.expected);
      assert.doesNotMatch(JSON.stringify(finish), /READY_TOKEN/);
    }
  } finally {
    await rm(workspace, { recursive: true, force: true });
    if (apiKey === undefined) delete process.env.BROWSER_USE_API_KEY;
    else process.env.BROWSER_USE_API_KEY = apiKey;
    restore();
  }
});
