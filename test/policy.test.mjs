import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BrowserUse } from '../dist/index.js';
import { navigationPolicy } from '../dist/policy.js';

test('domain matching: boundaries, deny precedence, schemes and explicit empty allow list', () => {
  const allowed = navigationPolicy({
    allowedDomains: ['*.example.com'],
    prohibitedDomains: ['private.example.com'],
  });
  for (const url of ['https://example.com', 'https://a.example.com', 'about:blank'])
    assert.equal(allowed(url), true);
  for (const url of [
    'https://example.com.evil.test',
    'https://evil-example.com',
    'https://private.example.com',
    'file:///tmp/x',
    'data:text/html,x',
    'https://user@example.com',
  ])
    assert.equal(allowed(url), false);
  assert.equal(navigationPolicy({ allowedDomains: [] })('https://example.com'), false);
  assert.throws(() => navigationPolicy({ allowedDomains: ['https://example.com'] }));
});

test('CDP domain guard: direct commands, redirects, script navigation, iframes and popups', async () => {
  let blockedHits = 0;
  const server = createServer((req, res) => {
    if (req.headers.host.startsWith('localhost')) blockedHits++;
    if (req.url === '/redirect') {
      res.writeHead(302, { location: `http://localhost:${server.address().port}/blocked` });
      res.end();
    } else {
      res.setHeader('Content-Type', 'text/html');
      res.end('<title>Allowed</title><input id="login"><button>Login</button>');
    }
  });
  await new Promise((resolve) => server.listen(0, '0.0.0.0', resolve));
  const port = server.address().port;
  const agent = await BrowserUse.create({
    model: 'openai/gpt-5.4',
    browser: { kind: 'chromium' },
    allowedDomains: ['127.0.0.1'],
  });
  try {
    await agent.execute(`await page.goto('http://127.0.0.1:${port}')`);
    await assert.rejects(
      agent.execute(`await page.cdp('Page.navigate', {url:'http://localhost:${port}/blocked'})`),
      /domain policy/,
    );
    await assert.rejects(
      agent.execute(
        `await browser.send('Target.createTarget', {url:'http://localhost:${port}/blocked'})`,
      ),
      /domain policy/,
    );
    await agent.execute(`await page.goto('http://127.0.0.1:${port}/redirect').catch(()=>{})`);
    await agent.execute(
      `await page.goto('http://127.0.0.1:${port}'); await page.evaluate(url=>{location.href=url}, 'http://localhost:${port}/blocked').catch(()=>{})`,
    );
    await agent.execute(
      `await page.goto('http://127.0.0.1:${port}'); await page.evaluate(url=>{const f=document.createElement('iframe');f.src=url;document.body.append(f)},'http://localhost:${port}/blocked')`,
    );
    await agent.execute(
      `await page.evaluate(url=>window.open(url), 'http://localhost:${port}/blocked').catch(()=>{}); await new Promise(r=>setTimeout(r,500))`,
    );
    assert.equal(blockedHits, 0, 'blocked server must receive zero document requests');
    await assert.rejects(agent.execute(`await page.cdp('Fetch.disable')`), /domain policy/);
  } finally {
    await agent.close();
    await rm(agent.workspace, { recursive: true, force: true });
    await new Promise((resolve) => server.close(resolve));
  }
});

