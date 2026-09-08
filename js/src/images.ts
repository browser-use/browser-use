import type { ResizedImage } from '@earendil-works/pi-coding-agent';
import type { Image } from './protocol.js';

/** Read the dimensions of the three formats emitted by CDP, without decoding pixels. */
export function imageDimensions(bytes: Buffer): { width: number; height: number } | undefined {
  let width = 0;
  let height = 0;
  if (bytes.length >= 24 && bytes.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex'))) {
    if (bytes.toString('ascii', 12, 16) !== 'IHDR') return;
    width = bytes.readUInt32BE(16);
    height = bytes.readUInt32BE(20);
  } else if (bytes.length >= 4 && bytes.readUInt16BE(0) === 0xffd8) {
    let offset = 2;
    while (offset + 1 < bytes.length && bytes[offset] === 0xff) {
      while (bytes[offset] === 0xff) offset++;
      const marker = bytes[offset++];
      if (marker === undefined || marker === 0xd9 || marker === 0xda) return;
      if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd8)) continue;
      if (offset + 2 > bytes.length) return;
      const length = bytes.readUInt16BE(offset);
      if (length < 2 || offset + length > bytes.length) return;
      if (
        [0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(
          marker,
        )
      ) {
        if (length < 8) return;
        height = bytes.readUInt16BE(offset + 3);
        width = bytes.readUInt16BE(offset + 5);
        break;
      }
      offset += length;
    }
  } else if (
    bytes.length >= 30 &&
    bytes.toString('ascii', 0, 4) === 'RIFF' &&
    bytes.toString('ascii', 8, 12) === 'WEBP'
  ) {
    const kind = bytes.toString('ascii', 12, 16);
    if (kind === 'VP8X') {
      width = bytes.readUIntLE(24, 3) + 1;
      height = bytes.readUIntLE(27, 3) + 1;
    } else if (kind === 'VP8 ' && bytes.readUIntBE(23, 3) === 0x9d012a) {
      width = bytes.readUInt16LE(26) & 0x3fff;
      height = bytes.readUInt16LE(28) & 0x3fff;
    } else if (kind === 'VP8L' && bytes[20] === 0x2f) {
      const packed = bytes.readUInt32LE(21);
      width = (packed & 0x3fff) + 1;
      height = ((packed >>> 14) & 0x3fff) + 1;
    }
  }
  return width > 0 && height > 0 ? { width, height } : undefined;
}

const maxDimension = 2000;
const maxBase64Bytes = 4.5 * 1024 * 1024;
type Resize = (bytes: Buffer, mimeType: string) => Promise<ResizedImage | null>;
const resize: Resize = async (bytes, mimeType) => {
  // Normal viewport captures never load the image backend or start a resize worker.
  const { resizeImage } = await import('@earendil-works/pi-coding-agent');
  return resizeImage(bytes, mimeType, {
    maxWidth: maxDimension,
    maxHeight: maxDimension,
    maxBytes: maxBase64Bytes,
  });
};

/** Only the model preview changes. Original CDP bytes and saved artifacts stay untouched. */
export async function prepareModelImages(captures: Image[], resizeImage: Resize = resize) {
  const images: Image[] = [];
  const notes: string[] = [];
  for (const [index, capture] of captures.entries()) {
    const bytes = Buffer.from(capture.data, 'base64');
    const dimensions = imageDimensions(bytes);
    if (!dimensions || dimensions.width * dimensions.height > 50_000_000) {
      notes.push(
        `[Screenshot ${index + 1} omitted from model vision: unsupported dimensions or over 50 megapixels. Capture a viewport or a bounded crop. Original CDP bytes are unchanged.]`,
      );
      continue;
    }
    if (
      dimensions.width <= maxDimension &&
      dimensions.height <= maxDimension &&
      capture.data.length < maxBase64Bytes
    ) {
      images.push(capture);
      continue;
    }
    try {
      const resized = await resizeImage(bytes, capture.mimeType);
      const verified = resized && imageDimensions(Buffer.from(resized.data, 'base64'));
      if (
        !resized ||
        !verified ||
        verified.width > maxDimension ||
        verified.height > maxDimension ||
        resized.data.length >= maxBase64Bytes
      ) {
        throw new Error('Preview exceeds inline limits');
      }
      images.push({ type: 'image', data: resized.data, mimeType: resized.mimeType });
      notes.push(
        `[Screenshot ${index + 1}: original ${dimensions.width}x${dimensions.height}, model preview ${verified.width}x${verified.height}. Original CDP bytes are unchanged. A full-page preview may have unreadable text; capture a viewport or bounded crop for detail. Do not assume preview coordinates are viewport coordinates.]`,
      );
    } catch {
      // Do not poison the next provider request or fail/replay an otherwise completed browser cell.
      notes.push(
        `[Screenshot ${index + 1} omitted from model vision: image resizing failed. Capture a viewport or bounded crop. Original CDP bytes are unchanged.]`,
      );
    }
  }
  return { images, notes };
}
