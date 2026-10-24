import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Browser, openBrowser, chromeProfileDirs } from '../dist/browser.js';
import { CDP } from '../dist/cdp.js';
import { BrowserUse } from '../dist/index.js';

for (const malformed of [false, true])
  test(`Cloud provisioning, ownership and cleanup: malformed=${malformed}`, async () => {
    const requests = [];
    const patch = mock.method(globalThis, 'fetch', async (url, options) => {
      requests.push({ url, ...options, body: JSON.parse(options.body) });
      return Response.json(
        options.method === 'POST'
          ? { id: 'fixture-id', cdpUrl: malformed ? 'file:///bad' : 'wss://example.com/cdp' }
          : {},
      );
    });
    try {
      const config = Browser.cloud({
        apiKey: 'fixture-public-api-key',
        profileId: 'fixture-profile',
        timeoutMinutes: 15,
      });
      if (malformed) await assert.rejects(openBrowser(config), /valid cdpUrl/);
      else {
        const browser = await openBrowser(config);
        await Promise.all([browser.close(), browser.close()]);
      }
      assert.equal(requests.length, 2);
      assert.equal(requests[0].headers['X-Browser-Use-API-Key'], 'fixture-public-api-key');
      assert.deepEqual(requests[0].body, {
        timeout: 15,
        enableRecording: false,
        profileId: 'fixture-profile',
      });
      assert.equal(requests[1].url, 'https://api.browser-use.com/api/v3/browsers/fixture-id');
      assert.deepEqual(requests[1].body, { action: 'stop' });
    } finally {
      patch.mock.restore();
    }
  });

test('Cloud never retries ambiguous provisioning or echoes provider response secrets', async () => {
  let calls = 0;
  const patch = mock.method(globalThis, 'fetch', async () => {
    calls++;
    return new Response('secret-from-provider', { status: 503 });
  });
  try {
    await assert.rejects(
      openBrowser(Browser.cloud({ apiKey: 'secret-key' })),
      /^Error: Browser Use Cloud POST failed \(503\)\.$/,
    );
    assert.equal(calls, 1);
  } finally {
    patch.mock.restore();
  }
});

test('real Chrome discovery uses current websocket and preserves the caller browser', async () => {
  const profile = await mkdtemp(join(tmpdir(), 'bu-discovery-'));
  await writeFile(join(profile, 'DevToolsActivePort'), '43210\n/devtools/browser/stale\n');
  const patch = mock.method(globalThis, 'fetch', async () =>
    Response.json({ webSocketDebuggerUrl: 'ws://127.0.0.1:43210/devtools/browser/current' }),
  );
  try {
    const browser = await openBrowser(Browser.chrome({ profileDir: profile }));
    assert.match(browser.endpoint, /current$/);
    await browser.close();
  } finally {
    patch.mock.restore();
    await rm(profile, { recursive: true, force: true });
  }
  assert.match(
    chromeProfileDirs('darwin', '/fixture')[0],
    /Library\/Application Support\/Google\/Chrome$/,
  );
  assert.match(chromeProfileDirs('win32', '/fixture', '/local')[0], /Google\/Chrome\/User Data$/);
});

test('persistent profile retains login across owned browser restarts and rejects concurrent use', async () => {
  const profile = await mkdtemp(join(tmpdir(), 'bu-profile-'));
  let browser;
  let cdp;
  try {
    browser = await openBrowser(Browser.chromium({ profileDir: profile }));
    cdp = await CDP.connect(browser.endpoint);
    await cdp.send('Storage.setCookies', {
      cookies: [
        {
          name: 'login',
          value: 'fixture-login',
          domain: 'example.com',
          path: '/',
          expires: Date.now() / 1000 + 3600,
        },
      ],
    });
    await assert.rejects(
      openBrowser(Browser.chromium({ profileDir: profile })),
      /profile is locked/,
    );
    cdp.close();
    await browser.close();
    browser = await openBrowser(Browser.chromium({ profileDir: profile }));
    cdp = await CDP.connect(browser.endpoint);
    assert.equal(
      (await cdp.send('Storage.getCookies')).cookies.find((c) => c.name === 'login').value,
      'fixture-login',
    );
  } finally {
    cdp?.close();
    await browser?.close();
    await rm(profile, { recursive: true, force: true });
  }
});

