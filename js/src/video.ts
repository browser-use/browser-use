import { spawn } from 'node:child_process';
import {
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
  copyFile,
  lstat,
  constants,
} from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { CDP } from './cdp.js';
import { Page } from './page.js';
import { openBrowser } from './browser.js';
import type { RecordingManifest } from './recording.js';

export interface VideoOptions {
  format?: 'mp4' | 'gif';
  output: string;
  title?: string;
  maxFrames?: number;
  /** Opaque rectangles in original screenshot pixels, applied to every exported frame. Raw capture is retained. */
  redact?: { x: number; y: number; width: number; height: number }[];
  ffmpegPath?: string;
  executablePath?: string;
  signal?: AbortSignal;
}

function encode(args: string[], executable: string, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const child = spawn(executable, args, {
      stdio: ['ignore', 'ignore', 'pipe'],
      ...(signal ? { signal } : {}),
    });
    let stderr = '';
    child.stderr.on('data', (chunk: Buffer) => {
      stderr = (stderr + chunk).slice(-4000);
    });
    const timer = setTimeout(() => child.kill('SIGKILL'), 120000);
    child.on('error', (error) => {
      clearTimeout(timer);
      reject(
        new Error(`Video encoder unavailable: ${error.message}. Install ffmpeg or set ffmpegPath.`),
      );
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      code === 0 ? resolve() : reject(new Error(`Video encoding failed (${code}): ${stderr}`));
    });
  });
}

const TEMPLATE = `<!doctype html><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#101318;color:#eef2f6;font:24px system-ui;width:1440px;height:1060px;overflow:hidden}
header{height:100px;padding:22px 34px;display:flex;align-items:center;gap:22px}.mark{background:#d8ff62;color:#111;border-radius:12px;padding:8px 12px;font-weight:900;font-size:28px}h1{font-size:24px;margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sub{font-size:14px;color:#9da7b7;margin-top:5px}
#stage{position:relative;margin:0 24px;width:1392px;height:870px;background:#20252c;border-radius:12px;overflow:hidden}#shot{width:100%;height:100%;object-fit:contain}#cursor{position:absolute;width:30px;height:40px;filter:drop-shadow(0 2px 4px #0009);transform:translate(-3px,-2px)}#ring{position:absolute;width:48px;height:48px;border:4px solid #d8ff62;border-radius:50%;transform:translate(-24px,-24px)}.mask{position:absolute;background:#101318}
footer{height:90px;display:flex;align-items:center;justify-content:space-between;padding:0 34px}#label{font-size:20px}#count{color:#9da7b7;font-size:16px}#progress{position:absolute;bottom:0;height:4px;background:#d8ff62;left:0}
</style><header><span class="mark">bu</span><div><h1 id="title"></h1><div class="sub">Actual browser recording · edited highlights</div></div></header><div id="stage"><img id="shot"><div id="masks"></div><div id="ring"></div><svg id="cursor" viewBox="0 0 30 40"><path d="M3 2L3 32L11 24L18 38L24 35L17 21L29 21Z" fill="#fff" stroke="#101318" stroke-width="2"/></svg></div><footer><div id="label"></div><div id="count"></div></footer><div id="progress"></div>`;

