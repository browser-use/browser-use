import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Browser, BrowserUse } from '../dist/index.js';
import { workerExecutable } from '../dist/runtime.js';

const node = await workerExecutable();

test('worker runtime selection ignores host preload flags and keeps keys out of cells', async () => {
  const previous = { ...process.env };
  let agent;
  try {
    process.env.BROWSER_USE_NODE = node;
    process.env.NODE_OPTIONS = '--require=/must-not-be-loaded.cjs';
    process.env.BU_FAKE_PROVIDER_SECRET = 'must-not-leak';
    assert.equal(await workerExecutable(), node);
    agent = await BrowserUse.create({ model: 'openai/gpt-5.4', telemetry: false });
    assert.equal(
      (
        await agent.execute(
          'JSON.stringify({bun:!!process.versions.bun,key:process.env.BU_FAKE_PROVIDER_SECRET,preload:process.env.NODE_OPTIONS})',
        )
      ).text,
      `'${JSON.stringify({ bun: false })}'`,
    );
  } finally {
    for (const key of ['BROWSER_USE_NODE', 'NODE_OPTIONS', 'BU_FAKE_PROVIDER_SECRET']) {
      if (previous[key] === undefined) delete process.env[key];
      else process.env[key] = previous[key];
    }
    await agent?.close();
    if (agent) await rm(agent.workspace, { recursive: true, force: true });
  }
});

test('missing worker runtime fails before creating a workspace or cloud browser', async () => {
  const root = await mkdtemp(join(tmpdir(), 'browser-use-runtime-'));
  const previous = process.env.BROWSER_USE_NODE;
  const fetch = globalThis.fetch;
  let requests = 0;
  try {
    process.env.BROWSER_USE_NODE = join(root, 'missing-node');
    globalThis.fetch = async () => {
      requests++;
      throw new Error('must not provision');
    };
    await assert.rejects(
      BrowserUse.create({
        model: 'openai/gpt-5.4',
        workspace: join(root, 'work'),
        browser: Browser.cloud({ apiKey: 'fixture-only' }),
        telemetry: false,
      }),
      /Node.js 22.19\+.*BROWSER_USE_NODE/,
    );
    assert.equal(requests, 0);
    await assert.rejects(stat(join(root, 'work')), { code: 'ENOENT' });
  } finally {
    globalThis.fetch = fetch;
    if (previous === undefined) delete process.env.BROWSER_USE_NODE;
    else process.env.BROWSER_USE_NODE = previous;
    await rm(root, { recursive: true, force: true });
  }
});

test(
  'runtime probe rejects old Node, Bun masquerading as Node, and malformed output',
  { skip: process.platform === 'win32' },
  async () => {
    const root = await mkdtemp(join(tmpdir(), 'browser-use-runtime-'));
    const previous = process.env.BROWSER_USE_NODE;
    try {
      const probe = join(root, 'probe');
      process.env.BROWSER_USE_NODE = probe;
      for (const output of [
        JSON.stringify({ path: node, node: '22.18.0', bun: false }),
        JSON.stringify({ path: node, node: '24.0.0', bun: true }),
        'invalid JSON',
      ]) {
        await writeFile(probe, `#!${node}\nconsole.log(${JSON.stringify(output)});\n`, {
          mode: 0o700,
        });
        await assert.rejects(workerExecutable(), /Node.js 22.19\+/);
      }
    } finally {
      if (previous === undefined) delete process.env.BROWSER_USE_NODE;
      else process.env.BROWSER_USE_NODE = previous;
      await rm(root, { recursive: true, force: true });
    }
  },
);
