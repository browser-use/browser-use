import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Console } from 'node:console';
import { Writable } from 'node:stream';
import { CELL_INSPECT_OPTIONS } from '../dist/protocol.js';

test('cell console prints nested data instead of [Object] (step-gap bu2-006)', () => {
  let text = '';
  const sink = new Writable({
    write(chunk, _encoding, callback) {
      text += chunk.toString();
      callback();
    },
  });
  const cellConsole = new Console({
    stdout: sink,
    stderr: sink,
    inspectOptions: CELL_INSPECT_OPTIONS,
  });
  const crumbs = { itemListElement: [{ item: { name: 'Shoes', offers: { price: 49 } } }] };
  cellConsole.log({ crumbs });
  cellConsole.log(Array.from({ length: 300 }, (_, i) => i));
  assert.match(text, /price: 49/);
  assert.doesNotMatch(text, /\[Object\]|more items/);
});
