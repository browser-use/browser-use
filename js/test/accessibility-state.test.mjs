import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CDP, Page } from '../dist/index.js';
import { openBrowser } from '../dist/browser.js';

test('snapshots preserve observed control state and refresh it after real input', async () => {
  const chrome = await openBrowser();
  const cdp = await CDP.connect(chrome.endpoint);
  try {
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const page = await Page.attach(cdp, targetId);
    await page.goto(
      'data:text/html,' +
        encodeURIComponent(`
      <label><input type="radio" name="sort" checked>Featured</label>
      <label><input type="radio" name="sort">Newest</label>
      <label><input id="mixed" type="checkbox">Partial</label>
      <button id="expand" aria-expanded="false"
        onclick="this.setAttribute('aria-expanded', 'true')">Details</button>
      <button id="toggle" aria-pressed="false"
        onclick="this.setAttribute('aria-pressed', 'true')">Pin</button>
      <button aria-pressed="mixed">Mixed toggle</button>
      <button disabled>Unavailable</button>
      <button>Ordinary</button>
      <div role="listbox" aria-label="Items">
        <div role="option" aria-selected="false">First</div>
        <div role="option" aria-selected="true">Second</div>
      </div>
      <script>document.querySelector('#mixed').indeterminate = true;</script>
    `),
    );
    const first = (await page.snapshot()).nodes;
    const byName = (nodes, name) => {
      const matches = nodes.filter(
        (node) =>
          node.name === name && ['radio', 'checkbox', 'button', 'option'].includes(node.role),
      );
      assert.equal(matches.length, 1, name);
      return matches[0];
    };
    assert.equal(byName(first, 'Featured').checked, true);
    assert.equal(byName(first, 'Newest').checked, false);
    assert.equal(byName(first, 'Partial').checked, 'mixed');
    assert.equal(byName(first, 'Details').expanded, false);
    assert.equal(byName(first, 'Pin').pressed, false);
    assert.equal(byName(first, 'Mixed toggle').pressed, 'mixed');
    assert.equal(byName(first, 'Unavailable').disabled, true);
    assert.equal(byName(first, 'First').selected, false);
    assert.equal(byName(first, 'Second').selected, true);
    for (const key of ['checked', 'selected', 'expanded', 'pressed', 'disabled'])
      assert.equal(Object.hasOwn(byName(first, 'Ordinary'), key), false, key);

    await page.click({ role: 'radio', name: 'Newest' });
    await page.click({ role: 'button', name: 'Details' });
    await page.click({ role: 'button', name: 'Pin' });
    await assert.rejects(page.click({ role: 'button', name: 'Unavailable' }), /disabled/);
    const second = (await page.snapshot()).nodes;
    assert.equal(byName(second, 'Featured').checked, false);
    assert.equal(byName(second, 'Newest').checked, true);
    assert.equal(byName(second, 'Details').expanded, true);
    assert.equal(byName(second, 'Pin').pressed, true);
    assert.equal(byName(first, 'Featured').checked, true, 'earlier observations remain unchanged');

    await page.goto('data:text/html,<button>New document</button>');
    assert.equal(
      (await page.snapshot()).nodes.some((node) => node.name === 'Newest'),
      false,
    );
  } finally {
    cdp.close();
    await chrome.close();
  }
});

test('snapshot state reaches controls inside shadow DOM and explicit frames', async () => {
  const chrome = await openBrowser();
  const cdp = await CDP.connect(chrome.endpoint);
  try {
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const page = await Page.attach(cdp, targetId);
    await page.goto(
      'data:text/html,' +
        encodeURIComponent(`
      <div id="host"></div><iframe srcdoc='<label><input type="checkbox" checked>Frame choice</label>'></iframe>
      <script>document.querySelector('#host').attachShadow({mode:'open'}).innerHTML =
        '<label><input type="checkbox" checked>Shadow choice</label>';</script>
    `),
    );
    assert.equal(
      (await page.snapshot()).nodes.find((n) => n.role === 'checkbox' && n.name === 'Shadow choice')
        .checked,
      true,
    );
    const info = (await page.frames()).find((frame) => frame.url === 'about:srcdoc');
    assert.ok(info);
    const frame = await page.frame(info.id);
    assert.equal(
      (await frame.snapshot()).nodes.find((n) => n.role === 'checkbox' && n.name === 'Frame choice')
        .checked,
      true,
    );
    await frame.click({ role: 'checkbox', name: 'Frame choice' });
    assert.equal(
      (await frame.snapshot()).nodes.find((n) => n.role === 'checkbox' && n.name === 'Frame choice')
        .checked,
      false,
    );
  } finally {
    cdp.close();
    await chrome.close();
  }
});
