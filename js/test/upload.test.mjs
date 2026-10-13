import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BrowserUse } from '../dist/index.js';
import { SYSTEM_PROMPT } from '../dist/prompt.js';
import { AX_PROMPT } from '../dist/ax.js';

// A fresh agent per test: the recipe prints once per file line, and ids repeat across pages.
let agent, workspace;
beforeEach(async () => {
  workspace = await mkdtemp(join(tmpdir(), 'bu-upload-'));
  agent = await BrowserUse.create({
    model: 'openai/gpt-5.4',
    mode: 'ultrafast',
    browser: process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {},
    workspace,
  });
});
afterEach(async () => {
  await agent?.close();
  if (workspace) await rm(workspace, { recursive: true, force: true });
});

const run = async (code) => (await agent.execute(code)).text;
const look = (html) =>
  run(
    `await page.goto(${JSON.stringify(`data:text/html,${encodeURIComponent(html)}`)}); await bu.state()`,
  );
/** The block of the [upload] line, with the three values a model fills in. */
const recipe = (state, id, path, type) => {
  const block = state.match(
    /^\[upload\] .*?(\{ const id = 0, path = 'cv\.pdf', type = 'application\/pdf';.*?\) \})/m,
  )?.[1];
  assert.ok(block, state);
  return block.replace(
    "const id = 0, path = 'cv.pdf', type = 'application/pdf'",
    `const id = ${id}, path = ${JSON.stringify(path)}, type = ${JSON.stringify(type)}`,
  );
};
const FORM = `<label>Attach scan <input type="file" id="f"></label><button id="go">Choose file</button><p id="log"></p>
  <script>for (const t of ['input', 'change']) document.addEventListener(t, (e) => (document.querySelector('#log').textContent += e.type + ' '));</script>`;
const file = (read) =>
  `await page.evaluate(async () => { const f = ${read}.files[0]; return f && JSON.stringify({name: f.name, type: f.type, bytes: [...new Uint8Array(await f.arrayBuffer())]}) })`;

test('the upload recipe prints once per file line, and only with a file line to use it on', async () => {
  assert.doesNotMatch(await look('<button>Go</button>'), /\[upload\]/);
  assert.doesNotMatch(AX_PROMPT, /DataTransfer/);

  const first = await look(FORM);
  assert.match(first, /^\[\d+\] file "Attach scan" = "No file chosen"$/m);
  assert.match(
    first,
    /^\[upload\] .*50 MB.*DOM\.setFileInputFiles', \{backendNodeId: id, files: \[path\]\}\)$/m,
  );
  // The same file line again: the model has the recipe already.
  const again = await run('await bu.state()');
  assert.match(again, /^\[\d+\] file "Attach scan"/m);
  assert.doesNotMatch(again, /\[upload\]/);
  // A file line with another id brings it again.
  assert.match(await look(`<button>Before</button>${FORM}`), /^\[upload\] /m);

  // The size cut drops the middle of a long page. With the file line gone there is no id to use the recipe on.
  const long = await run(
    `await page.goto('data:text/html,<body>'); await page.evaluate(() => { const buttons = (from) => Array.from({length: 150}, (_, i) => '<p><button>Button number ' + (from + i) + '</button></p>').join(''); document.body.innerHTML = buttons(0) + '<label>Attach scan <input type="file"></label>' + buttons(150) }); await bu.state()`,
  );
  assert.match(long, /lines cut here/);
  assert.doesNotMatch(long, /\] file |\[upload\]/);
  const whole = await run('await bu.state({max: 30000})');
  assert.match(whole, /^\[\d+\] file "Attach scan"/m);
  assert.match(whole, /^\[upload\] /m);
});

test('the recipe as printed sets name, type and bytes, fires input and change, and says how many files it set', async () => {
  const state = await look(FORM);
  const id = state.match(/^\[(\d+)\] file "Attach scan"/m)[1];
  const bytes = [0, 255, 128, 10, 13, 226, 130, 172];
  const path = (await run(`await artifact('scan.png', Uint8Array.from(${JSON.stringify(bytes)}))`))
    .trim()
    .replace(/^'|'$/g, '');
  const block = recipe(state, id, path, 'image/png');
  // Twice in one cell: every name it declares is its own.
  const out = await run(`${block}; ${block}; await bu.state()`);
  assert.equal(out.match(/^files set: 1$/gm)?.length, 2, out);
  assert.match(out, /^\[\d+\] file "Attach scan" = "scan\.png"$/m);
  assert.deepEqual(
    JSON.parse(
      JSON.parse(
        `"${(await run(file("document.querySelector('#f')"))).trim().slice(1, -1).replace(/"/g, '\\"')}"`,
      ),
    ),
    {
      name: 'scan.png',
      type: 'image/png',
      bytes,
    },
  );
  assert.equal(
    await run("await page.evaluate(() => document.querySelector('#log').textContent)"),
    "'input change input change '",
  );
});