test(
  'macOS approval script compiles without running or accepting any UI',
  { skip: process.platform !== 'darwin' },
  async () => {
    const { approveChromeConnection } = await import('../dist/browser.js');
    const { execFile } = await import('node:child_process');
    const { promisify } = await import('node:util');
    const script = approveChromeConnection.toString().match(/const script = `([\s\S]*?)`;/)[1];
    const directory = await mkdtemp(join(tmpdir(), 'bu-ax-compile-'));
    try {
      await writeFile(join(directory, 'approval.applescript'), script);
      await promisify(execFile)('/usr/bin/osacompile', [
        '-o',
        join(directory, 'approval.scpt'),
        join(directory, 'approval.applescript'),
      ]);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  },
);

test('Cloud reads its key from the environment and reports failed cleanup for retry', async () => {
  const previous = process.env.BROWSER_USE_API_KEY;
  const requests = [];
  let stopFails = true;
  const patch = mock.method(globalThis, 'fetch', async (_url, options) => {
    requests.push(options);
    if (options.method === 'PATCH' && stopFails) return new Response('', { status: 503 });
    return Response.json(
      options.method === 'POST' ? { id: 'fixture', cdpUrl: 'wss://example.com/cdp' } : {},
    );
  });
  try {
    process.env.BROWSER_USE_API_KEY = 'environment-fixture-key';
    const browser = await openBrowser(Browser.cloud());
    assert.equal(requests[0].headers['X-Browser-Use-API-Key'], 'environment-fixture-key');
    await assert.rejects(browser.close(), /PATCH failed \(503\)/);
    stopFails = false;
    await browser.close();
    assert.equal(requests.filter((request) => request.method === 'PATCH').length, 2);
    delete process.env.BROWSER_USE_API_KEY;
    await assert.rejects(openBrowser(Browser.cloud()), /BROWSER_USE_API_KEY/);
  } finally {
    patch.mock.restore();
    if (previous === undefined) delete process.env.BROWSER_USE_API_KEY;
    else process.env.BROWSER_USE_API_KEY = previous;
  }
});

test('invalid CDP endpoints never echo connection credentials', async () => {
  for (const browser of [
    { cdpUrl: 'private-token.invalid' },
    Browser.chrome({ cdpUrl: 'private-token.invalid' }),
  ])
    await assert.rejects(openBrowser(browser), (error) => {
      assert.match(error.message, /HTTP\(S\) or WebSocket/);
      assert.doesNotMatch(error.message, /private-token/);
      return true;
    });
});

test('session cleanup retries a failed Cloud stop without reopening execution', async () => {
  let stops = 0;
  const patch = mock.method(globalThis, 'fetch', async (_url, options) => {
    if (options.method === 'POST')
      return Response.json({ id: 'retry-fixture', cdpUrl: 'wss://example.com/cdp' });
    stops++;
    return stops === 1 ? new Response('', { status: 503 }) : Response.json({});
  });
  let agent;
  try {
    agent = await BrowserUse.create({
      browser: Browser.cloud({ apiKey: 'fixture-key' }),
      telemetry: false,
    });
    const first = agent.close();
    const concurrent = agent.close();
    assert.equal(first, concurrent);
    await assert.rejects(first, /PATCH failed/);
    await assert.rejects(agent.execute('1'), /closed/);
    await agent.close();
    await agent.close();
    assert.equal(stops, 2);
  } finally {
    await agent?.close().catch(() => {});
    if (agent) await rm(agent.workspace, { recursive: true, force: true });
    patch.mock.restore();
  }
});
