import { spawn } from 'node:child_process';
import { access, mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

export type BrowserOptions =
  | { cdpUrl: string; headless?: never; channel?: never; executablePath?: never }
  | { cdpUrl?: never; headless?: boolean; channel?: 'chrome' | 'msedge'; executablePath?: string };

async function executable(options: Exclude<BrowserOptions, { cdpUrl: string }>) {
  if (options.executablePath) {
    await access(options.executablePath);
    return options.executablePath;
  }
  const candidates =
    process.platform === 'darwin'
      ? [
          options.channel === 'msedge'
            ? '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
            : '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
          '/Applications/Chromium.app/Contents/MacOS/Chromium',
        ]
      : process.platform === 'win32'
        ? [
            join(
              process.env.PROGRAMFILES ?? 'C:\\Program Files',
              options.channel === 'msedge'
                ? 'Microsoft/Edge/Application/msedge.exe'
                : 'Google/Chrome/Application/chrome.exe',
            ),
          ]
        : options.channel === 'msedge'
          ? ['/usr/bin/microsoft-edge']
          : ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'];
  for (const path of candidates) {
    try {
      await access(path);
      return path;
    } catch {}
  }
  throw new Error(
    'Chrome not found. Install Chrome or set browser.executablePath / browser.cdpUrl.',
  );
}

/** Local Chrome has an isolated temporary profile; external Chrome always belongs to the caller. */
export async function openBrowser(options: BrowserOptions = {}) {
  if (options.cdpUrl) {
    if (['headless', 'channel', 'executablePath'].some((key) => key in options))
      throw new Error('cdpUrl cannot be combined with local browser options.');
    if (!['http:', 'https:', 'ws:', 'wss:'].includes(new URL(options.cdpUrl).protocol))
      throw new Error('cdpUrl must be an HTTP(S) or WebSocket endpoint.');
    return { endpoint: options.cdpUrl, close: async () => {} };
  }
  const path = await executable(options as Exclude<BrowserOptions, { cdpUrl: string }>);
  const profile = await mkdtemp(join(tmpdir(), 'browser-use-'));
  const child = spawn(
    path,
    [
      `--user-data-dir=${profile}`,
      '--remote-debugging-port=0',
      '--remote-debugging-address=127.0.0.1',
      '--no-first-run',
      '--no-default-browser-check',
      '--window-size=1440,900',
      ...(options.headless === false ? [] : ['--headless=new']),
      'about:blank',
    ],
    { stdio: 'ignore' },
  );
  let launchError: Error | undefined;
  child.on('error', (error) => {
    launchError = error;
  });
  let closing: Promise<void> | undefined;
  const close = () =>
    (closing ??= (async () => {
      if (child.exitCode === null && child.signalCode === null && child.pid) {
        const exited = new Promise<void>((resolve) => child.once('exit', () => resolve()));
        child.kill('SIGTERM');
        const timer = setTimeout(() => child.kill('SIGKILL'), 2000);
        await exited;
        clearTimeout(timer);
      }
      await rm(profile, { recursive: true, force: true });
    })());
  try {
    const deadline = Date.now() + 15_000;
    while (Date.now() < deadline) {
      if (launchError) throw launchError;
      if (child.exitCode !== null || child.signalCode !== null)
        throw new Error('Chrome exited before exposing CDP.');
      try {
        const [port, path] = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8'))
          .trim()
          .split('\n');
        if (port && path) return { endpoint: `ws://127.0.0.1:${port}${path}`, close };
      } catch {}
      await delay(50);
    }
    throw new Error('Chrome did not expose CDP within 15000 ms.');
  } catch (error) {
    await close();
    throw error;
  }
}
