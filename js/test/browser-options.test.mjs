import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Browser, openBrowser, chromeProfileDirs } from '../dist/browser.js';
import { CDP } from '../dist/cdp.js';
import { telemetry } from '../dist/telemetry.js';

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

test('telemetry allowlist, EU host, opt-outs and transport failure isolation', async () => {
  const environment = { ...process.env };
  delete process.env.NODE_TEST_CONTEXT;
  delete process.env.DO_NOT_TRACK;
  delete process.env.ANONYMIZED_TELEMETRY;
  const requests = [];
  const patch = mock.method(globalThis, 'fetch', async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body) });
    throw new Error('offline');
  });
  const result = {
    status: 'completed',
    steps: 2,
    durationMs: 42,
    usage: { input: 1, output: 2, cost: { total: 0.01 } },
    text: 'PRIVATE TASK',
    workspace: '/private/path',
    output: 'PASSWORD',
    model: 'PRIVATE_MODEL',
  };
  try {
    telemetry(undefined, Browser.chrome())(result);
    telemetry(false)(result);
    process.env.DO_NOT_TRACK = '1';
    telemetry(true)(result);
    delete process.env.DO_NOT_TRACK;
    process.env.ANONYMIZED_TELEMETRY = 'false';
    telemetry(true)(result);
    await new Promise((r) => setImmediate(r));
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, 'https://eu.i.posthog.com/i/v0/e/');
    assert.doesNotMatch(JSON.stringify(requests), /PRIVATE|PASSWORD/);
    assert.equal(requests[0].body.properties.$process_person_profile, false);
    assert.equal(requests[0].body.properties.browser, 'chrome');
  } finally {
    patch.mock.restore();
    for (const name of ['NODE_TEST_CONTEXT', 'DO_NOT_TRACK', 'ANONYMIZED_TELEMETRY']) {
      if (environment[name] === undefined) delete process.env[name];
      else process.env[name] = environment[name];
    }
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
