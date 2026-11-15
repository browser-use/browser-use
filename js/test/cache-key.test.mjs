import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Type } from 'typebox';
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { runAgent } from '../dist/agent.js';
import { RunControl } from '../dist/control.js';

test('every model request of a run carries the run id as its provider session (prompt_cache_key)', async () => {
  const workspace = await mkdtemp(join(tmpdir(), 'bu-cache-key-'));
  try {
    const faux = fauxProvider({ tokensPerSecond: 1e6 });
    const models = createModels();
    models.setProvider(faux.provider);
    faux.setResponses([
      fauxAssistantMessage(fauxToolCall('javascript', { code: '1' }), { stopReason: 'toolUse' }),
      fauxAssistantMessage(fauxToolCall('finish', { result: 'ok' }), { stopReason: 'toolUse' }),
    ]);
    const sessions = [];
    const result = await runAgent(
      { beginRun() {}, execute: async () => ({ text: 'ok', images: [] }) },
      { ...faux.getModel(), contextWindow: 250000 },
      {
        streamFn: (model, context, options) => {
          sessions.push(options.sessionId);
          return models.streamSimple(model, context, options);
        },
      },
      workspace,
      'task',
      Type.String(),
      {},
      { messages: [], control: new RunControl(() => {}), save() {}, runId: 'run-123' },
    );
    assert.equal(result.status, 'completed');
    assert.deepEqual(sessions, ['run-123', 'run-123']);
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
});
