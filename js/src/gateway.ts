import type { StreamFn } from '@earendil-works/pi-agent-core';
import { createAssistantMessageEventStream, type Api, type Model } from '@earendil-works/pi-ai';

/** Python browser_use/llm: the Browser Use gateway, OpenAI Responses, one Browser Use API key for model and browser. */
export const GATEWAY_URL = 'https://api.browser-use.com/api/v4/llm/v1';
export const GATEWAY_PROVIDER = 'browser-use';
/** Python 1.0.6 DEFAULT_MODEL: BU 4.0 (also bu-4.0-mini, bu-4.0-pro). bu-fast: gpt-6-luna, medium; bu-ultrafast: low. */
export const DEFAULT_MODEL = `${GATEWAY_PROVIDER}/bu-4.0`;
const BILLING_URL = 'https://cloud.browser-use.com/settings?tab=billing';
const PREFLIGHT_TIMEOUT_MS = 15_000;
/** Python GATEWAY_UPSTREAM: other bu-* models get the gpt-6-luna request profile. */
const UPSTREAM: Record<string, string> = {
  'bu-smart': 'gpt-6.1-sol',
  'bu-smart-v1': 'gpt-6.1-sol',
};
/** Python service.py: bu-fast and bu-ultrafast are evaluated in ultrafast mode (Google Flights 0/3 default vs 3/3). */
export const ULTRAFAST_ALIASES = new Set(['bu-fast', 'bu-ultrafast']);

/** 'bu-fast' alone means the gateway; 'openai/x' and the rest keep their provider. */
export function gatewayModelName(model: string | undefined) {
  if (model === undefined) return DEFAULT_MODEL;
  return /^bu-[^/]+$/.test(model) ? `${GATEWAY_PROVIDER}/${model}` : model;
}

/**
 * A gateway model in pi-ai's shape: the upstream OpenAI model's request features under the gateway's rules (store false,
 * no hosted or added tools). Rates are zero: cost is only what the gateway charged (charge_usd), never a retail estimate.
 */
export function gatewayModel(id: string, upstream?: Model<Api>): Model<'openai-responses'> {
  const base = upstream as Model<'openai-responses'> | undefined;
  return {
    id,
    name: id,
    api: 'openai-responses',
    provider: GATEWAY_PROVIDER,
    baseUrl: GATEWAY_URL,
    reasoning: true,
    input: ['text', 'image'],
    contextWindow: base?.contextWindow ?? 272_000,
    maxTokens: base?.maxTokens ?? 128_000,
    ...(base?.thinkingLevelMap ? { thinkingLevelMap: base.thinkingLevelMap } : {}),
    compat: { ...base?.compat, supportsAdditionalTools: false, supportsToolSearch: false },
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  } as Model<'openai-responses'>;
}
export const upstreamOf = (id: string) =>
  UPSTREAM[id] ?? (id.startsWith('bu-') ? 'gpt-6-luna' : id);

/** Python ChatBrowserUse._explain: one actionable line for a gateway HTTP error; the gateway's own message wins. */
export function explainGatewayError(
  model: string,
  status: number | undefined,
  code?: string,
  message?: string,
): string | undefined {
  if (status === 400 && (code === 'invalid_model' || code === 'model_not_on_gateway'))
    return `${model} is not on the Browser Use gateway (400): ${message || 'use bu-4.0, bu-4.0-mini or bu-4.0-pro.'}`;
  if (status === 401) return 'Browser Use API key rejected (401): check BROWSER_USE_API_KEY.';
  if (status === 402)
    return `Out of Browser Use credits (402): add credits at ${BILLING_URL} and run again`;
  if (status === 403)
    return message
      ? `${model} is not available for this key (403): ${message}`
      : `${model} is not available for this account (403). Use your own model meanwhile, e.g. model: 'openai/gpt-6-luna'.`;
  if (status === 404)
    return `The Browser Use gateway is not deployed at ${GATEWAY_URL} (404). Use your own model meanwhile, e.g. model: 'openai/gpt-6-luna'.`;
  return undefined;
}

/**
 * Python ChatBrowserUse.preflight: GET {baseUrl}/models (free). A gateway that is not there, a rejected key or a model
 * the gateway does not list fails here, before a browser is created and billed. Returns the error line, or undefined.
 */
