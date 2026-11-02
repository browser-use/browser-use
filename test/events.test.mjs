import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventStream } from '../dist/events.js';

test('filtered events never count against the stream bounds', async () => {
  const stream = new EventStream(
    () => {},
    256,
    (event) => event.type !== 'agent_event' || event.event.type !== 'agent_end',
  );
  const huge = { type: 'agent_event', event: { type: 'agent_end', messages: ['x'.repeat(9e6)] } };
  stream.push({ ...huge, sequence: 1, timestamp: 0, runId: 'r' });
  stream.push({ type: 'run_end', result: {}, sequence: 2, timestamp: 0, runId: 'r' });
  stream.end();
  const seen = [];
  for await (const event of stream) seen.push(event.type);
  assert.deepEqual(seen, ['run_end']);
});
