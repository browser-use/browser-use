import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BrowserUse } from '../dist/index.js';
import { startFixture } from './fixture.mjs';
import { imageDimensions } from '../dist/images.js';

let agent, fixture, workspace;
before(async () => {
  fixture = await startFixture();
  workspace = await mkdtemp(join(tmpdir(), 'bu-test-'));
  agent = await BrowserUse.create({
    model: 'openai/gpt-5.4',
    browser: process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {},
    workspace,
    maxOutputChars: 1200,
    operationTimeoutMs: 1500,
  });
});
after(async () => {
  await agent?.close();
  await fixture?.close();
  if (workspace) await rm(workspace, { recursive: true, force: true });
});

test('actual let/const/functions persist across awaited cells', async () => {
  await agent.execute(
    'const answer = 40; let increment = 1; function add(x) { return x + increment; }; await Promise.resolve()',
  );
  assert.equal((await agent.execute('increment += 1; add(answer)')).text, '42');
});
test('Node global alias points to the REPL realm and preserves native fetch bindings', async () => {
  assert.equal((await agent.execute('global === globalThis')).text, 'true');
  assert.equal(
    (
      await agent.execute(
        "const fetch = global.fetch; await (await fetch('data:text/plain,alias-works')).text()",
      )
    ).text,
    "'alias-works'",
  );
  await agent.execute('global.aliasMarker = 73; void 0');
  assert.equal((await agent.execute('globalThis.aliasMarker')).text, '73');
  assert.equal(globalThis.aliasMarker, undefined);
  await agent.execute('delete global.aliasMarker; void 0');
});
test('a CDP deadline preserves Node bindings and reports an uncertain action without replay', async () => {
  await agent.execute("await page.goto('data:text/html,<title>CDP deadline</title>')");
  await assert.rejects(
    agent.execute(
      'const cdpDeadlineMarker = 73; const cdpDeadlineTarget = page.targetId; await page.evaluate(() => { globalThis.deadlineActions = (globalThis.deadlineActions ?? 0) + 1; return new Promise(() => {}); })',
      { timeoutMs: 10_000 },
    ),
    (error) => {
      assert.match(error.message, /CDP Runtime.evaluate exceeded 1500 ms/);
      assert.equal(error.stateReset, false);
      return true;
    },
  );
  assert.equal((await agent.execute('cdpDeadlineMarker')).text, '73');
  assert.equal((await agent.execute('page.targetId === cdpDeadlineTarget')).text, 'true');
  assert.equal(
    (await agent.execute('await page.evaluate(() => globalThis.deadlineActions)')).text,
    '1',
  );
});
test('raw input, DOM extraction, AX discovery and native vision share the persistent REPL', async () => {
  await agent.execute(`await page.goto(${JSON.stringify(fixture.url)});
    const inputId=(await snapshot()).nodes.find(n=>n.role==='searchbox').id;
    await page.cdp('DOM.focus',{backendNodeId:inputId});
    await page.cdp('Input.insertText',{text:'Atlas'});
    const searchId=(await snapshot()).nodes.find(n=>n.role==='button'&&n.name==='Search').id;
    const box=(await page.cdp('DOM.getBoxModel',{backendNodeId:searchId})).model.content;
    await page.clickAt((box[0]+box[2]+box[4]+box[6])/4,(box[1]+box[3]+box[5]+box[7])/4)`);
  assert.match(
    (await agent.execute('(await snapshot()).nodes.filter(n => /Atlas/.test(n.name))')).text,
    /Atlas/,
  );
  assert.equal(
    (
      await agent.execute(
        "await page.evaluate(() => Array.from(document.querySelectorAll('article:not([hidden]) h2'), el => el.textContent))",
      )
    ).text.trim(),
    "[ 'Atlas' ]",
  );
  const result = await agent.execute('await screenshot()');
  assert.equal(result.images[0].mimeType, 'image/jpeg');
  assert.equal(Buffer.from(result.images[0].data, 'base64')[0], 0xff);
  assert.ok(!result.text.includes('/9j/'));
});
test('same-origin and cross-origin frames remain available through raw CDP', async () => {
  await agent.execute(`const crossUrl=${JSON.stringify(fixture.url.replace('127.0.0.1', 'localhost'))}+'/frame';
    await page.evaluate(url=>{const f=document.createElement('iframe');f.src=url;document.body.append(f)},crossUrl);`);
  for (let i = 0; i < 40; i++) {
    const result = await agent.execute(
      "(await browser.send('Target.getTargets')).targetInfos.some(t=>t.type==='iframe'&&t.url===crossUrl)",
    );
    if (result.text === 'true') break;
    await new Promise((r) => setTimeout(r, 50));
  }
  const result = await agent.execute(`
    const tree=(await page.cdp('Page.getFrameTree')).frameTree;
    const child=tree.childFrames.find(f=>f.frame.url.endsWith('/frame')).frame;
    const ctx=(await page.cdp('Page.createIsolatedWorld',{frameId:child.id,worldName:'test'})).executionContextId;
    const same=await page.cdp('Runtime.evaluate',{expression:'document.querySelector("label").textContent',contextId:ctx,returnByValue:true});
    const target=(await browser.send('Target.getTargets')).targetInfos.find(t=>t.type==='iframe'&&t.url===crossUrl);
    const attached=await browser.send('Target.attachToTarget',{targetId:target.targetId,flatten:true});
    const cross=await browser.send('Runtime.evaluate',{expression:'location.href',returnByValue:true},attached.sessionId);
    await browser.send('Target.detachFromTarget',{sessionId:attached.sessionId});
    console.log({same:same.result.value,cross:cross.result.value})`);
  assert.match(result.text, /Reference/);
  assert.match(result.text, /localhost/);
});
test('conventional filesystem API, output spooling, and exclusive artifact writes', async () => {
  assert.equal(
    (
      await agent.execute(
        "typeof require('node:fs').readFileSync + ':' + typeof require('node:fs').promises.readFile",
      )
    ).text,
    "'function:function'",
  );
  const result = await agent.execute("console.log('x'.repeat(5000))");
  assert.ok(result.text.length < 1500);
  assert.equal((await readFile(result.outputFile, 'utf8')).trim().length, 5000);
  await agent.execute("await artifact('notes.txt', 'verified')");
  await assert.rejects(agent.execute("await artifact('notes.txt', 'overwrite')"), /EEXIST/);
  await assert.rejects(agent.execute("await artifact('../escape', 'no')"), /plain filename/);
});
test('raw CDP downloads, uploads and explicit tab ownership', async () => {
  await agent.execute(`
    const root=(await page.cdp('DOM.getDocument')).root.nodeId;
    const upload=(await page.cdp('DOM.querySelector',{nodeId:root,selector:'#upload'})).nodeId;
    await page.cdp('DOM.setFileInputFiles',{nodeId:upload,files:[workspace+'/notes.txt']});
    await browser.send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:workspace,eventsEnabled:true});
    const download=browser.waitFor('Browser.downloadProgress',{predicate:e=>e.state==='completed'});
    await page.evaluate(()=>document.querySelector('[download]').click());
    await download;
    console.log(await page.evaluate(()=>document.querySelector('#upload').files[0].name));`);
  assert.match(await readFile(join(workspace, 'catalog.csv'), 'utf8'), /Atlas,29/);
  const result =
    await agent.execute(`const popup=await tabs.open(${JSON.stringify(fixture.url)}+'/details');
    const title=(await popup.info()).title;await popup.close();title`);
  assert.match(result.text, /Orbital Supply/);
});
test('a syntax or normal runtime error does not destroy healthy state', async () => {
  await assert.rejects(agent.execute('const = nope'), /Unexpected|SyntaxError/);
  await assert.rejects(agent.execute("throw new Error('expected failure')"), /expected failure/);
  assert.equal((await agent.execute('answer')).text, '40');
});
test('timeout kills infinite code; browser mutations survive exactly once', async () => {
  await agent.execute(
    "await page.clickAt(...await page.evaluate(s => {const el=document.querySelector(s);el.scrollIntoView({block:'center'});const r=el.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}, '#save'))",
  );
  await assert.rejects(agent.execute('while (true) {}', { timeoutMs: 100 }), /exceeded/);
  assert.equal((await agent.execute('typeof answer')).text, "'undefined'");
  assert.match(
    (
      await agent.execute(
        "await page.evaluate(() => document.querySelector('[role=status]').textContent)",
      )
    ).text,
    /Saved 1 time/,
  );
});
test('cancellation kills pending code; concurrent operations fail explicitly', async () => {
  const controller = new AbortController();
  const running = agent.execute('await new Promise(() => {})', { signal: controller.signal });
  await assert.rejects(agent.execute('42'), /busy/);
  setTimeout(() => controller.abort(), 100);
  await assert.rejects(running, /cancelled/);
  assert.equal((await agent.execute('6 * 7')).text, '42');
});
test('invalid timeouts fail before execution', async () => {
  await assert.rejects(agent.execute('42', { timeoutMs: NaN }), /positive integer/);
  await assert.rejects(agent.execute('42', { timeoutMs: -1 }), /positive integer/);
});
test('worker crashes do not kill the host and recovery is explicit', async () => {
  await assert.rejects(agent.execute('process.exit(7)'), /exited/);
  assert.equal((await agent.execute('42')).text, '42');
});
test('a killed REPL process cannot kill the SDK host', async () => {
  await assert.rejects(
    agent.execute("process.kill(process.pid, 'SIGKILL')"),
    /worker exited.*SIGKILL/,
  );
  assert.equal((await agent.execute('6*7')).text, '42');
});
test('a crash between cells reports lost state before executing new code', async () => {
  await agent.execute(
    "setTimeout(() => { throw new Error('background failure'); }, 20); 'scheduled'",
  );
  await new Promise((resolve) => setTimeout(resolve, 150));
  await assert.rejects(
    agent.execute(
      "require('node:fs').writeFileSync(require('node:path').join(workspace, 'must-not-run.txt'), 'unexpected')",
    ),
    (error) => {
      assert.match(error.message, /worker exited/);
      assert.equal(error.name, 'CellError');
      assert.equal(error.stateReset, true);
      assert.deepEqual(error.result.images, []);
      return true;
    },
  );
  await assert.rejects(readFile(join(workspace, 'must-not-run.txt')), { code: 'ENOENT' });
  assert.equal((await agent.execute('42')).text, '42');
});

