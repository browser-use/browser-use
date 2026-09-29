import { test, before, after } from 'node:test';
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
import { Browser, BrowserUse } from '../dist/index.js';
import { openBrowser } from '../dist/browser.js';
import { startFixture } from './fixture.mjs';

let fixture;
let chrome;
before(async () => {
  fixture = await startFixture();
  chrome = await openBrowser(
    process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {},
  );
});
after(async () => {
  await chrome?.close();
  await fixture?.close();
});

const call = (name, args) =>
  fauxAssistantMessage(fauxToolCall(name, args), { stopReason: 'toolUse' });

async function pendingSession(responses, config = {}) {
  const faux = fauxProvider({ tokensPerSecond: 1_000_000 });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses(responses);
  const workspace = await mkdtemp(join(tmpdir(), 'bu-pending-test-'));
  const agent = await BrowserUse.create({
    model: `${faux.getModel().provider}/${faux.getModel().id}`,
    models,
    browser: Browser.pending(),
    dedicatedBrowser: true,
    workspace,
    ...config,
  });
  return {
    agent,
    faux,
    close: async () => {
      await agent.close();
      await rm(workspace, { recursive: true, force: true });
    },
  };
}

test('the model starts before the browser exists; the first cell waits for it', async () => {
  let connected = false;
  let modelSawNoBrowser = false;
  let s;
  s = await pendingSession([
    () => {
      modelSawNoBrowser = !connected;
      // Attach only once the model is already running, as a host provisioning in parallel would.
      setTimeout(() => {
        connected = true;
        s.agent.connectBrowser(chrome.endpoint);
      }, 200);
      return call('javascript', {
        code: `await page.goto(${JSON.stringify(fixture.url)}); console.log(await page.evaluate(() => document.title))`,
      });
    },
    (context) => {
      const result = context.messages.findLast((m) => m.role === 'toolResult');
      assert.equal(result.isError, false);
      return call('finish', { result: result.content[0].text.trim() });
    },
  ]);
  try {
    const result = await s.agent.run('Read the title.');
    assert.equal(result.status, 'completed');
    assert.equal(result.output, 'Orbital Supply — test fixture');
    assert.ok(modelSawNoBrowser);
  } finally {
    await s.close();
  }
});

test('a cell fails cleanly when no browser arrives within its deadline', async () => {
  const s = await pendingSession(
    [
      call('javascript', { code: 'console.log(1)' }),
      (context) => {
        const result = context.messages.findLast((m) => m.role === 'toolResult');
        assert.equal(result.isError, true);
        assert.match(result.content[0].text, /No browser was connected within 300 ms/);
        return call('finish', { result: 'gave up' });
      },
    ],
    { cellTimeoutMs: 300 },
  );
  try {
    const result = await s.agent.run('Try.');
    assert.equal(result.status, 'completed');
  } finally {
    await s.close();
  }
});

test('connectBrowser needs a pending session, a valid endpoint, and runs once', async () => {
  const s = await pendingSession([]);
  try {
    assert.throws(() => s.agent.connectBrowser('file:///tmp/x'), /HTTP\(S\) or WebSocket/);
    s.agent.connectBrowser(chrome.endpoint);
    assert.throws(() => s.agent.connectBrowser(chrome.endpoint), /already has a browser/);
  } finally {
    await s.close();
  }
  const faux = fauxProvider({ tokensPerSecond: 1_000_000 });
  const models = createModels();
  models.setProvider(faux.provider);
  const workspace = await mkdtemp(join(tmpdir(), 'bu-pending-test-'));
  const direct = await BrowserUse.create({
    model: `${faux.getModel().provider}/${faux.getModel().id}`,
    models,
    browser: { cdpUrl: chrome.endpoint },
    workspace,
  });
  try {
    assert.throws(() => direct.connectBrowser(chrome.endpoint), /Browser\.pending\(\)/);
  } finally {
    await direct.close();
    await rm(workspace, { recursive: true, force: true });
  }
});
