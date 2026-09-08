import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, readFile, mkdir, symlink, readdir, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BrowserRuntime, CellError } from '../dist/runtime.js';
import { Observer } from '../dist/observer.js';
import { RunContext, contextChars } from '../dist/context.js';
import { researchTools } from '../dist/research-tools.js';
import { workspaceFiles } from '../dist/history.js';
import { createModels, fauxProvider, fauxAssistantMessage } from '@earendil-works/pi-ai';

async function workspace(fn) {
  const path = await mkdtemp(join(tmpdir(), 'bu-recovery-'));
  try {
    await fn(path);
  } finally {
    await rm(path, { recursive: true, force: true });
  }
}

test('unavailable CDP cannot block JS/files; killed cells retain output and durable checkpoints', () =>
  workspace(async (path) => {
    const runtime = new BrowserRuntime({
      endpoint: 'ws://127.0.0.1:1',
      workspace: path,
      operationTimeoutMs: 50,
      maxOutputChars: 100,
    });
    try {
      await runtime.execute(
        "let rows=[1,2,3]; await checkpoint('rows.json', rows); console.log('saved')",
      );
      await assert.rejects(
        runtime.execute("console.log('before failure'); throw new Error('broken')"),
        (error) => {
          assert(error instanceof CellError);
          assert.equal(error.stateReset, false);
          assert.match(error.result.text, /before failure/);
          return true;
        },
      );
      await assert.rejects(runtime.execute('await page.info()'), /connect/);
      assert.match((await runtime.execute('rows.length')).text, /3/);
      await assert.rejects(
        runtime.execute("console.log('last progress'); while(true){}", 100),
        (error) => {
          assert.equal(error.stateReset, true);
          assert.match(error.result.text, /last progress/);
          return true;
        },
      );
      assert.match(
        (
          await runtime.execute(
            "console.log(typeof rows); console.log(require('node:fs').readFileSync('rows.json','utf8'))",
          )
        ).text,
        /undefined\n\[1,2,3\]/,
      );
      assert.equal(await readFile(join(path, 'rows.json'), 'utf8'), '[1,2,3]');
    } finally {
      await runtime.close();
    }
  }));

test('observer timeout aborts observation without blocking work; shutdown cancels active callback', async () => {
  let aborted = false;
  const observer = new Observer(
    (_event, signal) =>
      new Promise((resolve) =>
        signal.addEventListener(
          'abort',
          () => {
            aborted = true;
            resolve();
          },
          { once: true },
        ),
      ),
    20,
  );
  observer.push({ type: 'agent_start' });
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert(aborted);
  assert.match(observer.warnings[0], /exceeded/);
  await observer.close();
});

test('Pi compaction preserves exact user constraints, recent tool pairs and provider signatures', () =>
  workspace(async (path) => {
    const faux = fauxProvider({ tokensPerSecond: 1e6 }),
      models = createModels();
    models.setProvider(faux.provider);
    faux.setResponses([
      fauxAssistantMessage(
        'Saved records in rows.json. Do not submit anything; finish the remaining inspection.',
      ),
    ]);
    const messages = [
      { role: 'user', content: 'Never submit. Inspect records and preserve IDs.', timestamp: 1 },
    ];
    for (let i = 0; i < 8; i++) {
      messages.push(
        fauxAssistantMessage(
          [
            { type: 'thinking', thinking: 'inspect', thinkingSignature: 'x'.repeat(30000) },
            { type: 'toolCall', id: `t${i}`, name: 'javascript', arguments: { code: 'inspect' } },
          ],
          { stopReason: 'toolUse' },
        ),
      );
      messages.push({
        role: 'toolResult',
        toolCallId: `t${i}`,
        toolName: 'javascript',
        content: [{ type: 'text', text: 'evidence '.repeat(600) }],
        isError: false,
        timestamp: i + 2,
      });
    }
    const before = contextChars(messages);
    assert(before < 100000);
    const ctx = new RunContext(
      faux.getModel(),
      models.streamSimple.bind(models),
      path,
      30000,
      true,
    );
    await ctx.prepare(messages, 'system');
    assert.equal(ctx.compactions, 1);
    assert.equal(faux.state.callCount, 1);
    const projected = ctx.project(messages);
    assert.match(projected[0].content, /Never submit/);
    assert(projected.length < messages.length);
    assert.equal(projected[1].content[0].thinkingSignature.length, 30000);
    assert.equal(projected[2].toolCallId, projected[1].content[1].id);
    assert.equal(messages.length, 17);
    assert(ctx.fits(messages, 'system'));
  }));

