import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { Type } from 'typebox';
import { fauxAssistantMessage, fauxToolCall, getCurrentTools } from '@earendil-works/pi-ai';
import { scripted, call, text } from './run-helper.mjs';

const response = (...calls) =>
  fauxAssistantMessage(
    calls.map(([name, args]) => fauxToolCall(name, args)),
    { stopReason: 'toolUse' },
  );
const lastResults = (request) =>
  request.messages.filter((m) => m.role === 'toolResult').map((m) => m.content[0].text);

test('a delivery followed by another call in the same response is refused once', async () => {
  const { result, requests } = await scripted([
    response(['finish', { result: 'stub', success: false }], ['javascript', { code: 'more()' }]),
    response(['finish', { result: 'stub again' }], ['javascript', { code: 'more()' }]),
  ]);
  assert.match(
    lastResults(requests[1]).join('\n'),
    /Not delivered: javascript came in the same response/,
  );
  // Refused in one response per run: the second split delivery is taken.
  assert.equal(result.status, 'completed');
  assert.equal(result.output, 'stub again');
});

test('two deliveries in one response are both refused; a later lone delivery is taken', async () => {
  const { result, requests } = await scripted([
    response(['finish', { result: 'first' }], ['finish_from_js', { expression: '"second"' }]),
    call('finish', { result: 'final' }),
  ]);
  const refused = lastResults(requests[1]);
  assert.equal(refused.length, 2);
  assert.ok(refused.every((text) => /^Not delivered:/.test(text)));
  assert.equal(result.output, 'final');
});

test('a placeholder result gets one repair; a second placeholder is accepted', async () => {
  const { result, requests } = await scripted([
    call('finish', { result: '...' }),
    call('finish', { result: '…' }),
  ]);
  assert.match(lastResults(requests[1]).at(-1), /is a placeholder, not the answer/);
  assert.equal(result.status, 'completed');
  assert.equal(result.output, '…');
});

test('an empty structured result is a placeholder', async () => {
  const schema = Type.Object({ authors: Type.Array(Type.String()) });
  const { result, requests } = await scripted(
    [call('finish', { result: { authors: [] } }), call('finish', { result: { authors: ['Ada'] } })],
    { schema },
  );
  assert.match(lastResults(requests[1]).at(-1), /placeholder/);
  assert.deepEqual(result.output, { authors: ['Ada'] });
});

test('a link to a file missing from the workspace gets one repair; existing files and URLs pass', async () => {
  const { result, requests } = await scripted(
    [
      call('finish', { result: 'See [report](report.md) and `missing.csv`.' }),
      call('finish', {
        result: 'See [report](report.md), `downloads.csv` and [site](https://x.test).',
      }),
    ],
    {
      setup: async (workspace) => {
        await writeFile(join(workspace, 'report.md'), '#');
        const { mkdir } = await import('node:fs/promises');
        await mkdir(join(workspace, 'downloads'));
        await writeFile(join(workspace, 'downloads', 'downloads.csv'), 'a');
      },
    },
  );
  assert.match(lastResults(requests[1]).at(-1), /do not exist in the workspace: missing\.csv\./);
  assert.equal(result.status, 'completed');
  assert.match(result.output, /downloads\.csv/);
});

test('on the last request a flawed answer is delivered with a warning, not refused', async () => {
  const { result } = await scripted([call('finish', { result: '...' })], {
    options: { maxSteps: 1 },
  });
  assert.equal(result.status, 'completed');
  assert.equal(result.output, '...');
  assert.match(result.warnings.join('\n'), /Delivered as it is on the last request/);
});

test('finish takes an optional success verdict', async () => {
  const { result, requests } = await scripted([
    call('finish', { result: 'blocked by login', success: false }),
  ]);
  assert.equal(result.success, false);
  const tool = getCurrentTools(requests[0].messages).find((t) => t.name === 'finish');
  assert.ok(tool.parameters.properties.success);
  assert.ok(!tool.parameters.required.includes('success'));
  const plain = await scripted([call('finish', { result: 'Paris' })]);
  assert.equal(plain.result.success, undefined);
});

test('a text reply on the last step is the answer only when it has no delivery problem', async () => {
  const empty = await scripted([text('')], { options: { maxSteps: 1 } });
  assert.equal(empty.result.status, 'max_steps');
  const answer = await scripted([text('Paris')], { options: { maxSteps: 1 } });
  assert.equal(answer.result.status, 'completed');
  assert.equal(answer.result.output, 'Paris');
});
