import test from 'node:test';
import assert from 'node:assert/strict';
import { imageDimensions, prepareModelImages } from '../dist/images.js';

const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZWQAAAAASUVORK5CYII=',
  'base64',
);
const image = (bytes) => ({ type: 'image', mimeType: 'image/png', data: bytes.toString('base64') });

test('ordinary captures preserve bytes and do not invoke image processing', async () => {
  let calls = 0;
  const original = image(png);
  const result = await prepareModelImages([original], async () => {
    calls++;
    throw new Error('unexpected');
  });
  assert.equal(calls, 0);
  assert.strictEqual(result.images[0], original);
  assert.deepEqual(result.notes, []);
  assert.deepEqual(imageDimensions(png), { width: 1, height: 1 });
});

test('bad headers and excessive decoded dimensions are omitted without invoking a decoder', async () => {
  const enormous = Buffer.from(png);
  enormous.writeUInt32BE(100_000, 16);
  enormous.writeUInt32BE(100_000, 20);
  const invalid = [
    Buffer.alloc(0),
    Buffer.from([255, 216, 255, 224, 0, 1]),
    Buffer.from('RIFFbroken'),
    enormous,
  ];
  const result = await prepareModelImages(invalid.map(image), async () => {
    assert.fail('decoder must not run');
  });
  assert.equal(result.images.length, 0);
  assert.equal(result.notes.length, invalid.length);
  assert.ok(result.notes.every((note) => /omitted.*Capture a viewport/.test(note)));
});

test('resize failures cannot forward an oversized image, and later valid captures survive', async () => {
  const large = Buffer.from(png);
  large.writeUInt32BE(22_000, 20);
  for (const fail of [
    async () => null,
    async () => {
      throw new Error('unavailable backend');
    },
    async () => ({ data: large.toString('base64'), mimeType: 'image/png' }),
  ]) {
    const original = image(large);
    const result = await prepareModelImages([original, image(png)], fail);
    assert.equal(result.images.length, 1);
    assert.equal(result.images[0].data, png.toString('base64'));
    assert.match(result.notes[0], /omitted.*resizing failed/);
    assert.equal(original.data, large.toString('base64'));
  }
});