test('named secrets: domain scoped insertion, redacted observations/checkpoints and failure', async () => {
  const server = createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html');
    res.end('<label>Password<input id="password"></label>');
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const workspace = await mkdtemp(join(tmpdir(), 'bu-secret-test-'));
  const value = 'test-credential-72q';
  const agent = await BrowserUse.create({
    model: 'openai/gpt-5.4',
    browser: { kind: 'chromium' },
    workspace,
    sensitiveData: {
      password: { value, domains: ['127.0.0.1'] },
      wrong: { value: 'wrong-domain-value', domains: ['example.com'] },
    },
  });
  try {
    await agent.execute(
      `await page.goto('http://127.0.0.1:${server.address().port}'); const input=(await snapshot()).nodes.find(n=>n.role==='textbox').id; await fillSecret('password',input)`,
    );
    assert.match(
      (await agent.execute(`await page.evaluate(()=>document.querySelector('input').value)`)).text,
      /REDACTED/,
    );
    assert.equal(
      (await agent.execute(`await page.evaluate(()=>document.querySelector('input').value.length)`))
        .text,
      String(value.length),
    );
    await assert.rejects(
      agent.execute(`await fillSecret('wrong',input)`),
      /outside its allowed domains/,
    );
    await agent.execute(
      `await page.evaluate(()=>Object.defineProperty(document.querySelector('input'), 'ownerDocument', {value:{location:{href:'https://example.com'}, defaultView:window}, configurable:true}))`,
    );
    await assert.rejects(
      agent.execute(`await fillSecret('wrong',input)`),
      /outside its allowed domains/,
    );
    await agent.execute(`await fillSecret('password',input)`);
    await agent.execute(
      `await checkpoint('partial.json', { password:await page.evaluate(()=>document.querySelector('input').value) }, {partial:true})`,
    );
    assert.doesNotMatch(await readFile(join(workspace, 'partial.json'), 'utf8'), /test-credential/);
  } finally {
    await agent.close();
    await rm(workspace, { recursive: true, force: true });
    await new Promise((resolve) => server.close(resolve));
  }
});

test('domain interception leaves unrelated tabs alone and owns only its popups', async () => {
  const { openBrowser } = await import('../dist/browser.js');
  const { CDP, Page } = await import('../dist/index.js');
  const external = await openBrowser();
  const cdp = await CDP.connect(external.endpoint);
  const caller = await Page.attach(
    cdp,
    (await cdp.send('Target.getTargets')).targetInfos.find((t) => t.type === 'page').targetId,
  );
  await caller.goto('data:text/html,<h1>Caller unchanged</h1>');
  const agent = await BrowserUse.create({
    model: 'openai/gpt-5.4',
    browser: { cdpUrl: external.endpoint },
    allowedDomains: ['127.0.0.1'],
  });
  let other;
  try {
    await agent.execute('await page.info()');
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    other = await Page.attach(cdp, targetId);
    await other.goto('data:text/html,<h1>Unrelated new tab</h1>');
    assert.equal(
      await caller.evaluate(() => document.querySelector('h1').textContent),
      'Caller unchanged',
    );
    assert.equal(
      await other.evaluate(() => document.querySelector('h1').textContent),
      'Unrelated new tab',
    );
    await agent.close();
    const remaining = (await cdp.send('Target.getTargets')).targetInfos.filter(
      (t) => t.type === 'page',
    );
    assert.equal(remaining.length, 2);
  } finally {
    await agent.close();
    cdp.close();
    await external.close();
    await rm(agent.workspace, { recursive: true, force: true });
  }
});

test('secrets split across console writes never enter captured artifacts', async () => {
  const agent = await BrowserUse.create({
    model: 'openai/gpt-5.4',
    browser: { kind: 'chromium' },
    sensitiveData: { token: { value: 'abcdef123456', domains: ['example.com'] } },
  });
  try {
    const result = await agent.execute(
      `console.log('prefix'); process.stdout.write('abc'); process.stdout.write('def123'); process.stdout.write('456');`,
    );
    // Inspect the SDK console stream because process.stdout bypasses console capture.
    const captured = await agent.execute(
      `console._stdout.write('abc'); console._stdout.write('def123'); console._stdout.write('456 suffix');`,
    );
    assert.doesNotMatch(captured.text, /abcdef123456/);
    assert.match(captured.text, /REDACTED/);
    assert.doesNotMatch(await readFile(captured.outputFile, 'utf8'), /abcdef123456/);
    assert.ok(result);
  } finally {
    await agent.close();
    await rm(agent.workspace, { recursive: true, force: true });
  }
});

test('text redaction preserves image bytes and masks object keys', async () => {
  const { redact } = await import('../dist/history.js');
  const value = {
    image: { type: 'image', data: 'base64containssecret', mimeType: 'image/png' },
    secret: 'secret',
  };
  const masked = redact(value, ['secret']);
  assert.equal(masked.image.data, value.image.data);
  assert.equal(masked['[REDACTED]'], '[REDACTED]');
});