test('explicit page, other-tab and raw CDP captures attach native images without changing saved bytes', async () => {
  const result = await agent.execute(`
    await page.goto(${JSON.stringify(fixture.url)});
    const captured = await page.screenshot({quality:70});
    await artifact('attached-capture.jpg', captured);
    const imageTab = await tabs.open(${JSON.stringify(fixture.url)});
    await imageTab.cdp('Emulation.setDeviceMetricsOverride', {width:390,height:844,deviceScaleFactor:1,mobile:false});
    await imageTab.cdp('Page.captureScreenshot', {format:'png'});
    await browser.send('Page.captureScreenshot', {format:'webp'}, imageTab.sessionId);
    await imageTab.close();
    await screenshot();
  `);
  assert.deepEqual(
    result.images.map((image) => image.mimeType),
    ['image/jpeg', 'image/png', 'image/webp', 'image/jpeg'],
  );
  const otherTabPng = Buffer.from(result.images[1].data, 'base64');
  assert.equal(otherTabPng.readUInt32BE(16), 390);
  assert.equal(otherTabPng.readUInt32BE(20), 844);
  assert.deepEqual(
    await readFile(join(workspace, 'attached-capture.jpg')),
    Buffer.from(result.images[0].data, 'base64'),
  );
  assert.equal((await agent.execute('42')).images.length, 0);
});

