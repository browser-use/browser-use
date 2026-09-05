import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BrowserUse } from '../dist/index.js';
import { startFixture } from '../examples/fixture.mjs';

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
test('browser interaction, extraction, native vision, iframes and shadow DOM', async () => {
  await agent.execute(
    `await page.goto(${JSON.stringify(fixture.url)}); await page.fill({role:'searchbox'}, 'Atlas'); await page.click({role:'button',name:'Search'})`,
  );
  assert.match(
    (await agent.execute('(await snapshot()).nodes.filter(n => /Atlas|Shadow done/.test(n.name))'))
      .text,
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
  await agent.execute(
    "const frame = await page.frame((await page.frames()).find(f=>f.url.endsWith('/frame')).id); await frame.fill({role:'textbox',name:'Reference'}, 'A42'); await frame.click({role:'button'}); await page.click({role:'button',name:'Shadow action'})",
  );
  assert.match((await agent.execute("await frame.text({css:'#value'})")).text, /A42/);
  assert.match(
    (await agent.execute('(await snapshot()).nodes.filter(n => /Atlas|Shadow done/.test(n.name))'))
      .text,
    /Shadow done/,
  );
  const result = await agent.execute('await screenshot()');
  assert.equal(result.images[0].mimeType, 'image/jpeg');
  assert.equal(Buffer.from(result.images[0].data, 'base64')[0], 0xff);
  assert.ok(!result.text.includes('/9j/'));
});
test('cross-origin iframe discovery and input use a real frame context', async () => {
  await agent.execute(
    `const crossUrl=${JSON.stringify(fixture.url.replace('127.0.0.1', 'localhost'))} + '/frame'; await page.evaluate(url=>{const f=document.createElement('iframe');f.id='cross';f.src=url;document.body.append(f)},crossUrl);`,
  );
  let result;
  for (let i = 0; i < 30; i++) {
    result = await agent.execute('(await page.frames()).some(f=>f.url===crossUrl)');
    if (result.text === 'true') break;
    await new Promise((r) => setTimeout(r, 50));
  }
  assert.equal(result.text, 'true');
  await agent.execute(
    "const cross = await page.frame((await page.frames()).find(f=>f.url===crossUrl).id); await cross.fill({role:'textbox',name:'Reference'}, 'CROSS'); await cross.click({role:'button',name:'Save reference'})",
  );
  assert.match((await agent.execute("await cross.text({css:'#value'})")).text, /CROSS/);
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
test('raw CDP downloads, uploads, select and tabs', async () => {
  await agent.execute(
    "await page.select({role:'combobox',name:'Shipping'}, 'Express'); await page.upload({css:'#upload'}, [workspace + '/notes.txt']); await browser.send('Browser.setDownloadBehavior', {behavior:'allow',downloadPath:workspace,eventsEnabled:true}); const nextDownload = browser.waitFor('Browser.downloadProgress', {predicate:e=>e.state==='completed'}); await page.click({role:'link',name:'Export catalog'}); await nextDownload",
  );
  assert.match(await readFile(join(workspace, 'catalog.csv'), 'utf8'), /Atlas,29/);
  const result = await agent.execute(
    "await page.click({role:'link',name:'Open details'}); const popupInfo = (await tabs.list()).find(t=>t.openerId===page.targetId); const popup=await tabs.get(popupInfo.targetId); await popup.waitFor(()=>document.readyState==='complete'); const popupTitle=(await popup.info()).title; await popup.close(); popupTitle",
  );
  assert.match(result.text, /Orbital Supply/);
});
test('a syntax or normal runtime error does not destroy healthy state', async () => {
  await assert.rejects(agent.execute('const = nope'), /Unexpected|SyntaxError/);
  await assert.rejects(agent.execute("throw new Error('expected failure')"), /expected failure/);
  assert.equal((await agent.execute('answer')).text, '40');
});
test('timeout kills infinite code; browser mutations survive exactly once', async () => {
  await agent.execute("await page.click({role:'button',name:'Save selection'})");
  await assert.rejects(agent.execute('while (true) {}', { timeoutMs: 100 }), /exceeded/);
  assert.equal((await agent.execute('typeof answer')).text, "'undefined'");
  assert.match((await agent.execute("await page.text({role:'status'})")).text, /Saved 1 time/);
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
  await assert.rejects(agent.execute('42'), /worker exited/);
  assert.equal((await agent.execute('42')).text, '42');
});

test('close is idempotent and closes active execution', async () => {
  const running = agent.execute('await new Promise(() => {})');
  const rejected = assert.rejects(running, /closed|exited|cancelled/);
  await new Promise((resolve) => setTimeout(resolve, 100));
  await Promise.all([agent.close(), agent.close()]);
  await rejected;
  await assert.rejects(agent.execute('42'), /closed/);
});