test('trusted init scripts run before navigation and preserve domain interception observers', async () => {
  const { openBrowser } = await import('../dist/browser.js');
  const { CDP } = await import('../dist/cdp.js');
  const { Page } = await import('../dist/page.js');
  const { installDomainPolicy } = await import('../dist/policy.js');
  let blocked = 0;
  const server = createServer((request, response) => {
    if (request.headers.host.startsWith('localhost')) blocked++;
    response.setHeader('content-type', 'text/html');
    response.end('<script>window.observedInit = window.fixtureInit;</script>');
  });
  await new Promise((resolve) => server.listen(0, '0.0.0.0', resolve));
  const chrome = await openBrowser();
  const cdp = await CDP.connect(chrome.endpoint);
  let events = 0;
  cdp.observeEvent = () => {
    events++;
  };
  try {
    const features = [];
    installDomainPolicy(
      cdp,
      { allowedDomains: ['127.0.0.1'], initScripts: ['window.fixtureInit = "ready";'] },
      undefined,
      (name) => features.push(name),
    );
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const page = await Page.attach(cdp, targetId);
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    assert.equal(await page.evaluate(() => window.observedInit), 'ready');
    await page
      .evaluate((url) => {
        location.href = url;
      }, `http://localhost:${server.address().port}/blocked`)
      .catch(() => {});
    const info = await page.info();
    assert.notEqual(info.url, `http://localhost:${server.address().port}/blocked`);
    assert.equal(blocked, 0);
    assert.ok(features.includes('domain_checks'));
    assert.ok(features.includes('domain_denials'));
    assert.ok(events > 0, 'The existing event observer still receives browser events.');
  } finally {
    cdp.close();
    await chrome.close();
    await new Promise((resolve) => server.close(resolve));
  }
});

test('domain interception ignores cancelled requests and detached sessions but closes other failures', async () => {
  const { installDomainPolicy } = await import('../dist/policy.js');
  for (const { detached, message, expectedClosed } of [
    {
      detached: false,
      message: 'Session closed during navigation cancellation.',
      expectedClosed: true,
    },
    {
      detached: true,
      message: 'Session closed during navigation cancellation.',
      expectedClosed: false,
    },
    { detached: false, message: 'CDP -32602: Invalid InterceptionId.', expectedClosed: false },
  ]) {
    let observer, complete, failed;
    let closed = false;
    const failedRequest = new Promise((resolve) => {
      failed = resolve;
    });
    const browser = {
      addEventObserver(callback) {
        observer = callback;
      },
      close() {
        closed = true;
      },
      async send(method) {
        if (method === 'Target.getTargetInfo') return { targetInfo: { url: 'about:blank' } };
        if (method === 'Target.attachToTarget') return { sessionId: 'fixture-session' };
        if (method === 'Fetch.failRequest') {
          failed();
          return new Promise((_resolve, reject) => {
            complete = reject;
          });
        }
        return {};
      },
    };
    installDomainPolicy(browser, { allowedDomains: ['example.com'] });
    await browser.send('Target.attachToTarget', { targetId: 'fixture-target' });
    observer(
      'Fetch.requestPaused',
      { requestId: 'fixture-request', request: { url: 'https://blocked.test' } },
      'fixture-session',
    );
    await failedRequest;
    if (detached) observer('Target.detachedFromTarget', { sessionId: 'fixture-session' });
    complete(new Error(message));
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(
      closed,
      expectedClosed,
      `Unexpected policy cleanup for detached=${detached}, error=${message}`,
    );
  }
});

test('trusted init scripts work without enabling a domain policy', async () => {
  const agent = await BrowserUse.create({
    browser: { kind: 'chromium' },
    initScripts: ['window.fixtureInit = "ready";'],
  });
  try {
    await agent.execute(
      `await page.goto('data:text/html,<script>window.fromInit=window.fixtureInit;</script>');`,
    );
    assert.equal(await agent.executeJson('await page.evaluate(() => window.fromInit)'), 'ready');
  } finally {
    await agent.close();
    await rm(agent.workspace, { recursive: true, force: true });
  }
});
