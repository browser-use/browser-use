import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer } from 'node:http';
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from '@earendil-works/pi-ai';
import { BrowserUse, Type } from '../dist/index.js';
import { EventStream } from '../dist/events.js';

const call = (name, args) =>
  fauxAssistantMessage(fauxToolCall(name, args), { stopReason: 'toolUse' });
async function fixture(responses, options = {}) {
  const faux = fauxProvider({ tokensPerSecond: 1000000 });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses(responses);
  const workspace = await mkdtemp(join(tmpdir(), 'bu-session-'));
  const agent = await BrowserUse.create({
    model: `${faux.getModel().provider}/${faux.getModel().id}`,
    models,
    workspace,
    ...options,
  });
  return {
    agent,
    faux,
    models,
    async close() {
      await agent.close();
      await rm(workspace, { recursive: true, force: true });
    },
  };
}

test('follow-up retains exact transcript and JS; fresh run drops transcript; costs remain per-run', async () => {
  const f = await fixture([
    call('javascript', { code: 'const records = ["Atlas", "Orbit"];' }),
    call('finish', { result: 'first' }),
    (context) => {
      assert.ok(JSON.stringify(context.messages).includes('first task'));
      return call('finish_from_js', { expression: 'records.length' });
    },
    (context) => {
      assert.ok(!JSON.stringify(context.messages).includes('first task'));
      return call('finish', { result: 'fresh' });
    },
  ]);
  try {
    await assert.rejects(f.agent.followUp('too early'), /before followUp/);
    const first = await f.agent.run('first task');
    const second = await f.agent.followUp('count them', { schema: Type.Number(), maxSteps: 1 });
    assert.equal(second.output, 2);
    assert.equal(second.steps, 1);
    assert.equal(f.agent.usage.totalTokens, first.usage.totalTokens + second.usage.totalTokens);
    assert.equal((await f.agent.run('fresh task')).output, 'fresh');
    assert.equal(f.agent.history.runs, 3);
  } finally {
    await f.close();
  }
});

test('save/restore validates model, preserves files, redacts saved text and announces lost JS state', async () => {
  const f = await fixture([call('finish', { result: 'secret-marker' })], {
    redact: ['secret-marker'],
  });
  let restored;
  try {
    await f.agent.run('remember secret-marker');
    const path = await f.agent.saveHistory();
    assert.ok(!(await readFile(path, 'utf8')).includes('secret-marker'));
    await writeFile(join(f.agent.workspace, 'input.csv'), 'a,b\n1,2');
    await symlink('/etc/hosts', join(f.agent.workspace, 'outside-link'));
    assert.deepEqual(
      (await f.agent.files()).map((f) => f.relativePath),
      ['input.csv'],
    );
    restored = await BrowserUse.create({
      model: f.agent.history.model,
      models: f.models,
      workspace: f.agent.workspace,
      historyFile: path,
    });
    assert.match(JSON.stringify(restored.history.messages.at(-1)), /JavaScript bindings.*reset/);
    await assert.rejects(
      BrowserUse.create({ model: 'openai/gpt-5.5', historyFile: path }),
      /model mismatch/,
    );
    const invalid = join(f.agent.workspace, 'bad.json');
    await writeFile(invalid, '{"version":99}');
    await assert.rejects(
      BrowserUse.create({ model: 'openai/gpt-5.5', historyFile: invalid }),
      /Unsupported/,
    );
  } finally {
    await restored?.close();
    await f.close();
  }
});

test('events arrive before completion and logs/history are usable on disk', async () => {
  const f = await fixture([call('finish', { result: 'ok' })]);
  try {
    const events = f.agent.events();
    const running = f.agent.run('stream');
    const first = await events.next();
    assert.equal(first.value.type, 'run_start');
    const result = await running;
    const log = (await readFile(result.eventsPath, 'utf8')).trim().split('\n').map(JSON.parse);
    assert.equal(log.at(-1).type, 'run_end');
    assert.ok(log.some((e) => e.event?.type === 'tool_execution_start'));
    assert.equal(JSON.parse(await readFile(result.historyPath, 'utf8')).version, 1);
    await events.return();
  } finally {
    await f.close();
  }
});

