import {
  createProvider,
  envApiKeyAuth,
  type Api,
  type CreateModelsOptions,
  type Model,
  type Models,
} from '@earendil-works/pi-ai';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';
import { builtinModels as piModels } from '@earendil-works/pi-ai/providers/all';
import type { ModelInfo } from './types.js';

export const DEFAULT_MODEL = 'bu-recommended';
const gatewayAliases = new Set([DEFAULT_MODEL, 'bu-balanced', 'bu-smart']);

export function isGatewayAlias(name: string | undefined): boolean {
  return typeof name === 'string' && gatewayAliases.has(name.replace(/^browser-use\//, ''));
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
          minimal: null,
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
    throw new Error('BU2 does not support Pi. Use bu-recommended or install browser-use<1.');
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
  const known = models.getModel(provider, id);
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
