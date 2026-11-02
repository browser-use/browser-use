import { test, before, after, mock } from 'node:test';
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
  assert.equal(await page.evaluate(() => document.querySelector('h1').textContent), 'events');
});
test('AX node IDs support trusted raw input, coordinates, unicode and stale-node errors', async () => {
  await page.goto(
    'data:text/html,' +
      encodeURIComponent(
        '<meta charset="utf-8"><label>Email <input value="old"></label><button onclick="window.trusted=event.isTrusted">Save</button>',
      ),
  );
  const nodes = (await page.snapshot()).nodes;
  const input = nodes.find((n) => n.role === 'textbox').id;
  await page.cdp('DOM.focus', { backendNodeId: input });
  await page.cdp('Input.dispatchKeyEvent', {
    type: 'rawKeyDown',
    key: 'a',
    code: 'KeyA',
    commands: ['selectAll'],
  });
  await page.cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: 'a', code: 'KeyA' });
  await page.cdp('Input.insertText', { text: '中文 é' });
  assert.equal(await page.evaluate(() => document.querySelector('input').value), '中文 é');
  const id = nodes.find((n) => n.role === 'button').id;
  const q = (await page.cdp('DOM.getBoxModel', { backendNodeId: id })).model.content;
  await page.clickAt((q[0] + q[2] + q[4] + q[6]) / 4, (q[1] + q[3] + q[5] + q[7]) / 4);
  assert.equal(await page.evaluate(() => window.trusted), true);
  await assert.rejects(page.clickAt(NaN, 0), /finite/);
  await page.goto('data:text/html,new document');
  await assert.rejects(page.cdp('DOM.focus', { backendNodeId: input }), /CDP/);
  await assert.rejects(
    page.waitFor(() => false, undefined, { timeoutMs: 30 }),
    /exceeded 30 ms/,
  );
});
test('failed page initialization detaches only its new session and preserves the original error', async () => {
  for (const failingMethod of ['Page.enable', 'Runtime.enable']) {
    const failure = new Error(`Injected ${failingMethod} timeout`);
    const send = cdp.send.bind(cdp);
    let attached;
    const detached = cdp.waitFor('Target.detachedFromTarget', {
      predicate: (event) => event.sessionId === attached,
    });
    const patch = mock.method(cdp, 'send', async (method, params, sessionId) => {
      if (method === failingMethod && sessionId === attached) throw failure;
      const result = await send(method, params, sessionId);
      if (method === 'Target.attachToTarget') attached = result.sessionId;
      return result;
    });
    try {
      await assert.rejects(Page.attach(cdp, page.targetId), (error) => error === failure);
      assert.equal((await detached).sessionId, attached);
      assert.notEqual(attached, page.sessionId);
      // The caller's existing session and browser remain usable.
      assert.equal((await page.info()).url, 'data:text/html,new document');
    } finally {
      patch.mock.restore();
    }
  }
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

test('response taps are passive, single-delivery and bound to the dispatched command', async () => {
  const lazy = CDP.lazy(chrome.endpoint, 1000);
  let observed = 0;
  try {
    lazy.observeResponse = (method, _params, result) => {
      assert.equal(method, 'Browser.getVersion');
      assert.match(result.product, /Chrome/);
      observed++;
      throw new Error('observer failure must not fail the command');
    };
    assert.match((await lazy.send('Browser.getVersion')).product, /Chrome/);
    assert.equal(observed, 1);
    await assert.rejects(lazy.send('MadeUp.method'), /CDP/);
    assert.equal(observed, 1);
    let original = 0,
      replacement = 0;
    cdp.observeResponse = () => original++;
    const pending = cdp.send(
      'Runtime.evaluate',
      {
        expression: 'new Promise(resolve => setTimeout(() => resolve(42), 50))',
        awaitPromise: true,
        returnByValue: true,
      },
      page.sessionId,
    );
    cdp.observeResponse = () => replacement++;
    assert.equal((await pending).result.value, 42);
    assert.equal(original, 1);
    assert.equal(replacement, 0);
  } finally {
    cdp.observeResponse = undefined;
    lazy.close();
  }
});

test('authenticated CDP discovery and WebSocket retain headers and reject credential forwarding', async () => {
  const { createServer } = await import('node:http');
  const { WebSocketServer } = await import('ws');
  const observed = [];
  let endpoint;
  let redirect = false;
  const server = createServer((request, response) => {
    observed.push(['discovery', request.headers.authorization]);
    if (redirect) {
      response.writeHead(302, { location: 'http://localhost:1/private' });
      response.end();
      return;
    }
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ webSocketDebuggerUrl: endpoint }));
  });
  const sockets = new WebSocketServer({ noServer: true });
  server.on('upgrade', (request, socket, head) => {
    observed.push(['websocket', request.headers.authorization]);
    if (request.headers.authorization !== 'Bearer fixture-token') return socket.destroy();
    sockets.handleUpgrade(request, socket, head, (connection) => {
      connection.on('message', (raw) => {
        const message = JSON.parse(String(raw));
        connection.send(JSON.stringify({ id: message.id, result: { product: 'fixture-browser' } }));
      });
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  endpoint = origin.replace('http:', 'ws:') + '/browser';
  let connection;
  try {
    connection = CDP.lazy(origin, 1000, false, {
      headers: { Authorization: 'Bearer fixture-token' },
    });
    assert.equal((await connection.send('Browser.getVersion')).product, 'fixture-browser');
    assert.deepEqual(observed, [
      ['discovery', 'Bearer fixture-token'],
      ['websocket', 'Bearer fixture-token'],
    ]);
    connection.close();
    endpoint = 'ws://localhost:1/browser';
    await assert.rejects(
      CDP.connect(origin, 1000, false, {
        headers: { Authorization: 'Bearer fixture-token' },
      }),
      /retain the endpoint host/,
    );
    redirect = true;
    await assert.rejects(
      CDP.connect(origin, 1000, false, { headers: { Authorization: 'Bearer fixture-token' } }),
      /discovery failed \(302\)/,
    );
    await assert.rejects(
      CDP.connect(origin.replace('http:', 'ws:') + '/browser', 1000, false, {
        headers: { Authorization: 'wrong-token' },
      }),
      /Could not connect/,
    );
    assert.equal(observed.filter(([kind]) => kind === 'websocket').length, 2);
  } finally {
    connection?.close();
    for (const socket of sockets.clients) socket.terminate();
    await new Promise((resolve) => sockets.close(resolve));
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});

test('CDP client certificates authenticate discovery and WebSocket without disabling server verification', async () => {
  const { createServer } = await import('node:https');
  const { WebSocketServer } = await import('ws');
  const { mkdtemp, readFile, rm } = await import('node:fs/promises');
  const { join } = await import('node:path');
  const { tmpdir } = await import('node:os');
  const { execFile } = await import('node:child_process');
  const { promisify } = await import('node:util');
  const directory = await mkdtemp(join(tmpdir(), 'bu-cdp-tls-'));
  let server, sockets, connection;
  try {
    await promisify(execFile)('openssl', [
      'req',
      '-x509',
      '-newkey',
      'rsa:2048',
      '-nodes',
      '-days',
      '1',
      '-subj',
      '/CN=localhost',
      '-addext',
      'subjectAltName=DNS:localhost,IP:127.0.0.1',
      '-keyout',
      join(directory, 'key.pem'),
      '-out',
      join(directory, 'cert.pem'),
    ]);
    const [key, cert] = await Promise.all([
      readFile(join(directory, 'key.pem'), 'utf8'),
      readFile(join(directory, 'cert.pem'), 'utf8'),
    ]);
    const authenticated = [];
    server = createServer(
      { key, cert, ca: cert, requestCert: true, rejectUnauthorized: true },
      (request, response) => {
        authenticated.push(request.socket.authorized);
        response.end(
          JSON.stringify({
            webSocketDebuggerUrl: `wss://127.0.0.1:${server.address().port}/browser`,
          }),
        );
      },
    );
    sockets = new WebSocketServer({ noServer: true });
    server.on('upgrade', (request, socket, head) => {
      authenticated.push(request.socket.authorized);
      sockets.handleUpgrade(request, socket, head, (client) => {
        client.on('message', (raw) =>
          client.send(
            JSON.stringify({
              id: JSON.parse(String(raw)).id,
              result: { product: 'secure-browser' },
            }),
          ),
        );
      });
    });
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    const endpoint = `https://127.0.0.1:${server.address().port}`;
    await assert.rejects(CDP.connect(endpoint, 1000), /discovery connection failed/);
    connection = await CDP.connect(endpoint, 1000, false, { tls: { ca: cert, cert, key } });
    assert.equal((await connection.send('Browser.getVersion')).product, 'secure-browser');
    assert.deepEqual(authenticated, [true, true]);
    await assert.rejects(
      CDP.connect(endpoint, 1000, false, {
        tls: { ca: cert, cert, key, rejectUnauthorized: false },
      }),
      /tls supports/,
    );
  } finally {
    connection?.close();
    if (sockets) {
      for (const socket of sockets.clients) socket.terminate();
      await new Promise((resolve) => sockets.close(resolve));
    }
    if (server) {
      server.closeAllConnections();
      await new Promise((resolve) => server.close(resolve));
    }
    await rm(directory, { recursive: true, force: true });
  }
});
