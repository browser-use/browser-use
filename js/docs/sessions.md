# Sessions, login and files

```js
import { Browser, BrowserUse } from '@browser_use/pi';

const agent = await BrowserUse.create({
  model: 'openrouter/openai/gpt-5.6-luna',
  browser: Browser.chromium({ profileDir: './profiles/work', headless: false }),
  workspace: './work/research',
});
try {
  await agent.run('Open the site.');
  // Sign in through the visible browser, then continue.
  await agent.followUp('Read my dashboard.');
  await agent.saveHistory('./work/research/session.json');
} finally {
  await agent.close();
}
```

| State                | Lifetime                                               |
| -------------------- | ------------------------------------------------------ |
| `run(task)`          | New transcript; existing browser, JS and files         |
| `followUp(task)`     | Continues the transcript and live session              |
| `browser.profileDir` | Chrome cookies and login across launches; one owner    |
| `workspace`          | Scripts, downloads and outputs across runs             |
| `historyFile`        | Restores a transcript; no JS bindings or browser login |

Reuse a profile to keep login. Reuse a workspace to keep files. Restore history to continue the conversation. These are independent. A busy profile is rejected; do not share one across concurrent sessions.

## Choose a browser

```js
import { Browser, BrowserUse } from '@browser_use/pi';

// Browser Use Cloud. close() stops the browser this session creates.
const browser = Browser.cloud({
  apiKey: process.env.BROWSER_USE_API_KEY,
  profileId: 'your-cloud-profile-id', // optional saved login
  timeoutMinutes: 30,
});

// Or an isolated local Chromium engine. Installed Chrome works too.
// const browser = Browser.chromium({ profileDir: './profiles/work' });

// Or your running Chrome, with its existing login.
// const browser = Browser.chrome();
// macOS only: Browser.chrome({ approveConnection: true }) accepts the exact
// "Allow remote debugging?" sheet. Requires existing Accessibility permission.

const agent = await BrowserUse.create({ model: 'openrouter/openai/gpt-5.6-luna', browser });
try {
  await agent.run('Read my dashboard.');
} finally {
  await agent.close();
}
```

Real Chrome must expose CDP. Enable `chrome://inspect/#remote-debugging`; Browser Use Pi discovers `DevToolsActivePort` on macOS, Linux and Windows. It never copies your profile, relaunches your browser, or grants OS permissions. Pass `Browser.chrome({ cdpUrl })` for an explicit endpoint. `profileDir` in this mode selects the existing user-data root for discovery. The legacy `{cdpUrl}` and local browser options still work.

A local `profileDir` stores cookies, local storage and IndexedDB on disk. First run: use `headless: false`, sign in, then close normally. Next run: reuse that directory. Without it, the local profile is temporary and deleted at close. Profile locks reject concurrent SDK owners; after a crash, verify Chrome and the SDK have exited before removing `.bu-pi.lock`. A Chrome profile is sensitive data, not a portable login export.

Cloud uses a provider-managed `profileId`, not a local directory. Its save/sync behavior follows Browser Use Cloud. Real Chrome retains its own profile normally. Workspace and conversation history never restore login. Remote downloads stay on the remote browser host; retrieve them through the provider API.

## Domains and secrets

```js
const agent = await BrowserUse.create({
  model: 'openrouter/openai/gpt-5.6-luna',
  allowedDomains: ['*.example.com'],
  prohibitedDomains: ['admin.example.com'],
  sensitiveData: {
    password: { value: process.env.SITE_PASSWORD, domains: ['login.example.com'] },
  },
});
```

Use hostnames, not URLs. `*.example.com` includes the apex and subdomains. Denials win. An empty allowlist blocks every website. `about:blank` remains available for fresh tabs. With a policy, non-HTTP(S) navigation is disallowed through navigation commands.

CDP document interception guards attached tabs, redirects, frames and their new popups. Unrelated Chrome tabs are resumed without interception. These are navigation controls, **not network isolation**: subresources, page fetches, arbitrary Node code and separate CDP connections are outside the boundary. Apply OS/container egress rules when tasks are untrusted. Enabling a policy reserves CDP interception/auto-attach commands for the SDK.

The model receives secret names and permitted domains. It uses `fillSecret('password', backendNodeId, page)`; the SDK checks the tab/frame and actual input document in an isolated world, then inserts into that same DOM object without a focus race. Input/change events support controlled forms; this specialized insertion is not trusted keyboard input. Secret values are redacted from model requests, captured text, checkpoints, results and saved logs/history. Do not put secrets directly in task text or generated code.

This is not a credential vault: generated Node code runs with host access. Encoded/transformed secrets, screenshots, recordings and files written directly by generated code are not automatically sanitized. Use narrow secret domains and isolated execution for untrusted pages/tasks.

## Intervention

`pause()` waits for a tool boundary. While paused, `execute(code)` lets you inspect or act in the same JS session. Then `resume()`. `steer(text)` adds instructions during a run; `cancel()` aborts it. Await cancellation before starting another run.

Each session accepts one operation at a time. Use separate sessions for concurrency. Always `close()` in `finally`.

## Recording

Enable `recording: true` on creation. When a run returns `recordingPath`:

```js
import { exportRecording } from '@browser_use/pi';
await exportRecording(result.recordingPath, { output: './demo.gif' });
```

Exports use captured CDP frames and never rerun actions. GIF/MP4 export requires Chrome and ffmpeg. Recording is optional and can fail independently of the task; inspect `warnings`. Text redaction does not hide screenshot pixels. Use the export’s rectangle redaction option before sharing sensitive frames.