test('oversized JPEG, PNG and WebP captures keep original artifacts and attach bounded previews without replay', async () => {
  const result = await agent.execute(
    `
    await page.goto(${JSON.stringify(fixture.url)});
    await page.evaluate(() => { document.body.style.height = '22000px'; globalThis.imageGuardActions = 1; });
    const imageGuardTarget = page.targetId;
    for (const format of ['jpeg', 'png', 'webp']) {
      const raw = await page.cdp('Page.captureScreenshot', {format, quality:60, captureBeyondViewport:true,
        clip:{x:0,y:0,width:1440,height:format==='webp'?6000:22000,scale:1}});
      await artifact('tall-original.' + format, Buffer.from(raw.data, 'base64'));
    }
    console.log('three original captures saved');
  `,
    { timeoutMs: 30_000 },
  );
  assert.equal(result.images.length, 3, result.text);
  assert.match(result.text, /model preview/);
  assert.match(result.text, /Do not assume preview coordinates are viewport coordinates/);
  for (const [index, format] of ['jpeg', 'png', 'webp'].entries()) {
    const original = await readFile(join(workspace, 'tall-original.' + format));
    const source = imageDimensions(original);
    assert.ok(source.height >= (format === 'webp' ? 6000 : 22000), format);
    const preview = Buffer.from(result.images[index].data, 'base64');
    const size = imageDimensions(preview);
    assert.ok(size.width <= 2000 && size.height <= 2000, format);
    assert.notDeepEqual(original, preview, format);
  }
  assert.equal((await agent.execute('page.targetId === imageGuardTarget')).text, 'true');
  assert.equal(
    (await agent.execute('await page.evaluate(() => globalThis.imageGuardActions)')).text,
    '1',
  );
  await agent.execute(`await page.goto(${JSON.stringify(fixture.url)})`);
});

