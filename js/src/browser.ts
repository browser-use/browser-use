import { spawn, execFile } from 'node:child_process';
import { access, mkdir, mkdtemp, open, readFile, realpath, rm, stat } from 'node:fs/promises';
import { tmpdir, homedir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

export interface LocalBrowserOptions {
  headless?: boolean;
  channel?: 'chrome' | 'msedge';
  executablePath?: string;
  profileDir?: string;
}
export interface CloudBrowserOptions {
  apiKey: string;
  profileId?: string;
  timeoutMinutes?: number;
  proxyCountryCode?: string;
}
export interface ChromeBrowserOptions {
  cdpUrl?: string;
  /** User-data root containing DevToolsActivePort, not its Default subdirectory. */
  profileDir?: string;
  targetId?: string;
  /** macOS only: accept Chrome’s exact remote-debugging sheet while connecting. */
  approveConnection?: boolean;
}
export type BrowserOptions =
  | ({ kind: 'cloud' } & CloudBrowserOptions)
  | ({ kind: 'chromium' } & LocalBrowserOptions)
  | ({ kind: 'chrome' } & ChromeBrowserOptions)
  | ({ kind?: never; cdpUrl: string; targetId?: string } & {
      [K in keyof LocalBrowserOptions]?: never;
    })
  | ({ kind?: never; cdpUrl?: never; targetId?: never } & LocalBrowserOptions);

/** Declarative browser choices. BrowserUse owns the resulting connection lifecycle. */
export const Browser = {
  cloud: (options: CloudBrowserOptions): BrowserOptions => ({ ...options, kind: 'cloud' }),
  chromium: (options: LocalBrowserOptions = {}): BrowserOptions => ({
    ...options,
    kind: 'chromium',
  }),
  chrome: (options: ChromeBrowserOptions = {}): BrowserOptions => ({ ...options, kind: 'chrome' }),
};

/** Same profile discovery convention as Browser Harness on macOS, Linux and Windows. */
export function chromeProfileDirs(
  platform = process.platform,
  home = homedir(),
  local = process.env.LOCALAPPDATA,
) {
  if (platform === 'darwin') return [join(home, 'Library/Application Support/Google/Chrome')];
  if (platform === 'win32')
    return [join(local || join(home, 'AppData/Local'), 'Google/Chrome/User Data')];
  return [join(home, '.config/google-chrome'), join(home, '.config/chromium')];
}
async function discoverChrome(options: ChromeBrowserOptions) {
  for (const profile of options.profileDir ? [options.profileDir] : chromeProfileDirs()) {
    try {
      const [port, path] = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8'))
        .trim()
        .split('\n');
      if (
        !port ||
        !/^\d+$/.test(port) ||
        +port < 1 ||
        +port > 65535 ||
        !path?.startsWith('/devtools/browser/')
      )
        continue;
      const response = await fetch(`http://127.0.0.1:${port}/json/version`, {
        signal: AbortSignal.timeout(1500),
      });
      // Chrome 147 can disable HTTP discovery for its default profile.
      if (response.status === 404) return `ws://127.0.0.1:${port}${path}`;
      if (!response.ok) continue;
      const info = (await response.json()) as { webSocketDebuggerUrl?: string };
      if (info.webSocketDebuggerUrl) return info.webSocketDebuggerUrl;
    } catch {}
  }
  throw new Error(
    'No running Chrome debugging endpoint found. Enable chrome://inspect/#remote-debugging and accept Chrome’s connection prompt, or pass Browser.chrome({ cdpUrl }). No browser was launched or profile copied.',
  );
}

async function openCloud(options: CloudBrowserOptions) {
  if (typeof options.apiKey !== 'string' || !options.apiKey.trim())
    throw new Error('Browser.cloud requires apiKey.');
  const timeout = options.timeoutMinutes ?? 30;
  if (!Number.isInteger(timeout) || timeout <= 0 || timeout > 240)
    throw new Error('timeoutMinutes must be an integer from 1 to 240.');
  const request = async (path: string, method: string, body: object) => {
    const response = await fetch(`https://api.browser-use.com/api/v3${path}`, {
      method,
      headers: { 'X-Browser-Use-API-Key': options.apiKey, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30_000),
      redirect: 'error',
    });
    if (!response.ok) throw new Error(`Browser Use Cloud ${method} failed (${response.status}).`);
    return response;
  };
  // Never retry provisioning: an ambiguous POST can already have created a billable browser.
  const data = (await (
    await request('/browsers', 'POST', {
      timeout,
      enableRecording: false,
      ...(options.profileId ? { profileId: options.profileId } : {}),
      ...(options.proxyCountryCode ? { proxyCountryCode: options.proxyCountryCode } : {}),
    })
  ).json()) as { id?: string; cdpUrl?: string; liveUrl?: string };
  if (typeof data.id !== 'string' || !data.id)
    throw new Error(
      'Cloud response missing browser id; check the Cloud dashboard for an orphaned browser.',
    );
  let closing: Promise<void> | undefined;
  const close = () =>
    (closing ??= request(`/browsers/${encodeURIComponent(data.id!)}`, 'PATCH', { action: 'stop' })
      .then(() => {})
      .catch((error) => {
        closing = undefined;
        throw error;
      }));
  try {
    if (
      typeof data.cdpUrl !== 'string' ||
      !['ws:', 'wss:', 'http:', 'https:'].includes(new URL(data.cdpUrl).protocol)
    )
      throw new Error('Cloud response missing valid cdpUrl.');
    return { endpoint: data.cdpUrl, close };
  } catch (error) {
    try {
      await close();
    } catch {
      throw new Error(
        `Invalid Cloud response and cleanup failed for browser ${data.id}; stop it in the Cloud dashboard.`,
      );
    }
    throw error;
  }
}

async function executable(options: LocalBrowserOptions) {
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
  if (options.kind !== undefined && !['cloud', 'chrome', 'chromium'].includes(options.kind))
    throw new Error('Unknown browser kind. Use Browser.cloud, Browser.chromium or Browser.chrome.');
  if (options.kind === 'cloud') return openCloud(options);
  if (options.kind === 'chrome') {
    if (options.approveConnection !== undefined && typeof options.approveConnection !== 'boolean')
      throw new Error('approveConnection must be boolean.');
    if (options.approveConnection && process.platform !== 'darwin')
      throw new Error('approveConnection is supported only on macOS.');
    const endpoint = options.cdpUrl ?? (await discoverChrome(options));
    if (!['http:', 'https:', 'ws:', 'wss:'].includes(new URL(endpoint).protocol))
      throw new Error('Invalid Chrome CDP endpoint.');
    return { endpoint, close: async () => {} };
  }
  if ('cdpUrl' in options && options.cdpUrl) {
    if (['headless', 'channel', 'executablePath', 'profileDir'].some((key) => key in options))
      throw new Error('cdpUrl cannot be combined with local browser options.');
    if (!['http:', 'https:', 'ws:', 'wss:'].includes(new URL(options.cdpUrl).protocol))
      throw new Error('cdpUrl must be an HTTP(S) or WebSocket endpoint.');
    return { endpoint: options.cdpUrl, close: async () => {} };
  }
  const path = await executable(options as LocalBrowserOptions);
  const persistent = !!options.profileDir;
  if (options.profileDir) await mkdir(options.profileDir, { recursive: true, mode: 0o700 });
  const profile = options.profileDir
    ? await realpath(options.profileDir)
    : await mkdtemp(join(tmpdir(), 'browser-use-'));
  const lockPath = join(profile, '.bu-pi.lock');
  const lock = await open(lockPath, 'wx', 0o600).catch(() => {
    throw new Error(
      `Browser profile is locked: ${profile}. Close its owner. After a crash, verify Chrome and the SDK have exited before removing .bu-pi.lock.`,
    );
  });
  await lock.writeFile(JSON.stringify({ pid: process.pid, createdAt: new Date().toISOString() }));
  const launchedAt = Date.now();
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
      await lock.close();
      await rm(lockPath, { force: true });
      if (!persistent) await rm(profile, { recursive: true, force: true });
    })());
  try {
    const deadline = Date.now() + 15_000;
    while (Date.now() < deadline) {
      if (launchError) throw launchError;
      if (child.exitCode !== null || child.signalCode !== null)
        throw new Error('Chrome exited before exposing CDP.');
      try {
        if ((await stat(join(profile, 'DevToolsActivePort'))).mtimeMs < launchedAt - 1)
          throw new Error('Waiting for a fresh DevTools endpoint.');
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

/** Narrow AX action from Browser Harness. Never enables debugging or grants Accessibility. */
export function approveChromeConnection(signal: AbortSignal): Promise<string> {
  const script = `using terms from application "System Events"
    on clickAllow(nodeRef)
      try
        if (role of nodeRef as text) is "AXButton" and (description of nodeRef as text) is "Allow" then
          perform action "AXPress" of nodeRef
          return true
        end if
      end try
      try
        repeat with childRef in UI elements of nodeRef
          if my clickAllow(childRef) then return true
        end repeat
      end try
      return false
    end clickAllow
  end using terms from
  tell application "System Events"
    if exists process "Google Chrome" then
      tell process "Google Chrome"
        repeat with w in windows
          try
            repeat with s in sheets of w
              if (name of s as text) is "Allow remote debugging?" then
                if my clickAllow(s) then return "ready"
              end if
            end repeat
          end try
        end repeat
      end tell
    end if
  end tell
  return "not-found"`;
  return new Promise((resolve, reject) => {
    execFile('/usr/bin/osascript', ['-e', script], { timeout: 5000, signal }, (error, stdout) => {
      if (error)
        reject(
          new Error(
            'Chrome approval needs macOS Accessibility permission for the app running Browser Use JS. Accept Chrome’s prompt manually, or grant that permission.',
          ),
        );
      else resolve(stdout.trim());
    });
  });
}
