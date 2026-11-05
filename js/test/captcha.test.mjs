import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { CDP } from '../dist/cdp.js';
import { CaptchaWatch } from '../dist/captcha.js';
import { BrowserUse } from '../dist/index.js';

/** A WebSocket CDP endpoint that answers the BrowserUse domain as `handle` says. Text frames only. */
async function fakeBrowser(handle) {
  const commands = [];
  const sockets = new Set();
  const server = createServer();
  server.on('upgrade', (req, socket) => {
    const accept = createHash('sha1')
      .update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
      .digest('base64');
    socket.write(
      `HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`,
    );
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
    socket.on('error', () => {});
    let buffer = Buffer.alloc(0);
    socket.on('data', (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      for (;;) {
        if (buffer.length < 2) return;
        let length = buffer[1] & 127;
        let offset = 2;
        if (length === 126) [length, offset] = [buffer.readUInt16BE(2), 4];
        if (buffer.length < offset + 4 + length) return;
        const mask = buffer.subarray(offset, offset + 4);
        const data = Buffer.from(buffer.subarray(offset + 4, offset + 4 + length));
        for (let i = 0; i < data.length; i++) data[i] ^= mask[i % 4];
        const opcode = buffer[0] & 15;
        buffer = buffer.subarray(offset + 4 + length);
        if (opcode === 8) return socket.end();
        if (opcode !== 1) continue;
        const message = JSON.parse(data.toString());
        commands.push(message.params ? [message.method, message.params] : [message.method]);
        // An answer may be a promise, to delay or withhold the response.
        void Promise.resolve(handle(message, emit)).then((answer) =>
          socket.write(
            frame(
              answer.error
                ? { id: message.id, error: answer.error }
                : { id: message.id, result: answer },
            ),
          ),
        );
      }
    });
  });
  const frame = (value) => {
    const data = Buffer.from(JSON.stringify(value));
    const head =
      data.length < 126
        ? Buffer.from([0x81, data.length])
        : Buffer.from([0x81, 126, data.length >> 8, data.length & 255]);
    return Buffer.concat([head, data]);
  };
  /** Without a delay the event goes out at once, ahead of the answer to the command being handled. */
  const emit = (method, params, delayMs) => {
    const write = () => {
      for (const socket of sockets) socket.write(frame({ method, params }));
    };
    if (delayMs === undefined) write();
    else setTimeout(write, delayMs);
  };
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const url = `ws://127.0.0.1:${server.address().port}/devtools/browser/fake`;
  return {
    url,
    commands,
    emit,
    async connect() {
      const cdp = await CDP.connect(url, 1000);
      return { cdp, watch: new CaptchaWatch(cdp) };
    },
    close: () => {
      for (const socket of sockets) socket.destroy();
      return new Promise((resolve) => server.close(resolve));
    },
  };
}

const started = {
  targetId: 'T1',
  vendor: 'recaptcha',
  url: 'https://example.com/login',
  startedAt: 1,
};
const finished = (success) => ({ ...started, durationMs: 40, finishedAt: 2, success });
/** A cloud browser with the solver off, which starts a solve once it is switched on. */
const solverOff = (onEnable) => {
  let enabled = false;
  return (message, emit) => {
    if (message.method === 'BrowserUse.getCaptchaSolverEnabled') return { enabled };
    if (message.method === 'BrowserUse.setCaptchaSolverEnabled') {
      enabled = message.params.enabled;
      if (enabled) onEnable?.(emit);
      return { enabled };
    }
    return { error: { code: -32601, message: `'${message.method}' wasn't found` } };
  };
};
const solverOn = (onRead) => (message, emit) => {
  if (message.method === 'BrowserUse.getCaptchaSolverEnabled') {
    onRead?.(emit);
    return { enabled: true };
  }
  if (message.method === 'BrowserUse.setCaptchaSolverEnabled')
    return { enabled: message.params.enabled };
  return { error: { code: -32601, message: `'${message.method}' wasn't found` } };
};
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const toggles = (commands) =>
  commands.filter(([m]) => m === 'BrowserUse.setCaptchaSolverEnabled').map(([, p]) => p.enabled);

