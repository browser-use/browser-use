import { randomUUID } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { isIP } from 'node:net';
import type { Api, Model, Usage } from '@earendil-works/pi-ai';
import type { BrowserOptions } from './browser.js';
import type { BrowserUseOptions, RunResult } from './types.js';

const token = 'phc_tcNY9BmpauyrDHDVhrhkFCaQEpH3vMnx3TDUZ49TWCek';
const host = 'https://eu.i.posthog.com/i/v0/e/';
const disabledValues = new Set(['false', '0', 'no', 'off']);
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const browserKinds = ['cloud', 'cdp', 'chrome', 'chromium', 'pending', 'unknown'] as const;
const counters = [
  'tool_calls',
  'tool_errors',
  'callback_calls',
  'callback_errors',
  'callback_timeouts',
  'pause_requests',
  'pauses',
  'resumes',
  'steering_accepted',
  'steering_consumed',
  'connections',
  'reconnects',
  'browser_switches',
  'domain_checks',
  'domain_denials',
  'secret_attempts',
  'secret_insertions',
  'uploads',
  'downloads',
  'recordings_saved',
  'history_saved',
  'schema_rejections',
  'validator_calls',
  'validator_rejections',
] as const;

export type BrowserKind = (typeof browserKinds)[number];
export type TelemetryCounter = (typeof counters)[number];
export type OperationKind = 'agent_run' | 'browser_session' | 'cli_command';
export type Coverage = 'complete' | 'partial' | 'unknown' | 'unsupported';
const errorClasses = [
  'configuration',
  'authentication',
  'provisioning',
  'connection',
  'policy',
  'model',
  'tool',
  'validation',
  'persistence',
  'cleanup',
  'cancelled',
  'unknown',
] as const;
const stages = [
  'startup',
  'configure',
  'provision',
  'connect',
  'model',
  'tool',
  'persist',
  'cleanup',
] as const;
export type ErrorClass = (typeof errorClasses)[number];
export type TelemetryStage = (typeof stages)[number];

type Configuration = Pick<
  BrowserUseOptions,
  | 'mode'
  | 'reasoning'
  | 'researchTools'
  | 'browserSwitching'
  | 'dedicatedBrowser'
  | 'focusTab'
  | 'allowedDomains'
  | 'prohibitedDomains'
  | 'sensitiveData'
  | 'tools'
  | 'beforeToolCall'
  | 'afterToolCall'
  | 'validateResult'
  | 'redact'
  | 'log'
  | 'historyFile'
  | 'recording'
  | 'highlightActions'
  | 'webSearch'
  | 'initScripts'
  | 'onBrowserReady'
>;

export interface TelemetryOptions {
  enabled?: boolean;
  browser?: BrowserOptions;
  browserSelection?: 'default' | 'explicit' | 'unknown';
  model?: Model<Api>;
  configuration?: Partial<Configuration>;
  clientLanguage?: 'python' | 'javascript' | 'unknown';
  entrypoint?: 'sdk' | 'cli' | 'adapter' | 'unknown';
  controller?: 'pi' | 'openai_toolset' | 'anthropic_toolset' | 'cli_direct' | 'custom';
  backend?: 'pi_runtime' | 'browser_harness' | 'unknown';
  clientVersion?: string;
  engineVersion?: string;
  installationSource?: 'wheel' | 'editable' | 'git' | 'unknown';
  modelMetadataSource?: 'catalog' | 'explicit' | 'template' | 'discovery' | 'unknown';
  pricingKnown?: boolean;
}

export interface TelemetryRunConfiguration {
  maxSteps?: number;
  timeoutMs?: number;
  maxCostUsd?: number;
  compaction?: boolean;
  maxContextChars?: number;
  schema?: boolean;
  onEvent?: boolean;
  observe?: boolean;
  onContextRecovery?: boolean;
}

export interface TelemetryStart {
  operationId?: string;
  parentOperationId?: string;
  childId?: string;
  aggregation?: 'direct' | 'cumulative_rollup';
  run?: TelemetryRunConfiguration;
}

export interface TelemetryFinish {
  status?: string;
  result?: RunResult<unknown>;
  errorClass?: ErrorClass;
  stage?: TelemetryStage;
  usageCompleteness?: 'complete' | 'partial' | 'unknown';
  summaryUsage?: Partial<Usage>;
  modelDurationMs?: number;
  toolDurationMs?: number;
  pausedDurationMs?: number;
  effectiveBrowser?: BrowserKind;
  coverage?: Coverage;
}