export async function gatewayPreflight(
  model: string,
  apiKey: string,
  baseUrl = GATEWAY_URL,
): Promise<string | undefined> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/+$/, '')}/models`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: AbortSignal.timeout(PREFLIGHT_TIMEOUT_MS),
      redirect: 'error',
    });
  } catch (error) {
    return `The Browser Use gateway at ${baseUrl} is not reachable: ${error instanceof Error ? error.message : String(error)}`;
  }
  const body = (await response.json().catch(() => ({}))) as {
    data?: { id?: unknown }[];
    error?: { code?: string; message?: string };
  };
  if (!response.ok) {
    const error = body?.error && typeof body.error === 'object' ? body.error : {};
    return (
      explainGatewayError(model, response.status, error.code, error.message) ??
      `The Browser Use gateway at ${baseUrl} answered HTTP ${response.status}: ${String(error.message ?? response.statusText).slice(0, 300)}`
    );
  }
  const listed = new Set(
    (Array.isArray(body?.data) ? body.data : []).map((entry) => entry?.id).filter(Boolean),
  );
  if (!listed.size || listed.has(model)) return undefined;
  return `${model} is not on the Browser Use gateway. Listed: ${[...listed].map(String).sort().join(', ')}.`;
}

/** USD the gateway charged for one response: browser_use.charge_usd, a decimal string (Python gateway_charge). */
export function chargeUsd(response: unknown): number | undefined {
  const charge = (response as { browser_use?: { charge_usd?: unknown } } | undefined)?.browser_use
    ?.charge_usd;
  const value = typeof charge === 'string' || typeof charge === 'number' ? Number(charge) : NaN;
  return Number.isFinite(value) && value >= 0 ? value : undefined;
}

/** Reads the charge out of the Responses event stream as it passes to the client, unchanged. */
function chargeReader(body: ReadableStream<Uint8Array>, onCharge: (usd: number) => void) {
  const decoder = new TextDecoder();
  let pending = '';
  const scan = (line: string) => {
    if (!line.startsWith('data:') || !line.includes('browser_use')) return;
    try {
      const event = JSON.parse(line.slice(5)) as { type?: string; response?: unknown };
      if (event.type === 'response.completed' || event.type === 'response.incomplete') {
        const usd = chargeUsd(event.response);
        if (usd !== undefined) onCharge(usd);
      }
    } catch {}
  };
  return body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        pending += decoder.decode(chunk, { stream: true });
        const lines = pending.split('\n');
        pending = lines.pop() ?? '';
        for (const line of lines) scan(line.trim());
        controller.enqueue(chunk);
      },
      flush() {
        scan(pending.trim());
      },
    }),
  );
}

/**
 * Gateway requests: the Browser Use key, no reasoning effort for a bu-* alias unless the caller set one (the alias
 * carries its own: bu-4.0 high, bu-fast medium, bu-ultrafast low, bu-smart high) with encrypted reasoning kept across stateless
 * turns, and each response's cost set to the gateway's charge_usd. Other providers pass through unchanged.
 */
export function gatewayStream(
  streamFn: StreamFn,
  apiKey: string,
  options: { aliasEffort: boolean },
): StreamFn {
  return (model, context, settings) => {
    if (model.provider !== GATEWAY_PROVIDER) return streamFn(model, context, settings);
    let charged: number | undefined;
    const base = settings?.fetch ?? globalThis.fetch;
    const output = createAssistantMessageEventStream();
    void (async () => {
      try {
        const source = await streamFn(model, context, {
          ...settings,
          apiKey,
          fetch: async (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
            const response = await base(input, init);
            if (!response.ok || !response.body) return response;
            return new Response(
              chargeReader(response.body, (usd) => (charged = usd)),
              response,
            );
          },
          onPayload: async (params, payloadModel) => {
            let next = ((await settings?.onPayload?.(params, payloadModel)) ?? params) as Record<
              string,
              unknown
            >;
            if (
              options.aliasEffort &&
              model.id.startsWith('bu-') &&
              !(settings as { keepEffort?: boolean } | undefined)?.keepEffort
            ) {
              // Drop only the effort: Python keeps openai_reasoning_summary 'auto', so reasoning summaries still come back.
              const { reasoning, ...rest } = next;
              const summary = (reasoning as { summary?: unknown } | undefined)?.summary ?? 'auto';
              next = { ...rest, reasoning: { summary }, include: ['reasoning.encrypted_content'] };
            }
            return next;
          },
        });
        for await (const event of source) {
          if (event.type === 'done' && charged !== undefined) {
            const cost = event.message.usage.cost;
            Object.assign(cost, {
              input: 0,
              output: 0,
              cacheRead: 0,
              cacheWrite: 0,
              total: charged,
            });
          }
          output.push(event);
          if (event.type === 'done' || event.type === 'error') break;
        }
      } catch (error) {
        output.push({
          type: 'error',
          reason: 'error',
          error: {
            role: 'assistant',
            content: [],
            api: model.api,
            provider: model.provider,
            model: model.id,
            usage: {
              input: 0,
              output: 0,
              cacheRead: 0,
              cacheWrite: 0,
              totalTokens: 0,
              cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
            },
            stopReason: 'error',
            errorMessage: error instanceof Error ? error.message : String(error),
            timestamp: Date.now(),
          },
        });
      }
      output.end();
    })();
    return output;
  };
}