test('a solver it switched on reports the solve, then goes back off', async () => {
  const fake = await fakeBrowser(
    solverOff((emit) => {
      emit('BrowserUse.captchaSolverStarted', started, 20);
      emit('BrowserUse.captchaSolverFinished', finished(true), 60);
    }),
  );
  const { cdp, watch } = await fake.connect();
  try {
    const result = await watch.solve({ timeoutMs: 2000 });
    assert.equal(result.solved, true);
    assert.equal(result.detail, 'solved');
    assert.equal(result.vendor, 'recaptcha');
    assert.equal(result.url, 'https://example.com/login');
    assert.ok(result.seconds < 2);
    await wait(30);
    assert.deepEqual(toggles(fake.commands), [true, false]);
    assert.match(
      watch.note(),
      /^\[Captcha solver finished: solved \(recaptcha\) on https:\/\/example.com\/login\.\]$/,
    );
    assert.equal(watch.note(), '', 'a finished solve is reported once');
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('a failed solve says so and leaves an enabled solver alone', async () => {
  const fake = await fakeBrowser(
    solverOn((emit) => {
      emit('BrowserUse.captchaSolverStarted', started, 10);
      emit('BrowserUse.captchaSolverFinished', finished(false), 40);
    }),
  );
  const { cdp, watch } = await fake.connect();
  try {
    const result = await watch.solve({ timeoutMs: 2000 });
    assert.equal(result.solved, false);
    assert.equal(result.detail, 'the solver failed');
    assert.deepEqual(toggles(fake.commands), []);
    assert.match(watch.note(), /finished: not solved/);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('no solve within the start window says no solve started; a solver it switched on goes off', async () => {
  const fake = await fakeBrowser(solverOff());
  const { cdp, watch } = await fake.connect();
  try {
    const result = await watch.solve({ timeoutMs: 2000, startMs: 80 });
    assert.deepEqual(
      { solved: result.solved, detail: result.detail },
      { solved: false, detail: 'no captcha solve started within 0 s' },
    );
    assert.ok(result.seconds < 1);
    assert.deepEqual(toggles(fake.commands), [true, false]);
    assert.equal(watch.note(), '');
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('a solve past the deadline is still solving; the solver stays on until it finishes', async () => {
  const fake = await fakeBrowser(
    solverOff((emit) => emit('BrowserUse.captchaSolverStarted', started, 10)),
  );
  const { cdp, watch } = await fake.connect();
  try {
    const result = await watch.solve({ timeoutMs: 150 });
    assert.equal(result.detail, 'still solving');
    assert.equal(result.next, 'call solveCaptcha() again');
    assert.equal(result.vendor, 'recaptcha');
    assert.deepEqual(toggles(fake.commands), [true]);
    assert.match(
      watch.note(),
      /^\[Captcha solver running \(recaptcha\) on https:\/\/example.com\/login for \d+ s\. Wait with await solveCaptcha\(\)/,
    );
    assert.match(watch.note(), /running/, 'an active solve is reported every cell');
    // The next call joins the running solve instead of toggling the solver again.
    fake.emit('BrowserUse.captchaSolverFinished', finished(true), 30);
    const next = await watch.solve({ timeoutMs: 2000 });
    assert.equal(next.detail, 'solved');
    await wait(30);
    assert.deepEqual(toggles(fake.commands), [true, false]);
    assert.equal(
      fake.commands.filter(([m]) => m === 'BrowserUse.getCaptchaSolverEnabled').length,
      1,
    );
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('a solve that started on its own is joined without toggling', async () => {
  const fake = await fakeBrowser(solverOn());
  const { cdp, watch } = await fake.connect();
  try {
    fake.emit('BrowserUse.captchaSolverStarted', started);
    await wait(30);
    assert.match(watch.note(), /Captcha solver running/);
    fake.emit('BrowserUse.captchaSolverFinished', finished(true), 30);
    const result = await watch.solve({ timeoutMs: 2000 });
    assert.equal(result.detail, 'solved');
    assert.deepEqual(fake.commands, []);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('a solve that finished before the call, in the same cell, is returned at once', async () => {
  const fake = await fakeBrowser(solverOn());
  const { cdp, watch } = await fake.connect();
  try {
    fake.emit('BrowserUse.captchaSolverStarted', started);
    fake.emit('BrowserUse.captchaSolverFinished', finished(true), 10);
    await wait(40);
    const result = await watch.solve({ timeoutMs: 2000, startMs: 1000 });
    assert.equal(result.detail, 'solved');
    assert.ok(result.seconds < 0.5);
    assert.deepEqual(fake.commands, []);
    // Once seen, it is not returned again: the next call waits for a new solve.
    const again = await watch.solve({ timeoutMs: 2000, startMs: 50 });
    assert.match(again.detail, /^no captcha solve started/);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('a finish already shown in cell output is not returned by a later call', async () => {
  const fake = await fakeBrowser(solverOn());
  const { cdp, watch } = await fake.connect();
  try {
    fake.emit('BrowserUse.captchaSolverFinished', finished(true));
    await wait(30);
    assert.match(watch.note(), /finished: solved/);
    const result = await watch.solve({ timeoutMs: 2000, startMs: 50 });
    assert.match(result.detail, /^no captcha solve started/);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('an endpoint without the BrowserUse domain reports the solver unavailable', async () => {
  const fake = await fakeBrowser((message) => ({
    error: { code: -32601, message: `'${message.method}' wasn't found` },
  }));
  const { cdp, watch } = await fake.connect();
  try {
    const result = await watch.solve({ timeoutMs: 2000 });
    assert.equal(result.solved, false);
    assert.match(
      result.detail,
      /^solver unavailable: CDP -32601: 'BrowserUse.getCaptchaSolverEnabled' wasn't found$/,
    );
    assert.deepEqual(toggles(fake.commands), []);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('abort rejects promptly and switches off a solver it turned on', async () => {
  const fake = await fakeBrowser(solverOff());
  const { cdp, watch } = await fake.connect();
  try {
    const controller = new AbortController();
    const solving = watch.solve({ timeoutMs: 5000, signal: controller.signal });
    setTimeout(() => controller.abort(), 50);
    const began = Date.now();
    await assert.rejects(solving, /cancelled/);
    assert.ok(Date.now() - began < 1000);
    assert.deepEqual(toggles(fake.commands), [true, false]);
    await assert.rejects(watch.solve({ timeoutMs: 100, signal: AbortSignal.abort() }), /abort/i);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('solves on several pages report the failure, not whichever finished last', async () => {
  const fake = await fakeBrowser(solverOn());
  const { cdp, watch } = await fake.connect();
  try {
    const other = { ...started, targetId: 'T2', url: 'https://example.com/other' };
    fake.emit('BrowserUse.captchaSolverStarted', started);
    fake.emit('BrowserUse.captchaSolverStarted', other);
    fake.emit('BrowserUse.captchaSolverFinished', finished(false), 10);
    fake.emit('BrowserUse.captchaSolverFinished', { ...other, success: true }, 20);
    await wait(40);
    const result = await watch.solve({ timeoutMs: 2000 });
    assert.equal(result.solved, false);
    assert.equal(result.detail, 'the solver failed');
    assert.equal(result.url, 'https://example.com/login');
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('concurrent calls share one result', async () => {
  const fake = await fakeBrowser(
    solverOff((emit) => {
      emit('BrowserUse.captchaSolverStarted', started, 10);
      emit('BrowserUse.captchaSolverFinished', finished(true), 40);
    }),
  );
  const { cdp, watch } = await fake.connect();
  try {
    const [a, b] = await Promise.all([
      watch.solve({ timeoutMs: 2000 }),
      watch.solve({ timeoutMs: 2000 }),
    ]);
    assert.equal(a.detail, 'solved');
    assert.equal(b.detail, 'solved');
    assert.deepEqual(toggles(fake.commands), [true, false]);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('a solve that finishes before the enable answer still switches the solver back off', async () => {
  const fake = await fakeBrowser(
    solverOff((emit) => {
      emit('BrowserUse.captchaSolverStarted', started);
      emit('BrowserUse.captchaSolverFinished', finished(true));
    }),
  );
  const { cdp, watch } = await fake.connect();
  try {
    const result = await watch.solve({ timeoutMs: 2000 });
    assert.equal(result.detail, 'solved');
    await wait(30);
    assert.deepEqual(toggles(fake.commands), [true, false]);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('the next call waits for a pending switch-off before reading the solver state', async () => {
  let enabled = false;
  const fake = await fakeBrowser((message, emit) => {
    if (message.method === 'BrowserUse.getCaptchaSolverEnabled') return { enabled };
    enabled = message.params.enabled;
    if (enabled) {
      emit('BrowserUse.captchaSolverStarted', started, 10);
      return { enabled };
    }
    // The switch-off answers late.
    return wait(150).then(() => {
      fake.commands.push(['answered']);
      return { enabled };
    });
  });
  const { cdp, watch } = await fake.connect();
  try {
    assert.equal((await watch.solve({ timeoutMs: 100 })).detail, 'still solving');
    // Finishes between cells: the watch switches the solver off on its own.
    fake.emit('BrowserUse.captchaSolverFinished', finished(true));
    await wait(20);
    watch.note();
    await watch.solve({ timeoutMs: 2000, startMs: 50 });
    const order = fake.commands.map(([m, p]) => (p && 'enabled' in p ? p.enabled : m));
    const answered = order.indexOf('answered');
    assert.ok(answered > 0);
    assert.ok(order.indexOf('BrowserUse.getCaptchaSolverEnabled', 1) > answered, String(order));
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('a solver switched off by someone else is not switched off again', async () => {
  const fake = await fakeBrowser(
    solverOff((emit) => emit('BrowserUse.captchaSolverStarted', started, 10)),
  );
  const { cdp, watch } = await fake.connect();
  try {
    assert.equal((await watch.solve({ timeoutMs: 100 })).detail, 'still solving');
    fake.emit('BrowserUse.captchaSolverStateChanged', { enabled: false, changedAt: 3 });
    fake.emit('BrowserUse.captchaSolverStateChanged', { enabled: true, changedAt: 4 });
    fake.emit('BrowserUse.captchaSolverFinished', finished(true), 10);
    await wait(50);
    assert.deepEqual(toggles(fake.commands), [true]);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('a solve with no finished event for 150 s ends as lost', async (t) => {
  const fake = await fakeBrowser(solverOn());
  const { cdp, watch } = await fake.connect();
  try {
    fake.emit('BrowserUse.captchaSolverStarted', started);
    await wait(30);
    t.mock.timers.enable({ apis: ['Date'], now: Date.now() });
    t.mock.timers.tick(151_000);
    const result = await watch.solve({ timeoutMs: 2000 });
    assert.equal(result.solved, false);
    assert.equal(result.detail, 'no result from the solver after 150 s');
    assert.match(watch.note(), /^\[Captcha solver finished: no result after 150 s \(recaptcha\)/);
    assert.doesNotMatch(watch.note(), /running/);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('a state read that never answers ends within the helper deadline', async () => {
  const fake = await fakeBrowser(() => new Promise(() => {}));
  const { cdp, watch } = await fake.connect();
  try {
    const began = Date.now();
    const result = await watch.solve({ timeoutMs: 200 });
    assert.match(result.detail, /^solver unavailable: no answer within/);
    assert.ok(Date.now() - began < 600);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('abort during a solve keeps the solver on until the solve finishes', async () => {
  const fake = await fakeBrowser(
    solverOff((emit) => emit('BrowserUse.captchaSolverStarted', started, 10)),
  );
  const { cdp, watch } = await fake.connect();
  try {
    const controller = new AbortController();
    const solving = watch.solve({ timeoutMs: 5000, signal: controller.signal });
    setTimeout(() => controller.abort(), 50);
    await assert.rejects(solving, /cancelled/);
    assert.deepEqual(toggles(fake.commands), [true]);
    fake.emit('BrowserUse.captchaSolverFinished', finished(true));
    await wait(30);
    assert.deepEqual(toggles(fake.commands), [true, false]);
  } finally {
    cdp.close();
    await fake.close();
  }
});

test('the REPL helper solves within the cell and cells report solves that run on their own', async () => {
  const fake = await fakeBrowser(
    solverOff((emit) => {
      emit('BrowserUse.captchaSolverStarted', started, 20);
      emit('BrowserUse.captchaSolverFinished', finished(true), 60);
    }),
  );
  const workspace = await mkdtemp(join(tmpdir(), 'bu-captcha-test-'));
  const agent = await BrowserUse.create({
    model: 'openai/gpt-5.4',
    browser: { cdpUrl: fake.url },
    workspace,
  });
  try {
    const cell = await agent.execute('console.log(JSON.stringify(await solveCaptcha()))');
    const [json, ...notes] = cell.text.split('\n');
    assert.equal(JSON.parse(json).detail, 'solved');
    assert.match(notes.join('\n'), /^\n?\[Captcha solver finished: solved \(recaptcha\)/);
    fake.emit('BrowserUse.captchaSolverStarted', { ...started, targetId: 'T2' });
    await wait(50);
    assert.match((await agent.execute('1')).text, /Captcha solver running \(recaptcha\)/);
    // A short cell leaves too little time to wait, instead of timing out and losing JS state.
    await assert.rejects(
      agent.execute('await solveCaptcha()', { timeoutMs: 3500 }),
      /Too little cell time left/,
    );
  } finally {
    await agent.close();
    await fake.close();
    await rm(workspace, { recursive: true, force: true });
  }
});

let chromeAgent;
after(() => chromeAgent?.close());
test('plain Chrome has no solver: the helper says so instead of throwing', async () => {
  chromeAgent = await BrowserUse.create({
    model: 'openai/gpt-5.4',
    browser: process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {},
  });
  const cell = await chromeAgent.execute('console.log(JSON.stringify(await solveCaptcha()))');
  const result = JSON.parse(cell.text);
  assert.equal(result.solved, false);
  assert.match(result.detail, /^solver unavailable: CDP -32601/);
});