test('a failed upload says why, also with code after it', async () => {
  const state = await look(FORM);
  const button = state.match(/^\[(\d+)\] button "Choose file"/m)[1];
  const path = (await run("await artifact('note.txt', 'text')")).trim().replace(/^'|'$/g, '');
  const out = await run(
    `${recipe(state, button, path, 'text/plain')}; console.log('next statement ran')`,
  );
  assert.match(out, /^upload failed: Error: not a file input$/m);
  assert.match(out, /^next statement ran$/m);
  assert.equal(
    await run("await page.evaluate(() => document.querySelector('#f').files.length)"),
    '0',
  );
  await assert.rejects(
    agent.execute(recipe(state, 999999, path, 'text/plain')),
    /No node with given id/,
  );
  // Clicking a file input fails with where to look, and the state printed after that cell carries the recipe again.
  const clicked = await agent.execute(`await bu.click(${state.match(/^\[(\d+)\] file/m)[1]})`).then(
    () => assert.fail('the click went through'),
    (e) => `${e.message}\n${e.result?.text ?? ''}`,
  );
  assert.match(
    clicked,
    /File input: clicking opens the OS file chooser; set its files with the \[upload\] line of bu\.state\(\) instead/,
  );
  assert.match(clicked, /^\[upload\] /m);
});

test('hidden file inputs get a line and the recipe, also in a shadow root and a same-origin frame', async () => {
  const state =
    await look(`<input type="file" name="maindoc" style="display:none"><div id="host"></div>
    <iframe id="frame" srcdoc="<input type=file name=inframe style=display:none><p>frame text</p>"></iframe><p>Styled uploader</p>
    <script>document.querySelector('#host').attachShadow({ mode: 'open' }).innerHTML = '<input type="file" name="inshadow" style="display:none">';</script>`);
  const ids = Object.fromEntries(
    ['maindoc', 'inshadow', 'inframe'].map((name) => [
      name,
      state.match(new RegExp(`^\\[(\\d+)\\] file "${name}" \\(hidden\\)$`, 'm'))?.[1],
    ]),
  );
  assert.ok(ids.maindoc && ids.inshadow && ids.inframe, state);
  assert.match(state, /^\[upload\] /m);

  const path = (await run("await artifact('cv.txt', 'text')")).trim().replace(/^'|'$/g, '');
  const out = await run(
    `${recipe(state, ids.inshadow, path, 'text/plain')}; ${recipe(state, ids.inframe, path, 'text/plain')}; await bu.state()`,
  );
  assert.equal(out.match(/^files set: 1$/gm)?.length, 2, out);
  // bu.state() can confirm a hidden input's upload, and does not repeat the recipe for lines it already came with.
  assert.match(
    out,
    new RegExp(`^\\[${ids.inshadow}\\] file "inshadow" \\(hidden\\) = "cv\\.txt"$`, 'm'),
  );
  assert.match(
    out,
    new RegExp(`^\\[${ids.inframe}\\] file "inframe" \\(hidden\\) = "cv\\.txt"$`, 'm'),
  );
  assert.match(out, new RegExp(`^\\[${ids.maindoc}\\] file "maindoc" \\(hidden\\)$`, 'm'));
  assert.doesNotMatch(out, /\[upload\]/);
  for (const read of [
    "document.querySelector('#host').shadowRoot.querySelector('input')",
    "document.querySelector('#frame').contentDocument.querySelector('input')",
  ])
    assert.match(
      await run(file(read)),
      /"name":"cv\.txt","type":"text\/plain","bytes":\[116,101,120,116\]/,
    );
});

test('the base prompt keeps the path call for a browser on this machine and names the bytes way for a remote one', () => {
  assert.match(
    SYSTEM_PROMPT,
    /Uploads: DOM\.setFileInputFiles\(\{backendNodeId,files\}\) when the browser runs on this machine\./,
  );
  assert.match(
    SYSTEM_PROMPT,
    /A remote browser cannot read paths here: .*new File\(\[bytes\], name, \{type\}\)/,
  );
});
