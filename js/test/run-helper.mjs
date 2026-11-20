// Shared harness for runAgent tests with a scripted faux model: no browser, no network.
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { Type } from 'typebox';
import { runAgent } from '../dist/agent.js';

export const call = (name, args) =>
  fauxAssistantMessage(fauxToolCall(name, args), { stopReason: 'toolUse' });
export const text = (value) => fauxAssistantMessage(value);

/** Runs a task against scripted responses. Returns the result, every request context and the workspace. */
export async function scripted(
  responses,
  { schema = Type.String(), options = {}, config = {}, runtime = {}, setup } = {},
) {
  const workspace = await mkdtemp(join(tmpdir(), 'bu-parity-'));
  try {
    await setup?.(workspace);
    const faux = fauxProvider({ tokensPerSecond: 1e6 });
    const models = createModels();
    models.setProvider(faux.provider);
    faux.setResponses(responses);
    const requests = [];
    const settings = [];
    const streamFn =
      config.streamFn ??
      ((model, context, options) => {
        requests.push(structuredClone(context));
        settings.push(options);
        return models.streamSimple(model, context, options);
      });
    const result = await runAgent(
      {
        beginRun() {},
        async execute() {
          return { text: 'ok', images: [] };
        },
        async readResult(expression) {
          return JSON.parse(expression);
        },
        ...runtime,
      },
      { ...faux.getModel(), contextWindow: 250000 },
      { ...config, streamFn },
      workspace,
      'task',
      schema,
      { maxSteps: 10, ...options },
    );
    return { result, requests, settings, workspace };
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
}
