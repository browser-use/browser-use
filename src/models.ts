import {
  createProvider,
  createAssistantMessageEventStream,
  envApiKeyAuth,
  type Api,
  type AssistantMessage,
  type CreateModelsOptions,
  type Model,
  type Models,
} from '@earendil-works/pi-ai';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';
import { builtinModels as piModels } from '@earendil-works/pi-ai/providers/all';
import type { StreamFn, ThinkingLevel } from '@earendil-works/pi-agent-core';
import type { ModelInfo, ServiceTier } from './types.js';

export const DEFAULT_MODEL = 'bu-auto';
const gatewayAliases = new Set([
  DEFAULT_MODEL,
  'bu-fast',
  'bu-ultrafast',
  'bu-smart',
  'bu-fast-v1',
  'bu-ultrafast-v1',
  'bu-smart-v1',
  'bu-recommended',
  'bu-balanced',
]);

export function isGatewayAlias(name: string | undefined): boolean {
  return (
    typeof name === 'string' &&
    (gatewayAliases.has(name.replace(/^browser-use\//, '')) ||
      /^bu-(fast|ultrafast|smart)-v[1-9][0-9]*$/.test(name.replace(/^browser-use\//, '')))
  );
}

export function gatewayErrorMessage(message: string): string {
  return message === 'Provider is not configured: browser-use'
    ? 'Set BROWSER_USE_API_KEY. Create an API key at https://cloud.browser-use.com/settings?tab=api-keys&new=1.'
    : message;
}

export function builtinModels(options?: CreateModelsOptions) {
  const models = piModels(options);
  const auth = envApiKeyAuth('Browser Use API key', ['BROWSER_USE_API_KEY']);
  models.setProvider(
    createProvider({
      id: 'browser-use',
      name: 'Browser Use',
      baseUrl: 'https://api.browser-use.com/api/llm/v1',
      auth: {
        apiKey: {
          ...auth,
          resolve: async (options) => {
            const result = await auth.resolve(options);
            if (!result) return undefined;
            return {
              ...result,
              auth: {
                ...result.auth,
                headers: { ...result.auth.headers, 'x-browser-use-client': 'pi' },
              },
            };
          },
        },
      },
      models: [...gatewayAliases].map((id): Model<'openai-completions'> => ({
        provider: 'browser-use',
        id,
        name: id,
        api: 'openai-completions',
        baseUrl: 'https://api.browser-use.com/api/llm/v1',
        reasoning: true,
        input: ['text', 'image'],
        contextWindow: 250000,
        maxTokens: 32000,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        thinkingLevelMap: {
          off: 'none',
          minimal: 'minimal',
          low: 'low',
          medium: 'medium',
          high: 'high',
          xhigh: 'xhigh',
          max: 'max',
        },
        compat: { supportsStore: false, supportsStrictMode: true },
      })),
      api: openAICompletionsApi(),
    }),
  );
  return models;
}

export interface ModelOptions {
  model?: string;
  models?: Models;
  modelInfo?: ModelInfo;
}

export function rejectBu2(name: string | undefined) {
  if (typeof name === 'string' && /(?:^|\/)bu[-_.]?2(?:$|[-_.])/i.test(name))
    throw new Error('BU2 does not support Pi. Use bu-auto or install browser-use<1.');
}

function splitModel(name: string | undefined): [string, string] {
  rejectBu2(name);
  if (isGatewayAlias(name)) return ['browser-use', name!.replace(/^browser-use\//, '')];
  const separator = typeof name === 'string' ? name.indexOf('/') : -1;
  if (typeof name !== 'string' || separator < 1 || separator === name.length - 1)
    throw new Error('model must be provider/model.');
  return [name.slice(0, separator), name.slice(separator + 1)];
}

function validateInfo(info: ModelInfo) {
  if (typeof info !== 'object' || info === null || Array.isArray(info))
    throw new Error('modelInfo must be an object.');
  for (const key of ['api', 'baseUrl'] as const)
    if (info[key] !== undefined && (typeof info[key] !== 'string' || !info[key].trim()))
      throw new Error(`modelInfo.${key} must be a non-empty string.`);
  for (const key of ['vision', 'reasoning'] as const)
    if (info[key] !== undefined && typeof info[key] !== 'boolean')
      throw new Error(`modelInfo.${key} must be boolean.`);
  for (const key of ['contextWindow', 'maxTokens'] as const)
    if (info[key] !== undefined && (!Number.isSafeInteger(info[key]) || info[key] <= 0))
      throw new Error(`modelInfo.${key} must be a positive integer.`);
  for (const key of ['compat', 'thinkingLevelMap'] as const)
    if (
      info[key] !== undefined &&
      (typeof info[key] !== 'object' || info[key] === null || Array.isArray(info[key]))
    )
      throw new Error(`modelInfo.${key} must be an object.`);
  if (
    info.thinkingLevelMap &&
    Object.values(info.thinkingLevelMap).some(
      (value) => value !== null && typeof value !== 'string',
    )
  )
    throw new Error('modelInfo.thinkingLevelMap values must be strings or null.');
  if (info.cost !== undefined) {
    const rates = info.cost as Model<Api>['cost'];
    if (typeof rates !== 'object' || rates === null || Array.isArray(rates))
      throw new Error('modelInfo.cost must contain non-negative rates.');
    const validRates = (value: Model<Api>['cost']) =>
      ['input', 'output', 'cacheRead', 'cacheWrite'].every((key) => {
        const rate = value[key as keyof typeof value];
        return typeof rate === 'number' && Number.isFinite(rate) && rate >= 0;
      });
    if (
      !validRates(rates) ||
      (rates.tiers !== undefined &&
        (!Array.isArray(rates.tiers) ||
          rates.tiers.some(
            (tier) =>
              typeof tier !== 'object' ||
              tier === null ||
              !validRates(tier) ||
              !Number.isSafeInteger(tier.inputTokensAbove) ||
              tier.inputTokensAbove < 0,
          )))
    )
      throw new Error('modelInfo.cost must contain non-negative rates and valid pricing tiers.');
  }
}

export function resolveModel(options: ModelOptions): { model: Model<Api>; priceKnown: boolean } {
  const [provider, id] = splitModel(options.model);
  const models = options.models ?? builtinModels();
  const owner = models.getProvider(provider);
  if (!owner)
    throw new Error(
      `Unknown provider ${provider}. Supply a Pi models collection with this provider registered.`,
    );
  const info = options.modelInfo ?? {};
  validateInfo(info);
  const known =
    models.getModel(provider, id) ??
    (provider === 'browser-use' && isGatewayAlias(id)
      ? { ...models.getModel(provider, DEFAULT_MODEL)!, id, name: id }
      : undefined);
  const template = info.template ? models.getModel(...splitModel(info.template)) : undefined;
  if (info.template !== undefined && !template)
    throw new Error(`Unknown modelInfo.template ${info.template}.`);
  const providerModels = models.getModels(provider);
  const transport =
    known ??
    template ??
    providerModels.find((candidate) => candidate.api === (info.api ?? 'openai-completions')) ??
    providerModels[0];
  const api = info.api ?? transport?.api;
  const baseUrl = info.baseUrl ?? transport?.baseUrl ?? owner.baseUrl;
  if (!api || !baseUrl)
    throw new Error(
      `Provider ${provider} needs modelInfo.api and modelInfo.baseUrl for unknown models.`,
    );
  const model: Model<Api> = known
    ? { ...known }
    : {
        id,
        name: id,
        provider,
        api,
        baseUrl,
        reasoning: false,
        input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 32768,
        maxTokens: 8192,
      };
  model.api = api;
  model.baseUrl = baseUrl;
  if (info.vision !== undefined) model.input = info.vision ? ['text', 'image'] : ['text'];
  if (info.reasoning !== undefined) model.reasoning = info.reasoning;
  if (info.contextWindow !== undefined) model.contextWindow = info.contextWindow;
  if (info.maxTokens !== undefined) model.maxTokens = info.maxTokens;
  if (info.cost !== undefined) model.cost = info.cost;
  if (info.compat !== undefined) model.compat = { ...model.compat, ...info.compat };
  if (info.thinkingLevelMap !== undefined) model.thinkingLevelMap = info.thinkingLevelMap;
  return { model, priceKnown: (!!known && provider !== 'browser-use') || info.cost !== undefined };
}

export interface GatewayModel {
  model: Model<Api>;
  reasoning: ThinkingLevel;
  serviceTier: ServiceTier;
  minimumCost: number;
  apiKey: string;
}

export async function resolveGatewayModel(
  model: Model<Api>,
  models: Models,
  options: { apiKey?: string; serviceTier?: ServiceTier; reasoning?: ThinkingLevel },
): Promise<GatewayModel> {
  const auth = await models.getAuth(model, options.apiKey ? { apiKey: options.apiKey } : {});
  const key = options.apiKey ?? auth?.auth.apiKey;
  if (!key) throw new Error(gatewayErrorMessage('Provider is not configured: browser-use'));
  const url = new URL(model.baseUrl.replace(/\/$/, '') + '/models');
  if (
    url.protocol !== 'https:' &&
    !(url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))
  )
    throw new Error('Browser Use model catalogs require HTTPS or a loopback test server.');
  let data: unknown;
  try {
    const response = await fetch(url, {
      headers: { Authorization: 'Bearer ' + key, 'x-browser-use-client': 'pi' },
      signal: AbortSignal.timeout(10000),
      redirect: 'error',
    });
    if (!response.ok) throw new Error('status:' + response.status);
    const reader = response.body?.getReader();
    if (!reader) throw new Error('empty');
    let bytes = 0;
    const chunks: Uint8Array[] = [];
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        bytes += chunk.value.byteLength;
        if (bytes > 1_048_576) throw new Error('oversized');
        chunks.push(chunk.value);
      }
    } finally {
      await reader.cancel();
    }
    data = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch (error) {
    const status =
      error instanceof Error && /^status:\d+$/.test(error.message)
        ? ' (HTTP ' + error.message.slice(7) + ')'
        : '';
    throw new Error(
      'Browser Use model catalog is unavailable' +
        status +
        '. Check your API key and gateway endpoint.',
    );
  }
  const entries = (data as { data?: unknown })?.data;
  const name = ['bu-recommended', 'bu-balanced'].includes(model.id) ? 'bu-fast-v1' : model.id;
  const entry = Array.isArray(entries) ? entries.find((value) => value?.id === name) : undefined;
  if (!entry)
    throw new Error(
      'Browser Use model ' + name + ' is unavailable. Use bu-auto or a published revision.',
    );
  if (/^bu-(fast|ultrafast|smart)-v[1-9][0-9]*$/.test(name) && entry.resolved_model !== name)
    throw new Error('Browser Use returned a different revision for pinned model ' + name + '.');
  const tier = options.serviceTier ?? entry.default_service_tier;
  const reasoning =
    options.reasoning ??
    (['bu-recommended', 'bu-balanced'].includes(model.id) ? 'high' : entry.default_reasoning);
  if (!Array.isArray(entry.service_tiers) || !entry.service_tiers.includes(tier))
    throw new Error('Service tier ' + tier + ' is unavailable for ' + name + '.');
  const price = entry.pricing?.[tier];
  const rateKeys = [
    'input',
    'output',
    'cache_read',
    'cache_write',
    'min_request_usd',
    'long_context_input_multiplier',
    'long_context_output_multiplier',
  ] as const;
  if (
    !/^bu-(fast|ultrafast|smart)-v[1-9][0-9]*$/.test(entry.resolved_model) ||
    !['default', 'priority', 'ultrafast'].includes(tier) ||
    !['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'].includes(reasoning) ||
    !Number.isSafeInteger(entry.context_window) ||
    entry.context_window < 1024 ||
    !Number.isSafeInteger(entry.max_output_tokens) ||
    entry.max_output_tokens < 1 ||
    entry.max_output_tokens > entry.context_window ||
    !price ||
    !Number.isSafeInteger(price.long_context_threshold_tokens) ||
    price.long_context_threshold_tokens < 1 ||
    price.long_context_input_multiplier < 1 ||
    price.long_context_output_multiplier < 1 ||
    rateKeys.some(
      (key) => typeof price[key] !== 'number' || !Number.isFinite(price[key]) || price[key] < 0,
    )
  )
    throw new Error('Browser Use returned invalid model metadata.');
  return {
    model: {
      ...model,
      id: entry.resolved_model,
      name: entry.resolved_model,
      contextWindow: entry.context_window,
      maxTokens: entry.max_output_tokens,
      cost: {
        input: price.input,
        output: price.output,
        cacheRead: price.cache_read,
        cacheWrite: price.cache_write,
        tiers: [
          {
            inputTokensAbove: price.long_context_threshold_tokens,
            input: price.input * price.long_context_input_multiplier,
            output: price.output * price.long_context_output_multiplier,
            cacheRead: price.cache_read * price.long_context_input_multiplier,
            cacheWrite: price.cache_write * price.long_context_input_multiplier,
          },
        ],
      },
    },
    reasoning,
    serviceTier: tier,
    minimumCost: price.min_request_usd,
    apiKey: key,
  };
}

export function configuredStream(
  source: StreamFn,
  options: { apiKey?: string; serviceTier?: ServiceTier; minimumCost?: number },
): StreamFn {
  return (model, context, settings) => {
    const stream = createAssistantMessageEventStream();
    void (async () => {
      try {
        const input = await source(model, context, {
          ...settings,
          ...(options.apiKey ? { apiKey: options.apiKey } : {}),
          ...(options.serviceTier
            ? {
                samplingParams: { ...settings?.samplingParams, service_tier: options.serviceTier },
              }
            : {}),
        });
        for await (const event of input) {
          if (event.type === 'done' && options.minimumCost) {
            const cost = event.message.usage.cost;
            if (cost.total < options.minimumCost) {
              cost.input += options.minimumCost - cost.total;
              cost.total = options.minimumCost;
            }
          }
          stream.push(event);
        }
        stream.end(await input.result());
      } catch (error) {
        const message: AssistantMessage = {
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
          timestamp: Date.now(),
          stopReason: 'error',
          errorMessage: gatewayErrorMessage(error instanceof Error ? error.message : String(error)),
        };
        stream.push({ type: 'error', reason: 'error', error: message });
        stream.end(message);
      }
    })();
    return stream;
  };
}
