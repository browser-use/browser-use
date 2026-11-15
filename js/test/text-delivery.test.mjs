import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Type } from 'typebox';
import { scripted, call, text } from './run-helper.mjs';

test('a plain-text reply is the answer for a string schema, with no repair request', async () => {
  const { result, requests } = await scripted([call('javascript', { code: '1' }), text('Paris')]);
  assert.equal(result.status, 'completed');
  assert.equal(result.output, 'Paris');
  assert.equal(result.finishRepairs, 0);
  assert.equal(requests.length, 2);
});

test('a structured schema still gets the delivery repair', async () => {
  const schema = Type.Object({ city: Type.String() });
  const { result, requests } = await scripted(
    [text('Paris'), call('finish', { result: { city: 'Paris' } })],
    {
      schema,
    },
  );
  assert.equal(result.status, 'completed');
  assert.deepEqual(result.output, { city: 'Paris' });
  assert.equal(result.finishRepairs, 1);
  assert.equal(requests.length, 2);
});

test('a tool call written as text is never the answer; it gets the repair', async () => {
  const { result, requests } = await scripted([
    text('<tool_call>{"name": "finish", "arguments": {"result": "x"}}</tool_call>'),
    call('finish', { result: 'Paris' }),
  ]);
  assert.equal(result.output, 'Paris');
  assert.equal(result.finishRepairs, 1);
  assert.match(JSON.stringify(requests[1].messages.at(-1)), /wrote a tool call as text/);
});

test('validateResult can still refuse a text answer, which then gets the repair', async () => {
  const { result } = await scripted([text('maybe'), call('finish', { result: 'Paris' })], {
    config: { validateResult: async (value) => (value === 'maybe' ? 'Be specific.' : undefined) },
  });
  assert.equal(result.output, 'Paris');
  assert.equal(result.finishRepairs, 1);
});

test('after the repair turn, valid JSON text is accepted for a structured schema', async () => {
  const schema = Type.Object({ city: Type.String() });
  const { result } = await scripted([text('thinking'), text('{"city":"Paris"}')], { schema });
  assert.equal(result.status, 'completed');
  assert.deepEqual(result.output, { city: 'Paris' });
});

test('a text answer on the last request is delivered with a warning, not dropped', async () => {
  const { result } = await scripted(
    [call('javascript', { code: '1' }), text('Summary in [the report](report.md).')],
    { options: { maxSteps: 2 } },
  );
  assert.equal(result.status, 'completed');
  assert.equal(result.output, 'Summary in [the report](report.md).');
  assert.match(result.warnings.join('\n'), /linked files do not exist/);
});

test('JSON text on the delivery-only turn is accepted for a structured schema', async () => {
  const schema = Type.Object({ city: Type.String() });
  const { result } = await scripted([call('javascript', { code: '1' }), text('{"city":"Paris"}')], {
    schema,
    options: { maxSteps: 2 },
  });
  assert.equal(result.status, 'completed');
  assert.deepEqual(result.output, { city: 'Paris' });
});
