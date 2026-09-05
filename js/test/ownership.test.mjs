import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BrowserUse, CDP, Page } from '../dist/index.js';
import { openBrowser } from '../dist/browser.js';

test('external tabs/cookies survive normal cleanup and timeout; SDK tabs are removed', async () => {
  const external = await openBrowser();
  const workspace = await mkdtemp(join(tmpdir(), 'bu-external-artifacts-'));
  const cdp = await CDP.connect(external.endpoint);
  try {
    const existing = await Page.attach(
      cdp,
      (await cdp.send('Target.getTargets')).targetInfos.find((t) => t.type === 'page').targetId,
    );
    await existing.goto('data:text/html,<h1>Caller-owned tab</h1>');
    await cdp.send('Storage.setCookies', {
      cookies: [{ name: 'session', value: 'fixture-only', domain: 'example.com', path: '/' }],
    });
    for (const crash of [false, true]) {
      const agent = await BrowserUse.create({
        model: 'openai/gpt-5.4',
        browser: { cdpUrl: external.endpoint },
        workspace,
      });
      try {
        assert.match(
          (await agent.execute("await browser.send('Storage.getCookies')")).text,
          /fixture-only/,
        );
        await agent.execute("await tabs.open('data:text/html,owned-secondary')");
        assert.equal(
          (await cdp.send('Target.getTargets')).targetInfos.filter((t) => t.type === 'page').length,
          3,
        );
        if (crash)
          await assert.rejects(agent.execute('while(true){}', { timeoutMs: 50 }), /exceeded/);
      } finally {
        await agent.close();
      }
      assert.equal(
        (await cdp.send('Target.getTargets')).targetInfos.filter((t) => t.type === 'page').length,
        1,
      );
      assert.equal(await existing.text({ css: 'h1' }), 'Caller-owned tab');
      assert.equal((await cdp.send('Storage.getCookies')).cookies[0].value, 'fixture-only');
    }
  } finally {
    cdp.close();
    await external.close();
    await rm(workspace, { recursive: true, force: true });
  }
});

test('provider environment and host preload flags are not inherited; dynamic imports work', async () => {
  process.env.BU_TEST_FAKE_SECRET = 'test-only-not-a-credential';
  const agent = await BrowserUse.create({ model: 'openai/gpt-5.4' });
  try {
    assert.equal((await agent.execute('process.env.BU_TEST_FAKE_SECRET')).text, '(no output)');
    assert.equal(
      (await agent.execute("typeof (await import('node:fs/promises')).readFile")).text,
      "'function'",
    );
  } finally {
    delete process.env.BU_TEST_FAKE_SECRET;
    await agent.close();
    await rm(agent.workspace, { recursive: true, force: true });
  }
});
