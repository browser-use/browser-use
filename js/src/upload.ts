import { randomBytes } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import { basename, extname, resolve } from 'node:path';
import type { Page } from './page.js';

/** Bytes per page call. One CDP message carries base64 of this; ~100 MB in one message dropped the connection. */
export const UPLOAD_PART = 4_000_000;

const TYPES: Record<string, string> = {
  '.pdf': 'application/pdf',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain',
  '.csv': 'text/csv',
  '.json': 'application/json',
  '.html': 'text/html',
  '.xml': 'application/xml',
  '.zip': 'application/zip',
  '.doc': 'application/msword',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.xls': 'application/vnd.ms-excel',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  '.mp3': 'audio/mpeg',
  '.mp4': 'video/mp4',
};

/** JS for the first match of selector in the page, its open shadow roots and same-origin frames (Python find). */
const find = (selector: string) => `(() => {
  const q = (r) => { let el = r.querySelector(${JSON.stringify(selector)});
    for (const e of r.querySelectorAll('*')) el ||= (e.shadowRoot && q(e.shadowRoot)) || (e.contentDocument && q(e.contentDocument));
    return el; };
  return q(document);
})()`;
const SIZES = 'function () { return Array.from(this.files || [], (f) => f.size) }';
const PUT = `function (key, i, n, b64) {
  const w = this.ownerDocument.defaultView;
  ((w[key] ||= [])[i] ||= [])[n] = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}`;
const SET = `function (key, meta) {
  if (this.type !== 'file') throw Error('not a file input');
  const w = this.ownerDocument.defaultView, parts = w[key] || [];
  delete w[key];
  const dt = new DataTransfer();
  meta.forEach(([name, type], i) => dt.items.add(new File(parts[i] || [], name, { type })));
  this.files = dt.files;
  this.dispatchEvent(new Event('input', { bubbles: true }));
  this.dispatchEvent(new Event('change', { bubbles: true }));
  return this.files.length;
}`;

/**
 * Python upload_file: set existing local file(s) on a file input; returns how many files it holds.
 * target: a backendNodeId or a CSS selector. A remote browser cannot read a local path (Browser Use Cloud rejects it,
 * another host's Chrome sets empty files), so there, and whenever the input does not then hold files of the local
 * sizes, the bytes go through the page in parts. Throws when the input ends up with no file.
 */
export async function uploadFile(
  page: Page,
  target: number | string,
  path: string | string[],
  remote: boolean,
): Promise<number> {
  const paths = await Promise.all(
    (Array.isArray(path) ? path : [path]).map(async (p) => {
      const full = resolve(String(p));
      const info = await stat(full).catch(() => undefined);
      if (!info?.isFile())
        throw new Error(`uploadFile: ${JSON.stringify(p)} is not a file (${full})`);
      return { full, size: info.size };
    }),
  );
  if (!paths.length) throw new Error('uploadFile: no path given.');
  let objectId: string | undefined;
  if (typeof target === 'number') {
    objectId = (await page.cdp('DOM.resolveNode', { backendNodeId: target })).object.objectId;
  } else {
    const { result } = await page.cdp('Runtime.evaluate', { expression: find(String(target)) });
    objectId = result.objectId;
    if (!objectId) throw new Error(`uploadFile: no element for ${JSON.stringify(target)}`);
  }
  if (!objectId) throw new Error(`uploadFile: no element for ${target}`);
  const call = async (functionDeclaration: string, ...args: unknown[]) => {
    const response = await page.cdp('Runtime.callFunctionOn', {
      objectId,
      functionDeclaration,
      arguments: args.map((value) => ({ value })),
      returnByValue: true,
    });
    if (response.exceptionDetails)
      throw new Error(
        `uploadFile: ${(response.exceptionDetails.exception?.description ?? response.exceptionDetails.text).split('\n')[0]}`,
      );
    return response.result.value as unknown;
  };
  if (!remote) {
    try {
      await page.cdp('DOM.setFileInputFiles', { objectId, files: paths.map((p) => p.full) });
      const sizes = (await call(SIZES)) as number[];
      if (JSON.stringify(sizes) === JSON.stringify(paths.map((p) => p.size))) return sizes.length;
    } catch {
      // Rejected or empty: a remote browser behind cdpUrl. Send the bytes instead.
    }
  }
  const key = `__buUpload${randomBytes(4).toString('hex')}`;
  try {
    for (const [i, p] of paths.entries()) {
      const data = await readFile(p.full);
      for (let n = 0, k = 0; k < data.length || n === 0; n++, k += UPLOAD_PART)
        await call(PUT, key, i, n, data.subarray(k, k + UPLOAD_PART).toString('base64'));
    }
    const held = (await call(
      SET,
      key,
      paths.map((p) => [
        basename(p.full),
        TYPES[extname(p.full).toLowerCase()] ?? 'application/octet-stream',
      ]),
    )) as number;
    if (!held) throw new Error('uploadFile: the input holds no file afterwards.');
    return held;
  } finally {
    await call('function (key) { delete this.ownerDocument.defaultView[key] }', key).catch(
      () => {},
    );
  }
}
