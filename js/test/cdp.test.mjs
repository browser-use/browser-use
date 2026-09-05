import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { CDP, Page } from '../dist/index.js';
import { openBrowser } from '../dist/browser.js';

let chrome, cdp, page;
before(async () => {
  chrome = await openBrowser();
  cdp = await CDP.connect(chrome.endpoint, 1000);
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  page = await Page.attach(cdp, targetId);
});
after(async () => {
  cdp?.close();
  await chrome?.close();
});

test('protocol errors are recoverable; event names are not magically commands', async () => {
  await assert.rejects(cdp.send('MadeUp.method'), /CDP -32601/);
  assert.equal(cdp.on, undefined);
  assert.match((await cdp.send('Browser.getVersion')).product, /Chrome/);
});
test('event timeouts and aborts are bounded and explicit', async () => {
  await assert.rejects(
    cdp.waitFor('Browser.downloadWillBegin', { timeoutMs: 30 }),
    /exceeded 30 ms/,
  );
  const controller = new AbortController();
  const waiting = cdp.waitFor('Browser.downloadWillBegin', { signal: controller.signal });
  controller.abort();
  await assert.rejects(waiting, /cancelled/);
  assert.throws(
    () => cdp.waitFor('Browser.downloadWillBegin', { timeoutMs: { timeout: 20 } }),
    /positive integer/,
  );
});
test('tab event waits are session scoped and commands remain usable', async () => {
  const waiting = cdp.waitFor('Page.loadEventFired', { sessionId: page.sessionId });
  await page.goto('data:text/html,<h1>events</h1>');
  await waiting;
  assert.equal(await page.text({ css: 'h1' }), 'events');
});
test('strict matching, overlay guards, stale ids, unicode and replacement input', async () => {
  await page.goto(
    'data:text/html,' +
      encodeURIComponent(
        '<meta charset="utf-8"><label>Email <input value="old"></label><button>Duplicate</button><button>Duplicate</button><button id="covered" style="position:absolute;top:100px;left:0">Covered</button><div style="position:absolute;top:100px;left:0;width:200px;height:100px;background:red;z-index:10"></div>',
      ),
  );
  await assert.rejects(page.click({ role: 'button', name: 'Duplicate' }), /Ambiguous/);
  await assert.rejects(page.click({ css: '#covered' }), /covered/);
  await page.fill({ role: 'textbox', name: 'Email' }, '中文 é');
  assert.equal(await page.evaluate(() => document.querySelector('input').value), '中文 é');
  await page.fill({ css: 'input' }, 'second');
  assert.equal(await page.evaluate(() => document.querySelector('input').value), 'second');
  await page.fill({ css: 'input' }, '');
  assert.equal(await page.evaluate(() => document.querySelector('input').value), '');
  const stale = await page.find({ css: 'input' });
  await page.goto('data:text/html,new document');
  await assert.rejects(page.fill(stale, 'oops'), /CDP|stale/);
  await assert.rejects(
    page.waitFor(() => false, undefined, { timeoutMs: 30 }),
    /exceeded 30 ms/,
  );
});
test('command deadline rejects; closing rejects pending commands without crashing host', async () => {
  const short = await CDP.connect(chrome.endpoint, 100);
  const other = await Page.attach(short, page.targetId);
  await assert.rejects(other.evaluate('new Promise(() => {})'), /exceeded 100 ms/);
  const pending = other.evaluate('new Promise(() => {})');
  short.close();
  await assert.rejects(pending, /closed/);
  assert.match((await cdp.send('Browser.getVersion')).product, /Chrome/);
});