test('screenshot bounds preserve command results and failed-cell images stay in their own cell', async () => {
  const bounded = await agent.execute(`
    for (let i=0;i<5;i++) await page.screenshot({quality:30});
    console.log('all five captures returned');
  `);
  assert.equal(bounded.images.length, 4);
  assert.match(bounded.text, /Screenshot omitted/);
  assert.match(bounded.text, /all five captures returned/);
  await assert.rejects(
    agent.execute("await page.screenshot(); throw new Error('after capture')"),
    (error) => {
      assert.match(error.message, /after capture/);
      assert.equal(error.result.images.length, 1);
      return true;
    },
  );
  assert.equal((await agent.execute('42')).images.length, 0);
  const reconnected = await agent.execute('await reconnect(); await page.screenshot(); void 0');
  assert.equal(reconnected.images.length, 1);
});

test('observation target follows named tabs and raw sessions without replacing the primary page', async () => {
  const primary = await agent.execute(
    `await page.goto(${JSON.stringify(fixture.url)}); page.targetId`,
  );
  const named = await agent.execute(
    `const observedTab = await tabs.open('data:text/html,<title>Named tab</title>'); await observedTab.info(); observedTab.targetId`,
  );
  assert.equal(named.targetId, primary.targetId);
  assert.notEqual(named.observationTargetId, primary.targetId);
  assert.equal(named.observationTargetId, named.text.slice(1, -1));
  const raw = await agent.execute(
    "await browser.send('Runtime.evaluate', {expression:'document.title', returnByValue:true}, observedTab.sessionId)",
  );
  assert.equal(raw.observationTargetId, named.observationTargetId);
  const first = await agent.execute('await page.info()');
  assert.equal(first.observationTargetId, primary.targetId);
  await assert.rejects(
    agent.execute("await observedTab.evaluate(() => {throw new Error('named tab failure')})"),
    (error) => {
      assert.equal(error.result.observationTargetId, named.observationTargetId);
      assert.equal(error.result.targetId, primary.targetId);
      return true;
    },
  );
  const closed = await agent.execute('await observedTab.close()');
  assert.equal(closed.observationTargetId, undefined);
  const reconnected = await agent.execute('await reconnect(); await page.info()');
  assert.equal(reconnected.targetId, primary.targetId);
  assert.equal(reconnected.observationTargetId, primary.targetId);
});

