#!/usr/bin/env node
/** Evaluate Pi + Browser Use Next over raw CDP. One isolated cloud browser; no action replay. */
import { mkdir, readFile, writeFile, appendFile, readdir } from 'node:fs/promises';
import { join, resolve, relative } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

export function parseOptions(value) {
  const allowed = new Set([
    'reasoning_effort',
    'max_context_chars',
    'task_timeout_seconds',
    'proxy_country_code',
    'browser_timeout_minutes',
  ]);
  if (!value || Array.isArray(value) || typeof value !== 'object')
    throw new Error('options must be an object');
  for (const key of Object.keys(value))
    if (!allowed.has(key)) throw new Error(`Unknown option: ${key}`);
  const options = {
    reasoning_effort: 'medium',
    max_context_chars: 800000,
    task_timeout_seconds: 1700,
    proxy_country_code: 'us',
    browser_timeout_minutes: 60,
    ...value,
  };
  if (!['off', 'minimal', 'low', 'medium', 'high', 'xhigh'].includes(options.reasoning_effort))
    throw new Error('Invalid reasoning_effort');
  if (
    !Number.isSafeInteger(options.max_context_chars) ||
    options.max_context_chars < 1000 ||
    options.max_context_chars > 3000000
  )
    throw new Error('max_context_chars must be 1000..3000000');
  if (
    !Number.isInteger(options.task_timeout_seconds) ||
    options.task_timeout_seconds < 1 ||
    options.task_timeout_seconds > 3500
  )
    throw new Error('task_timeout_seconds must be 1..3500');
  if (
    !Number.isInteger(options.browser_timeout_minutes) ||
    options.browser_timeout_minutes < 1 ||
    options.browser_timeout_minutes > 240
  )
    throw new Error('browser_timeout_minutes must be 1..240');
  if (options.browser_timeout_minutes * 60 <= options.task_timeout_seconds + 30)
    throw new Error('Browser lifetime must exceed task timeout plus 30 seconds');
  if (options.proxy_country_code !== null && !/^[a-z]{2}$/.test(options.proxy_country_code))
    throw new Error('proxy_country_code must be a lowercase country code or null');
  return options;
}

export function resultEnvelope(run, artifacts, metadata) {
  return {
    status: run.status === 'error' ? 'failed' : 'completed',
    final_output: run.text,
    self_reported_success: null, // A schema-valid finish is not a claim of factual correctness.
    error: run.error ?? null,
    metrics: {
      steps: run.steps,
      duration_seconds: run.durationMs / 1000,
      input_tokens: run.usage.input,
      output_tokens: run.usage.output,
      cached_input_tokens: run.usage.cacheRead,
      cache_write_tokens: run.usage.cacheWrite,
      total_tokens: run.usage.totalTokens,
      total_cost: run.usage.cost.total,
    },
    artifacts,
    metadata: {
      ...metadata,
      stop_reason: run.status,
      finish_repairs: run.finishRepairs,
      usage: run.usage,
      model: run.model,
    },
  };
}

async function files(directory, root = directory) {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) result.push(...(await files(path, root)));
    else if (entry.isFile()) result.push(relative(root, path));
  }
  return result;
}

