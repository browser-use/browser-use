import test from 'node:test';
import assert from 'node:assert/strict';
import { imageDimensions, imageMimeType, palettePng, prepareModelImages } from '../dist/images.js';

const gif = Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7', 'base64');
const palette = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAMAAABFaP0WAAAABlBMVEX/AAAAAP9sof2OAAAADElEQVR4nGNgYARCAAAMAAMrY8tQAAAAAElFTkSuQmCC',
  'base64',
);
const image = (bytes, mimeType) => ({ type: 'image', mimeType, data: bytes.toString('base64') });

test('GIF and palette PNG previews are re-encoded as plain PNG (xAI rejects them)', async () => {
  assert.equal(palettePng(palette), true);
  const { images, notes } = await prepareModelImages([
    image(gif, 'image/gif'),
    image(palette, 'image/png'),
  ]);
  assert.deepEqual(notes, []);
  assert.equal(images.length, 2);
  for (const [i, original] of [gif, palette].entries()) {
    const bytes = Buffer.from(images[i].data, 'base64');
    assert.equal(images[i].mimeType, 'image/png');
    assert.equal(imageMimeType(bytes), 'image/png');
    assert.equal(palettePng(bytes), false);
    assert.deepEqual(imageDimensions(bytes), imageDimensions(original));
  }
});

test('a failed conversion omits the preview with a note instead of poisoning the request', async () => {
  const { images, notes } = await prepareModelImages(
    [image(gif, 'image/gif')],
    undefined,
    async () => null,
  );
  assert.equal(images.length, 0);
  assert.match(notes[0], /could not be converted from GIF or palette PNG/);
});

test('previews are capped at 2048 px per side, as in Python', async () => {
  const tall = Buffer.from(palette);
  // A truecolour PNG header claiming 1000x4000: only the resize callback sees it.
  tall[25] = 2;
  tall.writeUInt32BE(1000, 16);
  tall.writeUInt32BE(4000, 20);
  let asked;
  await prepareModelImages([image(tall, 'image/png')], async (_bytes, _mime) => {
    asked = true;
    return null;
  });
  assert.equal(asked, true);
  const fits = Buffer.from(tall);
  fits.writeUInt32BE(2048, 20);
  const kept = await prepareModelImages([image(fits, 'image/png')], async () => {
    throw new Error('2048 px must not be resized');
  });
  assert.equal(kept.images.length, 1);
});
