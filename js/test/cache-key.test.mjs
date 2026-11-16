import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { BrowserUse } from '../dist/index.js';

// Python 1.0.5 sends no prompt_cache_key. With the run id as one (a4e738d), 123 of 199 BU Bench runs had one full
// cache miss mid-run and then alternated between the old and the new cache; 0 of 197 runs before it.
test('BrowserUse.run sends no provider session, so OpenAI gets no prompt_cache_key or session headers', async () => {
  const workspace = await mkdtemp(join(tmpdir(), 'bu-cache-key-'));
  const faux = fauxProvider({ tokensPerSecond: 1e6 });
  const models = createModels();
  models.setProvider(faux.provider);
  const finish = (result) =>
    fauxAssistantMessage(fauxToolCall('finish', { result }), { stopReason: 'toolUse' });
  faux.setResponses([finish('one'), finish('two')]);
  const sessions = [];
  const agent = await BrowserUse.create({
    judge: false,
    model: `${faux.getModel().provider}/${faux.getModel().id}`,
    models,
    workspace,
    streamFn: (model, context, options) => {
      sessions.push(options?.sessionId);
      return models.streamSimple(model, context, options);
    },
  });
  try {
    assert.equal((await agent.run('first')).status, 'completed');
    assert.equal((await agent.run('second')).status, 'completed');
    assert.deepEqual(sessions, [undefined, undefined]);
  } finally {
    await agent.close();
    await rm(workspace, { recursive: true, force: true });
  }
});
