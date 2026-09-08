import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CDP, Page } from '../dist/index.js';
import { openBrowser } from '../dist/browser.js';

const style = `<style>
  .sr { position:absolute; width:1px; height:1px; padding:0; margin:-1px;
    overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
  label { display:block; padding:18px; width:220px; background:#eee; margin:10px; }
</style>`;

async function fixture(html, run) {
  const chrome = await openBrowser();
  const cdp = await CDP.connect(chrome.endpoint);
  try {
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const page = await Page.attach(cdp, targetId);
    await page.goto('data:text/html,' + encodeURIComponent(style + html));
    await run(page);
  } finally {
    cdp.close();
    await chrome.close();
  }
}

test('AX clicks activate clipped native controls through their visible labels using trusted input', async () => {
  await fixture(
    `
    <input class="sr" id="choice" type="radio" name="plan"><label for="choice"><span>Choice</span></label>
    <label><input class="sr" id="check" type="checkbox">Included</label>
    <script>window.clicks=[]; document.addEventListener('click', e =>
      clicks.push({target:e.target.id, trusted:e.isTrusted}));</script>
  `,
    async (page) => {
      const before = (await page.snapshot()).nodes.find(
        (n) => n.role === 'radio' && n.name === 'Choice',
      );
      assert.ok(before);
      await page.click(before.id);
      assert.equal(await page.evaluate(() => document.querySelector('#choice').checked), true);
      await page.click({ role: 'checkbox', name: 'Included' });
      assert.equal(await page.evaluate(() => document.querySelector('#check').checked), true);
      await page.click({ role: 'checkbox', name: 'Included' });
      assert.equal(await page.evaluate(() => document.querySelector('#check').checked), false);
      const clicks = await page.evaluate(() => window.clicks);
      assert.equal(clicks.filter((e) => ['choice', 'check'].includes(e.target)).length, 3);
      assert.ok(
        clicks.every((e) => e.trusted),
        'activation must come from physical CDP input',
      );
      assert.equal(before.checked, false, 'old observations remain unchanged');
      // A label can legitimately have its own ordinary input at its center.
      await page.evaluate(() => {
        const label = document.createElement('label');
        label.id = 'direct';
        label.style.cssText = 'display:block;width:40px;height:40px;padding:0';
        label.innerHTML =
          '<input id="ordinary" type="checkbox" style="width:40px;height:40px;margin:0">';
        document.body.append(label);
      });
      await page.click({ css: '#direct' });
      assert.equal(await page.evaluate(() => document.querySelector('#ordinary').checked), true);
    },
  );
});

test('label fallback preserves disabled and overlay rejection without dispatching clicks', async () => {
  await fixture(
    `
    <fieldset disabled><input class="sr" id="disabled" type="checkbox"><label for="disabled">Disabled</label></fieldset>
    <input class="sr" id="aria" type="radio" aria-disabled="true"><label for="aria">ARIA disabled</label>
    <div style="position:relative"><input class="sr" id="covered" type="checkbox"><label for="covered">Covered</label>
      <div style="position:absolute;inset:0;z-index:10;background:white">Overlay</div></div>
    <div style="position:relative"><input id="ordinary" type="checkbox"><label for="ordinary">Visible label</label>
      <div style="position:absolute;top:0;left:0;width:30px;height:30px;z-index:10;background:white">Block</div></div>
    <script>window.clicks=0;document.addEventListener('click',()=>clicks++);</script>
  `,
    async (page) => {
      for (const id of ['disabled', 'aria'])
        await assert.rejects(page.click({ css: '#' + id }), /disabled/);
      await assert.rejects(page.click({ css: '#covered' }), /covered/);
      await assert.rejects(page.click({ css: '#ordinary' }), /covered/);
      assert.equal(await page.evaluate(() => window.clicks), 0);
      assert.deepEqual(
        await page.evaluate(() => [...document.querySelectorAll('input')].map((n) => n.checked)),
        [false, false, false, false],
      );
    },
  );
});

test('label fallback never activates an embedded link or guesses among visible labels', async () => {
  await fixture(
    `
    <input class="sr" id="link" type="checkbox"><label for="link" style="padding:0"><a href="#wrong" style="display:block;padding:20px">Link</a></label>
    <input class="sr" id="many" type="checkbox"><label for="many">First</label><label for="many">Second</label>
    <script>window.clicks=0;document.addEventListener('click',()=>clicks++);</script>
  `,
    async (page) => {
      await assert.rejects(page.click({ css: '#link' }), /covered|interactive/);
      await assert.rejects(page.click({ css: '#many' }), /Ambiguous|covered/);
      assert.equal(await page.evaluate(() => window.clicks), 0);
      assert.equal(await page.evaluate(() => location.hash), '');
    },
  );
});

test('associated labels work in shadow DOM and an explicit frame', async () => {
  const controls = `${style}<input class="sr" id="toggle" type="checkbox"><label for="toggle">Toggle</label>`;
  await fixture(
    `<div id="host"></div><iframe style="width:400px;height:250px"></iframe>`,
    async (page) => {
      await page.evaluate((html) => {
        document.querySelector('#host').attachShadow({ mode: 'open' }).innerHTML = html;
        document.querySelector('iframe').srcdoc = html;
      }, controls);
      await page.click({ role: 'checkbox', name: 'Toggle' });
      assert.equal(
        await page.evaluate(
          () => document.querySelector('#host').shadowRoot.querySelector('input').checked,
        ),
        true,
      );
      await page.waitFor(() =>
        document.querySelector('iframe').contentDocument?.querySelector('input'),
      );
      const info = (await page.frames()).find((f) => f.url === 'about:srcdoc');
      assert.ok(info);
      const frame = await page.frame(info.id);
      await frame.click({ role: 'checkbox', name: 'Toggle' });
      assert.equal(await frame.evaluate(() => document.querySelector('input').checked), true);
      assert.equal(
        await page.evaluate(
          () => document.querySelector('#host').shadowRoot.querySelector('input').checked,
        ),
        true,
      );
    },
  );
});