/** Render a shareable cut from captured frames. Export creates a new file; source browser is never touched. */
export async function exportRecording(
  recordingPath: string,
  options: VideoOptions,
): Promise<string> {
  options.signal?.throwIfAborted();
  await lstat(resolve(options.output)).then(
    () => {
      throw new Error('EEXIST: export output already exists.');
    },
    (error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error;
    },
  );
  const manifest = JSON.parse(await readFile(recordingPath, 'utf8')) as RecordingManifest;
  if (manifest.version !== 1 || !Array.isArray(manifest.frames) || !manifest.frames.length)
    throw new Error('Recording has no captured frames.');
  if (manifest.frames.length > 10001 || manifest.frames.some((f) => !/^\d{5}\.jpg$/.test(f.file)))
    throw new Error('Invalid recording frame manifest.');
  const count = options.maxFrames ?? 36;
  if (!Number.isSafeInteger(count) || count < 2 || count > 120)
    throw new Error('maxFrames must be between 2 and 120.');
  for (const box of options.redact ?? [])
    if (
      ![box.x, box.y, box.width, box.height].every(Number.isFinite) ||
      box.x < 0 ||
      box.y < 0 ||
      box.width <= 0 ||
      box.height <= 0
    )
      throw new Error('Invalid redaction rectangle.');
  const format = options.format ?? 'mp4';
  if (!['mp4', 'gif'].includes(format)) throw new Error('format must be mp4 or gif.');
  const frames = manifest.frames.filter(
    (_frame, i, all) =>
      all.length <= count ||
      new Set(
        Array.from({ length: count }, (_, j) => Math.round((j * (all.length - 1)) / (count - 1))),
      ).has(i),
  );
  const temp = await mkdtemp(join(tmpdir(), 'bu-video-'));
  let browser: Awaited<ReturnType<typeof openBrowser>> | undefined;
  let cdp: CDP | undefined;
  try {
    browser = await openBrowser(
      options.executablePath ? { executablePath: options.executablePath } : {},
    );
    cdp = await CDP.connect(browser.endpoint);
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const page = await Page.attach(cdp, targetId);
    await page.cdp('Emulation.setDeviceMetricsOverride', {
      width: 1440,
      height: 1060,
      deviceScaleFactor: 1,
      mobile: false,
    });
    const { frameTree } = await page.cdp('Page.getFrameTree');
    await page.cdp('Page.setDocumentContent', { frameId: frameTree.frame.id, html: TEMPLATE });
    let n = 0;
    let previousCursor = { x: 0, y: 0 };
    for (const [index, frame] of frames.entries()) {
      options.signal?.throwIfAborted();
      const bytes = await readFile(join(dirname(recordingPath), frame.file));
      if (bytes.length > 16000000) throw new Error('Recording frame exceeds 16 MB.');
      const image = `data:image/jpeg;base64,${bytes.toString('base64')}`;
      const cursor = frame.cursor;
      // Intermediate positions animate the recorded pointer; footage is never reenacted.
      for (let tween = 0; tween < 3; tween++) {
        const p = (tween + 1) / 3;
        await page.evaluate(
          async (data) => {
            const shot = document.getElementById('shot') as HTMLImageElement;
            shot.src = data.image;
            await shot.decode();
            document.getElementById('title')!.textContent = data.title;
            document.getElementById('label')!.textContent = data.label;
            document.getElementById('count')!.textContent = data.count;
            document.getElementById('progress')!.style.width = `${data.progress * 100}%`;
            const scale = Math.min(1392 / shot.naturalWidth, 870 / shot.naturalHeight);
            const ox = (1392 - shot.naturalWidth * scale) / 2,
              oy = (870 - shot.naturalHeight * scale) / 2;
            for (const id of ['cursor', 'ring']) {
              const el = document.getElementById(id)!;
              el.style.display =
                data.cursor && (id !== 'ring' || data.cursor.click) ? 'block' : 'none';
              el.style.left = `${ox + (data.cursor?.x ?? 0) * scale}px`;
              el.style.top = `${oy + (data.cursor?.y ?? 0) * scale}px`;
            }
            const masks = document.getElementById('masks')!;
            masks.replaceChildren();
            for (const box of data.redact) {
              const mask = document.createElement('div');
              mask.className = 'mask';
              Object.assign(mask.style, {
                left: `${ox + box.x * scale}px`,
                top: `${oy + box.y * scale}px`,
                width: `${box.width * scale}px`,
                height: `${box.height * scale}px`,
              });
              masks.append(mask);
            }
          },
          {
            image,
            title: (options.title ?? manifest.task).slice(0, 180),
            label: frame.label.slice(0, 100),
            count: `${index + 1} / ${frames.length} · ${manifest.status}`,
            progress: (index + 1) / frames.length,
            cursor: cursor
              ? {
                  x: previousCursor.x + (cursor.x - previousCursor.x) * p,
                  y: previousCursor.y + (cursor.y - previousCursor.y) * p,
                  click: cursor.click && tween === 2,
                }
              : null,
            redact: options.redact ?? [],
          },
        );
        await writeFile(
          join(temp, `${String(n++).padStart(5, '0')}.jpg`),
          await page.screenshot({ quality: 90 }),
        );
      }
      if (cursor) previousCursor = cursor;
    }
    cdp.close();
    cdp = undefined;
    await browser.close();
    browser = undefined;
    const encoded = join(temp, `video.${format}`);
    const filter =
      format === 'gif'
        ? 'fps=6,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse'
        : 'pad=ceil(iw/2)*2:ceil(ih/2)*2,tpad=stop_mode=clone:stop_duration=1';
    await encode(
      [
        '-hide_banner',
        '-loglevel',
        'error',
        '-n',
        '-framerate',
        '6',
        '-i',
        join(temp, '%05d.jpg'),
        '-filter_complex',
        filter,
        ...(format === 'mp4'
          ? ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
          : ['-loop', '0']),
        encoded,
      ],
      options.ffmpegPath ?? 'ffmpeg',
      options.signal,
    );
    const output = resolve(options.output);
    await mkdir(dirname(output), { recursive: true });
    await copyFile(encoded, output, constants.COPYFILE_EXCL);
    return output;
  } finally {
    cdp?.close();
    await browser?.close();
    await rm(temp, { recursive: true, force: true });
  }
}
