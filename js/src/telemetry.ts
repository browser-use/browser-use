import { randomUUID } from 'node:crypto';
import type { BrowserOptions } from './browser.js';
import type { RunResult } from './types.js';

// Public, write-only PostHog project token. EU ingestion; no SDK or persistent identifier.
const token = 'phc_tcNY9BmpauyrDHDVhrhkFCaQEpH3vMnx3TDUZ49TWCek';
const processId = randomUUID();
export function telemetry(enabled: boolean | undefined, browser: BrowserOptions | undefined) {
  const disabled =
    enabled === false ||
    process.env.DO_NOT_TRACK === '1' ||
    ['false', '0'].includes(process.env.ANONYMIZED_TELEMETRY?.toLowerCase() ?? '') ||
    !!process.env.NODE_TEST_CONTEXT;
  const kind =
    browser?.kind ?? (browser && 'cdpUrl' in browser && browser.cdpUrl ? 'cdp' : 'chromium');
  return (result: RunResult<unknown>): void => {
    if (disabled) return;
    // Explicit allowlist. Never spread config/results: they contain tasks, paths and credentials.
    const properties = {
      distinct_id: processId,
      $process_person_profile: false,
      $geoip_disable: true,
      $ip: null,
      sdk_version: '0.1.0',
      os: process.platform,
      node_major: process.versions.node.split('.')[0],
      browser: kind,
      status: result.status,
      steps: result.steps,
      duration_ms: result.durationMs,
      input_tokens: result.usage.input,
      output_tokens: result.usage.output,
      estimated_cost_usd: result.usage.cost.total,
    };
    // Bounded and best-effort. Telemetry cannot change the run result or trigger retries.
    void fetch('https://eu.i.posthog.com/i/v0/e/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: token, event: 'bu_pi_run', properties }),
      signal: AbortSignal.timeout(1000),
      redirect: 'error',
    }).catch(() => {});
  };
}
