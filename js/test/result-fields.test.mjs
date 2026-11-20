import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { BrowserUse } from '../dist/index.js';

const call = (name, args) =>
  fauxAssistantMessage(fauxToolCall(name, args), { stopReason: 'toolUse' });

test('result maps to Python AgentHistoryList: success, downloads of this run, top-level costUsd', async (t) => {
  const workspace = await mkdtemp(join(tmpdir(), 'bu-result-'));
  t.after(() => rm(workspace, { recursive: true, force: true }));
  await mkdir(join(workspace, 'downloads'));
  await writeFile(join(workspace, 'downloads', 'old.pdf'), 'from an earlier run');
  const faux = fauxProvider({
    tokensPerSecond: 1e6,
    models: [{ id: 'result-test', input: ['text'] }],
  });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses([
    // A file the browser saved during this run, and one still downloading.
    call('javascript', {
      code: "const fs = require('fs'); fs.writeFileSync('downloads/report.csv', 'a,b'); fs.writeFileSync('downloads/big.zip.crdownload', '')",
    }),
    call('finish', { result: 'saved', success: true }),
  ]);
  const agent = await BrowserUse.create({
    model: `${faux.getModel().provider}/${faux.getModel().id}`,
    models,
    browser: { cdpUrl: 'http://127.0.0.1:9' },
    workspace,
    judge: false,
    telemetry: false,
  });
  try {
    const result = await agent.run('Download the report.');
    assert.equal(result.status, 'completed', result.error);
    assert.equal(result.success, true);
    assert.deepEqual(result.downloads, [join(workspace, 'downloads', 'report.csv')]);
    assert.equal(typeof result.costUsd, 'number');
    assert.equal(result.costUsd, result.usage.cost.total);
  } finally {
    await agent.close();
  }
});