function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function boolean(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

function identifier(value: unknown): string | null {
  return typeof value === 'string' &&
    /^[a-zA-Z0-9][a-zA-Z0-9._:/+-]{0,199}$/.test(value) &&
    !value.includes('://')
    ? value
    : null;
}

function id(value: unknown): string | null {
  return typeof value === 'string' && uuidPattern.test(value) ? value : null;
}

function choice<T extends string>(value: unknown, values: readonly T[], fallback: T): T {
  return values.includes(value as T) ? (value as T) : fallback;
}

function version(): string {
  for (const path of ['./package.json', '../package.json']) {
    try {
      const metadata = JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
      const value = identifier(metadata.version);
      if (value) return value;
    } catch {}
  }
  return 'unknown';
}

function docker() {
  if (process.platform === 'darwin') return { docker: false, docker_detection: 'platform' };
  if (process.platform === 'linux') {
    if (existsSync('/.dockerenv')) return { docker: true, docker_detection: 'marker' };
    try {
      if (/docker/.test(readFileSync('/proc/self/cgroup', 'utf8')))
        return { docker: true, docker_detection: 'cgroup' };
    } catch {}
  }
  return { docker: null, docker_detection: 'unknown' };
}

export function telemetryEnabled(enabled?: boolean): boolean {
  return (
    enabled !== false &&
    process.env.DO_NOT_TRACK !== '1' &&
    !process.env.NODE_TEST_CONTEXT &&
    !['ANONYMIZED_TELEMETRY', 'BH_TELEMETRY', 'BROWSER_HARNESS_TELEMETRY'].some((name) =>
      disabledValues.has(process.env[name]?.trim().toLowerCase() ?? ''),
    )
  );
}

function kind(browser: BrowserOptions | undefined): BrowserKind {
  if (!browser || typeof browser !== 'object') return 'unknown';
  return choice(
    browser.kind ?? ('cdpUrl' in browser && browser.cdpUrl ? 'cdp' : 'unknown'),
    browserKinds,
    'unknown',
  );
}

function endpoint(browser: BrowserOptions | undefined) {
  let protocol: string | null = null;
  let category = 'unknown';
  try {
    if (browser && 'cdpUrl' in browser && browser.cdpUrl) {
      const url = new URL(browser.cdpUrl);
      protocol = choice(
        url.protocol.slice(0, -1),
        ['ws', 'wss', 'http', 'https', 'unknown'],
        'unknown',
      );
      const hostname = url.hostname.replace(/^\[|\]$/g, '').toLowerCase();
      if (
        hostname === 'localhost' ||
        hostname.endsWith('.localhost') ||
        hostname === '::1' ||
        hostname.startsWith('127.')
      )
        category = 'loopback';
      else if (isIP(hostname)) {
        const octets = hostname.split('.').map(Number);
        const privateAddress =
          octets[0] === 10 ||
          (octets[0] === 172 && octets[1]! >= 16 && octets[1]! <= 31) ||
          (octets[0] === 192 && octets[1] === 168) ||
          (octets[0] === 169 && octets[1] === 254) ||
          /^(fc|fd|fe[89ab])/i.test(hostname);
        category = privateAddress ? 'private' : 'public';
      } else category = 'hostname';
    }
  } catch {}
  return { cdp_protocol: protocol, cdp_endpoint_category: category };
}

function usage(
  value: (Omit<Partial<Usage>, 'cost'> & { cost?: Usage['cost'] | null }) | undefined,
  pricingKnown: boolean,
) {
  return {
    input_tokens: number(value?.input),
    output_tokens: number(value?.output),
    cache_read_tokens: number(value?.cacheRead),
    cache_write_tokens: number(value?.cacheWrite),
    reasoning_tokens: number(value?.reasoning),
    total_tokens: number(value?.totalTokens),
    estimated_cost_usd: pricingKnown ? number(value?.cost?.total) : null,
  };
}

function featureConfiguration(configuration: Partial<Configuration> | undefined) {
  const config = configuration ?? {};
  const present = (value: unknown) => (configuration === undefined ? null : value !== undefined);
  const callback = (value: unknown) =>
    configuration === undefined ? null : typeof value === 'function';
  return {
    mode: choice(config.mode, ['default', 'ultrafast', 'unknown'], 'unknown'),
    reasoning: choice(
      config.reasoning,
      ['minimal', 'low', 'medium', 'high', 'xhigh', 'unknown'],
      'unknown',
    ),
    research_tools: boolean(config.researchTools),
    browser_switching: boolean(config.browserSwitching),
    dedicated_browser: boolean(config.dedicatedBrowser),
    focus_tab: boolean(config.focusTab),
    allowlist_configured: present(config.allowedDomains),
    denylist_configured: present(config.prohibitedDomains),
    secrets_configured: present(config.sensitiveData),
    custom_tools_configured: present(config.tools),
    before_tool_callback: callback(config.beforeToolCall),
    after_tool_callback: callback(config.afterToolCall),
    validator_callback: callback(config.validateResult),
    redaction_configured: present(config.redact),
    log_format:
      config.log === false
        ? 'disabled'
        : choice(config.log, ['pretty', 'json', 'unknown'], 'unknown'),
    history_restore: present(config.historyFile),
    recording_configured: configuration === undefined ? null : !!config.recording,
    action_highlights: boolean(config.highlightActions),
    search_configured: present(config.webSearch),
    init_scripts_configured: present(config.initScripts),
    browser_ready_callback: callback(config.onBrowserReady),
  };
}

function modelMetadata(options: TelemetryOptions) {
  const model = options.model;
  const pricingKnown = options.pricingKnown === true;
  return {
    model_id: identifier(model?.id),
    model_provider: identifier(model?.provider),
    model_api: identifier(model?.api),
    model_context_window: number(model?.contextWindow),
    model_max_output_tokens: number(model?.maxTokens),
    model_reasoning: typeof model?.reasoning === 'boolean' ? model.reasoning : null,
    model_image_input: Array.isArray(model?.input) ? model.input.includes('image') : null,
    model_metadata_source: choice(
      options.modelMetadataSource,
      ['catalog', 'explicit', 'template', 'discovery', 'unknown'],
      'unknown',
    ),
    pricing_known: pricingKnown,
    pricing_unit: 'usd_per_million_tokens',
    pricing_input: pricingKnown ? number(model?.cost?.input) : null,
    pricing_output: pricingKnown ? number(model?.cost?.output) : null,
    pricing_cache_read: pricingKnown ? number(model?.cost?.cacheRead) : null,
    pricing_cache_write: pricingKnown ? number(model?.cost?.cacheWrite) : null,
  };
}

export function createTelemetry(options: TelemetryOptions = {}) {
  const enabled = telemetryEnabled(options.enabled);
  const sessionId = randomUUID();
  const pending = new Set<Promise<void>>();
  let reservedFinishes = 0;
  const base = {
    schema_version: 1,
    measurement_version: 1,
    distinct_id: sessionId,
    session_id: sessionId,
    $process_person_profile: false,
    $geoip_disable: true,
    os: process.platform,
    architecture: process.arch,
    runtime: process.versions.bun ? 'bun' : 'node',
    runtime_version: process.versions.bun ?? process.versions.node,
    ...docker(),
    engine_version: identifier(options.engineVersion) ?? version(),
    client_version: identifier(options.clientVersion),
    installation_source: choice(
      options.installationSource,
      ['wheel', 'editable', 'git', 'unknown'],
      'unknown',
    ),
    client_language: choice(
      options.clientLanguage,
      ['python', 'javascript', 'unknown'],
      'javascript',
    ),
    entrypoint: choice(options.entrypoint, ['sdk', 'cli', 'adapter', 'unknown'], 'sdk'),
    controller: choice(
      options.controller,
      ['pi', 'openai_toolset', 'anthropic_toolset', 'cli_direct', 'custom'],
      'pi',
    ),
    backend: choice(options.backend, ['pi_runtime', 'browser_harness', 'unknown'], 'pi_runtime'),
    browser_requested: kind(options.browser),
    browser_selection: choice(
      options.browserSelection,
      ['default', 'explicit', 'unknown'],
      'unknown',
    ),
    ...endpoint(options.browser),
    sampling_probability: 1,
    subagent_tracking: 'unsupported',
    ...modelMetadata(options),
  };
  const send = (event: string, properties: object) => {
    if (!enabled || !telemetryEnabled(options.enabled)) return;
    try {
      const request = fetch(host, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: token, event, properties: { ...base, ...properties } }),
        signal: AbortSignal.timeout(1000),
        redirect: 'error',
      }).then(
        async (response) => {
          try {
            await response.body?.cancel();
          } catch {}
        },
        () => {},
      );
      pending.add(request);
      void request.finally(() => pending.delete(request));
    } catch {}
  };
  return {
    sessionId,
    start(operationKind: OperationKind, details: TelemetryStart = {}) {
      const admitted =
        enabled && telemetryEnabled(options.enabled) && pending.size + reservedFinishes + 2 <= 32;
      if (admitted) reservedFinishes++;
      const operationId = id(details.operationId) ?? randomUUID();
      const started = performance.now();
      const counts = Object.fromEntries(counters.map((counter) => [counter, null])) as Record<
        TelemetryCounter,
        number | null
      >;
      const aggregation = choice(details.aggregation, ['direct', 'cumulative_rollup'], 'direct');
      const common = {
        operation_id: operationId,
        operation_kind: choice(
          operationKind,
          ['agent_run', 'browser_session', 'cli_command'],
          'agent_run',
        ),
        parent_operation_id: id(details.parentOperationId),
        child_id: id(details.childId),
        aggregation,
      };
      const run = details.run;
      let effectiveBrowser: BrowserKind = 'unknown';
      let finished = false;
      if (admitted)
        send('bu_operation_started', {
          ...common,
          event_id: randomUUID(),
          configured_features: featureConfiguration(options.configuration),
          max_steps: number(run?.maxSteps),
          timeout_ms: number(run?.timeoutMs),
          max_cost_usd: number(run?.maxCostUsd),
          compaction_enabled: boolean(run?.compaction),
          max_context_chars: number(run?.maxContextChars),
          structured_output: boolean(run?.schema),
          event_callback: boolean(run?.onEvent),
          observer_callback: boolean(run?.observe),
          context_recovery_callback: boolean(run?.onContextRecovery),
        });
      return {
        operationId,
        count(counter: TelemetryCounter, amount = 1) {
          if (
            !finished &&
            counters.includes(counter) &&
            Number.isSafeInteger(amount) &&
            amount >= 0
          )
            counts[counter] = Math.min(Number.MAX_SAFE_INTEGER, (counts[counter] ?? 0) + amount);
        },
        browser(browserKind: BrowserKind) {
          effectiveBrowser = choice(browserKind, browserKinds, 'unknown');
        },
        finish(finish: TelemetryFinish = {}) {
          if (finished) return;
          finished = true;
          if (admitted) reservedFinishes--;
          const result = finish.result;
          const statuses = [
            'completed',
            'max_steps',
            'timeout',
            'cancelled',
            'cost_limit',
            'context_limit',
            'incomplete',
            'error',
            'closed',
          ] as const;
          const status = choice(finish.status ?? result?.status, statuses, 'error');
          if (admitted)
            send('bu_operation_finished', {
              ...common,
              event_id: randomUUID(),
              status,
              operation_duration_ms: Math.max(0, performance.now() - started),
              run_duration_ms: number(result?.durationMs),
              paused_duration_ms: number(finish.pausedDurationMs),
              model_duration_ms_sum: number(finish.modelDurationMs),
              tool_duration_ms_sum: number(finish.toolDurationMs),
              browser_effective: choice(
                finish.effectiveBrowser ?? effectiveBrowser,
                browserKinds,
                'unknown',
              ),
              feature_usage: { ...counts },
              feature_coverage: choice(
                finish.coverage,
                ['complete', 'partial', 'unknown', 'unsupported'],
                'partial',
              ),
              steps: number(result?.steps),
              provider_retries: number(result?.providerRetries),
              compactions: number(result?.compactions),
              compaction_failures: number(result?.context?.compactionFailures),
              compaction_failure_class: result?.context?.lastCompactionFailure
                ? choice(
                    result.context.lastCompactionFailure,
                    ['timeout', 'not_reduced', 'error'],
                    'error',
                  )
                : null,
              context_chars: number(result?.context?.chars),
              context_tokens_estimated: number(result?.context?.tokens),
              finish_repairs: number(result?.finishRepairs),
              usage: usage(result?.usage, options.pricingKnown === true),
              summary_usage: usage(finish.summaryUsage, options.pricingKnown === true),
              usage_completeness: choice(
                finish.usageCompleteness,
                ['complete', 'partial', 'unknown'],
                'unknown',
              ),
              cost_completeness:
                options.pricingKnown === true && number(result?.usage?.cost?.total) !== null
                  ? choice(finish.usageCompleteness, ['complete', 'partial', 'unknown'], 'unknown')
                  : 'unknown',
              usage_scope:
                aggregation === 'direct'
                  ? 'direct_including_summary_and_retries'
                  : 'cumulative_rollup',
              descendant_usage: null,
              error_class: finish.errorClass
                ? choice(finish.errorClass, errorClasses, 'unknown')
                : status === 'error'
                  ? 'unknown'
                  : null,
              error_stage: finish.stage ? choice(finish.stage, stages, 'startup') : null,
              task_verification: 'unknown',
            });
        },
      };
    },
    async flush() {
      if (!pending.size) return;
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([
          Promise.allSettled([...pending]),
          new Promise<void>((resolve) => {
            timer = setTimeout(resolve, 1100);
          }),
        ]);
      } finally {
        clearTimeout(timer);
      }
    },
  };
}

export type Telemetry = ReturnType<typeof createTelemetry>;
export type TelemetryOperation = ReturnType<Telemetry['start']>;
