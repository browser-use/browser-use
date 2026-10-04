import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BrowserUse } from '../dist/index.js';

const hit = (n) => `Title: Hit ${n}\nURL: https://example.com/${n}\nHighlights:\nexcerpt ${n}`;
let agent, server, workspace;
const requests = [];
before(async () => {
  server = createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => (body += chunk));
    req.on('end', () => {
      const { query } = JSON.parse(body);
      requests.push({ authorization: req.headers.authorization, body: JSON.parse(body) });
      res.setHeader('content-type', 'application/json');
      if (query === 'over budget') {
        res.writeHead(402);
        res.end('{"detail":"run is out of budget"}');
      } else if (query === 'nothing') {
        res.end(JSON.stringify({ query, count: 0, results: '' }));
      } else {
        res.end(JSON.stringify({ query, count: 2, results: `${hit(1)}\n\n---\n\n${hit(2)}` }));
      }
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  workspace = await mkdtemp(join(tmpdir(), 'bu-search-test-'));
  agent = await BrowserUse.create({
    model: 'openai/gpt-5.4',
    browser: process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {},
    workspace,
    webSearch: {
      url: `http://127.0.0.1:${server.address().port}/api/v4/search`,
      token: 'run-token',
    },
  });
});
after(async () => {
  await agent?.close();
  await new Promise((resolve) => server?.close(resolve));
  if (workspace) await rm(workspace, { recursive: true, force: true });
});

test('search() posts to the configured endpoint and returns hits as an array, [] when empty', async () => {
  const twice = await agent.execute(
    "const first = await search('orbital chargers', {num_results: 2}); const second = await search('orbital chargers'); console.log(JSON.stringify([first, second]))",
  );
  const [first, second] = JSON.parse(twice.text);
  assert.deepEqual(first, { query: 'orbital chargers', count: 2, results: [hit(1), hit(2)] });
  assert.deepEqual(second.results, first.results);
  assert.deepEqual(requests[0], {
    authorization: 'Bearer run-token',
    body: { query: 'orbital chargers', num_results: 2 },
  });
  assert.deepEqual(requests[1].body, { query: 'orbital chargers' });
  const empty = await agent.execute("console.log(JSON.stringify(await search('nothing')))");
  assert.deepEqual(JSON.parse(empty.text), { query: 'nothing', count: 0, results: [] });
  await assert.rejects(agent.execute("await search('over budget')"), /HTTP 402.*out of budget/);
});