test('compaction archives omitted observations privately and links earlier archives across repeated compaction', () =>
  workspace(async (path) => {
    const faux = fauxProvider({ tokensPerSecond: 1e6 });
    const models = createModels();
    models.setProvider(faux.provider);
    faux.setResponses([
      fauxAssistantMessage('Continue the task.'),
      fauxAssistantMessage('Continue.'),
    ]);
    const ctx = new RunContext(
      faux.getModel(),
      models.streamSimple.bind(models),
      path,
      15000,
      true,
      ['test-secret'],
    );
    const messages = [{ role: 'user', content: 'Inspect; never submit.', timestamp: 1 }];
    const append = (from) => {
      for (let i = from; i < from + 8; i++) {
        messages.push(
          fauxAssistantMessage(
            [
              {
                type: 'thinking',
                thinking: 'private reasoning',
                thinkingSignature: 'private signature',
              },
              {
                type: 'toolCall',
                id: `t${i}`,
                name: 'javascript',
                arguments: { code: `inspect(${i})` },
              },
            ],
            { stopReason: 'toolUse' },
          ),
        );
        messages.push({
          role: 'toolResult',
          toolCallId: `t${i}`,
          toolName: 'javascript',
          content: [
            {
              type: 'text',
              text: i === 0 ? 'observed_units=73 test-secret' : 'evidence '.repeat(400),
            },
            { type: 'image', data: 'private-image-bytes', mimeType: 'image/png' },
          ],
          isError: i === 1,
          timestamp: i + 2,
        });
      }
    };
    append(0);
    await ctx.prepare(messages, 'system');
    const archivePath = () =>
      JSON.parse(
        ctx.project(messages)[0].content.match(/^Evidence archive \(JSON path\): (.+)$/m)[1],
      );
    const firstPath = archivePath();
    const firstText = await readFile(firstPath, 'utf8');
    const first = JSON.parse(firstText);
    assert.equal(first.summary, 'Continue the task.');
    assert.match(firstText, /observed_units=73 \[REDACTED\]/);
    assert.doesNotMatch(
      firstText,
      /test-secret|private reasoning|private signature|private-image-bytes/,
    );
    assert.equal(first.messages.find((m) => m.toolCallId === 't1').isError, true);
    assert.equal(first.messages.find((m) => m.toolCallId === 't0').toolName, 'javascript');
    assert.equal((await stat(firstPath)).mode & 0o777, 0o600);
    assert.equal(messages[2].content[0].text, 'observed_units=73 test-secret');
    assert.equal((await workspaceFiles(path)).length, 0);
    append(8);
    await ctx.prepare(messages, 'system');
    assert.equal(ctx.compactions, 2);
    const secondPath = archivePath();
    assert.notEqual(secondPath, firstPath);
    const second = JSON.parse(await readFile(secondPath, 'utf8'));
    assert(
      second.messages.some((m) => typeof m.content === 'string' && m.content.includes(firstPath)),
    );
    assert.equal(await readFile(firstPath, 'utf8'), firstText);
  }));

test('failed evidence archive write leaves original context available', () =>
  workspace(async (path) => {
    const faux = fauxProvider({ tokensPerSecond: 1e6 });
    const models = createModels();
    models.setProvider(faux.provider);
    faux.setResponses([fauxAssistantMessage('Summary that must not replace evidence.')]);
    const ctx = new RunContext(
      faux.getModel(),
      models.streamSimple.bind(models),
      path,
      15000,
      true,
    );
    const messages = [
      { role: 'user', content: 'Keep evidence.', timestamp: 1 },
      ...Array.from({ length: 8 }, () => fauxAssistantMessage('observation '.repeat(400))),
    ];
    await mkdir(join(path, '.browser-use'));
    await writeFile(join(path, '.browser-use', 'context'), 'occupied');
    await assert.rejects(ctx.prepare(messages, 'system'), /EEXIST|ENOTDIR/);
    assert.equal(ctx.compactions, 0);
    assert.deepEqual(ctx.project(messages), messages);
  }));

test('Pi shell tools do not inherit provider or judge secrets and work without a browser', () =>
  workspace(async (path) => {
    process.env.BU_FAKE_PROVIDER_SECRET = 'must-not-leak';
    try {
      const tools = researchTools(path, 2000);
      const bash = tools.find((t) => t.name === 'bash');
      const result = await bash.execute('test', {
        command: 'printf "%s" "${BU_FAKE_PROVIDER_SECRET-unset}"',
      });
      assert.match(result.content[0].text, /unset/);
      const write = tools.find((t) => t.name === 'write');
      await write.execute('write', { path: 'answer.json', content: '{"done":3}' });
      assert.equal(await readFile(join(path, 'answer.json'), 'utf8'), '{"done":3}');
    } finally {
      delete process.env.BU_FAKE_PROVIDER_SECRET;
    }
  }));

test('write reports delivery outside workspace without moving or replaying the successful write', () =>
  workspace(async (root) => {
    const path = join(root, 'deliverables');
    await mkdir(path);
    const write = researchTools(path, 2000).find((t) => t.name === 'write');
    const outside = await write.execute('outside', {
      path: '../report.md',
      content: 'observed data',
    });
    assert.match(outside.content.at(-1).text, /write succeeded outside workspace/);
    assert.equal(await readFile(join(root, 'report.md'), 'utf8'), 'observed data');
    assert.deepEqual(await workspaceFiles(path), []);
    const inside = await write.execute('repair', { path: 'report.md', content: 'observed data' });
    assert.equal(inside.content.length, 1);
    assert.deepEqual(
      (await workspaceFiles(path)).map((f) => f.relativePath),
      ['report.md'],
    );
    assert.equal(await readFile(join(root, 'report.md'), 'utf8'), 'observed data');
  }));

test('write location checks resolve symlink escapes and keep concurrent write observations separate', () =>
  workspace(async (root) => {
    const path = join(root, 'deliverables');
    const outside = join(root, 'deliverables-other');
    await mkdir(path);
    await mkdir(outside);
    await symlink(outside, join(path, 'link'), 'dir');
    const write = researchTools(path, 2000).find((t) => t.name === 'write');
    const [escaped, normal] = await Promise.all([
      write.execute('escaped', { path: 'link/report.md', content: 'external' }),
      write.execute('normal', { path: 'nested/report.md', content: 'local' }),
    ]);
    assert.match(escaped.content.at(-1).text, /write succeeded outside workspace/);
    assert.equal(normal.content.length, 1);
    assert.equal(await readFile(join(outside, 'report.md'), 'utf8'), 'external');
    assert.deepEqual(
      (await workspaceFiles(path)).map((f) => f.relativePath),
      ['nested/report.md'],
    );
    const abort = new AbortController();
    abort.abort();
    await assert.rejects(
      write.execute('aborted', { path: '../aborted.md', content: 'no' }, abort.signal),
      /aborted/i,
    );
    assert(!(await readdir(root)).includes('aborted.md'));
  }));