test('slow event consumers are bounded and fail visibly', async () => {
  let disposed = false;
  const stream = new EventStream(() => {
    disposed = true;
  }, 2);
  const e = { sequence: 1, timestamp: 1, runId: 'test', type: 'paused' };
  stream.push(e);
  stream.push(e);
  stream.push(e);
  await assert.rejects(stream.next(), /fell behind/);
  assert.equal(disposed, true);
});

test('pause acknowledges safe boundary; manual browser code then steering resumes the same run', async () => {
  let paused;
  const f = await fixture([
    call('javascript', { code: 'const value = 7' }),
    (context) => {
      assert.match(JSON.stringify(context.messages), /return eight/);
      return call('finish_from_js', { expression: 'value + 1' });
    },
  ]);
  try {
    let requested = false;
    const running = f.agent.run('control test', {
      schema: Type.Number(),
      onEvent: (e) => {
        if (!requested && e.type === 'turn_start') {
          requested = true;
          paused = f.agent.pause();
        }
      },
    });
    while (!paused) await new Promise((r) => setTimeout(r, 5));
    await paused;
    assert.equal(f.agent.isPaused, true);
    assert.equal((await f.agent.execute('const manual = 3; manual')).text, '3');
    f.agent.steer('return eight');
    f.agent.resume();
    assert.equal((await running).output, 8);
  } finally {
    await f.close();
  }
});

test('cancellation releases a paused run without performing the queued mutation', async () => {
  let paused;
  const f = await fixture([call('javascript', { code: 'globalThis.didRun = true;' })]);
  try {
    const running = f.agent.run('cancel paused', {
      onEvent: (e) => {
        if (e.type === 'turn_start') paused = f.agent.pause();
      },
    });
    while (!paused) await new Promise((r) => setTimeout(r, 5));
    await paused;
    f.agent.cancel();
    assert.equal((await running).status, 'cancelled');
    assert.equal((await f.agent.execute('globalThis.didRun')).text, '(no output)');
  } finally {
    await f.close();
  }
});

test('result validation feeds correction back; after-tool hooks see failures and can add feedback', async () => {
  let saw = false;
  const f = await fixture(
    [
      call('javascript', { code: 'throw new Error("fixture")' }),
      call('finish', { result: 1 }),
      (context) => {
        assert.match(JSON.stringify(context.messages), /must be two/);
        return call('finish', { result: 2 });
      },
    ],
    {
      validateResult: async (output) => (output === 2 ? undefined : 'must be two'),
      afterToolCall: async (ctx) => {
        if (ctx.toolCall.name === 'javascript') {
          saw = ctx.isError;
          return { content: [{ type: 'text', text: 'fixture failed; continue' }] };
        }
      },
    },
  );
  try {
    assert.equal((await f.agent.run('validate', { schema: Type.Number() })).output, 2);
    assert.equal(saw, true);
  } finally {
    await f.close();
  }
});

test('hung hooks respect deadlines and do not execute the blocked browser action', async () => {
  const f = await fixture([call('javascript', { code: 'globalThis.hookRan = true' })], {
    hookTimeoutMs: 30,
    beforeToolCall: () => new Promise(() => {}),
  });
  try {
    const result = await f.agent.run('hung', { maxSteps: 1, timeoutMs: 300 });
    assert.notEqual(result.status, 'completed');
    assert.equal((await f.agent.execute('globalThis.hookRan')).text, '(no output)');
  } finally {
    await f.close();
  }
});