export async function main() {
  const env = process.env;
  const workspace = resolve(env.EVAL_WORKSPACE);
  const resultPath = resolve(env.EVAL_RESULT_PATH);
  let browser, agent, observer, Laminar, root;
  const spans = new Map();
  let modelSpan;
  let envelope = {
    status: 'failed',
    final_output: '',
    self_reported_success: null,
    error: 'Harness did not start',
    metrics: {},
    artifacts: [],
    metadata: {},
  };
  const cleanupErrors = [];
  const cloudRequest = async (path, method, body) => {
    const response = await fetch(`https://api.browser-use.com/api/v3${path}`, {
      method,
      headers: {
        'X-Browser-Use-API-Key': env.BROWSER_USE_API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30000),
    });
    if (!response.ok)
      throw new Error(`Browser provider ${method} returned HTTP ${response.status}`);
    return response.status === 204 ? {} : response.json();
  };
  try {
    const options = parseOptions(JSON.parse(env.EVAL_OPTIONS_JSON || '{}'));
    if (Number(env.EVAL_TIMEOUT_MINUTES) * 60 < options.task_timeout_seconds + 90)
      throw new Error('Platform timeout must exceed task timeout by at least 90 seconds');
    if (!env.EVAL_MODEL_API_KEY || !env.BROWSER_USE_API_KEY || !env.LMNR_PROJECT_API_KEY)
      throw new Error('Model, browser, and Laminar credentials are required');
    const task = JSON.parse(await readFile(env.EVAL_TASK_PATH, 'utf8'));
    const sdk = resolve(env.EVAL_TARGET_DIR);
    const { BrowserUse, CDP } = await import(pathToFileURL(join(sdk, 'dist/index.js')).href);
    const require = createRequire(join(sdk, 'package.json'));
    const telemetry = require('@lmnr-ai/lmnr');
    Laminar = telemetry.Laminar;
    const A = telemetry.LaminarAttributes;
    Laminar.initialize({
      projectApiKey: env.LMNR_PROJECT_API_KEY,
      instrumentModules: {},
    });
    root = Laminar.startSpan({
      name: 'pi.browser_use_next',
      parentSpanContext: env.LMNR_SPAN_CONTEXT,
      input: { task, options, model: env.EVAL_MODEL },
    });
    const outputDir = join(workspace, 'agent_outputs');
    const screenshots = join(outputDir, 'screenshots');
    await mkdir(screenshots, { recursive: true });
    const model = env.EVAL_MODEL.includes('/') ? env.EVAL_MODEL : `openai/${env.EVAL_MODEL}`;
    if (!model.startsWith('openai/'))
      throw new Error('This eval adapter currently maps EVAL_MODEL_API_KEY to OpenAI only');
    env.OPENAI_API_KEY = env.EVAL_MODEL_API_KEY;
    browser = await cloudRequest('/browsers', 'POST', {
      timeout: options.browser_timeout_minutes,
      proxyCountryCode: options.proxy_country_code,
      browserScreenWidth: 1440,
      browserScreenHeight: 900,
      enableRecording: false,
    });
    if (!browser.id || !browser.cdpUrl)
      throw new Error('Browser provider returned no browser id/CDP endpoint');
    observer = await CDP.connect(browser.cdpUrl);
    agent = await BrowserUse.create({
      model,
      reasoning: options.reasoning_effort,
      browser: { cdpUrl: browser.cdpUrl },
      workspace: outputDir,
      cellTimeoutMs: 120000,
      operationTimeoutMs: 20000,
      instructions:
        'Use browser UI and page evaluation for research. Do not use web search or read files outside the output workspace. Do not inspect benchmark source, rubrics, judge code, or credentials. Save requested files in workspace.',
    });
    let screenshotIndex = 0;
    let screenshotErrors = 0;
    let screenshotTimeMs = 0;
    let screenshotDetachErrors = 0;
    const screenshotErrorDetails = [];
    const clean = (value) =>
      JSON.parse(
        JSON.stringify(value, (key, value) =>
          key === 'data' && typeof value === 'string' && value.length > 10000
            ? '[image bytes in evidence file]'
            : value,
        ),
      );
    const run = await Laminar.withSpan(
      root,
      () =>
        agent.run(
          `${task.confirmed_task}${task.website ? `\nStarting website: ${task.website}` : ''}`,
          {
            maxSteps: Number(env.EVAL_MAX_STEPS || 35),
            timeoutMs: options.task_timeout_seconds * 1000,
            maxContextChars: options.max_context_chars,
            async onEvent(event) {
              if (
                ['message_end', 'tool_execution_start', 'tool_execution_end'].includes(event.type)
              )
                await appendFile(
                  join(workspace, 'events.jsonl'),
                  JSON.stringify(clean(event)) + '\n',
                );
              if (event.type === 'turn_start')
                modelSpan = Laminar.startSpan({
                  name: 'pi.model',
                  spanType: 'LLM',
                  input: { task: task.confirmed_task, model },
                });
              if (event.type === 'message_end' && event.message.role === 'assistant' && modelSpan) {
                const m = event.message,
                  u = m.usage;
                modelSpan.setAttributes({
                  [A.PROVIDER]: m.provider,
                  [A.REQUEST_MODEL]: m.model,
                  [A.RESPONSE_MODEL]: m.model,
                  [A.INPUT_TOKEN_COUNT]: u.input + u.cacheRead + u.cacheWrite,
                  [A.OUTPUT_TOKEN_COUNT]: u.output,
                  [A.TOTAL_TOKEN_COUNT]: u.totalTokens,
                  [A.INPUT_COST]: u.cost.input + u.cost.cacheRead + u.cost.cacheWrite,
                  [A.OUTPUT_COST]: u.cost.output,
                  [A.TOTAL_COST]: u.cost.total,
                });
                Laminar.withSpan(modelSpan, () => Laminar.setSpanOutput(clean(m)), false);
                if (m.stopReason === 'error')
                  modelSpan.setStatus({
                    code: 2,
                    message: m.errorMessage || 'Provider error',
                  });
                modelSpan.end();
                modelSpan = undefined;
              }
              if (event.type === 'tool_execution_start')
                spans.set(
                  event.toolCallId,
                  Laminar.startSpan({
                    name: `tool.${event.toolName}`,
                    spanType: 'TOOL',
                    input: event.args,
                  }),
                );
              if (event.type === 'tool_execution_end') {
                const span = spans.get(event.toolCallId);
                if (span) {
                  Laminar.withSpan(span, () => Laminar.setSpanOutput(clean(event.result)), false);
                  if (event.isError)
                    span.setStatus({
                      code: 2,
                      message: 'Tool execution failed',
                    });
                  span.end();
                  spans.delete(event.toolCallId);
                }
                await appendFile(
                  join(workspace, 'agent_steps.txt'),
                  `${event.toolName}${event.isError ? ' ERROR' : ''}\n${JSON.stringify(clean(event.result))}\n`,
                );
                if (event.toolName === 'javascript') {
                  let sessionId;
                  const captureStarted = Date.now();
                  try {
                    const targetId = event.result.details?.targetId;
                    if (!targetId) throw new Error('Active page target unavailable after cell.');
                    // Screenshot capture needs a target session, not Page/Runtime event subscriptions.
                    ({ sessionId } = await observer.send('Target.attachToTarget', {
                      targetId,
                      flatten: true,
                    }));
                    const { data } = await observer.send(
                      'Page.captureScreenshot',
                      {
                        format: 'jpeg',
                        quality: 70,
                      },
                      sessionId,
                    );
                    await writeFile(
                      join(screenshots, `${String(++screenshotIndex).padStart(3, '0')}.jpg`),
                      Buffer.from(data, 'base64'),
                    );
                  } catch (error) {
                    screenshotErrors++;
                    if (screenshotErrorDetails.length < 20)
                      screenshotErrorDetails.push({
                        tool_call_id: event.toolCallId,
                        message: String(error.message).slice(0, 500),
                      });
                  } finally {
                    if (sessionId)
                      await observer
                        .send('Target.detachFromTarget', {
                          sessionId,
                        })
                        .catch(() => {
                          screenshotDetachErrors++;
                        });
                    screenshotTimeMs += Date.now() - captureStarted;
                  }
                }
              }
            },
          },
        ),
      false,
    );
    await writeFile(join(workspace, 'final_message.txt'), run.text);
    await writeFile(join(workspace, 'sdk-result.json'), JSON.stringify(run, null, 2));
    envelope = resultEnvelope(
      run,
      (await files(outputDir))
        .map((p) => `agent_outputs/${p}`)
        .concat(['events.jsonl', 'agent_steps.txt', 'final_message.txt', 'sdk-result.json']),
      {
        browser: { id: browser.id },
        options,
        node: process.version,
        dependency_lock_sha256: (
          await readFile(join(workspace, 'dependencies.sha256'), 'utf8')
        ).trim(),
        screenshot_errors: screenshotErrors,
        screenshot_time_ms: screenshotTimeMs,
        screenshot_detach_errors: screenshotDetachErrors,
        screenshot_error_details: screenshotErrorDetails,
        retries: 0,
      },
    );
  } catch (error) {
    envelope.error = error.message;
    envelope.metadata.failure_class = 'harness-or-provider';
    console.error(error.message);
  } finally {
    modelSpan?.end();
    for (const span of spans.values()) span.end();
    try {
      await agent?.close();
    } catch (error) {
      cleanupErrors.push(`SDK: ${error.message}`);
    }
    observer?.close();
    if (browser?.id) {
      try {
        await cloudRequest(`/browsers/${encodeURIComponent(browser.id)}`, 'PATCH', {
          action: 'stop',
        });
      } catch (error) {
        cleanupErrors.push(`Cloud: ${error.message}`);
      }
    }
    if (cleanupErrors.length) envelope.metadata.cleanup_errors = cleanupErrors;
    await writeFile(resultPath, JSON.stringify(envelope, null, 2) + '\n');
    if (root) {
      Laminar.withSpan(root, () => Laminar.setSpanOutput(envelope), false);
      root.end();
    }
    if (Laminar) {
      await Laminar.flush();
      await Laminar.shutdown();
    }
  }
  return envelope.status === 'failed' ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href)
  process.exitCode = await main();
