import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { openBrowser } from '../dist/browser.js';
import { CDP, Page } from '../dist/index.js';

test('a timed-out synchronous page evaluation stops in Chrome without replaying or undoing prior effects', async () => {
  const chrome = await openBrowser();
  const cdp = await CDP.connect(chrome.endpoint, 200);
  try {
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const page = await Page.attach(cdp, targetId);
    await page.evaluate(() => {
      window.effects = { before: 0, after: 0 };
    });
    await assert.rejects(
      page.evaluate(() => {
        window.effects.before++;
        const until = Date.now() + 1200;
        while (Date.now() < until) {
          /* finite CPU-bound fixture */
        }
        window.effects.after++;
      }),
      /exceeded|terminated|timed out/i,
    );
    // The socket deadline alone rejects the promise but leaves Chrome executing.
    // A fresh command must work before that original loop could naturally finish.
    assert.deepEqual(await page.evaluate(() => window.effects), { before: 1, after: 0 });
    await delay(1300);
    assert.deepEqual(await page.evaluate(() => window.effects), { before: 1, after: 0 });
    // Subsequent valid evaluations, including promises and serialized arguments, still work.
    assert.equal(
      await page.evaluate(async (n) => {
        await new Promise((resolve) => setTimeout(resolve, 20));
        return n + window.effects.before;
      }, 41),
      42,
    );
  } finally {
    cdp.close();
    await chrome.close();
  }
});

test('evaluation deadlines do not claim cancellation of asynchronous page work', async () => {
  const chrome = await openBrowser();
  const cdp = await CDP.connect(chrome.endpoint, 200);
  try {
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const page = await Page.attach(cdp, targetId);
    await assert.rejects(
      page.evaluate(async () => {
        window.delayed = 0;
        await new Promise((resolve) => setTimeout(resolve, 700));
        window.delayed++;
      }),
      /exceeded|terminated|timed out/i,
    );
    assert.equal(await page.evaluate('window.delayed'), 0);
    await delay(800);
    assert.equal(await page.evaluate('window.delayed'), 1);
  } finally {
    cdp.close();
    await chrome.close();
  }
});