test('persistent profile survives restart with cookies, localStorage and IndexedDB; concurrent owner rejected', async () => {
  const profile = await mkdtemp(join(tmpdir(), 'bu-profile-'));
  const server = createServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end('<h1>Login fixture</h1>');
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const url = `http://127.0.0.1:${server.address().port}`;
  let a, b;
  try {
    a = await BrowserUse.create({ model: 'openai/gpt-5.5', browser: { profileDir: profile } });
    await assert.rejects(
      BrowserUse.create({ model: 'openai/gpt-5.5', browser: { profileDir: profile } }),
      /locked/,
    );
    await a.execute(
      `await page.goto(${JSON.stringify(url)}); await page.evaluate(async () => { document.cookie='session=fixture; max-age=3600'; localStorage.setItem('login','yes'); await new Promise((resolve,reject)=>{ const r=indexedDB.open('auth',1); r.onupgradeneeded=()=>r.result.createObjectStore('tokens'); r.onsuccess=()=>{ const tx=r.result.transaction('tokens','readwrite');tx.objectStore('tokens').put('fixture','token');tx.oncomplete=()=>{r.result.close();resolve()};tx.onerror=reject };r.onerror=reject }) });`,
    );
    await a.close();
    b = await BrowserUse.create({ model: 'openai/gpt-5.5', browser: { profileDir: profile } });
    const value = await b.execute(
      `await page.goto(${JSON.stringify(url)}); await page.evaluate(async () => ({ cookie:document.cookie, storage:localStorage.getItem('login'), db:await new Promise((resolve,reject)=>{ const r=indexedDB.open('auth');r.onsuccess=()=>{const q=r.result.transaction('tokens').objectStore('tokens').get('token');q.onsuccess=()=>{r.result.close();resolve(q.result)};q.onerror=reject};r.onerror=reject }) }))`,
    );
    assert.match(value.text, /session=fixture/);
    assert.match(value.text, /yes/);
    assert.match(value.text, /db: 'fixture'/);
  } finally {
    await a?.close();
    await b?.close();
    if (a) await rm(a.workspace, { recursive: true, force: true });
    if (b) await rm(b.workspace, { recursive: true, force: true });
    await rm(profile, { recursive: true, force: true });
    await new Promise((r) => server.close(r));
  }
});

test('history persistence failure preserves delivered output and reports an explicit warning', async () => {
  const { mkdir } = await import('node:fs/promises');
  const f = await fixture([call('finish', { result: 'usable result' })]);
  try {
    let runId;
    const stream = f.agent.events();
    const read = (async () => {
      for await (const e of stream) {
        if (e.type === 'run_start') runId = e.runId;
      }
    })();
    const result = await f.agent.run('deliver despite history IO failure', {
      onEvent: async (e) => {
        if (e.type === 'tool_execution_start' && e.toolName === 'finish')
          await mkdir(join(f.agent.workspace, '.browser-use', 'runs', `${runId}.json`));
      },
    });
    assert.equal(result.output, 'usable result');
    assert.equal(result.status, 'completed');
    assert.equal(result.historyPath, undefined);
    assert.match(result.warnings.join(' '), /History could not be saved/);
    await stream.return();
    await read;
  } finally {
    await f.close();
  }
});

test('oversized follow-up does not call the provider or return previous task text', async () => {
  const f = await fixture([call('finish', { result: 'old answer' })]);
  try {
    await f.agent.run('old task');
    const result = await f.agent.followUp('new task', { maxContextChars: 100 });
    assert.equal(result.status, 'context_limit');
    assert.equal(result.text, '');
    assert.equal(result.usage.totalTokens, 0);
    assert.equal(f.faux.state.callCount, 1);
  } finally {
    await f.close();
  }
});

test('non-JSON custom-tool metadata cannot break event logging or final delivery', async () => {
  const details = { count: 1n, handler() {} };
  details.self = details;
  const f = await fixture([call('metadata', {}), call('finish', { result: 'done' })], {
    tools: [
      {
        name: 'metadata',
        label: 'metadata',
        description: 'fixture',
        parameters: Type.Object({}),
        execute: async () => ({ content: [{ type: 'text', text: 'ok' }], details }),
      },
    ],
  });
  try {
    const result = await f.agent.run('metadata');
    assert.equal(result.output, 'done');
    assert.match(await readFile(result.historyPath, 'utf8'), /Circular metadata/);
  } finally {
    await f.close();
  }
});