test('primary browser state from an initially failed cell survives a later worker reset', async () => {
  const isolated = await BrowserUse.create({ model: 'openai/gpt-5.4' });
  let primary;
  try {
    await assert.rejects(
      isolated.execute(
        `await page.goto(${JSON.stringify(fixture.url)}); await page.clickAt(...await page.evaluate(s => {const el=document.querySelector(s);el.scrollIntoView({block:'center'});const r=el.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}, '#save')); throw new Error('first cell failed')`,
      ),
      (error) => {
        primary = error.result.targetId;
        assert.ok(primary);
        return true;
      },
    );
    await assert.rejects(isolated.execute('while(true){}', { timeoutMs: 100 }), /exceeded/);
    const result = await isolated.execute(
      "await page.evaluate(() => document.querySelector('[role=status]').textContent)",
    );
    assert.equal(result.targetId, primary);
    assert.match(result.text, /Saved 1 time/);
  } finally {
    await isolated.close();
    await rm(isolated.workspace, { recursive: true, force: true });
  }
});

test('close is idempotent and closes active execution', async () => {
  const running = agent.execute('await new Promise(() => {})');
  const rejected = assert.rejects(running, /closed|exited|cancelled/);
  await new Promise((resolve) => setTimeout(resolve, 100));
  await Promise.all([agent.close(), agent.close()]);
  await rejected;
  await assert.rejects(agent.execute('42'), /closed/);
});

for (const enabled of [false, true]) {
  test(`interaction corner brackets are passive, transient and opt-in: ${enabled}`, async () => {
    const session = await BrowserUse.create({ model: 'openai/gpt-5.4', highlightActions: enabled });
    try {
      await session.execute(`
        await page.goto('data:text/html,<label>Postal code <input id="postal"></label><button onclick="window.clicked=event.isTrusted">Save</button>');
        const before = await snapshot();
        const input = before.nodes.find(n=>n.role==='textbox').id;
        await page.cdp('DOM.focus',{backendNodeId:input});
        await page.cdp('Input.insertText',{text:'06238'});
        await new Promise(resolve=>setTimeout(resolve,200));
        const afterTyping = await snapshot();
      `);
      assert.equal(
        (
          await session.execute(
            `await page.evaluate(()=>!!document.querySelector('[data-browser-use-interaction-highlight]'))`,
          )
        ).text,
        String(enabled),
      );
      if (enabled) {
        assert.equal(
          (
            await session.execute(
              `await page.evaluate(()=>getComputedStyle(document.querySelector('[data-browser-use-interaction-highlight]')).pointerEvents)`,
            )
          ).text,
          "'none'",
        );
        assert.equal(
          (
            await session.execute(
              `await page.evaluate(()=>document.querySelector('[data-browser-use-interaction-highlight]').getAttribute('aria-hidden'))`,
            )
          ).text,
          "'true'",
        );
      }
      const shot = await session.execute('await screenshot()');
      assert.ok(shot.images.length);
      await session.execute('await new Promise(resolve=>setTimeout(resolve,1400))');
      assert.equal(
        (
          await session.execute(
            `await page.evaluate(()=>!!document.querySelector('[data-browser-use-interaction-highlight]'))`,
          )
        ).text,
        'false',
      );
      assert.equal(
        (
          await session.execute(
            `JSON.stringify((await snapshot()).nodes.map(n=>[n.role,n.name])) === JSON.stringify(afterTyping.nodes.map(n=>[n.role,n.name]))`,
          )
        ).text,
        'true',
      );
      await session.execute(`
        const q=(await page.cdp('DOM.getBoxModel',{backendNodeId:(await snapshot()).nodes.find(n=>n.role==='button').id})).model.content;
        await page.clickAt((q[0]+q[2]+q[4]+q[6])/4,(q[1]+q[3]+q[5]+q[7])/4);
      `);
      assert.equal((await session.execute('await page.evaluate(()=>window.clicked)')).text, 'true');
    } finally {
      await session.close();
      await rm(session.workspace, { recursive: true, force: true });
    }
  });
}
